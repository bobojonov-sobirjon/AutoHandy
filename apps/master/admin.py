from django.contrib import admin
from django.utils.html import format_html
from nested_admin import NestedModelAdmin, NestedTabularInline

from apps.categories.models import Category

from .models import (
    Master,
    MasterBusySlot,
    MasterImage,
    MasterScheduleDay,
    MasterService,
    MasterServiceItems,
)


def _thumbnail(file_field, height=60):
    """
    Render an image thumbnail in Django admin.
    If media is missing, returns a dash.
    """
    if not file_field:
        return '-'
    try:
        return format_html("<img src='{}' style='height:{}px; width:auto;' />", file_field.url, height)
    except Exception:
        return '-'


class MasterImageInline(NestedTabularInline):
    model = MasterImage
    extra = 1
    ordering = ('-created_at',)
    fields = ('image_preview', 'image', 'created_at')
    readonly_fields = ('image_preview', 'created_at')

    def image_preview(self, obj):
        return _thumbnail(obj.image)


class MasterScheduleDayInline(NestedTabularInline):
    model = MasterScheduleDay
    extra = 1
    ordering = ('date',)
    fields = ('date', 'start_time', 'end_time')


class MasterBusySlotInline(NestedTabularInline):
    model = MasterBusySlot
    extra = 1
    ordering = ('date', 'start_time')
    fields = ('date', 'start_time', 'end_time', 'reason', 'order')
    readonly_fields = ('order',)


class MasterServiceItemsInline(NestedTabularInline):
    model = MasterServiceItems
    extra = 1
    ordering = ('-created_at',)
    fields = ('category_icon_preview', 'category', 'price')
    readonly_fields = ('category_icon_preview',)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'category':
            # API (validate_skill_category) allows only by_order catalog for line items.
            kwargs['queryset'] = Category.objects.filter(
                type_category=Category.TypeCategory.BY_ORDER,
            ).select_related('parent').order_by('parent_id', 'name')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def category_icon_preview(self, obj):
        if not obj or not obj.category_id:
            return '-'
        return _thumbnail(obj.category.icon)


class MasterServiceInline(NestedTabularInline):
    """
    Master ichida services chiqarish uchun nested inline.
    Bu inline 'master' FK ni avtomatik oladi (parent Master bo'lgani uchun).
    """

    model = MasterService
    extra = 0
    ordering = ('-created_at',)
    # master FK parent Master ga to'g'ri bo'lgani uchun admin uni avtomatik bog'laydi.
    inlines = [MasterServiceItemsInline]


@admin.register(Master)
class MasterAdmin(NestedModelAdmin):
    list_display = (
        'full_name',
        'phone_number',
        'city',
        'latitude',
        'longitude',
        'service_area_radius_miles',
        'created_at',
    )
    list_filter = ('city', 'created_at')
    search_fields = ('user__phone_number', 'user__first_name', 'user__last_name', 'city')
    ordering = ('-created_at',)

    fieldsets = (
        ('Profile', {
            'fields': ('user', 'description'),
        }),
        ('Location', {
            'fields': ('city', 'address', 'latitude', 'longitude', 'service_area_radius_miles'),
            'description': 'Map pin (lat/lon) + optional service radius (15 / 45 / 100 miles).',
        }),
        ('Contact', {
            'fields': ('phone', 'working_time'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'last_activity'),
            'classes': ('collapse',),
        }),
    )

    readonly_fields = ('created_at', 'updated_at', 'last_activity')

    inlines = [
        MasterServiceInline,
        MasterImageInline,
        MasterScheduleDayInline,
        MasterBusySlotInline,
    ]

    def full_name(self, obj):
        return obj.full_name

    full_name.short_description = 'Full name'

    def phone_number(self, obj):
        return obj.phone_number

    phone_number.short_description = 'Phone'
