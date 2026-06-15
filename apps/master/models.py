from django.core.validators import MinValueValidator
from django.db import models
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.master.towing_types import TowingServiceType

User = get_user_model()


class MasterServiceAreaRadiusMiles(models.IntegerChoices):
    """Work zone radius tiers (miles). Separate from home / profile address."""

    MILES_15 = 15, '15 miles (minimum)'
    MILES_45 = 45, '45 miles (medium)'
    MILES_100 = 100, '100 miles (extended)'


class MasterIdentityVerificationStatus(models.TextChoices):
    NOT_STARTED = 'not_started', 'Not started'
    PENDING = 'pending', 'Pending'
    VERIFIED = 'verified', 'Verified'
    REQUIRES_INPUT = 'requires_input', 'Requires input'
    CANCELED = 'canceled', 'Canceled'
    FAILED = 'failed', 'Failed'


class Master(models.Model):
    """Master (workshop) model"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='master_profiles',
        verbose_name='User'
    )

    # Location
    city = models.CharField(max_length=100, blank=True, default='', verbose_name='City')
    address = models.TextField(blank=True, verbose_name='Address')
    latitude = models.DecimalField(
        max_digits=22,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name='Latitude',
        help_text='Workshop / service point on map; used with service area radius for distance and visibility.',
    )
    longitude = models.DecimalField(
        max_digits=22,
        decimal_places=18,
        null=True,
        blank=True,
        verbose_name='Longitude',
        help_text='Workshop / service point on map; used with service area radius for distance and visibility.',
    )

    service_area_radius_miles = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        choices=MasterServiceAreaRadiusMiles.choices,
        verbose_name='Service area radius (miles)',
        help_text='15 / 45 / 100 miles around latitude/longitude for order matching.',
    )

    phone = models.CharField(max_length=20, default='', verbose_name='Phone')
    working_time = models.CharField(max_length=100, default='', verbose_name='Working hours')

    description = models.TextField(blank=True, verbose_name='Description', null=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created at')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Updated at')
    last_activity = models.DateTimeField(null=True, blank=True, verbose_name='Last activity')
    stripe_connect_account_id = models.CharField(
        max_length=64,
        blank=True,
        default='',
        verbose_name='Stripe Connect account id',
        help_text='acct_… — destination for marketplace payouts.',
    )
    stripe_identity_verification_session_id = models.CharField(
        max_length=128,
        blank=True,
        default='',
        verbose_name='Stripe Identity verification session id',
        help_text='vs_… — document/selfie verification session (no PII stored locally).',
    )
    identity_verification_status = models.CharField(
        max_length=32,
        choices=MasterIdentityVerificationStatus.choices,
        default=MasterIdentityVerificationStatus.NOT_STARTED,
        verbose_name='Identity verification status',
    )
    identity_verified_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Identity verified at',
    )
    identity_last_error_code = models.CharField(
        max_length=64,
        blank=True,
        default='',
        verbose_name='Identity last error code',
        help_text='Stripe error code only — no document or SSN data.',
    )

    class Meta:
        verbose_name = 'Master'
        verbose_name_plural = 'Masters'
        ordering = ['-created_at']

    def __str__(self):
        return f"Master {self.user.get_full_name() or self.user.phone_number}"

    @property
    def full_name(self):
        """Master full name"""
        return self.user.get_full_name() or self.user.phone_number

    @property
    def phone_number(self):
        """Master phone number"""
        return self.user.phone_number

    @property
    def completion_rate(self):
        """Order completion rate percentage (all-time)."""
        try:
            from apps.master.services.rates import master_completion_rate_percent

            return master_completion_rate_percent(self)
        except Exception:  # noqa: BLE001
            return 0

    def get_work_location_for_distance(self):
        """Point for distance to orders: latitude / longitude."""
        if self.latitude is not None and self.longitude is not None:
            return float(self.latitude), float(self.longitude)
        return None, None

    def max_order_distance_km(self) -> float:
        """Max distance from work location to order/client location for this master."""
        from apps.master.services.geo import MILES_TO_KM

        if self.service_area_radius_miles:
            return float(self.service_area_radius_miles) * MILES_TO_KM
        return 50.0


class MasterImage(models.Model):
    """Master image"""
    master = models.ForeignKey(
        Master,
        on_delete=models.CASCADE,
        related_name='master_images',
        verbose_name='Master'
    )
    image = models.ImageField(upload_to='master_images/', verbose_name='Image')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Added at')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Updated at')

    class Meta:
        verbose_name = 'Master image'
        verbose_name_plural = 'Master images'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.master} - {self.image.name}"


class MasterService(models.Model):
    """Master services with prices"""
    master = models.ForeignKey(
        Master,
        on_delete=models.CASCADE,
        related_name='master_services',
        verbose_name='Master'
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Added at')

    class Meta:
        verbose_name = 'Master service'
        verbose_name_plural = 'Master services'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.master} - {self.id}"


class MasterServiceItems(models.Model):
    """
    One priced line per by_order service subcategory (same catalog as driver orders).
    """

    master_service = models.ForeignKey(
        MasterService,
        on_delete=models.CASCADE,
        related_name='master_service_items',
        verbose_name='Master service',
    )
    category = models.ForeignKey(
        'categories.Category',
        on_delete=models.CASCADE,
        related_name='master_service_items',
        verbose_name='Service (subcategory)',
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name='Price',
    )
    has_gas_container_2gal = models.BooleanField(
        default=False,
        verbose_name='Has separate 2-gallon gas container',
        help_text='Required for Fuel Delivery: master confirms a dedicated gasoline container.',
    )
    has_diesel_container_2gal = models.BooleanField(
        default=False,
        verbose_name='Has separate 2-gallon diesel container',
        help_text='Required for Fuel Delivery: master confirms a dedicated diesel container.',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Added at')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Updated at')

    class Meta:
        verbose_name = 'Master service item'
        verbose_name_plural = 'Master service items'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['master_service', 'category'],
                name='uniq_masterserviceitem_service_category',
            ),
        ]

    def __str__(self):
        return f'{self.category.name} – {self.price}'

    @property
    def fuel_delivery_equipment_confirmed(self) -> bool:
        return bool(self.has_gas_container_2gal and self.has_diesel_container_2gal)

    def fuel_delivery_is_active(self) -> bool:
        from apps.categories.services.fuel_delivery_catalog import is_fuel_delivery_category

        if not self.category_id:
            return False
        if not is_fuel_delivery_category(self.category):
            return True
        return self.fuel_delivery_equipment_confirmed


class MasterScheduleDay(models.Model):
    """Working hours for a specific calendar day (min. 14 days ahead coverage expected by app)."""

    master = models.ForeignKey(
        Master,
        on_delete=models.CASCADE,
        related_name='schedule_days',
        verbose_name='Master',
    )
    date = models.DateField(verbose_name='Date', db_index=True)
    start_time = models.TimeField(verbose_name='Start time')
    end_time = models.TimeField(verbose_name='End time')

    class Meta:
        verbose_name = 'Master schedule day'
        verbose_name_plural = 'Master schedule days'
        ordering = ['date', 'start_time']
        constraints = [
            models.UniqueConstraint(fields=['master', 'date'], name='uniq_master_schedule_date'),
        ]

    def clean(self):
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValidationError('end_time must be after start_time.')

    def __str__(self):
        return f'{self.master_id} {self.date} {self.start_time}-{self.end_time}'


class MasterBusySlot(models.Model):
    """
    Occupied interval on a day: linked to a scheduled order or a manual master block.
    """

    master = models.ForeignKey(
        Master,
        on_delete=models.CASCADE,
        related_name='busy_slots',
        verbose_name='Master',
    )
    date = models.DateField(verbose_name='Date', db_index=True)
    start_time = models.TimeField(verbose_name='Start time')
    end_time = models.TimeField(verbose_name='End time')
    start_time_rest = models.TimeField(
        null=True,
        blank=True,
        verbose_name='Rest start',
        help_text='If set with time_range_rest, marks a daily break; start/end are derived. '
        'Only for manual slots (no order).',
    )
    time_range_rest = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Rest duration (hours)',
        help_text='Break length from start_time_rest (e.g. 1.00). Used for available-slots break_data.',
    )
    order = models.OneToOneField(
        'order.Order',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='master_busy_slot',
        verbose_name='Order',
    )
    reason = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='Note',
        help_text='Optional note for manual blocks',
    )

    class Meta:
        verbose_name = 'Master busy slot'
        verbose_name_plural = 'Master busy slots'
        ordering = ['date', 'start_time']

    def clean(self):
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValidationError('end_time must be after start_time.')

        if self.order_id:
            if self.start_time_rest is not None or (
                self.time_range_rest is not None and self.time_range_rest > 0
            ):
                raise ValidationError('Rest fields are not allowed on order-linked busy slots.')

        if self.start_time_rest is not None:
            if self.time_range_rest is None or self.time_range_rest < 0:
                raise ValidationError(
                    {'time_range_rest': 'Set a duration >= 0 when start_time_rest is set.'}
                )
        elif self.time_range_rest is not None:
            raise ValidationError(
                {'start_time_rest': 'Set start_time_rest when time_range_rest is set.'}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.master_id} {self.date} {self.start_time}-{self.end_time}'


class MasterTowingPricing(models.Model):
    """Per-master, per-service-type towing tariff: base fee + per mile + minimum."""

    master = models.ForeignKey(
        Master,
        on_delete=models.CASCADE,
        related_name='towing_pricing_items',
        verbose_name='Master',
    )
    service_type = models.CharField(
        max_length=32,
        choices=TowingServiceType.choices,
        verbose_name='Service type',
    )
    base_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name='Base fee',
        help_text='Flat fee for this towing service type (e.g. $80).',
    )
    price_per_mile = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name='Price per mile',
        help_text='Additional charge per mile (e.g. $5).',
    )
    minimum_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name='Minimum total',
        help_text='Final price for this service type will not be lower than this amount.',
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='Active',
        help_text='When false, master is hidden from estimates for this service type.',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created at')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Updated at')

    class Meta:
        verbose_name = 'Master towing pricing'
        verbose_name_plural = 'Master towing pricing'
        constraints = [
            models.UniqueConstraint(
                fields=['master', 'service_type'],
                name='master_towing_pricing_master_service_type_uniq',
            ),
        ]
        ordering = ['master_id', 'service_type']

    def __str__(self):
        return f'Towing {self.service_type} for master {self.master_id}'

    def has_configured_rates(self) -> bool:
        return self.is_active and (self.base_fee > 0 or self.price_per_mile > 0)
