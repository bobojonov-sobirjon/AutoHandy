from django.db import models
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta

from apps.accounts.models import CustomUser
from apps.car.models import Car
from apps.categories.models import Category

User = get_user_model()


class OrderStatus(models.TextChoices):
    """Order statuses (workflow for master accept → work → complete)."""

    PENDING = 'pending', 'Pending'
    ACCEPTED = 'accepted', 'Accepted'
    ON_THE_WAY = 'on_the_way', 'On the way'
    ARRIVED = 'arrived', 'Arrived'
    IN_PROGRESS = 'in_progress', 'In progress'
    COMPLETED = 'completed', 'Completed'
    CANCELLED = 'cancelled', 'Cancelled'
    REJECTED = 'rejected', 'Rejected'


class LocationSource(models.TextChoices):
    MANUAL = 'manual', 'Address text (coordinates optional)'
    GPS_PROFILE = 'gps_profile', 'GPS from user profile (CustomUser lat/long)'
    GPS_CUSTOM = 'gps_custom', 'GPS coordinates sent by client'


class OrderPriority(models.TextChoices):
    """Order priorities"""

    LOW = 'low', 'Low'
    HIGH = 'high', 'High'


class OrderType(models.TextChoices):
    """Order types: standard (normal booking with a master) vs SOS (emergency)."""

    STANDARD = 'standard', 'Standard'
    SOS = 'sos', 'SOS / Emergency'


class Order(models.Model):
    """Order model"""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='orders',
        verbose_name='User',
    )
    car = models.ManyToManyField(
        Car,
        related_name='orders',
        verbose_name='Car',
    )
    category = models.ManyToManyField(
        Category,
        related_name='orders',
        verbose_name='Category',
    )
    text = models.TextField(
        verbose_name='Order description',
        help_text='Detailed description of the problem or service',
    )
    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING,
        verbose_name='Order status',
    )
    priority = models.CharField(
        max_length=20,
        choices=OrderPriority.choices,
        default=OrderPriority.LOW,
        verbose_name='Order priority',
    )
    order_type = models.CharField(
        max_length=20,
        choices=OrderType.choices,
        default=OrderType.STANDARD,
        verbose_name='Order type',
        help_text='Standard — order with a chosen master; SOS — emergency assistance',
    )
    location = models.TextField(
        blank=True,
        default='',
        verbose_name='Location',
        help_text='Service address text; optional if GPS coordinates are provided',
    )
    latitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        verbose_name='Latitude',
        help_text='Location latitude',
    )
    longitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        verbose_name='Longitude',
        help_text='Location longitude',
    )
    master = models.ForeignKey(
        'master.Master',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        verbose_name='Master',
    )

    discount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        verbose_name='Discount',
        help_text='Order discount (percentage or amount)',
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Created at',
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Updated at',
    )
    expiration_time = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Expiration time',
        help_text='Order expiration time (1 day from creation)',
    )
    accepted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Accepted at',
        help_text='When the assigned master accepted the order (exact address visible after this)',
    )
    master_response_deadline = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Master offer deadline',
        help_text='Master must accept or decline before this time (e.g. 15 minutes from offer)',
    )
    on_the_way_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='On the way at',
        help_text='When master marked status "on the way".',
    )
    estimated_arrival_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Estimated arrival',
        help_text='Expected arrival time (set on on_the_way from eta_minutes or explicit datetime).',
    )
    eta_minutes = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name='ETA minutes',
        help_text='Minutes until arrival committed when marking on the way.',
    )
    arrived_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Arrived at',
    )
    work_started_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Work started at',
        help_text='When master started job (in_progress) after arrival.',
    )
    client_penalty_free_cancel_unlocked = models.BooleanField(
        default=False,
        verbose_name='Client penalty-free cancel (2h on the way)',
        help_text='Set automatically after configured hours on the way; client cancel without penalty.',
    )
    sos_offer_queue = models.JSONField(
        default=list,
        blank=True,
        verbose_name='SOS offer queue (master IDs)',
        help_text='SOS: nearest master IDs (broadcast to all in zone); first accept wins.',
    )
    sos_offer_index = models.PositiveSmallIntegerField(
        default=0,
        verbose_name='SOS offer index',
        help_text='Legacy ring index; unused for broadcast SOS.',
    )
    sos_declined_master_ids = models.JSONField(
        default=list,
        blank=True,
        verbose_name='SOS declined master IDs',
        help_text='SOS broadcast: master IDs who declined while order still pending.',
    )
    location_source = models.CharField(
        max_length=20,
        choices=LocationSource.choices,
        default=LocationSource.MANUAL,
        verbose_name='Location source',
    )
    parts_purchase_required = models.BooleanField(
        default=False,
        verbose_name='Parts purchase required',
        help_text='If true, master buys parts; client pays parts outside the app.',
    )
    preferred_date = models.DateField(
        null=True,
        blank=True,
        verbose_name='Preferred service date',
        help_text='Standard orders: visit day chosen by client (with preferred_time_start).',
    )
    preferred_time_start = models.TimeField(
        null=True,
        blank=True,
        verbose_name='Preferred time start',
        help_text='Standard: client-chosen slot start (POST). End is set by master after accept (PATCH).',
    )
    preferred_time_end = models.TimeField(
        null=True,
        blank=True,
        verbose_name='Preferred time end',
        help_text='Set by assigned master via PATCH when status is accepted.',
    )

    class Meta:
        verbose_name = 'Order'
        verbose_name_plural = 'Orders'
        ordering = ['-created_at']

    def __str__(self):
        order_type_display = self.get_order_type_display()
        return f"Order #{self.id} - {order_type_display} - {self.user.get_full_name()} ({self.get_status_display()})"

    def clean(self):
        """Model validation"""
        if self.latitude is not None and (self.latitude < -90 or self.latitude > 90):
            raise ValidationError({'latitude': 'Latitude must be between -90 and 90'})

        if self.longitude is not None and (self.longitude < -180 or self.longitude > 180):
            raise ValidationError({'longitude': 'Longitude must be between -180 and 180'})

        if self.preferred_time_start and self.preferred_time_end:
            if self.preferred_time_end <= self.preferred_time_start:
                raise ValidationError(
                    {'preferred_time_end': 'Must be after preferred_time_start.'}
                )

    def save(self, *args, **kwargs):
        # Set expiration time automatically on create
        if not self.pk and not self.expiration_time:
            self.expiration_time = timezone.now() + timedelta(days=1)
        self.clean()
        super().save(*args, **kwargs)

    def is_expired(self):
        """
        Check if order has expired
        """
        if self.expiration_time:
            return timezone.now() > self.expiration_time
        return False

    def mark_as_cancelled_if_expired(self):
        """
        Mark order as cancelled if expired
        """
        if self.is_expired() and self.status == OrderStatus.PENDING:
            self.status = OrderStatus.CANCELLED
            self.save()
            return True
        return False


class OrderImage(models.Model):
    """Photos attached to an order by the client (visible to master before accept)."""

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='images',
        verbose_name='Order',
    )
    image = models.ImageField(upload_to='order_images/', verbose_name='Image')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created at')

    class Meta:
        verbose_name = 'Order image'
        verbose_name_plural = 'Order images'
        ordering = ['created_at']

    def __str__(self):
        return f'Order {self.order_id} image {self.pk}'


class OrderWorkCompletionImage(models.Model):
    """Photos of completed work uploaded by the assigned master (required before complete)."""

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='work_completion_images',
        verbose_name='Order',
    )
    image = models.ImageField(upload_to='order_work_completion/', verbose_name='Image')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created at')

    class Meta:
        verbose_name = 'Order work completion image'
        verbose_name_plural = 'Order work completion images'
        ordering = ['created_at']

    def __str__(self):
        return f'Order {self.order_id} work photo {self.pk}'


class MasterCancelReason(models.TextChoices):
    """Allowed reasons when a master cancels after accept (too_far is not allowed)."""

    CLIENT_REQUEST = 'client_request', 'Client request'
    VEHICLE_UNAVAILABLE = 'vehicle_unavailable', 'Vehicle unavailable'
    DUPLICATE = 'duplicate', 'Duplicate order'
    EMERGENCY = 'emergency', 'Emergency'
    OTHER = 'other', 'Other'


class MasterOrderCancellation(models.Model):
    """Audit trail for master-initiated cancellations (monthly free limit + schedule rules)."""

    master = models.ForeignKey(
        'master.Master',
        on_delete=models.CASCADE,
        related_name='order_cancellations',
        verbose_name='Master',
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='master_cancellations',
        verbose_name='Order',
    )
    reason = models.CharField(
        max_length=32,
        choices=MasterCancelReason.choices,
        verbose_name='Reason',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created at')

    class Meta:
        verbose_name = 'Master order cancellation'
        verbose_name_plural = 'Master order cancellations'
        ordering = ['-created_at']

    def __str__(self):
        return f'Master {self.master_id} cancelled order {self.order_id}'


class ReviewTag(models.TextChoices):
    """Aspect of the experience (positive or negative); pick one."""

    FAST_WORK = 'fast_work', 'Fast work'
    NO_OVERPAY = 'no_overpay', 'No overpayment'
    DEADLINE = 'deadline', 'On time'
    ALWAYS_AVAILABLE = 'always_available', 'Always available'
    INDIVIDUAL_APPROACH = 'individual_approach', 'Individual approach'
    POLITE = 'polite', 'Polite'
    LATE_OR_DELAYED = 'late_or_delayed', 'Late / delays'
    POOR_QUALITY = 'poor_quality', 'Poor quality of work'
    OVERPRICED = 'overpriced', 'Overpriced'
    UNPROFESSIONAL = 'unprofessional', 'Unprofessional behavior'
    HARD_TO_REACH = 'hard_to_reach', 'Hard to reach / poor communication'
    OTHER_ISSUE = 'other_issue', 'Other issue'


class Rating(models.Model):
    """Rating model for masters"""
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='ratings',
        verbose_name='Order'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='given_ratings',
        verbose_name='User (rater)'
    )
    master = models.ForeignKey(
        'master.Master',
        on_delete=models.CASCADE,
        related_name='ratings',
        null=True,
        blank=True,
        verbose_name='Master'
    )
    rating = models.PositiveIntegerField(
        verbose_name='Rating',
        help_text='Rating from 1 to 5'
    )
    comment = models.TextField(
        blank=True,
        null=True,
        verbose_name='Comment',
        help_text='Rating comment'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Created at'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Updated at'
    )

    class Meta:
        verbose_name = 'Rating'
        verbose_name_plural = 'Ratings'
        ordering = ['-created_at']
        unique_together = [
            ['order', 'user', 'master']
        ]

    def __str__(self):
        if self.master:
            return f"Rating {self.rating} for master {self.master} from {self.user}"
        return f"Rating {self.rating} from {self.user}"

    def clean(self):
        """Model validation"""
        if self.rating < 1 or self.rating > 5:
            raise ValidationError({'rating': 'Rating must be from 1 to 5'})

        if not self.master:
            raise ValidationError('Master must be specified')

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class Review(models.Model):
    """Review for an order; rating updates the order's primary master (order.master)."""
    order = models.OneToOneField(
        Order,
        on_delete=models.CASCADE,
        related_name='review',
        verbose_name='Order',
        help_text='Order this review belongs to'
    )
    reviewer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='reviews_given',
        verbose_name='Review author',
        help_text='User who left the review'
    )
    rating = models.PositiveIntegerField(
        verbose_name='Rating',
        help_text='Rating from 1 to 5'
    )
    comment = models.TextField(
        blank=True,
        null=True,
        verbose_name='Comment',
        help_text='Review text'
    )
    tag = models.CharField(
        max_length=50,
        choices=ReviewTag.choices,
        verbose_name='Review tag',
        help_text='What best describes your experience (one tag)'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Created at'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Updated at'
    )

    class Meta:
        verbose_name = 'Review'
        verbose_name_plural = 'Reviews'
        ordering = ['-created_at']

    def __str__(self):
        return f"Review for order #{self.order.id} from {self.reviewer.get_full_name()}"

    def clean(self):
        """Model validation"""
        if self.rating < 1 or self.rating > 5:
            raise ValidationError({'rating': 'Rating must be from 1 to 5'})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

        # After saving review, update rating for order.master
        self.update_masters_rating()

    def update_masters_rating(self):
        """Update rating for the primary master on the order."""
        if self.order.master:
            self._update_user_rating(self.order.master.user)

    def _update_user_rating(self, user):
        """Update user average rating based on all their reviews"""
        from django.db.models import Avg

        orders_as_main_master = Order.objects.filter(master__user=user)
        all_order_ids = set(orders_as_main_master.values_list('id', flat=True))

        avg_rating = Review.objects.filter(order_id__in=all_order_ids).aggregate(Avg('rating'))['rating__avg']

        if avg_rating:
            UserRating.objects.update_or_create(
                user=user,
                defaults={'average_rating': round(avg_rating, 2)}
            )


class UserRating(models.Model):
    """
    Model for storing user (master) average rating
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='rating_profile',
        verbose_name='User'
    )
    average_rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0.00,
        verbose_name='Average rating',
        help_text='Average rating based on all reviews'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Updated at'
    )

    class Meta:
        verbose_name = 'User rating'
        verbose_name_plural = 'User ratings'
        ordering = ['-average_rating']

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.average_rating}"


class OrderService(models.Model):
    """
    Order–master service link model
    Stores selected services for a specific order
    """

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='order_services',
        verbose_name='Order',
    )
    master_service_item = models.ForeignKey(
        'master.MasterServiceItems',
        on_delete=models.CASCADE,
        related_name='order_services',
        verbose_name='Master service',
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Added at',
    )

    class Meta:
        verbose_name = 'Order service'
        verbose_name_plural = 'Order services'
        ordering = ['-created_at']
        unique_together = ['order', 'master_service_item']

    def __str__(self):
        if self.master_service_item_id and self.master_service_item.category_id:
            return f"Order #{self.order.id} - {self.master_service_item.category.name}"
        return f"Order #{self.order.id} - service #{self.master_service_item_id}"


class StandardOrderManager(models.Manager):
    """Manager for standard (non-SOS) orders."""

    def get_queryset(self):
        return super().get_queryset().filter(order_type=OrderType.STANDARD)


class StandardOrder(Order):
    """Proxy for standard orders (client picked a master; not emergency)."""

    objects = StandardOrderManager()

    class Meta:
        proxy = True
        verbose_name = 'Standard order'
        verbose_name_plural = 'Standard orders'
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.order_type:
            self.order_type = OrderType.STANDARD
        super().save(*args, **kwargs)


class SOSOrderManager(models.Manager):
    """Manager for SOS orders"""
    def get_queryset(self):
        return super().get_queryset().filter(order_type=OrderType.SOS)


class SOSOrder(Order):
    """
    Proxy model for SOS orders (emergency assistance)
    Orders that client makes urgently with current geolocation
    """
    objects = SOSOrderManager()

    class Meta:
        proxy = True
        verbose_name = 'SOS order'
        verbose_name_plural = 'SOS orders (emergency assistance)'
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.order_type:
            self.order_type = OrderType.SOS
        self.priority = OrderPriority.HIGH
        super().save(*args, **kwargs)
