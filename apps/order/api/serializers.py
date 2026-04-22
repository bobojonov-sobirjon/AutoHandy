from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from rest_framework import serializers
from django.contrib.auth import get_user_model
from apps.order.models import (
    Order,
    OrderStatus,
    OrderPriority,
    OrderType,
    CustomRequestOffer,
    Rating,
    OrderService,
    Review,
    ReviewTag,
    UserRating,
    LocationSource,
)
from apps.car.models import Car
from apps.categories.models import Category
from apps.master.models import Master
from apps.master.services.geo import haversine_distance_km, km_to_miles
from apps.accounts.serializers import UserSerializer
from apps.master.api.serializers import MasterSerializer
from apps.order.services.master_offer import activate_pending_master_offer
from apps.order.services.sos_master_queue import build_sos_master_id_queue
from apps.order.services.status_workflow import (
    client_cancellation_snapshot,
    order_master_distance_mi,
    resolve_master_coordinates_for_start_job,
)
from apps.order.services.completion_pin import clear_completion_pin, issue_completion_pin
from apps.order.services.order_pricing import get_cached_order_pricing
from apps.order.services.standard_booking_availability import preferred_slot_blocked_message
from apps.order.services.notifications import _media_url
from config.wgs84 import WGS84_COORD_DECIMAL_KWARGS

User = get_user_model()

CUSTOM_REQUEST_CATEGORY_MASK_MASTER = 'Incoming request'


def review_tags_detail(tags):
    """[{value, label}, ...] for API responses."""
    if not tags:
        return []
    out = []
    for t in tags:
        try:
            label = str(ReviewTag(t).label)
        except ValueError:
            label = str(t)
        out.append({'value': t, 'label': label})
    return out


def _request_user_is_master(request) -> bool:
    if not request or not request.user.is_authenticated:
        return False
    return request.user.groups.filter(name='Master').exists()


class LenientTimeField(serializers.TimeField):
    """
    Accepts ISO-like time strings from mobile clients, e.g. ``04:05:41.902Z``
    (trailing Z is ignored). Falls back to DRF ``TimeField`` parsing.
    """

    def to_internal_value(self, data):
        if data is None and getattr(self, 'allow_null', False):
            return None
        if hasattr(data, 'hour'):
            return data
        if isinstance(data, str):
            s = data.strip()
            if s.endswith('Z') or s.endswith('z'):
                s = s[:-1]
            for fmt in ('%H:%M:%S.%f', '%H:%M:%S', '%H:%M'):
                try:
                    return datetime.strptime(s, fmt).time()
                except ValueError:
                    continue
        return super().to_internal_value(data)


def _money_fmt(v) -> str:
    return format(
        Decimal(str(v if v is not None else 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
        'f',
    )


class OrderPricingNestedSerializer(serializers.ModelSerializer):
    """
    Line subtotal from order services; discount split across lines (proportional for amount mode).
    Service line amounts are multiplied by the number of cars on the order (same work per vehicle).
    See ``ORDER_DISCOUNT_IS_PERCENT`` in settings for percent vs fixed amount.
    """

    discount_mode = serializers.SerializerMethodField()
    subtotal = serializers.SerializerMethodField()
    discount_applied = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    car_count = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = (
            'discount',
            'discount_mode',
            'subtotal',
            'discount_applied',
            'total',
            'car_count',
        )

    def get_discount_mode(self, obj):
        return get_cached_order_pricing(obj, self.context)['discount_mode']

    def get_subtotal(self, obj):
        return format(get_cached_order_pricing(obj, self.context)['subtotal'], 'f')

    def get_discount_applied(self, obj):
        return format(get_cached_order_pricing(obj, self.context)['discount_applied'], 'f')

    def get_total(self, obj):
        return format(get_cached_order_pricing(obj, self.context)['total'], 'f')

    def get_car_count(self, obj):
        return get_cached_order_pricing(obj, self.context).get('car_count', 1)


class OrderWorkflowNestedSerializer(serializers.ModelSerializer):
    """Status oqimi: qabul, muddatlar, yo‘lda / yetib keldi / ish boshlandi, klient bekor huquqi."""

    class Meta:
        model = Order
        fields = (
            'accepted_at',
            'on_the_way_at',
            'arrival_deadline_at',
            'arrived_at',
            'work_started_at',
            'client_penalty_free_cancel_unlocked',
            'auto_cancel_reason',
        )


class OrderEtaNestedSerializer(serializers.ModelSerializer):
    """Taxminiy yetib kelish: vaqt, daqiqa, masofa (miles)."""

    eta_distance_mi = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ('estimated_arrival_at', 'eta_minutes', 'eta_distance_mi')

    def get_eta_distance_mi(self, obj):
        return order_master_distance_mi(obj)


class OrderTimestampsNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ('created_at', 'updated_at')


class OrderSerializer(serializers.ModelSerializer):
    """Order serializer (pricing/workflow/eta guruhlari; SOS navbati API da yashirin)."""
    user = serializers.SerializerMethodField()
    master = serializers.SerializerMethodField()
    client_completion_pin = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    order_type_display = serializers.CharField(source='get_order_type_display', read_only=True)
    car_data = serializers.SerializerMethodField()
    category_data = serializers.SerializerMethodField()
    services = serializers.SerializerMethodField()
    reviews = serializers.SerializerMethodField()
    average_rating = serializers.SerializerMethodField()
    location_precision = serializers.SerializerMethodField()
    order_images = serializers.SerializerMethodField()
    work_completion_images = serializers.SerializerMethodField()
    cancellation = serializers.SerializerMethodField()
    custom_request_selected_offer = serializers.SerializerMethodField()
    chat_room_id = serializers.IntegerField(source='chat_room_id', read_only=True)
    latitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS, required=False, allow_null=True)
    longitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS, required=False, allow_null=True)

    pricing = OrderPricingNestedSerializer(source='*', read_only=True)
    workflow = OrderWorkflowNestedSerializer(source='*', read_only=True)
    eta = OrderEtaNestedSerializer(source='*', read_only=True)
    timestamps = OrderTimestampsNestedSerializer(source='*', read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'user', 'order_type', 'order_type_display',
            'car_data', 'category_data',
            'text', 'status', 'status_display', 'priority', 'priority_display',
            'location', 'latitude', 'longitude', 'location_precision',
            'parts_purchase_required',
            'preferred_date', 'preferred_time_start', 'preferred_time_end',
            'custom_request_date', 'custom_request_time',
            'master',
            'pricing', 'services', 'reviews', 'average_rating',
            'workflow', 'eta',
            'order_images', 'work_completion_images',
            'timestamps', 'cancellation',
            'client_completion_pin',
            'custom_request_selected_offer',
            'chat_room_id',
        ]
        read_only_fields = [
            'id',
            'workflow', 'eta', 'timestamps', 'pricing',
        ]
    
    def get_user(self, obj):
        return UserSerializer(obj.user, context=self.context).data

    def get_custom_request_selected_offer(self, obj):
        """
        Custom-request: price offer from the master currently assigned on the order (``order.master``).
        Not all offers — only the row matching ``CustomRequestOffer`` (order + assigned master).
        """
        if obj.order_type != OrderType.CUSTOM_REQUEST or not obj.master_id:
            return None
        matched = None
        cache = getattr(obj, '_prefetched_objects_cache', None)
        if cache and 'custom_request_offers' in cache:
            for o in cache['custom_request_offers']:
                if o.master_id == obj.master_id:
                    matched = o
                    break
        else:
            matched = (
                CustomRequestOffer.objects.filter(order_id=obj.pk, master_id=obj.master_id)
                .only('id', 'price', 'created_at', 'updated_at')
                .first()
            )
        if not matched:
            return None
        return {
            'id': matched.id,
            'price': str(matched.price),
            'created_at': matched.created_at,
            'updated_at': matched.updated_at,
        }

    def get_client_completion_pin(self, obj):
        """4-digit code for the order owner while in_progress; master never sees this in API."""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        if obj.user_id != request.user.id:
            return None
        if obj.status != OrderStatus.IN_PROGRESS:
            return None
        pin = (getattr(obj, 'completion_pin', None) or '').strip()
        if len(pin) != 4 or not pin.isdigit():
            return None
        return pin

    def get_master(self, obj):
        if not obj.master_id:
            return None
        request = self.context.get('request')
        hide = True
        if request and request.user.is_authenticated:
            if obj.master.user_id == request.user.id:
                hide = False
            elif obj.user_id == request.user.id:
                # Driver: show workshop coords once master is on the order (not custom-request still pending).
                if obj.order_type == OrderType.CUSTOM_REQUEST and obj.status == OrderStatus.PENDING:
                    hide = True
                else:
                    hide = False
        master = obj.master
        dist_mi = order_master_distance_mi(obj)
        if dist_mi is not None:
            master.distance = float(dist_mi)
        ctx = {
            **self.context,
            'hide_master_exact_location': hide,
            'embed_order_min_price': True,
        }
        first_cat = obj.category.first()
        if first_cat is not None:
            ctx['filter_service_category_id'] = first_cat.id
        return MasterSerializer(master, context=ctx).data
    
    def get_car_data(self, obj):
        """Get car data"""
        cars = obj.car.all()
        return [
            {
                'id': car.id,
                'brand': car.brand,
                'model': car.model,
                'year': car.year,
                'category': car.category.name if car.category else None
            }
            for car in cars
        ]
    
    def get_category_data(self, obj):
        """
        Order M2M categories grouped by parent — same shape as `services`:
        `[{ parent: { id, name, icon } | null, items: [...] }, ...]`.
        """
        from apps.master.api.serializers import _absolute_media_url

        request = self.context.get('request')
        categories = (
            obj.category.all()
            .select_related('parent')
            .order_by('parent_id', 'name')
        )
        groups = {}
        mask_for_master = _request_user_is_master(request) and (
            obj.order_type == OrderType.CUSTOM_REQUEST
            or obj.category.filter(is_custom_request_entry=True).exists()
        )
        for cat in categories:
            parent = cat.parent
            gid = parent.id if parent is not None else 0
            if gid not in groups:
                p_block = None
                if parent:
                    p_block = {
                        'id': parent.id,
                        'name': (
                            CUSTOM_REQUEST_CATEGORY_MASK_MASTER
                            if mask_for_master and parent.is_custom_request_entry
                            else parent.name
                        ),
                        'icon': _absolute_media_url(request, parent.icon),
                    }
                groups[gid] = {'parent': p_block, 'items': []}
            item_name = (
                CUSTOM_REQUEST_CATEGORY_MASK_MASTER
                if mask_for_master
                and (cat.is_custom_request_entry or (cat.parent and cat.parent.is_custom_request_entry))
                else cat.name
            )
            groups[gid]['items'].append(
                {
                    'id': cat.id,
                    'name': item_name,
                    'type_category': cat.type_category,
                    'icon': _absolute_media_url(request, cat.icon),
                }
            )
        return list(groups.values())

    def get_services(self, obj):
        """
        Order lines grouped by parent category — same structure as
        `master.services[].master_service_items`: `[{ parent, items }, ...]`.
        Each item line matches `master_service_item_line_dict` plus `order_service_id`, `added_at`.
        """
        from apps.master.api.serializers import master_service_item_line_dict, _absolute_media_url

        request = self.context.get('request')
        order_services = (
            obj.order_services.all()
            .select_related(
                'master_service_item',
                'master_service_item__category',
                'master_service_item__category__parent',
            )
            .order_by(
                'master_service_item__category__parent_id',
                'master_service_item__category__name',
            )
        )
        groups = {}
        br = get_cached_order_pricing(obj, self.context)
        for os_row in order_services:
            item = os_row.master_service_item
            if not item:
                continue
            parent = item.category.parent if item.category_id else None
            gid = parent.id if parent else 0
            if gid not in groups:
                groups[gid] = {
                    'parent': (
                        {
                            'id': parent.id,
                            'name': parent.name,
                            'icon': _absolute_media_url(request, parent.icon),
                        }
                        if parent
                        else None
                    ),
                    'items': [],
                }
            line = master_service_item_line_dict(item, request)
            line['order_service_id'] = os_row.id
            line['added_at'] = os_row.created_at
            meta = br['lines_by_order_service_id'].get(os_row.id)
            if meta:
                line['discount_allocated'] = format(meta['discount_allocated'], 'f')
                line['line_total'] = format(meta['line_total'], 'f')
                line['car_count'] = meta.get('car_count', br.get('car_count', 1))
            else:
                line['discount_allocated'] = '0.00'
                line['line_total'] = _money_fmt(line.get('price'))
                line['car_count'] = br.get('car_count', 1)
            groups[gid]['items'].append(line)
        return list(groups.values())
    
    def get_reviews(self, obj):
        """Get order reviews"""
        from apps.order.models import Review

        request = self.context.get('request')
        reviews = Review.objects.filter(order=obj).select_related('reviewer')
        if not reviews.exists():
            return []

        return [
            {
                'id': review.id,
                'rating': review.rating,
                'comment': review.comment,
                'tags': review.tags,
                'tags_detail': review_tags_detail(review.tags),
                'reviewer': {
                    'id': review.reviewer.id,
                    'full_name': review.reviewer.get_full_name(),
                    'avatar': _media_url(request, review.reviewer.avatar),
                }
                if review.reviewer
                else None,
                'created_at': review.created_at,
            }
            for review in reviews
        ]
    
    def get_average_rating(self, obj):
        """Get order average rating"""
        from django.db.models import Avg
        from apps.order.models import Review
        
        avg = Review.objects.filter(order=obj).aggregate(avg_rating=Avg('rating'))
        return round(avg['avg_rating'], 2) if avg['avg_rating'] else None

    def get_location_precision(self, obj):
        return 'exact'

    def get_order_images(self, obj):
        request = self.context.get('request')
        out = []
        for im in obj.images.all().order_by('id'):
            out.append(
                {
                    'id': im.id,
                    'image': _media_url(request, im.image),
                    'created_at': im.created_at,
                }
            )
        return out

    def get_work_completion_images(self, obj):
        request = self.context.get('request')
        out = []
        for im in obj.work_completion_images.all().order_by('id'):
            out.append(
                {
                    'id': im.id,
                    'image': _media_url(request, im.image),
                    'created_at': im.created_at,
                }
            )
        return out

    def get_cancellation(self, obj):
        """Client cancellation policy for this order (see status_workflow.client_cancellation_snapshot)."""
        return client_cancellation_snapshot(obj)

    def validate_latitude(self, value):
        """Validate latitude"""
        if value is not None and (value < -90 or value > 90):
            raise serializers.ValidationError('Latitude must be between -90 and 90')
        return value

    def validate_longitude(self, value):
        """Validate longitude"""
        if value is not None and (value < -180 or value > 180):
            raise serializers.ValidationError('Longitude must be between -180 and 180')
        return value


class OrderCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating order.

    Supports two order types:
    1. STANDARD: client selects master; optional ``preferred_date`` + ``preferred_time_start``.
    2. SOS: client makes urgent order with current geolocation

    Required for both: order_type, text, location, latitude, longitude, car_list, category_list.
    For STANDARD also: master_id.
    For SOS: priority optional (defaults high). master_id optional — nearest masters with selected
    by_order service are queued; WebSocket + 30s offer each.

    Optional: ``parts_purchase_required`` (boolean).
    Use **multipart/form-data** to upload ``images`` (field name ``images``, multiple files);
    send ``car_list`` / ``category_list`` as JSON strings (e.g. ``[1,2]``).
    """
    order_type = serializers.CharField(
        required=True,
        help_text="Order type: 'standard' or 'sos' (legacy body value 'scheduled' is accepted as standard).",
    )
    master_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        write_only=True,
        help_text="Master ID (required for standard orders; optional for SOS — auto nearby queue)"
    )
    car_list = serializers.ListField(
        child=serializers.IntegerField(),
        required=True,
        allow_empty=False,
        write_only=True,
        help_text="List of car IDs [1, 2, 3, ...] (required)"
    )
    category_list = serializers.ListField(
        child=serializers.IntegerField(),
        required=True,
        allow_empty=False,
        write_only=True,
        help_text="List of category IDs [1, 2, 3, ...] (required)"
    )
    parts_purchase_required = serializers.BooleanField(
        required=False,
        default=False,
        help_text='If true, master may need to buy parts; client pays outside the app',
    )
    preferred_date = serializers.DateField(
        required=False,
        allow_null=True,
        help_text='Standard only: service day (use with preferred_time_start). preferred_time_end is not set here.',
    )
    preferred_time_start = LenientTimeField(
        required=False,
        allow_null=True,
        help_text='Standard only: desired slot start time. Master sets preferred_time_end after accept (PATCH).',
    )
    latitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS)
    longitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS)

    class Meta:
        model = Order
        fields = [
            'order_type', 'text', 'priority', 'location', 'latitude', 'longitude',
            'master_id',
            'car_list', 'category_list',
            'parts_purchase_required',
            'preferred_date', 'preferred_time_start',
        ]
        extra_kwargs = {
            'text': {'required': True},
            'location': {'required': True},
            'latitude': {'required': True},
            'longitude': {'required': True},
            'priority': {'required': False},  # For SOS set automatically
        }

    def validate_order_type(self, value):
        v = (value or '').strip().lower()
        if v == 'scheduled':
            return OrderType.STANDARD
        if v == OrderType.STANDARD:
            return OrderType.STANDARD
        if v == OrderType.SOS:
            return OrderType.SOS
        if v == OrderType.CUSTOM_REQUEST:
            raise serializers.ValidationError("Use POST /api/order/custom-request/ for custom requests.")
        raise serializers.ValidationError("order_type must be 'standard' or 'sos'.")

    def validate_master_id(self, value):
        """Validate master"""
        if value is not None:
            try:
                Master.objects.get(id=value)
            except Master.DoesNotExist:
                raise serializers.ValidationError(f"Master with ID {value} not found")
        return value

    def validate_car_list(self, value):
        """Validate car list: all IDs must exist and belong to the requesting user."""
        if not isinstance(value, list):
            raise serializers.ValidationError("car_list must be a list of IDs")

        user = self.context['request'].user
        seen = []
        for car_id in dict.fromkeys(value):
            try:
                car = Car.objects.get(id=car_id)
            except Car.DoesNotExist:
                raise serializers.ValidationError(f"Car with ID {car_id} not found")
            if car.user_id != user.id:
                raise serializers.ValidationError(
                    f'Car {car_id} does not belong to you.'
                )
            seen.append(car_id)
        return seen

    def validate_category_list(self, value):
        """Validate category list"""
        if not isinstance(value, list):
            raise serializers.ValidationError("category_list must be a list of IDs")

        for category_id in value:
            try:
                Category.objects.get(id=category_id)
            except Category.DoesNotExist:
                raise serializers.ValidationError(f"Category with ID {category_id} not found")

        return value

    def validate_latitude(self, value):
        """Validate latitude"""
        if value is not None and (value < -90 or value > 90):
            raise serializers.ValidationError('Latitude must be between -90 and 90')
        return value

    def validate_longitude(self, value):
        """Validate longitude"""
        if value is not None and (value < -180 or value > 180):
            raise serializers.ValidationError('Longitude must be between -180 and 180')
        return value

    def validate(self, attrs):
        """Validate order data based on order type"""
        order_type = attrs.get('order_type')
        master_id = attrs.get('master_id')
        order_lat = attrs.get('latitude')
        order_lon = attrs.get('longitude')

        if order_type == OrderType.STANDARD:
            if not master_id:
                raise serializers.ValidationError({
                    'master_id': 'Master is required for standard order'
                })
            pd = attrs.get('preferred_date')
            ps = attrs.get('preferred_time_start')
            if (pd is None) ^ (ps is None):
                raise serializers.ValidationError(
                    'preferred_date and preferred_time_start must both be sent together, or omit both.'
                )
            if pd is not None and ps is not None:
                blocked = preferred_slot_blocked_message(
                    master_id=master_id,
                    preferred_date=pd,
                    preferred_time_start=ps,
                )
                if blocked:
                    raise serializers.ValidationError({'preferred_time_start': blocked})

        elif order_type == OrderType.SOS:
            if not attrs.get('priority'):
                attrs['priority'] = OrderPriority.HIGH
            attrs.pop('preferred_date', None)
            attrs.pop('preferred_time_start', None)

            cats = attrs.get('category_list') or []
            if not master_id:
                by_order_ok = Category.objects.filter(
                    id__in=cats,
                    type_category=Category.TypeCategory.BY_ORDER,
                ).exists()
                if not by_order_ok:
                    raise serializers.ValidationError({
                        'category_list': 'Select at least one by_order service category for SOS.',
                    })
                queue = build_sos_master_id_queue(
                    float(order_lat),
                    float(order_lon),
                    [int(c) for c in cats],
                )
                if not queue:
                    raise serializers.ValidationError({
                        'category_list': (
                            'No masters with this service are available within their acceptance zones '
                            'for this location.'
                        ),
                    })
                attrs['_sos_queue'] = queue

        if master_id and order_lat and order_lon:
            try:
                master = Master.objects.get(id=master_id)
                wlat, wlon = master.get_work_location_for_distance()
                if wlat is None:
                    raise serializers.ValidationError({
                        'master_id': 'Selected master has no work location or profile coordinates. '
                                      'Please choose another master.'
                    })
                lat1 = float(order_lat)
                lon1 = float(order_lon)
                distance_km = haversine_distance_km(lat1, lon1, wlat, wlon)
                max_km = master.max_order_distance_km()
                if distance_km > max_km:
                    d_mi = km_to_miles(distance_km)
                    max_mi = km_to_miles(max_km)
                    if order_type == OrderType.STANDARD:
                        msg = (
                            f'This master cannot take this booking: the order location is outside their '
                            f'acceptance zone ({d_mi:.1f} mi from their map pin; maximum allowed '
                            f'{max_mi:.1f} mi). Choose another master or change the visit coordinates.'
                        )
                    else:
                        msg = (
                            f'The SOS location is outside this master’s acceptance zone '
                            f'({d_mi:.1f} mi; limit {max_mi:.1f} mi). Choose another master.'
                        )
                    raise serializers.ValidationError({'master_id': msg})

            except Master.DoesNotExist:
                pass

        return attrs

    def create(self, validated_data):
        """Create order with cars and categories"""
        master_id = validated_data.pop('master_id', None)
        sos_queue = validated_data.pop('_sos_queue', None)
        car_list = validated_data.pop('car_list', [])
        category_list = validated_data.pop('category_list', [])

        if master_id and validated_data.get('order_type') == OrderType.STANDARD:
            validated_data['master'] = Master.objects.get(id=master_id)

        order = super().create(validated_data)
        if car_list:
            order.car.set(list(dict.fromkeys(car_list)))
        if category_list:
            order.category.set(category_list)

        if order.master_id:
            from apps.order.services.order_category_services import sync_order_services_from_order_categories

            sync_order_services_from_order_categories(order)

        if order.order_type == OrderType.SOS:
            if sos_queue is not None:
                order.sos_offer_queue = sos_queue
                order.sos_offer_index = 0
                order.save(update_fields=['sos_offer_queue', 'sos_offer_index'])
            elif master_id:
                order.sos_offer_queue = [master_id]
                order.sos_offer_index = 0
                order.save(update_fields=['sos_offer_queue', 'sos_offer_index'])

        if order.status == OrderStatus.PENDING:
            activate_pending_master_offer(order, request=self.context.get('request'))

        return order


class CustomRequestCreateSerializer(serializers.Serializer):
    """Driver multipart/JSON create: text, location, GPS, optional cars; category is assigned server-side."""

    text = serializers.CharField()
    location = serializers.CharField()
    latitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS)
    longitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS)
    custom_request_date = serializers.DateField(
        required=False,
        allow_null=True,
        help_text='Calendar day for the requested service (client local date / request time).',
    )
    custom_request_time = LenientTimeField(
        required=False,
        allow_null=True,
        help_text='Preferred time for the service (client local; use with custom_request_date).',
    )
    car_list = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        default=list,
    )
    parts_purchase_required = serializers.BooleanField(required=False, default=False)

    def validate_car_list(self, value):
        user = self.context['request'].user
        out = []
        for car_id in dict.fromkeys(value):
            try:
                car = Car.objects.get(id=car_id)
            except Car.DoesNotExist:
                raise serializers.ValidationError(f'Car with ID {car_id} not found')
            if car.user_id and car.user_id != user.id:
                raise serializers.ValidationError(f'Car {car_id} does not belong to you.')
            out.append(car_id)
        return out

    def validate_latitude(self, value):
        if value is not None and (value < -90 or value > 90):
            raise serializers.ValidationError('Latitude must be between -90 and 90')
        return value

    def validate_longitude(self, value):
        if value is not None and (value < -180 or value > 180):
            raise serializers.ValidationError('Longitude must be between -180 and 180')
        return value

    def validate(self, attrs):
        from apps.order.services.custom_request_broadcast import get_custom_request_catalog_category

        if not get_custom_request_catalog_category():
            raise serializers.ValidationError(
                'Custom request is not configured. Add a main by_order category with '
                'is_custom_request_entry in the admin.'
            )
        return attrs

    def create(self, validated_data):
        from apps.order.services.custom_request_broadcast import get_custom_request_catalog_category

        user = self.context['request'].user
        car_list = validated_data.pop('car_list', [])
        crd = validated_data.pop('custom_request_date', None)
        crt = validated_data.pop('custom_request_time', None)
        cat = get_custom_request_catalog_category()
        order = Order.objects.create(
            user=user,
            text=validated_data['text'],
            location=validated_data['location'],
            latitude=validated_data['latitude'],
            longitude=validated_data['longitude'],
            order_type=OrderType.CUSTOM_REQUEST,
            status=OrderStatus.PENDING,
            priority=OrderPriority.LOW,
            location_source=LocationSource.GPS_CUSTOM,
            parts_purchase_required=validated_data.get('parts_purchase_required', False),
            custom_request_date=crd,
            custom_request_time=crt,
        )
        if car_list:
            order.car.set(list(dict.fromkeys(car_list)))
        order.category.set([cat.pk])
        return order


class CustomRequestOfferCreateSerializer(serializers.Serializer):
    price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))


class CustomRequestOfferSerializer(serializers.ModelSerializer):
    master_id = serializers.IntegerField(source='master.id', read_only=True)

    class Meta:
        model = CustomRequestOffer
        fields = ('id', 'order', 'master_id', 'price', 'created_at', 'updated_at')
        read_only_fields = fields


class CustomRequestOfferWithMasterSerializer(serializers.ModelSerializer):
    """Offer row for custom-request list/detail: full `MasterSerializer` + distance from order coords."""

    master = serializers.SerializerMethodField()

    class Meta:
        model = CustomRequestOffer
        fields = ('id', 'price', 'created_at', 'updated_at', 'master')
        read_only_fields = fields

    def get_master(self, obj):
        order = self.context['order']
        request = self.context['request']
        hide_exact = True
        if order.master_id and obj.master_id == order.master_id:
            hide_exact = False
        if request.user.is_authenticated and obj.master.user_id == request.user.id:
            hide_exact = False

        m = obj.master
        if order.latitude is not None and order.longitude is not None:
            mlat, mlon, _err = resolve_master_coordinates_for_start_job(m, {})
            if mlat is not None and mlon is not None:
                m.distance = float(
                    round(
                        km_to_miles(
                            haversine_distance_km(
                                mlat,
                                mlon,
                                float(order.latitude),
                                float(order.longitude),
                            )
                        ),
                        3,
                    )
                )

        ctx = {
            **self.context,
            'hide_master_exact_location': hide_exact,
            'embed_order_min_price': True,
        }
        first_cat = order.category.first()
        if first_cat is not None:
            ctx['filter_service_category_id'] = first_cat.id
        return MasterSerializer(m, context=ctx).data


class OrderMasterPreferredTimePatchSerializer(serializers.Serializer):
    """Assigned master sets preferred_time_end after accept (start comes from client on create)."""

    preferred_time_end = LenientTimeField()

    def validate(self, attrs):
        order = self.context['order']
        start = order.preferred_time_start
        end = attrs['preferred_time_end']
        if start is None:
            raise serializers.ValidationError(
                {
                    'preferred_time_end': (
                        'Order has no preferred_time_start from the client; cannot set end time.'
                    )
                }
            )
        if end <= start:
            raise serializers.ValidationError(
                {'preferred_time_end': 'Must be after preferred_time_start.'}
            )
        return attrs


class OrderUpdateSerializer(serializers.ModelSerializer):
    """Order update serializer"""

    latitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS, required=False, allow_null=True)
    longitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS, required=False, allow_null=True)

    class Meta:
        model = Order
        fields = [
            'text', 'status', 'priority', 'location', 'latitude', 'longitude', 'master',
        ]

    def validate_latitude(self, value):
        """Validate latitude"""
        if value is not None and (value < -90 or value > 90):
            raise serializers.ValidationError('Latitude must be between -90 and 90')
        return value

    def validate_longitude(self, value):
        """Validate longitude"""
        if value is not None and (value < -180 or value > 180):
            raise serializers.ValidationError('Longitude must be between -180 and 180')
        return value

    def update(self, instance, validated_data):
        """Keep completion PIN in sync for generic status updates."""
        previous_status = instance.status
        new_status = validated_data.get('status', previous_status)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if new_status != previous_status:
            if new_status == OrderStatus.IN_PROGRESS:
                issue_completion_pin(instance)
            else:
                clear_completion_pin(instance)

        instance.save()
        return instance


class OrderStatusUpdateSerializer(serializers.Serializer):
    """Order status update serializer"""
    status = serializers.ChoiceField(choices=OrderStatus.choices)

    def validate_status(self, value):
        """Validate status"""
        if value not in [choice[0] for choice in OrderStatus.choices]:
            raise serializers.ValidationError('Invalid order status')
        return value


class OrderServiceSerializer(serializers.ModelSerializer):
    """Order service serializer"""
    service_details = serializers.SerializerMethodField()

    class Meta:
        model = OrderService
        fields = ['id', 'order', 'master_service_item', 'service_details', 'created_at']
        read_only_fields = ['id', 'created_at']

    def get_service_details(self, obj):
        """Get service details"""
        if obj.master_service_item:
            from apps.master.api.serializers import MasterServiceItemsSerializer
            return MasterServiceItemsSerializer(
                obj.master_service_item,
                context=self.context,
            ).data
        return None


class AddServicesToOrderSerializer(serializers.Serializer):
    """Serializer for adding services to order"""
    order_id = serializers.IntegerField()
    services_list = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False,
        help_text='List of master service item IDs (MasterServiceItems)'
    )
    discount = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        default=0.00,
        help_text='Order discount'
    )

    def validate_order_id(self, value):
        """Check order exists"""
        try:
            Order.objects.get(id=value)
        except Order.DoesNotExist:
            raise serializers.ValidationError(f'Order with ID {value} not found')
        return value

    def validate_services_list(self, value):
        """Check services exist"""
        from apps.master.models import MasterServiceItems

        if not value:
            raise serializers.ValidationError('Services list cannot be empty')

        existing_services = MasterServiceItems.objects.filter(id__in=value)
        existing_ids = set(existing_services.values_list('id', flat=True))
        invalid_ids = set(value) - existing_ids
        if invalid_ids:
            raise serializers.ValidationError(
                f'Services with ID {list(invalid_ids)} not found'
            )
        return value


class AddMasterToOrderSerializer(serializers.Serializer):
    """Set primary master (FK) on order: `master_id` = Master profile id."""

    order_id = serializers.IntegerField()
    master_id = serializers.IntegerField()

    def validate_order_id(self, value):
        try:
            Order.objects.get(id=value)
        except Order.DoesNotExist:
            raise serializers.ValidationError(f'Order with ID {value} not found')
        return value

    def validate_master_id(self, value):
        try:
            Master.objects.get(id=value)
        except Master.DoesNotExist:
            raise serializers.ValidationError(f'Master with ID {value} not found')
        return value


class ReviewSerializer(serializers.ModelSerializer):
    """Review serializer (GET): absolute avatar URL, multiple tags."""
    reviewer_info = serializers.SerializerMethodField()
    tags_detail = serializers.SerializerMethodField()
    order_info = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = [
            'id', 'order', 'order_info', 'reviewer', 'reviewer_info',
            'rating', 'comment', 'tags', 'tags_detail', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'reviewer', 'created_at', 'updated_at']

    def get_reviewer_info(self, obj):
        """Review author info"""
        request = self.context.get('request')
        if obj.reviewer:
            return {
                'id': obj.reviewer.id,
                'full_name': obj.reviewer.get_full_name(),
                'email': obj.reviewer.email,
                'avatar': _media_url(request, obj.reviewer.avatar),
            }
        return None

    def get_tags_detail(self, obj):
        return review_tags_detail(obj.tags)

    def get_order_info(self, obj):
        """Short order info"""
        if obj.order:
            return {
                'id': obj.order.id,
                'text': obj.order.text,
                'status': obj.order.status,
                'created_at': obj.order.created_at,
            }
        return None


class ReviewCreateSerializer(serializers.Serializer):
    """Create review: multipart or JSON; multiple ``tags``. No images — use work-completion-image API."""

    order_id = serializers.IntegerField(help_text='Order ID')
    rating = serializers.IntegerField(min_value=1, max_value=5, help_text='Rating from 1 to 5')
    comment = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text='Review comment',
    )
    tags = serializers.ListField(
        child=serializers.ChoiceField(choices=ReviewTag.choices),
        min_length=1,
        max_length=32,
        help_text='One or more ReviewTag values (same as legacy single tag, but repeatable).',
    )

    def validate_order_id(self, value):
        """Check order exists, belongs to request user, and can be reviewed."""
        request = self.context.get('request')
        try:
            order = Order.objects.get(id=value)
        except Order.DoesNotExist:
            raise serializers.ValidationError(f'Order with ID {value} not found')

        if order.status != OrderStatus.COMPLETED:
            raise serializers.ValidationError('Review can only be left for a completed order')

        if Review.objects.filter(order=order).exists():
            raise serializers.ValidationError('A review for this order has already been submitted')

        if request and request.user.is_authenticated and order.user_id != request.user.id:
            raise serializers.ValidationError('You can only review your own orders.')

        return value


class CancelOrderRequestSerializer(serializers.Serializer):
    """Body for ``POST /api/order/{order_id}/cancel/`` (master must send ``cancel_reason``)."""

    cancel_reason = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text=(
            'Assigned master only: one of client_request, vehicle_unavailable, duplicate, '
            'emergency, other. Omit for client (driver) cancel.'
        ),
    )
