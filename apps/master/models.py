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

    # Bank details
    card_number = models.CharField(max_length=19, blank=True, verbose_name='Card number')
    card_expiry_month = models.PositiveIntegerField(null=True, blank=True, verbose_name='Card expiry month')
    card_expiry_year = models.PositiveIntegerField(null=True, blank=True, verbose_name='Card expiry year')
    card_cvv = models.CharField(max_length=4, blank=True, verbose_name='CVV/CVC')

    # Master balance
    balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        verbose_name='Master balance'
    )

    # Reserved amount
    reserved_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        verbose_name='Reserved amount'
    )

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

    def can_take_order(self, amount=200):
        """Whether master can take order (reserve check)"""
        return self.reserved_amount >= amount

    def reserve_amount(self, amount):
        """Reserve amount"""
        self.reserved_amount += amount
        self.save(update_fields=['reserved_amount'])

    def release_amount(self, amount):
        """Release reserved amount"""
        self.reserved_amount = max(0, self.reserved_amount - amount)
        self.save(update_fields=['reserved_amount'])


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
    """Master service item"""
    master_service = models.ForeignKey(
        MasterService,
        on_delete=models.CASCADE,
        related_name='master_service_items',
        verbose_name='Master service'
    )
    name = models.CharField(max_length=200, default='', verbose_name='Service name')
    price_from = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        verbose_name='Price from'
    )
    price_to = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        verbose_name='Price to'
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name='master_service_items',
        verbose_name='Category'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Added at')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Updated at')

    class Meta:
        verbose_name = 'Master service item'
        verbose_name_plural = 'Master service items'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.master_service} - {self.name}: {self.price_from}-{self.price_to}"


class MasterEmployee(models.Model):
    """Workshop employees"""
    master = models.ForeignKey(
        Master,
        on_delete=models.CASCADE,
        related_name='employees',
        verbose_name='Master'
    )
    employee = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='master_employments',
        verbose_name='Employee'
    )
    added_at = models.DateTimeField(auto_now_add=True, verbose_name='Added at')

    class Meta:
        verbose_name = 'Workshop employee'
        verbose_name_plural = 'Workshop employees'
        unique_together = ['master', 'employee']
        ordering = ['added_at']

    def __str__(self):
        return f"{self.master} - {self.employee.email}"
