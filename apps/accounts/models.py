from django.contrib.auth.models import AbstractUser
from django.db import models
from decimal import Decimal
import random


class CustomUser(AbstractUser):
    """
    Custom User model that extends Django's AbstractUser
    """
    email = models.EmailField(
        unique=True,
        verbose_name="Email",
        help_text="Required. Enter a valid email address."
    )
    phone_number = models.CharField(
        max_length=15,
        blank=True,
        null=True,
        verbose_name="Phone number",
        help_text="Optional. Enter your phone number."
    )
    telegram_chat_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="Telegram Chat ID",
        help_text="Optional. Enter your Telegram Chat ID for SMS."
    )
    private_id = models.CharField(
        max_length=6,
        unique=True,
        blank=True,
        null=True,
        verbose_name="Private ID",
        help_text="Unique 6-digit user identifier. Generated automatically."
    )
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name="Description",
        help_text="Optional. Enter your description."
    )
    date_of_birth = models.DateField(
        blank=True,
        null=True,
        verbose_name="Date of birth",
        help_text="Optional. Enter your date of birth."
    )
    avatar = models.ImageField(
        upload_to='avatars/',
        blank=True,
        null=True,
        verbose_name="Avatar",
        help_text="Optional. Upload your profile photo."
    )
    address = models.TextField(
        blank=True,
        null=True,
        verbose_name="Address",
        help_text="Optional. Enter your address."
    )
    longitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        blank=True,
        null=True,
        verbose_name="Longitude",
        help_text="Optional. Longitude of your location."
    )
    latitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        blank=True,
        null=True,
        verbose_name="Latitude",
        help_text="Optional. Latitude of your location."
    )
    is_verified = models.BooleanField(
        default=False,
        verbose_name="Email verified",
        help_text="Indicates whether this user's email is verified."
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created at"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated at"
    )

    # Use email as the username field
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'first_name', 'last_name']

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.email} ({self.get_full_name()})"

    def _generate_unique_private_id(self):
        """Generate unique 6-digit private_id"""
        while True:
            private_id = str(random.randint(100000, 999999))
            if not CustomUser.objects.filter(private_id=private_id).exists():
                return private_id

    def save(self, *args, **kwargs):
        """Override save for automatic private_id generation"""
        if not self.private_id:
            self.private_id = self._generate_unique_private_id()
        super().save(*args, **kwargs)

    def get_full_name(self):
        """
        Return the first_name plus the last_name, with a space in between.
        """
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name if full_name else self.email

    def get_short_name(self):
        """
        Return the short name for the user.
        """
        return self.first_name if self.first_name else self.email

    def get_role_name(self):
        """
        Return the role name based on user groups.
        """
        groups = self.groups.all()
        if groups.exists():
            return groups.first().name
        return 'No role'


class UserBalance(models.Model):
    """
    User balance model for managing user's financial balance
    """
    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='balance',
        verbose_name="User"
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        verbose_name="Balance amount",
        help_text="Current user balance"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created at"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated at"
    )

    class Meta:
        verbose_name = "User balance"
        verbose_name_plural = "03. User balances"
        ordering = ['-updated_at']

    def __str__(self):
        return f"Balance {self.user.get_full_name()}: {self.amount}"

    def has_minimum_balance(self, minimum=1000):
        """
        Check if user has minimum balance
        """
        return self.amount >= Decimal(str(minimum))

    def can_afford_order(self, order_cost=200):
        """
        Check if user can afford order
        """
        return self.amount >= Decimal(str(order_cost))

    def deduct_amount(self, amount):
        """
        Deduct amount from balance
        """
        if self.can_afford_order(amount):
            self.amount -= Decimal(str(amount))
            self.save()
            return True
        return False

    def add_amount(self, amount):
        """
        Add amount to balance
        """
        self.amount += Decimal(str(amount))
        self.save()

    @classmethod
    def get_or_create_balance(cls, user):
        """
        Get or create balance for user
        """
        balance, created = cls.objects.get_or_create(
            user=user,
            defaults={'amount': 0.00}
        )
        return balance


class UserSMSCode(models.Model):
    """
    Model for storing SMS codes with created_by tracking
    """
    code = models.CharField(
        max_length=10,
        verbose_name="SMS code",
        help_text="Verification code"
    )
    identifier = models.CharField(
        max_length=255,
        verbose_name="Identifier",
        help_text="Phone number or email"
    )
    identifier_type = models.CharField(
        max_length=10,
        choices=[('phone', 'Phone'), ('email', 'Email')],
        verbose_name="Identifier type",
        help_text="Identifier type: phone or email"
    )
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='sms_codes',
        null=True,
        blank=True,
        verbose_name="Created by",
        help_text="User who requested the code (if registered)"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created at"
    )
    expires_at = models.DateTimeField(
        verbose_name="Expires at"
    )
    is_used = models.BooleanField(
        default=False,
        verbose_name="Used",
        help_text="Whether the code was used"
    )
    used_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Used at"
    )

    class Meta:
        verbose_name = "SMS code"
        verbose_name_plural = "SMS codes"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['identifier', 'identifier_type']),
            models.Index(fields=['code', 'identifier']),
            models.Index(fields=['is_used', 'expires_at']),
        ]

    def __str__(self):
        return f"SMS code {self.code} for {self.identifier}"

    def is_expired(self):
        """Check if code has expired"""
        from django.utils import timezone
        return timezone.now() > self.expires_at

    def mark_as_used(self):
        """Mark code as used"""
        from django.utils import timezone
        self.is_used = True
        self.used_at = timezone.now()
        self.save(update_fields=['is_used', 'used_at'])


class MasterCustomUser(CustomUser):
    """
    Proxy model for masters
    """
    class Meta:
        proxy = True
        verbose_name = "Master"
        verbose_name_plural = "02. Masters"


class CarOwner(CustomUser):
    """
    Proxy model for car owners
    """
    class Meta:
        proxy = True
        verbose_name = "Car owner"
        verbose_name_plural = "01. Car owners"


class Owner(CustomUser):
    """
    Proxy model for owners
    """
    class Meta:
        proxy = True
        verbose_name = "Owner"
        verbose_name_plural = "Owners"


class FAQ(models.Model):
    """
    FAQ (Frequently Asked Questions) model
    """
    question = models.TextField(
        verbose_name="Question",
        help_text="Frequently asked question"
    )
    answer = models.TextField(
        verbose_name="Answer",
        help_text="Answer to the question"
    )
    order = models.IntegerField(
        default=0,
        verbose_name="Order",
        help_text="Display order (lower number = higher)"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Active",
        help_text="Whether to show question in list"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created at"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated at"
    )

    class Meta:
        verbose_name = "FAQ"
        verbose_name_plural = "04. FAQ"
        ordering = ['order', '-created_at']

    def __str__(self):
        return f"{self.question[:50]}..."
