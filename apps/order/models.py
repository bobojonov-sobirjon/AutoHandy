from django.db import models
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
import secrets

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


class OrderPaymentType(models.TextChoices):
    """Completed jobs are paid by card only (Stripe)."""

    CARD = 'card', 'Card'


class OrderStripePaymentStatus(models.TextChoices):
    """Stripe capture status after master completes (card orders)."""

    NOT_APPLICABLE = 'not_applicable', 'Not applicable'
    PENDING = 'pending', 'Pending'
    SUCCEEDED = 'succeeded', 'Succeeded'
    FAILED = 'failed', 'Failed'


class OrderType(models.TextChoices):
    """Order types: standard (normal booking with a master) vs SOS (emergency)."""

    STANDARD = 'standard', 'Standard'
    SOS = 'sos', 'SOS / Emergency'
    CUSTOM_REQUEST = 'custom_request', 'Custom request'


class Order(models.Model):
    """Order model"""

    order_number = models.CharField(
        max_length=8,
        unique=True,
        blank=True,
        null=True,
        default=None,
        db_index=True,
        verbose_name='Order number',
        help_text='Auto-generated order code like ORD_1234',
    )
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
        max_digits=22,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name='Latitude',
        help_text='Location latitude',
    )
    longitude = models.DecimalField(
        max_digits=22,
        decimal_places=18,
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
    chat_room = models.ForeignKey(
        'chat.ChatRoom',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        verbose_name='Chat room',
        help_text='Auto-created on accept: master (initiator) ↔ user (receiver).',
    )

    discount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        verbose_name='Discount',
        help_text='Order discount (percentage or amount)',
    )
    extra_money = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0.00,
        verbose_name='Extra money',
        help_text='Additional charges added after service selection (e.g. extra work/parts).',
    )
    order_penalty_total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0.00,
        verbose_name='Order penalties total',
        help_text=(
            'Fixed penalties on this order (e.g. client cancel fee). Added to client payable total; '
            'not part of master job payout percentage base.'
        ),
    )
    average_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        default=None,
        verbose_name='Average price',
        help_text='Optional: average price estimate for the order (shown to client).',
    )
    average_service_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        default=None,
        verbose_name='Average service name',
        help_text='Optional: service name/label associated with average_price (shown to client).',
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
    arrival_deadline_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Arrival deadline',
        help_text='Auto-cancel cutoff when master did not arrive in time (ETA + grace).',
    )
    auto_cancel_reason = models.CharField(
        max_length=32,
        blank=True,
        default='',
        verbose_name='Auto-cancel reason',
        help_text='Internal reason code when the system cancels an order automatically.',
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
    parts_purchase_required_json = models.JSONField(
        default=list,
        blank=True,
        verbose_name='Parts purchase required (items)',
        help_text=(
            'List of parts the master may need to buy. Each item: '
            '{ "vehicle_vin": "…", "part_name": "…", "is_address": true/false }.'
        ),
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
    custom_request_date = models.DateField(
        null=True,
        blank=True,
        verbose_name='Custom request date',
        help_text='Calendar day for the requested service (client local / request time zone).',
    )
    custom_request_time = models.TimeField(
        null=True,
        blank=True,
        verbose_name='Custom request time',
        help_text='Preferred time of day for the service (client local / same TZ as custom_request_date).',
    )
    payment_type = models.CharField(
        max_length=16,
        choices=OrderPaymentType.choices,
        default=OrderPaymentType.CARD,
        verbose_name='Payment type',
        help_text='Card only: charge on master complete via Stripe (Connect destination when set).',
    )
    saved_card = models.ForeignKey(
        'payment.SavedCard',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders',
        verbose_name='Saved card',
        help_text='Client card used when payment_type=card.',
    )
    stripe_payment_intent_id = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='Stripe PaymentIntent id',
    )
    stripe_payment_status = models.CharField(
        max_length=32,
        choices=OrderStripePaymentStatus.choices,
        default=OrderStripePaymentStatus.NOT_APPLICABLE,
        verbose_name='Stripe payment status',
    )
    stripe_payment_amount_cents = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name='Stripe charged amount (minor units)',
    )
    stripe_payment_currency = models.CharField(
        max_length=8,
        blank=True,
        default='',
        verbose_name='Stripe charge currency',
    )
    stripe_payment_error = models.TextField(
        blank=True,
        default='',
        verbose_name='Stripe last error',
    )
    completion_pin = models.CharField(
        max_length=4,
        blank=True,
        default='',
        verbose_name='Work completion PIN',
        help_text='4-digit code shown to the client during in_progress; master must submit it to complete.',
    )
    completion_pin_issued_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Completion PIN issued at',
        help_text='When status became in_progress and the PIN was generated.',
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
        if not self.pk:
            if not self.expiration_time:
                self.expiration_time = timezone.now() + timedelta(days=1)
            if not (self.order_number or '').strip():
                # Generate a short readable code; loop until unique.
                while True:
                    code = f"ORD_{secrets.randbelow(10000):04d}"
                    if not Order.objects.filter(order_number=code).exists():
                        self.order_number = code
                        break
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


class ExtraMoneyRequestStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    APPROVED = 'approved', 'Approved'
    REJECTED = 'rejected', 'Rejected'


class OrderExtraMoneyRequest(models.Model):
    """
    Extra money increment requested by assigned master, pending client approval.
    This creates an audit trail and avoids silent price changes for the client.
    """

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='extra_money_requests',
        verbose_name='Order',
    )
    master = models.ForeignKey(
        'master.Master',
        on_delete=models.CASCADE,
        related_name='extra_money_requests',
        verbose_name='Master',
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name='Amount',
        help_text='Requested extra money increment (positive).',
    )
    master_comment = models.TextField(
        blank=True,
        default='',
        verbose_name='Master comment',
        help_text='Reason/description for the extra money request.',
    )
    status = models.CharField(
        max_length=16,
        choices=ExtraMoneyRequestStatus.choices,
        default=ExtraMoneyRequestStatus.PENDING,
        db_index=True,
        verbose_name='Status',
    )
    client_comment = models.TextField(
        blank=True,
        default='',
        verbose_name='Client comment',
        help_text='Required when rejecting (reason).',
    )
    decided_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Decided at',
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Created at',
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Updated at',
    )

    class Meta:
        verbose_name = 'Order extra money request'
        verbose_name_plural = 'Order extra money requests'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['order', 'status']),
            models.Index(fields=['master', 'status']),
        ]

    def __str__(self):
        return f'ExtraMoneyRequest#{self.pk} order={self.order_id} amount={self.amount} status={self.status}'


class ServiceAddRequestStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    APPROVED = 'approved', 'Approved'
    REJECTED = 'rejected', 'Rejected'


class OrderServiceAddRequest(models.Model):
    """
    Pending request from assigned master to add one or more extra services to an order.
    Services are applied to the order ONLY after client approval.

    `services_json` shape:
      [{ "master_service_item_id": 123, "count": 1 }, ...]
    """

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='service_add_requests',
        verbose_name='Order',
    )
    master = models.ForeignKey(
        'master.Master',
        on_delete=models.CASCADE,
        related_name='service_add_requests',
        verbose_name='Master',
    )
    services_json = models.JSONField(
        default=list,
        blank=True,
        verbose_name='Requested services (items)',
        help_text='List of items: { "master_service_item_id": <int>, "count": <int>=1.. }',
    )
    master_comment = models.TextField(
        blank=True,
        default='',
        verbose_name='Master comment',
        help_text='Reason/description for adding services.',
    )
    status = models.CharField(
        max_length=16,
        choices=ServiceAddRequestStatus.choices,
        default=ServiceAddRequestStatus.PENDING,
        db_index=True,
        verbose_name='Status',
    )
    client_comment = models.TextField(
        blank=True,
        default='',
        verbose_name='Client comment',
        help_text='Required when rejecting (reason).',
    )
    decided_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Decided at',
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Created at',
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Updated at',
    )

    class Meta:
        verbose_name = 'Order service add request'
        verbose_name_plural = 'Order service add requests'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['order', 'status']),
            models.Index(fields=['master', 'status']),
        ]

    def __str__(self):
        return f'ServiceAddRequest#{self.pk} order={self.order_id} status={self.status}'


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


class MasterAssignmentFailureReason(models.TextChoices):
    """System-initiated assignment failures (completion rate)."""

    SOS_NO_DEPARTURE = 'sos_no_departure', 'SOS: no departure after accept'
    STANDARD_NO_DEPARTURE = 'standard_no_departure', 'Standard: no departure after accept'
    SCHEDULED_NO_START = 'scheduled_no_start', 'Scheduled: did not start by deadline'


class MasterAssignmentFailure(models.Model):
    """
    When the system penalizes a master (reassign / auto-cancel) but the order is no longer
    ``master`` + ``cancelled`` on the same row (e.g. SOS rebroadcast), this row drives completion rate.
    """

    master = models.ForeignKey(
        'master.Master',
        on_delete=models.CASCADE,
        related_name='assignment_failures',
        verbose_name='Master',
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='assignment_failures',
        verbose_name='Order',
    )
    reason = models.CharField(
        max_length=32,
        choices=MasterAssignmentFailureReason.choices,
        verbose_name='Reason',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created at')

    class Meta:
        verbose_name = 'Master assignment failure'
        verbose_name_plural = 'Master assignment failures'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=('master', 'order', 'reason'),
                name='uniq_master_assignment_failure_master_order_reason',
            ),
        ]

    def __str__(self):
        return f'Failure {self.reason}: master={self.master_id} order={self.order_id}'


class MasterOfferEventStatus(models.TextChoices):
    SENT = 'sent', 'Sent'
    ACCEPTED = 'accepted', 'Accepted'
    DECLINED = 'declined', 'Declined'
    EXPIRED = 'expired', 'Expired'


class MasterOfferEvent(models.Model):
    """
    Per-master offer audit trail to compute acceptance rate reliably.
    Created when the system sends an order offer to a master (standard assignment or SOS broadcast).
    Updated on accept/decline/expiry.
    """

    master = models.ForeignKey(
        'master.Master',
        on_delete=models.CASCADE,
        related_name='offer_events',
        verbose_name='Master',
    )
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='offer_events',
        verbose_name='Order',
    )
    status = models.CharField(
        max_length=16,
        choices=MasterOfferEventStatus.choices,
        default=MasterOfferEventStatus.SENT,
        verbose_name='Offer status',
    )
    offered_at = models.DateTimeField(auto_now_add=True, verbose_name='Offered at')
    responded_at = models.DateTimeField(null=True, blank=True, verbose_name='Responded at')

    class Meta:
        verbose_name = 'Master offer event'
        verbose_name_plural = 'Master offer events'
        ordering = ['-offered_at']
        constraints = [
            models.UniqueConstraint(fields=('master', 'order'), name='uniq_master_offer_event_master_order'),
        ]

    def __str__(self):
        return f'Offer {self.status}: master={self.master_id} order={self.order_id}'


class ReviewTag(models.TextChoices):
    """Aspect of the experience (positive or negative); client may pick several."""

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
    tags = models.JSONField(
        default=list,
        verbose_name='Review tags',
        help_text='List of ReviewTag values (at least one)',
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
        valid = {c[0] for c in ReviewTag.choices}
        raw = self.tags
        if not isinstance(raw, list) or len(raw) == 0:
            raise ValidationError({'tags': 'Select at least one tag.'})
        seen = set()
        ordered_unique = []
        for t in raw:
            if t not in valid:
                raise ValidationError({'tags': f'Invalid tag: {t}'})
            if t not in seen:
                seen.add(t)
                ordered_unique.append(t)
        self.tags = ordered_unique

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
    count = models.PositiveIntegerField(
        default=1,
        verbose_name='Count',
        help_text='How many times this service is applied within the order (per service item).',
    )
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Locked unit price',
        help_text=(
            'Per-car base price frozen when the line is added (or on order completion). '
            'Master profile price changes must not alter past orders.'
        ),
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


class CustomRequestOffer(models.Model):
    """Price offer from a master on a pending custom-request order (client compares via WebSocket + API)."""

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='custom_request_offers',
        verbose_name='Order',
    )
    master = models.ForeignKey(
        'master.Master',
        on_delete=models.CASCADE,
        related_name='custom_request_offers',
        verbose_name='Master',
    )
    price = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='Offer price')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created at')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Updated at')

    class Meta:
        verbose_name = 'Custom request offer'
        verbose_name_plural = 'Custom request offers'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=('order', 'master'), name='uniq_custom_request_offer_order_master'),
        ]

    def __str__(self):
        return f'Order {self.order_id} offer from master {self.master_id}'


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


class CustomRequestOrderManager(models.Manager):
    """Manager for custom-request orders (client broadcast; masters send offers)."""

    def get_queryset(self):
        return super().get_queryset().filter(order_type=OrderType.CUSTOM_REQUEST)


class CustomRequestOrder(Order):
    """Proxy for custom-request orders (same DB table as ``Order``)."""

    objects = CustomRequestOrderManager()

    class Meta:
        proxy = True
        verbose_name = 'Custom request order'
        verbose_name_plural = 'Custom request orders'
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.order_type:
            self.order_type = OrderType.CUSTOM_REQUEST
        super().save(*args, **kwargs)
