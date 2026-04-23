from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.sites.models import Site
from .models import (
    CustomUser,
    MasterCustomUser,
    CarOwner,
    Owner,
    UserBalance,
    UserSMSCode,
    UserDevice,
    FAQ,
    EmailVerificationToken,
    AppVersion,
)
from apps.car.models import Car
from django.utils.html import mark_safe



class CarInline(admin.TabularInline):
    """Inline for cars"""
    
    def get_icon(self, obj):
        if obj.image:
            return mark_safe(f'<img src="{obj.image.url}" height="150px" width="150px" alt="Car image" />')
        return '-'

    get_icon.short_description = 'Car image'

    model = Car
    extra = 0
    readonly_fields = ('brand', 'model', 'year', 'get_icon')
    fields = ('get_icon','brand', 'model', 'year' )
    can_delete = False
    max_num = 0  # Display only, no editing


class UserBalanceInline(admin.StackedInline):
    """Inline for user balance"""
    model = UserBalance
    extra = 0
    readonly_fields = ('created_at', 'updated_at')
    fields = ('amount', 'created_at', 'updated_at')


class UserSMSCodeInline(admin.TabularInline):
    """Inline for user SMS codes"""
    model = UserSMSCode
    extra = 0
    readonly_fields = ('code', 'identifier', 'identifier_type', 'created_at', 'expires_at', 'is_used', 'used_at')
    fields = ('code', 'identifier', 'identifier_type', 'created_at', 'expires_at', 'is_used', 'used_at')
    can_delete = False
    max_num = 0  # Display only, no editing


class EmailVerificationTokenInline(admin.TabularInline):
    """Inline for email verification tokens"""
    model = EmailVerificationToken
    extra = 0
    readonly_fields = ('token', 'email', 'created_at', 'expires_at', 'is_used')
    fields = ('token', 'email', 'created_at', 'expires_at', 'is_used')
    can_delete = False
    max_num = 0  # Display only, no editing
    
    
@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    """
    Base admin for CustomUser (hidden from menu but available via links)
    """

    def has_module_permission(self, request):
        """Hide from admin menu"""
        return False

    list_display = ('private_id', 'email', 'username', 'first_name', 'last_name', 'created_at')
    list_filter = ('groups', 'is_verified', 'is_staff', 'is_superuser', 'is_active', 'created_at')
    search_fields = ('email', 'username', 'first_name', 'last_name', 'phone_number', 'private_id')
    ordering = ('-created_at',)
    inlines = [UserBalanceInline, UserSMSCodeInline]

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal information', {'fields': ('private_id', 'first_name', 'last_name', 'email', 'phone_number', 'date_of_birth', 'avatar')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups')}),
        ('Important dates', {'fields': ('last_login', 'date_joined', 'created_at', 'updated_at')}),
        ('Verification', {'fields': ('is_verified', 'is_email_verified')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'first_name', 'last_name', 'password1', 'password2'),
        }),
    )

    readonly_fields = ('private_id', 'created_at', 'updated_at', 'date_joined', 'last_login')


@admin.register(MasterCustomUser)
class MasterCustomUserAdmin(UserAdmin):
    """
    Admin for masters
    """

    def get_role_name(self, obj):
        return obj.get_role_name()
    get_role_name.short_description = 'Role'

    def get_queryset(self, request):
        """Filter only users with Master group"""
        qs = super().get_queryset(request)
        return qs.filter(groups__name='Master').distinct()

    list_display = ('private_id', 'email', 'phone_number', 'first_name', 'last_name', 'get_role_name', 'created_at')
    list_filter = ('is_verified', 'is_staff', 'is_active', 'created_at')
    search_fields = ('email', 'username', 'first_name', 'last_name', 'phone_number')
    ordering = ('-created_at',)
    inlines = [UserSMSCodeInline]

    fieldsets = (
        ('Personal information', {'fields': ('private_id', 'first_name', 'last_name', 'email', 'phone_number', 'date_of_birth', 'avatar')}),
        ('Verification', {'fields': ('is_verified', 'is_email_verified')}),
        ('Important dates', {'fields': ('last_login', 'date_joined', 'created_at', 'updated_at')}),
        
    )

    readonly_fields = ('created_at', 'updated_at', 'date_joined', 'last_login')


@admin.register(CarOwner)
class CarOwnerAdmin(UserAdmin):
    """
    Admin for car owners (users in the Driver group).
    """

    def get_role_name(self, obj):
        return obj.get_role_name()
    get_role_name.short_description = 'Role'

    def get_queryset(self, request):
        """Filter only users with Driver group"""
        qs = super().get_queryset(request)
        return qs.filter(groups__name='Driver').distinct()

    list_display = ('private_id', 'email', 'phone_number', 'first_name', 'last_name', 'get_role_name', 'created_at')
    list_filter = ('is_verified', 'is_staff', 'is_active', 'created_at', 'groups')
    search_fields = ('email', 'username', 'first_name', 'last_name', 'phone_number', 'private_id')
    ordering = ('-created_at',)
    inlines = [EmailVerificationTokenInline, CarInline]

    fieldsets = (
        ('Personal information', {'fields': ('private_id', 'first_name', 'last_name', 'email', 'phone_number', 'date_of_birth', 'avatar')}),
        ('Location', {'fields': ('address', 'longitude', 'latitude')}),
        ('Verification', {'fields': ('is_verified', 'is_email_verified')}),
        ('Important dates', {'fields': ('last_login', 'date_joined', 'created_at', 'updated_at')}),
    )

    readonly_fields = ('private_id', 'created_at', 'updated_at', 'date_joined', 'last_login')
    

@admin.register(UserDevice)
class UserDeviceAdmin(admin.ModelAdmin):
    list_display = ('user', 'device_type', 'device_token_short', 'updated_at', 'created_at')
    list_filter = ('device_type', 'updated_at')
    search_fields = ('device_token', 'user__email', 'user__phone_number', 'user__private_id')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-updated_at',)

    @admin.display(description='Token (short)')
    def device_token_short(self, obj):
        t = obj.device_token or ''
        return f'{t[:24]}…' if len(t) > 24 else t


@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    """Admin for FAQ"""
    list_display = ('question_short', 'order', 'is_active', 'created_at', 'updated_at')
    list_filter = ('is_active', 'created_at', 'updated_at')
    search_fields = ('question', 'answer')
    ordering = ('order', '-created_at')
    list_editable = ('order', 'is_active')

    fieldsets = (
        (None, {'fields': ('question', 'answer', 'order', 'is_active')}),
        ('Dates', {'fields': ('created_at', 'updated_at')}),
    )

    readonly_fields = ('created_at', 'updated_at')

    def question_short(self, obj):
        """Short version of question for list display"""
        return obj.question[:100] + '...' if len(obj.question) > 100 else obj.question
    question_short.short_description = 'Question'


admin.site.unregister(Site)

admin.site.register(AppVersion)

admin.site.site_header = 'AutoHandy'
admin.site.site_title = 'AutoHandy'
admin.site.index_title = 'AutoHandy'