from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Order, OrderStatus, OrderPriority, OrderType, Rating, OrderService, Review, ReviewTag, UserRating
from apps.car.models import Car
from apps.categories.models import Category
from apps.master.models import Master
from apps.accounts.serializers import UserSerializer
from apps.master.serializers import MasterSerializer

User = get_user_model()


class OrderSerializer(serializers.ModelSerializer):
    """Order serializer"""
    user = serializers.SerializerMethodField()
    master = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    order_type_display = serializers.CharField(source='get_order_type_display', read_only=True)
    car_data = serializers.SerializerMethodField()
    category_data = serializers.SerializerMethodField()
    services = serializers.SerializerMethodField()
    reviews = serializers.SerializerMethodField()
    average_rating = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'user', 'order_type', 'order_type_display',
            'car_data', 'category_data',
            'text', 'status', 'status_display', 'priority', 'priority_display',
            'location', 'latitude', 'longitude', 'master',
            'scheduled_date', 'scheduled_time_start', 'scheduled_time_end',
            'discount', 'services', 'reviews', 'average_rating',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_user(self, obj):
        return UserSerializer(obj.user, context=self.context).data
    
    def get_master(self, obj):
        if not obj.master_id:
            return None
        return MasterSerializer(obj.master, context=self.context).data
    
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
        """Get category data"""
        categories = obj.category.all()
        return [
            {
                'id': category.id,
                'name': category.name,
                'type_category': category.type_category
            }
            for category in categories
        ]
    
    def get_services(self, obj):
        """Get order services"""
        from apps.master.serializers import MasterServiceItemsSerializer
        
        order_services = obj.order_services.all().select_related('master_service_item')
        return [
            MasterServiceItemsSerializer(os.master_service_item, context=self.context).data
            for os in order_services if os.master_service_item
        ]
    
    def get_reviews(self, obj):
        """Get order reviews"""
        from .models import Review
        
        reviews = Review.objects.filter(order=obj).select_related('reviewer')
        if not reviews.exists():
            return []
        
        return [
            {
                'id': review.id,
                'rating': review.rating,
                'comment': review.comment,
                'tag': review.tag,
                'tag_display': review.get_tag_display(),
                'reviewer': {
                    'id': review.reviewer.id,
                    'full_name': review.reviewer.get_full_name(),
                    'avatar': self.context['request'].build_absolute_uri(review.reviewer.avatar.url) if review.reviewer.avatar and self.context.get('request') else None
                } if review.reviewer else None,
                'created_at': review.created_at
            }
            for review in reviews
        ]
    
    def get_average_rating(self, obj):
        """Get order average rating"""
        from django.db.models import Avg
        from .models import Review
        
        avg = Review.objects.filter(order=obj).aggregate(avg_rating=Avg('rating'))
        return round(avg['avg_rating'], 2) if avg['avg_rating'] else None

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
    1. SCHEDULED: client selects master, date and visit time
    2. SOS: client makes urgent order with current geolocation

    Required for both: order_type, text, location, latitude, longitude, car_list, category_list.
    For SCHEDULED also: master_id, scheduled_date, scheduled_time_start, scheduled_time_end.
    For SOS also: master_id, priority ('low' or 'high').
    """
    order_type = serializers.ChoiceField(
        choices=OrderType.choices,
        required=True,
        help_text="Order type: 'scheduled' or 'sos'"
    )
    master_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        write_only=True,
        help_text="Master ID (required for scheduled and sos)"
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
    class Meta:
        model = Order
        fields = [
            'order_type', 'text', 'priority', 'location', 'latitude', 'longitude', 
            'master_id', 'scheduled_date', 'scheduled_time_start', 'scheduled_time_end',
            'car_list', 'category_list',
        ]
        extra_kwargs = {
            'text': {'required': True},
            'location': {'required': True},
            'latitude': {'required': True},
            'longitude': {'required': True},
            'priority': {'required': False},  # For SOS set automatically
            'scheduled_date': {'required': False},
            'scheduled_time_start': {'required': False},
            'scheduled_time_end': {'required': False},
        }

    def validate_master_id(self, value):
        """Validate master"""
        if value is not None:
            try:
                Master.objects.get(id=value)
            except Master.DoesNotExist:
                raise serializers.ValidationError(f"Master with ID {value} not found")
        return value

    def validate_car_list(self, value):
        """Validate car list"""
        if not isinstance(value, list):
            raise serializers.ValidationError("car_list must be a list of IDs")

        for car_id in value:
            try:
                Car.objects.get(id=car_id)
            except Car.DoesNotExist:
                raise serializers.ValidationError(f"Car with ID {car_id} not found")

        return value

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

        if order_type == OrderType.SCHEDULED:
            if not master_id:
                raise serializers.ValidationError({
                    'master_id': 'Master is required for scheduled order'
                })
            if not attrs.get('scheduled_date'):
                raise serializers.ValidationError({
                    'scheduled_date': 'Visit date is required for scheduled order'
                })
            if not attrs.get('scheduled_time_start'):
                raise serializers.ValidationError({
                    'scheduled_time_start': 'Start time is required for scheduled order'
                })
            if not attrs.get('scheduled_time_end'):
                raise serializers.ValidationError({
                    'scheduled_time_end': 'End time is required for scheduled order'
                })

            from datetime import date
            if attrs.get('scheduled_date') < date.today():
                raise serializers.ValidationError({
                    'scheduled_date': 'Visit date cannot be in the past'
                })

            if attrs.get('scheduled_time_start') >= attrs.get('scheduled_time_end'):
                raise serializers.ValidationError({
                    'scheduled_time_start': 'Start time must be before end time'
                })

        elif order_type == OrderType.SOS:
            if not master_id:
                raise serializers.ValidationError({
                    'master_id': 'Master is required for SOS order'
                })

            if not attrs.get('priority'):
                raise serializers.ValidationError({
                    'priority': 'Priority is required for SOS order (low or high)'
                })

            attrs['scheduled_date'] = None
            attrs['scheduled_time_start'] = None
            attrs['scheduled_time_end'] = None

        if master_id and order_lat and order_lon:
            try:
                master = Master.objects.get(id=master_id)

                if not master.latitude or not master.longitude:
                    raise serializers.ValidationError({
                        'master_id': 'Selected master has no coordinates. Please choose another master.'
                    })

                from math import radians, sin, cos, sqrt, atan2

                R = 6371.0  # Earth radius in km

                master_lat = float(master.latitude)
                master_lon = float(master.longitude)
                lat1 = float(order_lat)
                lon1 = float(order_lon)
                lat1_rad = radians(lat1)
                lon1_rad = radians(lon1)
                lat2_rad = radians(master_lat)
                lon2_rad = radians(master_lon)
                dlat = lat2_rad - lat1_rad
                dlon = lon2_rad - lon1_rad
                a = sin(dlat / 2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2)**2
                c = 2 * atan2(sqrt(a), sqrt(1 - a))
                distance = R * c
                MAX_DISTANCE = 50  # km
                if distance > MAX_DISTANCE:
                    raise serializers.ValidationError({
                        'master_id': f'Selected master is too far ({distance:.1f} km). '
                                   f'Maximum distance: {MAX_DISTANCE} km. '
                                   f'Please choose a master closer to your location.'
                    })

            except Master.DoesNotExist:
                pass

        return attrs

    def create(self, validated_data):
        """Create order with cars and categories"""
        master_id = validated_data.pop('master_id', None)
        car_list = validated_data.pop('car_list', [])
        category_list = validated_data.pop('category_list', [])

        if master_id:
            validated_data['master'] = Master.objects.get(id=master_id)

        order = super().create(validated_data)
        if car_list:
            order.car.set(car_list)
        if category_list:
            order.category.set(category_list)

        return order


class OrderUpdateSerializer(serializers.ModelSerializer):
    """Order update serializer"""
    
    class Meta:
        model = Order
        fields = [
            'text', 'status', 'priority', 'location', 'latitude', 'longitude', 'master',
            'scheduled_date', 'scheduled_time_start', 'scheduled_time_end'
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
            from apps.master.serializers import MasterServiceItemsSerializer
            return MasterServiceItemsSerializer(obj.master_service_item).data
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
    """Review serializer"""
    reviewer_info = serializers.SerializerMethodField()
    tag_display = serializers.CharField(source='get_tag_display', read_only=True)
    order_info = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = [
            'id', 'order', 'order_info', 'reviewer', 'reviewer_info',
            'rating', 'comment', 'tag', 'tag_display', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'reviewer', 'created_at', 'updated_at']

    def get_reviewer_info(self, obj):
        """Review author info"""
        if obj.reviewer:
            return {
                'id': obj.reviewer.id,
                'full_name': obj.reviewer.get_full_name(),
                'email': obj.reviewer.email,
                'avatar': obj.reviewer.avatar.url if obj.reviewer.avatar else None
            }
        return None
    
    def get_order_info(self, obj):
        """Short order info"""
        if obj.order:
            return {
                'id': obj.order.id,
                'text': obj.order.text,
                'status': obj.order.status,
                'created_at': obj.order.created_at
            }
        return None


class ReviewCreateSerializer(serializers.Serializer):
    """Serializer for creating review"""
    order_id = serializers.IntegerField(
        help_text='Order ID'
    )
    rating = serializers.IntegerField(
        min_value=1,
        max_value=5,
        help_text='Rating from 1 to 5'
    )
    comment = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text='Review comment'
    )
    tag = serializers.ChoiceField(
        choices=ReviewTag.choices,
        help_text='What you liked about the master work (choose one)'
    )

    def validate_order_id(self, value):
        """Check order exists and can be reviewed"""
        try:
            order = Order.objects.get(id=value)

            if order.status != OrderStatus.COMPLETED:
                raise serializers.ValidationError(
                    'Review can only be left for a completed order'
                )

            if Review.objects.filter(order=order).exists():
                raise serializers.ValidationError(
                    'A review for this order has already been submitted'
                )

        except Order.DoesNotExist:
            raise serializers.ValidationError(f'Order with ID {value} not found')
        return value
