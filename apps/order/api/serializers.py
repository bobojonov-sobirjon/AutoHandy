from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from rest_framework import serializers
from django.contrib.auth import get_user_model
from apps.order.models import (
    Order,
    OrderStatus,
    OrderPriority,
    OrderType,
    FuelDeliveryType,
    OrderStripePaymentStatus,
    CustomRequestOffer,
    Rating,
    OrderService,
    Review,
    ReviewTag,
    UserRating,
    LocationSource,
    OrderExtraMoneyRequest,
    ExtraMoneyRequestStatus,
    OrderTimeChangeRequest,
    TimeChangeRequestStatus,
    OrderServiceAddRequest,
    ServiceAddRequestStatus,
)
from apps.order.services.post_completion import build_post_completion_payload
from apps.car.models import Car
from apps.categories.models import Category
from apps.master.models import Master
from apps.master.services.geo import haversine_distance_km, km_to_miles
from apps.accounts.serializers import UserSerializer
from apps.master.api.serializers import MasterSerializer
from apps.order.services.master_offer import activate_pending_master_offer
from apps.order.services.sos_master_queue import build_sos_master_id_queue
from apps.order.services.sos_rotation import (
    filter_master_ids_meeting_emergency_thresholds,
    master_meets_emergency_offer_thresholds,
)
from apps.order.services.status_workflow import (
    client_cancellation_snapshot,
    order_master_distance_mi,
    resolve_master_coordinates_for_start_job,
)
from apps.order.services.completion_pin import clear_completion_pin, issue_completion_pin
from apps.order.services.order_pricing import get_cached_order_pricing
from apps.payment.services.checkout_fees import (
    build_order_marketplace_fee_display,
    order_pricing_platform_fee,
)
from apps.order.services.standard_booking_availability import preferred_slot_blocked_message
from apps.order.services.notifications import _media_url
from config.wgs84 import WGS84_COORD_DECIMAL_KWARGS

User = get_user_model()

CUSTOM_REQUEST_CATEGORY_MASK_MASTER = 'Incoming request'
TOWING_CATEGORY_MASK_MASTER = 'Towing request'


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


class PartsPurchaseRequiredItemSerializer(serializers.Serializer):
    """
    One "parts to buy" item (stored inside Order.parts_purchase_required_json).

    Canonical keys:
    - vehicle_vin: string (0..17)
    - part_name: string (0..100)
    - is_address: bool (client knows where to buy / has address)

    Backward/typo-tolerant input aliases:
    - "vehicle vin" -> vehicle_vin
    - "part name" -> part_name
    - "is_addess" -> is_address
    """

    vehicle_vin = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=17,
        help_text='Vehicle VIN (0–17 chars).',
    )
    part_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=100,
        help_text='Exact part name (0–100 chars).',
    )
    is_address = serializers.BooleanField(
        required=True,
        help_text='Whether client knows where to buy this part (has address/place).',
    )

    def to_internal_value(self, data):
        if isinstance(data, dict):
            # Accept common mobile typos/labels.
            if 'vehicle_vin' not in data and 'vehicle vin' in data:
                data = {**data, 'vehicle_vin': data.get('vehicle vin')}
            if 'part_name' not in data and 'part name' in data:
                data = {**data, 'part_name': data.get('part name')}
            if 'is_address' not in data and 'is_addess' in data:
                data = {**data, 'is_address': data.get('is_addess')}
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
    extra_money = serializers.SerializerMethodField()
    work_total = serializers.SerializerMethodField()
    penalty_total = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    car_count = serializers.SerializerMethodField()
    emergency_pricing = serializers.SerializerMethodField()
    offer_price = serializers.SerializerMethodField()
    platform_fee = serializers.SerializerMethodField()
    marketplace_fees = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = (
            'discount',
            'offer_price',
            'discount_mode',
            'subtotal',
            'discount_applied',
            'extra_money',
            'work_total',
            'penalty_total',
            'total',
            'car_count',
            'emergency_pricing',
            'platform_fee',
            'marketplace_fees',
        )

    def get_discount_mode(self, obj):
        return get_cached_order_pricing(obj, self.context)['discount_mode']

    def get_subtotal(self, obj):
        return format(get_cached_order_pricing(obj, self.context)['subtotal'], 'f')

    def get_discount_applied(self, obj):
        return format(get_cached_order_pricing(obj, self.context)['discount_applied'], 'f')

    def get_extra_money(self, obj):
        return format(get_cached_order_pricing(obj, self.context).get('extra_money', Decimal('0')), 'f')

    def get_work_total(self, obj):
        br = get_cached_order_pricing(obj, self.context)
        wt = br.get('work_total', br.get('total'))
        return format(Decimal(str(wt)), 'f')

    def get_penalty_total(self, obj):
        return format(Decimal(str(get_cached_order_pricing(obj, self.context).get('penalty_total', 0))), 'f')

    def get_total(self, obj):
        return format(get_cached_order_pricing(obj, self.context)['total'], 'f')

    def get_car_count(self, obj):
        return get_cached_order_pricing(obj, self.context).get('car_count', 1)

    def get_emergency_pricing(self, obj):
        """
        Emergency (SOS) price metadata:
        - coefficient: 1.3 (day) / 1.6 (night) / 1.0 (non-SOS)
        - base prices are not shown here, only per-line in services.
        """
        br = get_cached_order_pricing(obj, self.context)
        em = (br.get('emergency') or {}).copy()
        coef = em.get('coefficient', Decimal('1.0'))
        em['coefficient'] = format(Decimal(str(coef)), 'f')
        # Expose both base subtotal and final subtotal for SOS pricing UI.
        em['base_subtotal'] = format(Decimal(str(br.get('base_subtotal', br.get('subtotal', 0)))), 'f')
        em['final_subtotal'] = format(Decimal(str(br.get('subtotal', 0))), 'f')
        return em

    def get_offer_price(self, obj):
        br = get_cached_order_pricing(obj, self.context)
        v = br.get('offer_price')
        return format(Decimal(str(v)), 'f') if v is not None else None

    def get_platform_fee(self, obj):
        """Client platform fee ($); same field name for standard, custom_request, and SOS."""
        return order_pricing_platform_fee(obj)

    def get_marketplace_fees(self, obj):
        """TZ-aligned fee lines: scheduled vs emergency; client vs master (see checkout_fees)."""
        return build_order_marketplace_fee_display(obj)


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
    offer_price = serializers.SerializerMethodField()
    chat_room_id = serializers.IntegerField(read_only=True)
    latitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS, required=False, allow_null=True)
    longitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS, required=False, allow_null=True)

    pricing = OrderPricingNestedSerializer(source='*', read_only=True)
    workflow = OrderWorkflowNestedSerializer(source='*', read_only=True)
    eta = OrderEtaNestedSerializer(source='*', read_only=True)
    timestamps = OrderTimestampsNestedSerializer(source='*', read_only=True)
    payment_type = serializers.CharField(read_only=True)
    saved_card = serializers.SerializerMethodField()
    stripe_payment_intent_id = serializers.SerializerMethodField()
    stripe_payment_status = serializers.SerializerMethodField()
    stripe_payment_amount_cents = serializers.SerializerMethodField()
    stripe_payment_currency = serializers.SerializerMethodField()
    post_completion = serializers.SerializerMethodField()
    towing = serializers.SerializerMethodField()
    fuel_delivery_type_display = serializers.SerializerMethodField()
    fuel_delivery_summary = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'user', 'order_type', 'order_type_display',
            'car_data', 'category_data',
            'text', 'status', 'status_display', 'priority', 'priority_display',
            'location', 'latitude', 'longitude', 'location_precision',
            'towing',
            'fuel_delivery_type',
            'fuel_delivery_type_display',
            'fuel_delivery_summary',
            'parts_purchase_required',
            'parts_purchase_required_json',
            'preferred_date', 'preferred_time_start', 'preferred_time_end',
            'master',
            'average_price',
            'average_service_name',
            'order_penalty_total',
            'offer_price',
            'pricing', 'services', 'reviews', 'average_rating',
            'workflow', 'eta',
            'order_images', 'work_completion_images',
            'timestamps', 'cancellation',
            'client_completion_pin',
            'custom_request_selected_offer',
            'chat_room_id',
            'payment_type', 'saved_card',
            'stripe_payment_intent_id', 'stripe_payment_status',
            'stripe_payment_amount_cents', 'stripe_payment_currency',
            'post_completion',
        ]
        read_only_fields = [
            'id',
            'workflow', 'eta', 'timestamps', 'pricing',
            'order_penalty_total',
        ]
    
    def get_user(self, obj):
        return UserSerializer(obj.user, context=self.context).data

    def get_saved_card(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated or obj.user_id != request.user.id:
            return None
        if not obj.saved_card_id:
            return None
        try:
            c = obj.saved_card
        except Exception:
            return None
        return {'id': c.id, 'brand': c.brand, 'last4': c.last4}

    def _payment_privileged(self, obj):
        request = self.context.get('request')
        return bool(request and request.user.is_authenticated and obj.user_id == request.user.id)

    def get_stripe_payment_intent_id(self, obj):
        return obj.stripe_payment_intent_id if self._payment_privileged(obj) else None

    def get_stripe_payment_status(self, obj):
        return obj.stripe_payment_status if self._payment_privileged(obj) else None

    def get_stripe_payment_amount_cents(self, obj):
        return obj.stripe_payment_amount_cents if self._payment_privileged(obj) else None

    def get_stripe_payment_currency(self, obj):
        return obj.stripe_payment_currency if self._payment_privileged(obj) else None

    def get_post_completion(self, obj):
        """Driver post-completion flow: review, rating, tip modal."""
        if not self._payment_privileged(obj):
            return None
        return build_post_completion_payload(obj)

    def get_towing(self, obj):
        if obj.order_type != OrderType.TOWING:
            return None
        return {
            'pickup': {
                'location': obj.location or '',
                'latitude': obj.latitude,
                'longitude': obj.longitude,
            },
            'delivery': {
                'location': obj.delivery_location or '',
                'latitude': obj.delivery_latitude,
                'longitude': obj.delivery_longitude,
            },
            'distance_miles': (
                format(Decimal(str(obj.towing_distance_miles)), 'f')
                if obj.towing_distance_miles is not None
                else None
            ),
            'base_fee': (
                format(Decimal(str(obj.towing_base_fee)), 'f')
                if obj.towing_base_fee is not None
                else None
            ),
            'price_per_mile': (
                format(Decimal(str(obj.towing_price_per_mile)), 'f')
                if obj.towing_price_per_mile is not None
                else None
            ),
            'minimum_fee': (
                format(Decimal(str(obj.towing_minimum_fee)), 'f')
                if obj.towing_minimum_fee is not None
                else None
            ),
            'total_price': (
                format(Decimal(str(obj.towing_total)), 'f')
                if obj.towing_total is not None
                else None
            ),
            'trip_type': obj.towing_trip_type,
        }

    def get_fuel_delivery_type_display(self, obj):
        if not obj.fuel_delivery_type:
            return None
        try:
            return str(FuelDeliveryType(obj.fuel_delivery_type).label)
        except ValueError:
            return obj.fuel_delivery_type

    def get_fuel_delivery_summary(self, obj):
        label = self.get_fuel_delivery_type_display(obj)
        if not label:
            return None
        return f'Delivery of 2 gallons of fuel ({label})'

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

    def get_offer_price(self, obj):
        """
        Explicit offer base for custom requests.
        If there is no matched offer (pending/unassigned), return null.
        """
        br = get_cached_order_pricing(obj, self.context)
        v = br.get('offer_price')
        return format(Decimal(str(v)), 'f') if v is not None else None

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
        cache = getattr(obj, '_prefetched_objects_cache', None) or {}
        if 'category' in cache:
            categories = sorted(
                cache['category'],
                key=lambda c: ((c.parent_id or 0), (c.name or '')),
            )
        else:
            categories = list(
                obj.category.all().select_related('parent').order_by('parent_id', 'name')
            )
        from apps.categories.services.fuel_delivery_catalog import is_fuel_delivery_category

        fuel_type_by_category_id = {}
        for os_row in obj.order_services.all().select_related('master_service_item__category'):
            item = os_row.master_service_item
            if not item or not item.category_id or not os_row.fuel_type:
                continue
            fuel_type_by_category_id[item.category_id] = os_row.fuel_type

        groups = {}
        mask_for_master = _request_user_is_master(request) and (
            obj.order_type in (OrderType.CUSTOM_REQUEST, OrderType.TOWING)
            or any(getattr(c, 'is_custom_request_entry', False) for c in categories)
            or any(getattr(c, 'is_towing_entry', False) for c in categories)
        )
        for cat in categories:
            parent = cat.parent
            gid = parent.id if parent is not None else 0
            if gid not in groups:
                p_block = None
                if parent:
                    parent_mask = None
                    if mask_for_master:
                        if parent.is_custom_request_entry:
                            parent_mask = CUSTOM_REQUEST_CATEGORY_MASK_MASTER
                        elif parent.is_towing_entry:
                            parent_mask = TOWING_CATEGORY_MASK_MASTER
                    p_block = {
                        'id': parent.id,
                        'name': parent_mask or parent.name,
                        'icon': _absolute_media_url(request, parent.icon),
                    }
                groups[gid] = {'parent': p_block, 'items': []}
            item_mask = None
            if mask_for_master:
                if cat.is_custom_request_entry or (cat.parent and cat.parent.is_custom_request_entry):
                    item_mask = CUSTOM_REQUEST_CATEGORY_MASK_MASTER
                elif cat.is_towing_entry or (cat.parent and cat.parent.is_towing_entry):
                    item_mask = TOWING_CATEGORY_MASK_MASTER
            item_name = item_mask or cat.name
            item_payload = {
                'id': cat.id,
                'name': item_name,
                'type_category': cat.type_category,
                'icon': _absolute_media_url(request, cat.icon),
            }
            if is_fuel_delivery_category(cat):
                ft = fuel_type_by_category_id.get(cat.id)
                if ft:
                    item_payload['fuel_type'] = ft
                    try:
                        item_payload['fuel_type_display'] = str(FuelDeliveryType(ft).label)
                    except ValueError:
                        item_payload['fuel_type_display'] = ft
                    item_payload['fuel_delivery_summary'] = (
                        f'Delivery of 2 gallons of fuel ({item_payload["fuel_type_display"]})'
                    )
            groups[gid]['items'].append(item_payload)
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
        em = br.get('emergency') or {}
        coef = em.get('coefficient', Decimal('1.0'))
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
            line['count'] = int(getattr(os_row, 'count', 1) or 1)
            if os_row.fuel_type:
                line['fuel_type'] = os_row.fuel_type
                try:
                    line['fuel_type_display'] = str(FuelDeliveryType(os_row.fuel_type).label)
                except ValueError:
                    line['fuel_type_display'] = os_row.fuel_type
                line['fuel_delivery_summary'] = (
                    f'Delivery of 2 gallons of fuel ({line["fuel_type_display"]})'
                )
            meta = br['lines_by_order_service_id'].get(os_row.id)
            if meta:
                line['discount_allocated'] = format(meta['discount_allocated'], 'f')
                line['line_total'] = format(meta['line_total'], 'f')
                line['car_count'] = meta.get('car_count', br.get('car_count', 1))
                line['count'] = int(meta.get('service_count', line.get('count', 1)) or 1)
                # Emergency: expose base/coefficient/final (unit) prices.
                base_u = meta.get('base_unit_price')
                if base_u is not None:
                    line['base_price'] = format(Decimal(str(base_u)), 'f')
                else:
                    line['base_price'] = _money_fmt(line.get('price'))
                line['emergency_coefficient'] = format(Decimal(str(meta.get('emergency_coefficient', coef))), 'f')
                # `price` in master_service_item_line_dict is the base price; show final separately.
                line['final_price'] = format(Decimal(str(meta.get('unit_price'))), 'f')
            else:
                line['discount_allocated'] = '0.00'
                line['line_total'] = _money_fmt(line.get('price'))
                line['car_count'] = br.get('car_count', 1)
                line['base_price'] = _money_fmt(line.get('price'))
                line['emergency_coefficient'] = format(Decimal(str(coef)), 'f')
                line['final_price'] = _money_fmt(line.get('price'))
            groups[gid]['items'].append(line)
        return list(groups.values())
    
    def get_reviews(self, obj):
        """Get order reviews"""
        request = self.context.get('request')
        review = self._get_order_review(obj)
        if review is None:
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
        ]

    def _get_order_review(self, obj):
        try:
            return obj.review
        except Exception:
            from apps.order.models import Review

            return Review.objects.filter(order_id=obj.pk).select_related('reviewer').first()

    def get_average_rating(self, obj):
        """Get order average rating"""
        review = self._get_order_review(obj)
        if review is None:
            return None
        return round(float(review.rating), 2)

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
    parts_purchase_required_json = serializers.ListField(
        child=PartsPurchaseRequiredItemSerializer(),
        required=False,
        default=list,
        help_text=(
            'Parts to buy list. Example: '
            '[{ "vehicle_vin": "", "part_name": "", "is_address": true }]. '
            'Aliases accepted: "vehicle vin", "part name", "is_addess".'
        ),
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
    average_price = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        allow_null=True,
        help_text='Optional: average price estimate for this order.',
    )
    average_service_name = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=255,
        help_text='Optional: service name/label associated with average_price.',
    )
    fuel_type = serializers.ChoiceField(
        choices=FuelDeliveryType.choices,
        required=False,
        allow_null=True,
        help_text=(
            'Required when category_list includes Fuel Delivery: '
            'gasoline or diesel (delivery of 2 gallons of fuel).'
        ),
    )

    class Meta:
        model = Order
        fields = [
            'order_type', 'text', 'priority', 'location', 'latitude', 'longitude',
            'average_price',
            'average_service_name',
            'master_id',
            'car_list', 'category_list',
            'fuel_type',
            'parts_purchase_required',
            'parts_purchase_required_json',
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
        if v == OrderType.TOWING:
            raise serializers.ValidationError("Use POST /api/order/towing/ for towing orders.")
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
                from apps.order.services.order_scheduled_start import (
                    scheduled_slot_is_in_future,
                    scheduled_slot_past_cancel_deadline,
                )

                if not scheduled_slot_is_in_future(preferred_date=pd, preferred_time_start=ps):
                    raise serializers.ValidationError(
                        {
                            'preferred_time_start': (
                                'Scheduled start time must be in the future (service timezone).'
                            )
                        }
                    )
                if scheduled_slot_past_cancel_deadline(
                    preferred_date=pd,
                    preferred_time_start=ps,
                ):
                    raise serializers.ValidationError(
                        {
                            'preferred_time_start': (
                                'Scheduled time window has already passed; choose a later slot.'
                            )
                        }
                    )
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
                queue = filter_master_ids_meeting_emergency_thresholds(queue)
                if not queue:
                    raise serializers.ValidationError({
                        'category_list': (
                            'No masters with this service are available within their acceptance zones '
                            'for this location, or none meet emergency acceptance/completion rate requirements.'
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
                if order_type == OrderType.SOS and not master_meets_emergency_offer_thresholds(master_id):
                    raise serializers.ValidationError({
                        'master_id': (
                            'This master does not meet emergency order acceptance/completion rate requirements.'
                        ),
                    })

            except Master.DoesNotExist:
                pass

        from apps.categories.services.fuel_delivery_catalog import categories_include_fuel_delivery
        from apps.master.services.fuel_delivery import master_has_active_fuel_delivery

        cats = attrs.get('category_list') or []
        needs_fuel_type = categories_include_fuel_delivery([int(c) for c in cats])
        fuel_type = attrs.get('fuel_type')
        if needs_fuel_type:
            if not fuel_type:
                raise serializers.ValidationError({
                    'fuel_type': (
                        'Select fuel type (gasoline or diesel) for Fuel Delivery — '
                        'delivery of 2 gallons of fuel.'
                    ),
                })
            if fuel_type not in FuelDeliveryType.values:
                raise serializers.ValidationError({
                    'fuel_type': 'Invalid fuel type. Use gasoline or diesel.',
                })
            fuel_cat_ids = list(
                Category.objects.filter(id__in=cats, name__iexact='Fuel Delivery').values_list('id', flat=True)
            )
            if master_id and fuel_cat_ids:
                for cid in fuel_cat_ids:
                    if not master_has_active_fuel_delivery(int(master_id), int(cid)):
                        raise serializers.ValidationError({
                            'master_id': (
                                'Selected master has not activated Fuel Delivery '
                                '(both 2-gallon fuel containers must be confirmed).'
                            ),
                        })
        elif fuel_type:
            raise serializers.ValidationError({
                'fuel_type': 'fuel_type is only used when Fuel Delivery is in category_list.',
            })

        return attrs

    def create(self, validated_data):
        """Create order with cars and categories"""
        master_id = validated_data.pop('master_id', None)
        sos_queue = validated_data.pop('_sos_queue', None)
        car_list = validated_data.pop('car_list', [])
        category_list = validated_data.pop('category_list', [])
        fuel_type = validated_data.pop('fuel_type', None)

        if master_id and validated_data.get('order_type') == OrderType.STANDARD:
            validated_data['master'] = Master.objects.get(id=master_id)

        if fuel_type:
            validated_data['fuel_delivery_type'] = fuel_type

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
    average_price = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        allow_null=True,
        help_text='Optional: average price estimate for this order.',
    )
    average_service_name = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=255,
        help_text='Optional: service name/label associated with average_price.',
    )
    preferred_date = serializers.DateField(
        required=False,
        allow_null=True,
        help_text='Preferred service date for this custom request (YYYY-MM-DD).',
    )
    preferred_time_start = LenientTimeField(
        required=False,
        allow_null=True,
        help_text='Preferred time start for this custom request (HH:MM). Optional; send together with preferred_date.',
    )
    car_list = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        default=list,
    )
    parts_purchase_required = serializers.BooleanField(required=False, default=False)
    parts_purchase_required_json = serializers.ListField(
        child=PartsPurchaseRequiredItemSerializer(),
        required=False,
        default=list,
        help_text=(
            'Parts to buy list. Example: '
            '[{ "vehicle_vin": "", "part_name": "", "is_address": true }]. '
            'Aliases accepted: "vehicle vin", "part name", "is_addess".'
        ),
    )

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
        pd = attrs.get('preferred_date')
        ps = attrs.get('preferred_time_start')
        if (pd is None) ^ (ps is None):
            raise serializers.ValidationError(
                'preferred_date and preferred_time_start must both be sent together, or omit both.'
            )
        return attrs

    def create(self, validated_data):
        from apps.order.services.custom_request_broadcast import get_custom_request_catalog_category

        user = self.context['request'].user
        car_list = validated_data.pop('car_list', [])
        pd = validated_data.pop('preferred_date', None)
        ps = validated_data.pop('preferred_time_start', None)
        cat = get_custom_request_catalog_category()
        order = Order.objects.create(
            user=user,
            text=validated_data['text'],
            location=validated_data['location'],
            latitude=validated_data['latitude'],
            longitude=validated_data['longitude'],
            average_price=validated_data.get('average_price'),
            average_service_name=(validated_data.get('average_service_name') or None),
            order_type=OrderType.CUSTOM_REQUEST,
            status=OrderStatus.PENDING,
            priority=OrderPriority.LOW,
            location_source=LocationSource.GPS_CUSTOM,
            parts_purchase_required=validated_data.get('parts_purchase_required', False),
            parts_purchase_required_json=validated_data.get('parts_purchase_required_json', []),
            preferred_date=pd,
            preferred_time_start=ps,
        )
        if car_list:
            order.car.set(list(dict.fromkeys(car_list)))
        order.category.set([cat.pk])
        return order


class TowingEstimateRequestSerializer(serializers.Serializer):
    """Pickup + delivery coords or explicit miles for price estimate."""

    latitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS, help_text='Pickup latitude')
    longitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS, help_text='Pickup longitude')
    delivery_latitude = serializers.DecimalField(
        **WGS84_COORD_DECIMAL_KWARGS,
        required=False,
        allow_null=True,
    )
    delivery_longitude = serializers.DecimalField(
        **WGS84_COORD_DECIMAL_KWARGS,
        required=False,
        allow_null=True,
    )
    distance_miles = serializers.DecimalField(
        max_digits=8,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=Decimal('0.01'),
        help_text='Optional: override computed pickup→delivery distance.',
    )
    radius_miles = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        max_value=200,
        help_text='Search radius around pickup (default from settings).',
    )

    def validate(self, attrs):
        miles = attrs.get('distance_miles')
        dlat = attrs.get('delivery_latitude')
        dlon = attrs.get('delivery_longitude')
        if miles is None and (dlat is None or dlon is None):
            raise serializers.ValidationError(
                'Send delivery_latitude + delivery_longitude, or distance_miles.'
            )
        if (dlat is None) ^ (dlon is None):
            raise serializers.ValidationError(
                'delivery_latitude and delivery_longitude must be sent together.'
            )
        return attrs


class TowingCreateSerializer(serializers.Serializer):
    """Create towing order with pre-selected master and locked mileage price."""

    master_id = serializers.IntegerField()
    car_list = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False,
    )
    text = serializers.CharField(required=False, allow_blank=True, default='Towing service')
    location = serializers.CharField(help_text='Pickup address')
    latitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS)
    longitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS)
    delivery_location = serializers.CharField(required=False, allow_blank=True, default='')
    delivery_latitude = serializers.DecimalField(
        **WGS84_COORD_DECIMAL_KWARGS,
        required=False,
        allow_null=True,
    )
    delivery_longitude = serializers.DecimalField(
        **WGS84_COORD_DECIMAL_KWARGS,
        required=False,
        allow_null=True,
    )
    distance_miles = serializers.DecimalField(
        max_digits=8,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=Decimal('0.01'),
    )

    def validate_car_list(self, value):
        user = self.context['request'].user
        seen = []
        for car_id in dict.fromkeys(value):
            try:
                car = Car.objects.get(id=car_id)
            except Car.DoesNotExist:
                raise serializers.ValidationError(f'Car with ID {car_id} not found')
            if car.user_id != user.id:
                raise serializers.ValidationError(f'Car {car_id} does not belong to you.')
            seen.append(car_id)
        return seen

    def validate_master_id(self, value):
        try:
            Master.objects.get(id=value)
        except Master.DoesNotExist:
            raise serializers.ValidationError(f'Master with ID {value} not found')
        return value

    def validate(self, attrs):
        from apps.master.models import MasterTowingPricing
        from apps.order.services.towing_pricing import (
            calculate_towing_price_for_pricing,
            resolve_towing_distance_miles,
        )

        miles_in = attrs.get('distance_miles')
        dlat = attrs.get('delivery_latitude')
        dlon = attrs.get('delivery_longitude')
        if miles_in is None and (dlat is None or dlon is None):
            raise serializers.ValidationError(
                'Send delivery_latitude + delivery_longitude, or distance_miles.'
            )
        if (dlat is None) ^ (dlon is None):
            raise serializers.ValidationError(
                'delivery_latitude and delivery_longitude must be sent together.'
            )

        master = Master.objects.get(id=attrs['master_id'])
        try:
            pricing = MasterTowingPricing.objects.get(master=master, is_active=True)
        except MasterTowingPricing.DoesNotExist:
            raise serializers.ValidationError({'master_id': 'This master has no active towing pricing.'})

        pickup_lat = float(attrs['latitude'])
        pickup_lon = float(attrs['longitude'])
        wlat, wlon = master.get_work_location_for_distance()
        if wlat is None:
            raise serializers.ValidationError(
                {'master_id': 'Selected master has no work location coordinates.'}
            )
        distance_km = haversine_distance_km(pickup_lat, pickup_lon, wlat, wlon)
        max_km = master.max_order_distance_km()
        if distance_km > max_km:
            d_mi = km_to_miles(distance_km)
            max_mi = km_to_miles(max_km)
            raise serializers.ValidationError(
                {
                    'master_id': (
                        f'Selected master is too far from pickup ({d_mi:.1f} mi; limit {max_mi:.1f} mi).'
                    )
                }
            )

        try:
            distance_miles = resolve_towing_distance_miles(
                pickup_lat=pickup_lat,
                pickup_lon=pickup_lon,
                delivery_lat=float(dlat) if dlat is not None else None,
                delivery_lon=float(dlon) if dlon is not None else None,
                distance_miles=miles_in,
            )
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

        breakdown = calculate_towing_price_for_pricing(pricing, distance_miles)
        attrs['_pricing'] = pricing
        attrs['_distance_miles'] = distance_miles
        attrs['_breakdown'] = breakdown
        attrs['_trip_type'] = breakdown.get('trip_type')
        return attrs

    def create(self, validated_data):
        from apps.order.services.towing_catalog import get_towing_catalog_category

        pricing = validated_data.pop('_pricing')
        distance_miles = validated_data.pop('_distance_miles')
        breakdown = validated_data.pop('_breakdown')
        trip_type = validated_data.pop('_trip_type', None)
        master_id = validated_data.pop('master_id')
        car_list = validated_data.pop('car_list', [])
        text = (validated_data.pop('text', None) or 'Towing service').strip() or 'Towing service'

        cat = get_towing_catalog_category()
        if cat is None:
            raise serializers.ValidationError(
                'Towing category is not configured. Set is_towing_entry on a main by_order category.'
            )

        master = Master.objects.get(id=master_id)
        order = Order.objects.create(
            user=self.context['request'].user,
            master=master,
            order_type=OrderType.TOWING,
            status=OrderStatus.PENDING,
            priority=OrderPriority.HIGH,
            location_source=LocationSource.GPS_CUSTOM,
            text=text,
            location=validated_data['location'],
            latitude=validated_data['latitude'],
            longitude=validated_data['longitude'],
            delivery_location=validated_data.get('delivery_location') or '',
            delivery_latitude=validated_data.get('delivery_latitude'),
            delivery_longitude=validated_data.get('delivery_longitude'),
            towing_distance_miles=distance_miles,
            towing_base_fee=Decimal(breakdown['base_fee']),
            towing_price_per_mile=Decimal(breakdown['price_per_mile']),
            towing_minimum_fee=pricing.minimum_fee,
            towing_trip_type=trip_type,
            towing_total=Decimal(breakdown['total_price']),
            average_price=Decimal(breakdown['total_price']),
            average_service_name='Towing',
        )
        if car_list:
            order.car.set(list(dict.fromkeys(car_list)))
        order.category.set([cat.pk])

        if order.status == OrderStatus.PENDING:
            activate_pending_master_offer(order, request=self.context.get('request'))
            try:
                from apps.order.services.towing_notifications import notify_towing_order_created

                notify_towing_order_created(order, request=self.context.get('request'))
            except Exception:  # noqa: BLE001
                pass
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
    fuel_type_display = serializers.SerializerMethodField()

    class Meta:
        model = OrderService
        fields = [
            'id',
            'order',
            'master_service_item',
            'count',
            'unit_price',
            'fuel_type',
            'fuel_type_display',
            'service_details',
            'created_at',
        ]
        read_only_fields = ['id', 'unit_price', 'created_at']

    def get_fuel_type_display(self, obj):
        if not obj.fuel_type:
            return None
        try:
            return str(FuelDeliveryType(obj.fuel_type).label)
        except ValueError:
            return obj.fuel_type

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
    comment = serializers.CharField(
        required=False,
        allow_blank=True,
        default='',
        help_text='Optional comment/reason for adding services (for client confirmation).',
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


class OrderServiceCountPatchSerializer(serializers.Serializer):
    """Set quantity for one OrderService row (per service item)."""

    count = serializers.IntegerField(min_value=1)


class OrderExtraMoneyPatchSerializer(serializers.Serializer):
    """Increment order.extra_money by given amount."""

    extra_money = serializers.DecimalField(max_digits=12, decimal_places=2)


class OrderExtraMoneyRequestCreateSerializer(serializers.Serializer):
    """Master creates an extra money request (pending client approval)."""

    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    comment = serializers.CharField(required=False, allow_blank=True, default='')


class OrderExtraMoneyRequestDecisionSerializer(serializers.Serializer):
    """Client approves/rejects a request. Reject requires comment."""

    comment = serializers.CharField(required=False, allow_blank=True, default='')


class OrderExtraMoneyRequestSerializer(serializers.ModelSerializer):
    order_id = serializers.IntegerField(source='order.id', read_only=True)
    master_id = serializers.IntegerField(source='master.id', read_only=True)
    master_user_id = serializers.IntegerField(source='master.user_id', read_only=True)
    master = serializers.SerializerMethodField()
    order = serializers.SerializerMethodField()

    class Meta:
        model = OrderExtraMoneyRequest
        fields = [
            'id',
            'order_id',
            'master_id',
            'master_user_id',
            'master',
            'order',
            'amount',
            'master_comment',
            'status',
            'client_comment',
            'decided_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def get_master(self, obj):
        from apps.accounts.display_name import build_compact_master_user_payload

        m = getattr(obj, 'master', None)
        if not m:
            return None
        request = self.context.get('request') if isinstance(self.context, dict) else None
        return build_compact_master_user_payload(m, request, media_url_fn=_media_url)

    def get_order(self, obj):
        o = getattr(obj, 'order', None)
        if not o:
            return None
        return {
            'id': getattr(o, 'id', None),
            'order_number': getattr(o, 'order_number', None),
            'order_type': getattr(o, 'order_type', None),
            'status': getattr(o, 'status', None),
        }


class OrderTimeChangeRequestCreateSerializer(serializers.Serializer):
    """Master proposes a new service date/time (pending client approval)."""

    proposed_preferred_date = serializers.DateField()
    proposed_preferred_time_start = LenientTimeField()
    proposed_preferred_time_end = LenientTimeField(required=False, allow_null=True)
    comment = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, attrs):
        from apps.order.services.order_time_change import (
            has_pending_time_change,
            order_allows_time_change_proposal,
            validate_proposed_time_change,
        )

        order = self.context['order']
        err = order_allows_time_change_proposal(order)
        if err:
            raise serializers.ValidationError({'order': err})
        if has_pending_time_change(order.pk):
            raise serializers.ValidationError({'order': 'A time change request is already pending for this order.'})

        field_errors = validate_proposed_time_change(
            order=order,
            proposed_date=attrs['proposed_preferred_date'],
            proposed_time_start=attrs['proposed_preferred_time_start'],
            proposed_time_end=attrs.get('proposed_preferred_time_end'),
        )
        if field_errors:
            raise serializers.ValidationError(field_errors)
        return attrs


class OrderTimeChangeRequestDecisionSerializer(serializers.Serializer):
    comment = serializers.CharField(required=False, allow_blank=True, default='')


class OrderTimeChangeRequestSerializer(serializers.ModelSerializer):
    order_id = serializers.IntegerField(source='order.id', read_only=True)
    master_id = serializers.IntegerField(source='master.id', read_only=True)
    master_user_id = serializers.IntegerField(source='master.user_id', read_only=True)
    master = serializers.SerializerMethodField()
    order = serializers.SerializerMethodField()

    class Meta:
        model = OrderTimeChangeRequest
        fields = [
            'id',
            'order_id',
            'master_id',
            'master_user_id',
            'master',
            'order',
            'previous_preferred_date',
            'previous_preferred_time_start',
            'previous_preferred_time_end',
            'proposed_preferred_date',
            'proposed_preferred_time_start',
            'proposed_preferred_time_end',
            'master_comment',
            'status',
            'client_comment',
            'decided_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def get_master(self, obj):
        from apps.accounts.display_name import build_compact_master_user_payload

        m = getattr(obj, 'master', None)
        if not m:
            return None
        request = self.context.get('request') if isinstance(self.context, dict) else None
        return build_compact_master_user_payload(m, request, media_url_fn=_media_url)

    def get_order(self, obj):
        o = getattr(obj, 'order', None)
        if not o:
            return None
        return {
            'id': getattr(o, 'id', None),
            'order_number': getattr(o, 'order_number', None),
            'order_type': getattr(o, 'order_type', None),
            'status': getattr(o, 'status', None),
            'preferred_date': getattr(o, 'preferred_date', None),
            'preferred_time_start': getattr(o, 'preferred_time_start', None),
            'preferred_time_end': getattr(o, 'preferred_time_end', None),
        }


class OrderServiceAddRequestCreateSerializer(serializers.Serializer):
    """Master creates a pending request to add extra services (requires client approval)."""

    services_list = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False,
        help_text='List of MasterServiceItems IDs to add (duplicates increase count).',
    )
    comment = serializers.CharField(required=False, allow_blank=True, default='')


class OrderServiceAddRequestDecisionSerializer(serializers.Serializer):
    """Client approves/rejects a pending service-add request."""

    comment = serializers.CharField(required=False, allow_blank=True, default='')


class OrderServiceAddRequestSerializer(serializers.ModelSerializer):
    order_id = serializers.IntegerField(source='order.id', read_only=True)
    master_id = serializers.IntegerField(source='master.id', read_only=True)
    master_user_id = serializers.IntegerField(source='master.user_id', read_only=True)
    master = serializers.SerializerMethodField()
    order = serializers.SerializerMethodField()
    services_preview = serializers.SerializerMethodField()

    class Meta:
        model = OrderServiceAddRequest
        fields = [
            'id',
            'order_id',
            'master_id',
            'master_user_id',
            'master',
            'order',
            'services_json',
            'services_preview',
            'master_comment',
            'status',
            'client_comment',
            'decided_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields

    def get_master(self, obj):
        from apps.accounts.display_name import build_compact_master_user_payload

        m = getattr(obj, 'master', None)
        if not m:
            return None
        request = self.context.get('request') if isinstance(self.context, dict) else None
        return build_compact_master_user_payload(m, request, media_url_fn=_media_url)

    def get_order(self, obj):
        o = getattr(obj, 'order', None)
        if not o:
            return None
        return {
            'id': getattr(o, 'id', None),
            'order_number': getattr(o, 'order_number', None),
            'order_type': getattr(o, 'order_type', None),
            'status': getattr(o, 'status', None),
        }

    def get_services_preview(self, obj):
        """
        Lightweight preview for client popup:
        [{ master_service_item_id, name, unit_price, count, line_total }, ...] + subtotal
        """
        try:
            from decimal import Decimal
            from collections import defaultdict
            from apps.master.models import MasterServiceItems

            raw = getattr(obj, 'services_json', None) or []
            counts = defaultdict(int)
            for it in raw:
                if not isinstance(it, dict):
                    continue
                mid = it.get('master_service_item_id')
                cnt = it.get('count', 1)
                try:
                    mid = int(mid)
                    cnt = int(cnt or 1)
                except Exception:
                    continue
                if mid <= 0 or cnt <= 0:
                    continue
                counts[mid] += cnt

            if not counts:
                return {'items': [], 'subtotal': '0.00'}

            # Car multiplier matches pricing rules.
            try:
                car_count = max(1, int(obj.order.car.count()))
            except Exception:
                car_count = 1
            items_by_id = {
                x.id: x for x in MasterServiceItems.objects.filter(id__in=list(counts.keys())).select_related('category').only('id', 'price', 'category__name')
            }
            out_items = []
            subtotal = Decimal('0')
            for mid, cnt in counts.items():
                svc = items_by_id.get(mid)
                if not svc:
                    continue
                unit = Decimal(str(getattr(svc, 'price', 0) or 0)).quantize(Decimal('0.01'))
                line = (unit * Decimal(car_count) * Decimal(cnt)).quantize(Decimal('0.01'))
                subtotal += line
                out_items.append(
                    {
                        'master_service_item_id': mid,
                        'name': getattr(getattr(svc, 'category', None), 'name', None),
                        'unit_price': format(unit, 'f'),
                        'car_count': car_count,
                        'count': int(cnt),
                        'line_total': format(line, 'f'),
                    }
                )
            return {'items': out_items, 'subtotal': format(subtotal, 'f')}
        except Exception:  # noqa: BLE001
            return {'items': [], 'subtotal': '0.00'}


class EmergencyPriceEstimateRequestSerializer(serializers.Serializer):
    """
    Estimate SOS (emergency) price before order creation.
    Client sends GPS + selected service categories.
    """

    latitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS)
    longitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS)
    address = serializers.CharField(required=False, allow_blank=True, default='')
    category_list = serializers.ListField(
        child=serializers.IntegerField(),
        required=True,
        allow_empty=False,
        help_text='List of by_order category IDs selected by the client',
    )
    radius_miles = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=200,
        default=10,
        help_text='Search radius around client location (miles). Default 10.',
    )


class EmergencyPriceEstimateResponseSerializer(serializers.Serializer):
    """
    Estimated price range (avg/min/max) from nearby masters' configured prices,
    plus emergency coefficient (day/night) and the estimated emergency totals.
    """

    radius_miles = serializers.IntegerField()
    master_count = serializers.IntegerField()
    matched_master_count = serializers.IntegerField()
    category_count = serializers.IntegerField()

    coefficient = serializers.CharField()
    time_bucket = serializers.CharField(allow_null=True)
    time_zone = serializers.CharField(allow_null=True)

    base_min = serializers.CharField(allow_null=True)
    base_avg = serializers.CharField(allow_null=True)
    base_max = serializers.CharField(allow_null=True)

    emergency_min = serializers.CharField(allow_null=True)
    emergency_avg = serializers.CharField(allow_null=True)
    emergency_max = serializers.CharField(allow_null=True)

    note = serializers.CharField(allow_blank=True, required=False, default='')

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
    """
    Post-completion feedback: review + rating (+ optional tip), or tip-only / decline tip.
    Same endpoint: ``POST /api/order/reviews/create/``.
    """

    order_id = serializers.IntegerField(help_text='Order ID')
    tip_only = serializers.BooleanField(
        required=False,
        default=False,
        help_text='True to submit only a tip (or decline_tip) without a review.',
    )
    decline_tip = serializers.BooleanField(
        required=False,
        default=False,
        help_text='Client chose "No Thanks" on the tip modal.',
    )
    rating = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=5,
        help_text='Rating from 1 to 5 (required unless tip_only).',
    )
    comment = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text='Review comment',
    )
    tags = serializers.ListField(
        child=serializers.ChoiceField(choices=ReviewTag.choices),
        required=False,
        min_length=1,
        max_length=32,
        help_text='One or more ReviewTag values (required unless tip_only).',
    )
    tip_amount = serializers.DecimalField(
        required=False,
        max_digits=12,
        decimal_places=2,
        min_value=Decimal('0'),
        help_text='Optional tip in USD ($5 / $10 / $20 / custom). Charged off-session to saved card.',
    )

    def validate_order_id(self, value):
        request = self.context.get('request')
        try:
            order = Order.objects.get(id=value)
        except Order.DoesNotExist:
            raise serializers.ValidationError(f'Order with ID {value} not found')

        if order.status != OrderStatus.COMPLETED:
            raise serializers.ValidationError('Only completed orders support review/tip')

        if request and request.user.is_authenticated and order.user_id != request.user.id:
            raise serializers.ValidationError('You can only review or tip your own orders.')

        return value

    def validate(self, attrs):
        order = Order.objects.get(id=attrs['order_id'])
        tip_only = bool(attrs.get('tip_only'))
        decline_tip = bool(attrs.get('decline_tip'))
        tip_amount = attrs.get('tip_amount')
        has_review = Review.objects.filter(order=order).exists()
        tip_paid = order.tip_stripe_payment_status == OrderStripePaymentStatus.SUCCEEDED

        if tip_paid and (tip_amount is not None and tip_amount > 0):
            raise serializers.ValidationError({'tip_amount': 'A tip has already been paid for this order.'})

        if tip_only:
            if decline_tip:
                if tip_paid:
                    raise serializers.ValidationError({'decline_tip': 'Tip already paid for this order.'})
                if order.tip_declined:
                    raise serializers.ValidationError({'decline_tip': 'Tip already declined for this order.'})
                return attrs
            if tip_amount is None or tip_amount <= 0:
                raise serializers.ValidationError(
                    {'tip_amount': 'Provide tip_amount > 0 or set decline_tip=true.'}
                )
            if tip_paid:
                raise serializers.ValidationError({'tip_amount': 'Tip already paid for this order.'})
            return attrs

        if has_review:
            raise serializers.ValidationError({'order_id': 'A review for this order has already been submitted'})

        if not attrs.get('rating'):
            raise serializers.ValidationError({'rating': 'Rating is required.'})
        if not attrs.get('tags'):
            raise serializers.ValidationError({'tags': 'At least one tag is required.'})

        if tip_paid and tip_amount and tip_amount > 0:
            raise serializers.ValidationError({'tip_amount': 'Tip already paid for this order.'})

        return attrs


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
