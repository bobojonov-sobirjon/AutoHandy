from django.core.validators import MinValueValidator
from django.db import models
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from apps.categories.models import Category

User = get_user_model()


class Master(models.Model):
    """Master (workshop) model"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='master_profiles',
        verbose_name='User'
    )

    name = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='Workshop name',
        help_text='Workshop name (e.g. "Auto Service Station")'
    )

    category = models.ManyToManyField(
        Category,
        verbose_name='Category',
        related_name='master_categories'
    )

    # Location
    city = models.CharField(max_length=100, blank=True, default='', verbose_name='City')
    address = models.TextField(blank=True, verbose_name='Address')
    latitude = models.DecimalField(
        max_digits=12,
        decimal_places=9,
        null=True,
        blank=True,
        verbose_name='Latitude'
    )
    longitude = models.DecimalField(
        max_digits=12,
        decimal_places=9,
        null=True,
        blank=True,
        verbose_name='Longitude'
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
        Category,
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

    def __str__(self):
        return f'{self.master_id} {self.date} {self.start_time}-{self.end_time}'
