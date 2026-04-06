from django.core.validators import MinValueValidator
from django.db import models
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

User = get_user_model()


class MasterServiceAreaRadiusMiles(models.IntegerChoices):
    """Work zone radius tiers (miles). Separate from home / profile address."""

    MILES_15 = 15, '15 miles (minimum)'
    MILES_45 = 45, '45 miles (medium)'
    MILES_100 = 100, '100 miles (extended)'


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
        max_digits=12,
        decimal_places=9,
        null=True,
        blank=True,
        verbose_name='Latitude',
        help_text='Workshop / service point on map; used with service area radius for distance and visibility.',
    )
    longitude = models.DecimalField(
        max_digits=12,
        decimal_places=9,
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
        """Order completion rate percentage"""
        return 0  # Field removed, always return 0

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
            if self.time_range_rest is None or self.time_range_rest <= 0:
                raise ValidationError(
                    {'time_range_rest': 'Set a positive duration when start_time_rest is set.'}
                )
        elif self.time_range_rest is not None and self.time_range_rest > 0:
            raise ValidationError(
                {'start_time_rest': 'Set start_time_rest when time_range_rest is set.'}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.master_id} {self.date} {self.start_time}-{self.end_time}'
