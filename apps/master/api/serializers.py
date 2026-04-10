from datetime import date, timedelta
from decimal import Decimal

from drf_spectacular.utils import OpenApiExample, extend_schema_serializer
from rest_framework import serializers
from apps.master.models import (
    Master,
    MasterBusySlot,
    MasterImage,
    MasterScheduleDay,
    MasterService,
    MasterServiceItems,
)
from apps.categories.models import Category
from apps.master.services.validation import validate_skill_category
from apps.order.models import Order, OrderStatus, Rating
from apps.order.services.status_workflow import (
    master_cancellations_this_month,
    master_schedule_coverage_span_days,
    master_schedule_forward_horizon_days,
    master_schedule_missing_coverage_dates,
)
from django.contrib.auth import get_user_model
from apps.accounts.serializers import UserDetailsSerializer
from config.wgs84 import WGS84_COORD_DECIMAL_KWARGS

User = get_user_model()

SERVICE_AREA_RADIUS_CHOICES = (15, 45, 100)


def validate_master_service_area_triplet(attrs, instance=None):
    """latitude, longitude, and service_area_radius_miles together, or all omitted / cleared."""

    def _pick(key):
        if key in attrs:
            return attrs[key]
        if instance is not None:
            return getattr(instance, key, None)
        return None

    lat = _pick('latitude')
    lon = _pick('longitude')
    rad = _pick('service_area_radius_miles')
    any_set = any(v is not None for v in (lat, lon, rad))
    all_set = all(v is not None for v in (lat, lon, rad))
    if any_set and not all_set:
        raise serializers.ValidationError(
            'Set latitude, longitude, and service_area_radius_miles (15, 45, or 100) together, '
            'or leave all three unset.'
        )

class MasterImageSerializer(serializers.ModelSerializer):
    """Master images — `image` maydoni har doim to‘liq (absolute) URL."""

    class Meta:
        model = MasterImage
        fields = ['id', 'image', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        if instance.image and request:
            data['image'] = request.build_absolute_uri(instance.image.url)
        elif instance.image:
            data['image'] = instance.image.url
        return data


class MasterSerializer(serializers.ModelSerializer):
    """Master serializer"""
    latitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS, required=False, allow_null=True)
    longitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS, required=False, allow_null=True)
    user_info = serializers.SerializerMethodField()
    services = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    rating_data = serializers.SerializerMethodField()
    distance = serializers.SerializerMethodField()
    skills_profile = serializers.SerializerMethodField()
    schedule_profile = serializers.SerializerMethodField()
    completed_orders_count = serializers.SerializerMethodField()
    eta_minutes_approx = serializers.SerializerMethodField()
    min_service_price_for_category = serializers.SerializerMethodField()

    class Meta:
        model = Master
        fields = [
            'id', 'user_info', 'city', 'address',
            'latitude', 'longitude', 'service_area_radius_miles',
            'phone', 'working_time', 'services',
            'description', 'images',
            'rating_data', 'distance', 'completed_orders_count',
            'eta_minutes_approx', 'min_service_price_for_category',
            'created_at', 'updated_at',
            'last_activity', 'skills_profile', 'schedule_profile',
        ]
        read_only_fields = [
            'id', 'user', 'created_at', 'updated_at', 'last_activity', 'distance',
            'completed_orders_count', 'eta_minutes_approx', 'min_service_price_for_category',
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if self.context.get('hide_master_exact_location'):
            for k in (
                'address',
                'latitude',
                'longitude',
                'service_area_radius_miles',
            ):
                data.pop(k, None)
        return data
    
    def get_user_info(self, obj):
        """Get full user info"""
        user = obj.user
        return UserDetailsSerializer(user, context=self.context).data
    
    def get_services(self, obj):
        """Get master services"""
        qs = MasterService.objects.filter(master=obj)
        fid = self.context.get('filter_service_category_id')
        if fid is not None:
            qs = qs.filter(master_service_items__category_id=fid).distinct()
        return MasterServiceSerializer(qs, many=True, context=self.context).data
    
    def get_images(self, obj):
        """Get master images"""
        master_images = MasterImage.objects.filter(master=obj)
        return MasterImageSerializer(master_images, many=True, context=self.context).data
    
    def get_rating_data(self, obj):
        """Get rating data for master"""
        return self._get_rating_data_for_master(obj)
    
    def _get_rating_data_for_master(self, master):
        """Get rating data for master"""
        ratings = Rating.objects.filter(master=master)
        if not ratings.exists():
            return {
                'average_rating': 0,
                'total_ratings': 0,
                'ratings': []
            }
        
        total_ratings = ratings.count()
        average_rating = sum(r.rating for r in ratings) / total_ratings
        
        return {
            'average_rating': round(average_rating, 2),
            'total_ratings': total_ratings,
            'ratings': [
                {
                    'id': r.id,
                    'rating': r.rating,
                    'comment': r.comment,
                    'user_name': r.user.get_full_name(),
                    'created_at': r.created_at
                }
                for r in ratings[:10]  # Last 10 ratings
            ]
        }
    
    def get_distance(self, obj):
        """Get distance from user (if computed)"""
        # If distance was set in view, return it
        return getattr(obj, 'distance', None)

    def get_completed_orders_count(self, obj):
        c = getattr(obj, 'completed_orders_count', None)
        if c is not None:
            return c
        return Order.objects.filter(master=obj, status=OrderStatus.COMPLETED).count()

    def get_eta_minutes_approx(self, obj):
        """Грубая оценка времени в пути: расстояние / 30 км/ч."""
        d_km = getattr(obj, 'distance', None)
        if d_km is None:
            return None
        hours = float(d_km) / 30.0
        return max(1, int(round(hours * 60)))

    def get_min_service_price_for_category(self, obj):
        fid = self.context.get('filter_service_category_id')
        embed = self.context.get('embed_order_min_price')
        from django.db.models import Min

        def _min_price(qs):
            m = qs.aggregate(m=Min('price')).get('m')
            return float(m) if m is not None else None

        if fid is not None:
            v = _min_price(
                MasterServiceItems.objects.filter(master_service__master=obj, category_id=fid)
            )
            if v is not None:
                return v
        if embed:
            return _min_price(MasterServiceItems.objects.filter(master_service__master=obj))
        return None

    def get_skills_profile(self, obj):
        items = MasterServiceItems.objects.filter(master_service__master=obj)
        count = items.count()
        parent_ids = set(items.values_list('category__parent_id', flat=True))
        parent_groups = len([p for p in parent_ids if p is not None])
        recommendation = None
        if count < 3:
            recommendation = 'Add more skills to increase your earnings.'
        return {
            'skill_count': count,
            'parent_group_count': parent_groups,
            'recommendation_message': recommendation,
        }

    def get_schedule_profile(self, obj):
        from django.utils import timezone

        today = timezone.localdate()
        span = master_schedule_coverage_span_days(obj)
        horizon_end = today + timedelta(days=span - 1)
        qs = MasterScheduleDay.objects.filter(master=obj, date__gte=today, date__lte=horizon_end)
        scheduled_dates = set(qs.values_list('date', flat=True))
        missing_list = master_schedule_missing_coverage_dates(obj)
        missing_set = set(missing_list)
        last_any = (
            MasterScheduleDay.objects.filter(master=obj, date__gte=today)
            .order_by('-date')
            .values_list('date', flat=True)
            .first()
        )
        needs = bool(missing_set)
        cap = master_schedule_forward_horizon_days(obj)
        return {
            'min_days_ahead_required': span,
            'scheduled_days_in_next_14': len(scheduled_dates),
            'missing_days_in_next_14': len(missing_set),
            'last_scheduled_date': last_any.isoformat() if last_any else None,
            'needs_extension': needs,
            'reminder_message': 'Update your schedule to receive more orders.' if needs else None,
            'master_cancellations_this_month': master_cancellations_this_month(obj),
            'schedule_forward_horizon_days_cap': cap,
        }


@extend_schema_serializer(
    examples=[
        OpenApiExample(
            'Namuna (barcha maydonlar)',
            summary='Standart namuna',
            description='latitude/longitude — map pin; service_area_radius_miles — 15, 45, or 100 (set all three together).',
            value={
                'city': 'Toshkent',
                'address': "Amir Temur ko'chasi, 15",
                'latitude': 41.3111,
                'longitude': 69.2797,
                'service_area_radius_miles': 45,
                'phone': '+998901234567',
                'working_time': 'Dush-Juma 09:00-18:00, Shan 10:00-15:00',
                'description': "To'liq avtoservis, diagnostika va ta'mirlash.",
            },
            request_only=True,
        ),
    ],
)
class MasterCreateSerializer(serializers.ModelSerializer):
    """Master create (no skills here — use POST /api/master/service-items/)."""

    latitude = serializers.DecimalField(
        **WGS84_COORD_DECIMAL_KWARGS,
        required=False,
        allow_null=True,
        help_text='Latitude -90…90 — workshop map pin; set with longitude + service_area_radius_miles.',
    )
    longitude = serializers.DecimalField(
        **WGS84_COORD_DECIMAL_KWARGS,
        required=False,
        allow_null=True,
        help_text='Longitude -180…180 — same point as workshop map pin; set with latitude + service_area_radius_miles.',
    )
    service_area_radius_miles = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text='15, 45, or 100 (miles) around latitude/longitude — set together with both coordinates.',
    )

    images = serializers.ListField(
        child=serializers.ImageField(required=False),
        write_only=True,
        required=False,
        allow_empty=True,
        help_text="multipart/form-data: repeat field name 'images' for each file (Swagger shows as array of files).",
    )

    class Meta:
        model = Master
        fields = [
            'city', 'address', 'latitude', 'longitude', 'service_area_radius_miles',
            'phone', 'working_time',
            'description', 'images',
        ]
        extra_kwargs = {
            'city': {'required': False, 'allow_blank': True},
            'address': {'required': False, 'allow_blank': True},
            'phone': {'required': False, 'allow_blank': True},
            'working_time': {'required': False, 'allow_blank': True},
            'description': {'required': False, 'allow_blank': True, 'allow_null': True},
        }
    
    def to_internal_value(self, data):
        """Convert data from multipart/form-data"""
        from django.http import QueryDict

        # Создаем обычный dict из данных для возможности модификации
        if isinstance(data, QueryDict):
            data_dict = {}
            for key in data.keys():
                if key == 'images':
                    files = [f for f in data.getlist(key) if f]
                    if files:
                        data_dict[key] = files
                    continue
                value = data.get(key)
                if value is not None:
                    data_dict[key] = value
            data = data_dict
        elif hasattr(data, 'copy'):
            data = data.copy()
        else:
            data = dict(data)

        def _coerce_float_key(d, key):
            if key not in d:
                return
            v = d.get(key)
            if isinstance(v, str):
                s = v.replace(',', '.').strip()
                if not s:
                    return
                try:
                    d[key] = float(s)
                except ValueError:
                    pass

        _coerce_float_key(data, 'latitude')
        _coerce_float_key(data, 'longitude')

        return super().to_internal_value(data)
    
    def validate_latitude(self, value):
        """Validate latitude; store as Decimal for the model."""
        if value is None:
            return None
        f = float(value)
        if not (-90 <= f <= 90):
            raise serializers.ValidationError('Latitude must be between -90 and 90')
        return value

    def validate_longitude(self, value):
        if value is None:
            return None
        f = float(value)
        if not (-180 <= f <= 180):
            raise serializers.ValidationError('Longitude must be between -180 and 180')
        return value

    def validate_service_area_radius_miles(self, value):
        if value is None:
            return None
        if value not in SERVICE_AREA_RADIUS_CHOICES:
            raise serializers.ValidationError(f'Radius must be one of: {", ".join(map(str, SERVICE_AREA_RADIUS_CHOICES))} miles.')
        return value

    def validate(self, attrs):
        validate_master_service_area_triplet(attrs, instance=getattr(self, 'instance', None))
        return attrs

    def create(self, validated_data):
        """Create master with automatic user assignment"""
        from django.contrib.auth.models import Group

        validated_data.pop('images', None)
        user = self.context['request'].user
        validated_data['user'] = user

        master = super().create(validated_data)

        master_group, created = Group.objects.get_or_create(name='Master')
        if not user.groups.filter(name='Master').exists():
            user.groups.add(master_group)

        return master


@extend_schema_serializer(
    examples=[
        OpenApiExample(
            'Namuna yangilash',
            summary='PATCH/PUT namunasi',
            value={
                'city': 'Toshkent',
                'address': 'Navoiy ko‘chasi, 10',
                'latitude': 41.2995,
                'longitude': 69.2401,
                'service_area_radius_miles': 15,
                'phone': '+998901111111',
                'working_time': '09:00-21:00',
                'description': 'Yangilangan profil.',
            },
            request_only=True,
        ),
    ],
)
class MasterUpdateSerializer(serializers.ModelSerializer):
    """Master update serializer (partial update)"""

    latitude = serializers.DecimalField(
        **WGS84_COORD_DECIMAL_KWARGS,
        required=False,
        allow_null=True,
        help_text='Latitude -90…90 — workshop map pin; set with longitude + service_area_radius_miles.',
    )
    longitude = serializers.DecimalField(
        **WGS84_COORD_DECIMAL_KWARGS,
        required=False,
        allow_null=True,
        help_text='Longitude -180…180 — workshop map pin.',
    )
    service_area_radius_miles = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text='15, 45, or 100 (miles) around latitude/longitude.',
    )

    images = serializers.ListField(
        child=serializers.ImageField(required=False),
        write_only=True,
        required=False,
        allow_empty=True,
        help_text="multipart/form-data: repeat field name 'images' for each new file.",
    )

    class Meta:
        model = Master
        fields = [
            'city', 'address', 'latitude', 'longitude', 'service_area_radius_miles',
            'phone', 'working_time',
            'description', 'images',
        ]
        extra_kwargs = {
            'city': {'required': False},
            'address': {'required': False},
            'phone': {'required': False},
            'working_time': {'required': False},
            'description': {'required': False, 'allow_blank': True, 'allow_null': True},
        }
    
    def to_internal_value(self, data):
        """Convert data from multipart/form-data"""
        from django.http import QueryDict
        
        # Создаем обычный dict из данных для возможности модификации
        if isinstance(data, QueryDict):
            data_dict = {}
            for key in data.keys():
                if key == 'images':
                    files = [f for f in data.getlist(key) if f]
                    if files:
                        data_dict[key] = files
                    continue
                value = data.get(key)
                if value is not None:
                    data_dict[key] = value
            data = data_dict
        elif hasattr(data, 'copy'):
            data = data.copy()
        else:
            data = dict(data)

        for coord in ('latitude', 'longitude'):
            if coord in data and isinstance(data.get(coord), str):
                s = data[coord].replace(',', '.').strip()
                if s:
                    try:
                        data[coord] = float(s)
                    except ValueError:
                        pass
        
        return super().to_internal_value(data)
    
    def validate_latitude(self, value):
        if value is None:
            return None
        f = float(value)
        if not (-90 <= f <= 90):
            raise serializers.ValidationError('Latitude must be between -90 and 90')
        return value

    def validate_longitude(self, value):
        if value is None:
            return None
        f = float(value)
        if not (-180 <= f <= 180):
            raise serializers.ValidationError('Longitude must be between -180 and 180')
        return value

    def validate_service_area_radius_miles(self, value):
        if value is None:
            return None
        if value not in SERVICE_AREA_RADIUS_CHOICES:
            raise serializers.ValidationError(f'Radius must be one of: {", ".join(map(str, SERVICE_AREA_RADIUS_CHOICES))} miles.')
        return value

    def validate(self, attrs):
        validate_master_service_area_triplet(attrs, instance=self.instance)
        return attrs

    def update(self, instance, validated_data):
        validated_data.pop('images', None)
        return super().update(instance, validated_data)


class AddMasterImagesSerializer(serializers.Serializer):
    """Serializer for adding images to master"""
    master_id = serializers.IntegerField(
        required=True,
        help_text="Master ID to add images to"
    )
    images = serializers.ListField(
        child=serializers.ImageField(),
        required=True,
        allow_empty=False,
        help_text="List of images to add (multiple files)"
    )

    def validate_master_id(self, value):
        """Check master exists"""
        try:
            Master.objects.get(id=value)
        except Master.DoesNotExist:
            raise serializers.ValidationError("Master with this ID not found")
        return value

    def validate_images(self, value):
        """Validate images"""
        if not value:
            raise serializers.ValidationError("At least one image must be uploaded")
        return value


class UpdateMasterImageSerializer(serializers.ModelSerializer):
    """Serializer for updating master image"""

    class Meta:
        model = MasterImage
        fields = ['image']

    def validate_image(self, value):
        """Validate image"""
        if not value:
            raise serializers.ValidationError("Image is required")
        return value


class MasterNearbySerializer(serializers.ModelSerializer):
    """Serializer for nearby masters"""
    user_name = serializers.ReadOnlyField(source='user.get_full_name')
    user_phone = serializers.ReadOnlyField(source='user.phone_number')
    services_display = serializers.SerializerMethodField()
    distance = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()

    class Meta:
        model = Master
        fields = [
            'id', 'user_name', 'user_phone', 'city', 'address',
            'latitude', 'longitude', 'services_display',
            'distance', 'description', 'images',
        ]

    def get_services_display(self, obj):
        items = MasterServiceItems.objects.filter(master_service__master=obj).select_related('category')
        return [i.category.name for i in items if i.category_id]
    
    def get_distance(self, obj):
        """Get distance (set in view)"""
        return getattr(obj, 'calculated_distance', None)
    
    def get_images(self, obj):
        """Get master images"""
        master_images = MasterImage.objects.filter(master=obj)
        return MasterImageSerializer(master_images, many=True, context=self.context).data


class MasterServiceItemsSerializer(serializers.ModelSerializer):
    """Master skill line: by_order category + price + icons."""

    service_name = serializers.CharField(source='category.name', read_only=True)
    type_category = serializers.CharField(source='category.type_category', read_only=True)
    category_icon = serializers.SerializerMethodField()
    parent_category_id = serializers.IntegerField(source='category.parent_id', read_only=True, allow_null=True)
    parent_category_name = serializers.SerializerMethodField()
    parent_category_icon = serializers.SerializerMethodField()
    price = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        coerce_to_string=False,
    )

    class Meta:
        model = MasterServiceItems
        fields = [
            'id',
            'master_service',
            'category',
            'service_name',
            'type_category',
            'category_icon',
            'parent_category_id',
            'parent_category_name',
            'parent_category_icon',
            'price',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def _abs_media(self, file_field):
        if not file_field:
            return None
        request = self.context.get('request')
        url = file_field.url
        if request:
            return request.build_absolute_uri(url)
        return url

    def get_category_icon(self, obj):
        if not obj.category_id:
            return None
        return self._abs_media(obj.category.icon)

    def get_parent_category_name(self, obj):
        if obj.category_id and obj.category.parent_id:
            return obj.category.parent.name
        return None

    def get_parent_category_icon(self, obj):
        if not obj.category_id or not obj.category.parent_id:
            return None
        return self._abs_media(obj.category.parent.icon)

    def validate_category(self, value):
        validate_skill_category(value)
        return value


def _absolute_media_url(request, file_field):
    if not file_field:
        return None
    url = file_field.url
    if request:
        return request.build_absolute_uri(url)
    return url


def master_service_item_line_dict(item, request):
    """
    Bir qator skill (pastki kategoriya) — parent ma’lumotlari yo‘q;
    parent guruh darajasida beriladi.
    """
    cat = item.category
    if not cat:
        return {
            'id': item.id,
            'category_id': item.category_id,
            'name': None,
            'type_category': None,
            'icon': None,
            'price': item.price,
            'created_at': item.created_at,
            'updated_at': item.updated_at,
        }
    return {
        'id': item.id,
        'category_id': item.category_id,
        'name': cat.name,
        'type_category': cat.type_category,
        'icon': _absolute_media_url(request, cat.icon),
        'price': item.price,
        'created_at': item.created_at,
        'updated_at': item.updated_at,
    }


class MasterServiceSerializer(serializers.ModelSerializer):
    """
    Master service container.
    master_service_items: [{ parent: {id, name, icon} | null, items: [skill lines] }, ...]
    Har bir skill: category_id, name, type_category, icon, price, timestamps (parent takrorlanmaydi).
    """

    master = serializers.IntegerField(source='master_id', read_only=True)
    master_service_items = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    master_items = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        allow_empty=True,
        write_only=True,
        help_text="[{'category': subcategory_id, 'price': 100.00}, ...]",
    )
    master_id = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = MasterService
        fields = [
            'id',
            'master',
            'master_service_items',
            'images',
            'master_items',
            'master_id',
            'created_at',
        ]
        read_only_fields = ['id', 'master', 'created_at']

    def get_images(self, obj):
        qs = MasterImage.objects.filter(master_id=obj.master_id).order_by('-created_at')
        return MasterImageSerializer(qs, many=True, context=self.context).data

    def get_master_service_items(self, obj):
        request = self.context.get('request')
        items = MasterServiceItems.objects.filter(master_service=obj).select_related(
            'category', 'category__parent',
        ).order_by('category__parent_id', 'category__name')
        fid = self.context.get('filter_service_category_id')
        if fid is not None:
            items = items.filter(category_id=fid)
        groups = {}
        for item in items:
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
            groups[gid]['items'].append(master_service_item_line_dict(item, request))
        return list(groups.values())

    def validate_master_items(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('master_items must be a list')
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError('Each item must be an object')
            if 'category' not in item or 'price' not in item:
                raise serializers.ValidationError("Each item must contain 'category' and 'price'")
            try:
                cat = Category.objects.get(id=item['category'])
            except Category.DoesNotExist:
                raise serializers.ValidationError(f"Category with ID {item['category']} not found")
            validate_skill_category(cat)
        return value

    def validate_master_id(self, value):
        if value:
            try:
                Master.objects.get(id=value)
            except Master.DoesNotExist:
                raise serializers.ValidationError(f'Master with ID {value} not found')
        return value

    def create(self, validated_data):
        master_items_data = validated_data.pop('master_items', [])
        validated_data.pop('master_id', None)
        master_service = super().create(validated_data)
        for item_data in master_items_data:
            MasterServiceItems.objects.update_or_create(
                master_service=master_service,
                category_id=item_data['category'],
                defaults={'price': item_data['price']},
            )
        return master_service

    def update(self, instance, validated_data):
        master_items_data = validated_data.pop('master_items', None)
        if master_items_data is not None:
            MasterServiceItems.objects.filter(master_service=instance).delete()
            for item_data in master_items_data:
                MasterServiceItems.objects.create(
                    master_service=instance,
                    category_id=item_data['category'],
                    price=item_data['price'],
                )
        return super().update(instance, validated_data)


class ServiceItemLineSerializer(serializers.Serializer):
    """Одна строка навыка: подкатегория + цена (Swagger: category — integer, price — number)."""

    category = serializers.IntegerField(
        min_value=1,
        help_text='ID категории типа by_order (подкаталог услуги)',
    )
    price = serializers.FloatField(help_text='Цена (number, ≥ 0)')

    def validate_category(self, value):
        try:
            cat = Category.objects.get(pk=value)
        except Category.DoesNotExist:
            raise serializers.ValidationError('Category not found')
        validate_skill_category(cat)
        return value

    def validate_price(self, value):
        f = float(value)
        if f < 0:
            raise serializers.ValidationError('Price must be >= 0')
        return Decimal(str(f))


@extend_schema_serializer(
    examples=[
        OpenApiExample(
            'Add services',
            value={
                'master_id': 1,
                'services': [
                    {'category': 101, 'price': 150000},
                    {'category': 102, 'price': 80000},
                ],
            },
            request_only=True,
        ),
        OpenApiExample(
            'Без master_id (одна мастерская у пользователя)',
            value={'services': [{'category': 101, 'price': 150000}]},
            request_only=True,
        ),
    ],
)
class AddServiceItemsSerializer(serializers.Serializer):
    """Добавление навыков: POST /api/master/service-items/"""

    master_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text='ID мастерской. Не обязателен, если у пользователя ровно одна мастерская (Master.user).',
    )
    services = ServiceItemLineSerializer(
        many=True,
        allow_empty=False,
        help_text='List of {category: integer id, price: number}',
    )

    def validate(self, attrs):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            raise serializers.ValidationError('Authentication required.')
        user = request.user
        mid = attrs.get('master_id')
        if mid in (None, ''):
            qs = Master.objects.filter(user=user)
            n = qs.count()
            if n == 0:
                raise serializers.ValidationError({
                    'master_id': 'Master profile not found. Create a master profile first.',
                })
            if n > 1:
                raise serializers.ValidationError({
                    'master_id': 'Provide master_id: you have multiple master profiles.',
                })
            attrs['master_id'] = qs.first().id
        else:
            try:
                master = Master.objects.get(id=int(mid))
            except (ValueError, TypeError, Master.DoesNotExist):
                raise serializers.ValidationError({'master_id': 'Master not found'})
            if master.user_id != user.id:
                raise serializers.ValidationError({'master_id': 'No access to this master profile'})
        return attrs


@extend_schema_serializer(
    examples=[
        OpenApiExample(
            'Update price / category',
            value={'price': 175000, 'category': 101},
            request_only=True,
        ),
    ],
)
class UpdateServiceItemSerializer(serializers.ModelSerializer):
    """Update skill price or category (by_order catalog)."""

    price = serializers.FloatField(required=False, help_text='Цена (number, ≥ 0)')

    class Meta:
        model = MasterServiceItems
        fields = ['price', 'category']

    def validate_category(self, value):
        validate_skill_category(value)
        return value

    def validate_price(self, value):
        if value is None:
            return None
        f = float(value)
        if f < 0:
            raise serializers.ValidationError('Price must be >= 0')
        return Decimal(str(f))


class MasterScheduleDaySerializer(serializers.ModelSerializer):
    class Meta:
        model = MasterScheduleDay
        fields = ['id', 'date', 'start_time', 'end_time']
        read_only_fields = ['id']

    def validate(self, attrs):
        start = attrs.get('start_time')
        end = attrs.get('end_time')
        if self.instance:
            if start is None:
                start = self.instance.start_time
            if end is None:
                end = self.instance.end_time
        if start and end and end <= start:
            raise serializers.ValidationError('end_time must be after start_time.')
        return attrs


class MasterScheduleDayWriteSerializer(serializers.Serializer):
    date = serializers.DateField()
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()

    def validate(self, attrs):
        if attrs['end_time'] <= attrs['start_time']:
            raise serializers.ValidationError('end_time must be after start_time.')
        return attrs


class MasterScheduleBulkSerializer(serializers.Serializer):
    days = MasterScheduleDayWriteSerializer(many=True)

    def validate_days(self, value):
        dates = [item['date'] for item in value]
        if len(dates) != len(set(dates)):
            raise serializers.ValidationError('Each date must appear at most once.')
        return value


class MasterBusySlotSerializer(serializers.ModelSerializer):
    """
    Manual slot (no order).

    **POST:** Either ``start_time`` + ``end_time`` (plain busy block), or ``start_time_rest`` +
    ``time_range_rest`` (server fills ``start_time`` / ``end_time`` from the break duration).

    **PATCH:** Only fields present in the JSON body are updated. Sending ``start_time`` / ``end_time``
    does **not** change ``start_time_rest`` / ``time_range_rest``, and vice versa.
    """

    class Meta:
        model = MasterBusySlot
        fields = [
            'id',
            'date',
            'start_time',
            'end_time',
            'start_time_rest',
            'time_range_rest',
            'reason',
        ]
        read_only_fields = ['id']
        extra_kwargs = {
            'start_time': {'required': False, 'allow_null': True},
            'end_time': {'required': False, 'allow_null': True},
        }

    def validate(self, attrs):
        from apps.master.services.slots import break_window_times

        inst = self.instance
        merged: dict = {}
        if inst:
            merged = {
                'date': inst.date,
                'start_time': inst.start_time,
                'end_time': inst.end_time,
                'start_time_rest': inst.start_time_rest,
                'time_range_rest': inst.time_range_rest,
            }
        merged.update(attrs)

        date = merged.get('date')
        if date is None:
            raise serializers.ValidationError({'date': 'This field is required.'})

        rest_keys_in_request = {'start_time_rest', 'time_range_rest'} & attrs.keys()
        time_keys_in_request = {'start_time', 'end_time'} & attrs.keys()

        def _validate_rest_pair(rs, tr):
            if rs is not None:
                if tr is None or tr <= 0:
                    raise serializers.ValidationError(
                        {'time_range_rest': 'Set a positive duration when start_time_rest is set.'}
                    )
            elif tr is not None and tr > 0:
                raise serializers.ValidationError(
                    {'start_time_rest': 'Set start_time_rest when time_range_rest is set.'}
                )

        if self.partial:
            if time_keys_in_request and not rest_keys_in_request:
                st = merged.get('start_time')
                et = merged.get('end_time')
                if st is None or et is None:
                    raise serializers.ValidationError(
                        'start_time and end_time must both be set after merge '
                        '(include the missing field in the request or keep it on the row).'
                    )
                if et <= st:
                    raise serializers.ValidationError('end_time must be after start_time.')
                return attrs

            if rest_keys_in_request and not time_keys_in_request:
                _validate_rest_pair(merged.get('start_time_rest'), merged.get('time_range_rest'))
                return attrs

            if rest_keys_in_request and time_keys_in_request:
                st = merged.get('start_time')
                et = merged.get('end_time')
                if st is None or et is None:
                    raise serializers.ValidationError(
                        'start_time and end_time must both be set when updating times in the same request.'
                    )
                if et <= st:
                    raise serializers.ValidationError('end_time must be after start_time.')
                _validate_rest_pair(merged.get('start_time_rest'), merged.get('time_range_rest'))
                return attrs

        rs = merged.get('start_time_rest')
        tr = merged.get('time_range_rest')
        st = merged.get('start_time')
        et = merged.get('end_time')

        rest_mode = rs is not None and tr is not None and tr > 0

        if rest_mode:
            _, b1 = break_window_times(date, rs, tr)
            exp_end = b1.time()
            attrs['start_time'] = rs
            attrs['end_time'] = exp_end
            attrs['start_time_rest'] = rs
            attrs['time_range_rest'] = tr
        else:
            _validate_rest_pair(rs, tr)
            attrs['start_time_rest'] = None
            attrs['time_range_rest'] = None
            if st is None or et is None:
                raise serializers.ValidationError(
                    'Provide start_time and end_time, or start_time_rest with time_range_rest.'
                )
            if et <= st:
                raise serializers.ValidationError('end_time must be after start_time.')
            attrs['start_time'] = st
            attrs['end_time'] = et

        return attrs

    def create(self, validated_data):
        master = self.context['master']
        validated_data['master'] = master
        validated_data['order'] = None
        return MasterBusySlot.objects.create(**validated_data)


class ServiceCardSerializer(serializers.Serializer):
    """
    UI uchun "service card" ko'rinishi:
    - icon (category.icon)
    - average price range (MasterServiceItems.price min/max/avg)
    - masters_count (shu service ni beradigan masterlar soni)
    - average_rating (shu service ni beradigan masterlar bo'yicha Rating.avg)
    """

    category_id = serializers.IntegerField()
    name = serializers.CharField()
    icon = serializers.CharField(allow_null=True, required=False)

    price_min = serializers.FloatField()
    price_max = serializers.FloatField()
    price_avg = serializers.FloatField()

    masters_count = serializers.IntegerField()

    average_rating = serializers.FloatField(allow_null=True, required=False)
    rating_count = serializers.IntegerField()

    is_most_common = serializers.BooleanField()


class ServiceCardGroupSerializer(serializers.Serializer):
    parent_category_id = serializers.IntegerField(allow_null=True)
    parent_category_name = serializers.CharField()
    parent_category_icon = serializers.CharField(allow_null=True, required=False)

    services = ServiceCardSerializer(many=True)


class ServiceCardsResponseSerializer(serializers.Serializer):
    groups = ServiceCardGroupSerializer(many=True)
