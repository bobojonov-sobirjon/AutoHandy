from django.contrib import admin
# from django.utils.html import format_html
# from django.urls import reverse
# from django.utils.safestring import mark_safe
# from .models import Order, OrderStatus, OrderPriority, OrderType, ScheduledOrder, SOSOrder, OrderService, Review, UserRating

"""
class BaseOrderAdmin(admin.ModelAdmin):
    list_per_page = 25
    list_max_show_all = 100
    readonly_fields = ['id', 'created_at', 'updated_at', 'user_link', 'master_link', 'order_type']
    filter_horizontal = ['masters', 'car', 'category']
    search_fields = [
        'id', 'text', 'location', 'user__first_name', 'user__last_name',
        'user__email', 'master__user__first_name', 'master__user__last_name'
    ]
    def user_link(self, obj):
        if obj.user:
            url = reverse('admin:accounts_customuser_change', args=[obj.user.id])
            return format_html('<a href="{}">{}</a>', url, obj.user.get_full_name() or obj.user.email)
        return '-'
    user_link.short_description = 'User'
    user_link.admin_order_field = 'user__first_name'
    def master_link(self, obj):
        if obj.master:
            url = reverse('admin:master_master_change', args=[obj.master.id])
            return format_html('<a href="{}">{}</a>', url, obj.master.full_name)
        return '-'
    master_link.short_description = 'Master'
    master_link.admin_order_field = 'master__user__first_name'
    def status_badge(self, obj):
        colors = {
            OrderStatus.PENDING: '#ffc107',
            OrderStatus.IN_PROGRESS: '#17a2b8',
            OrderStatus.COMPLETED: '#28a745',
            OrderStatus.CANCELLED: '#6c757d',
            OrderStatus.REJECTED: '#dc3545',
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 11px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    status_badge.admin_order_field = 'status'
    def priority_badge(self, obj):
        colors = {
            OrderPriority.LOW: '#28a745',
            OrderPriority.HIGH: '#dc3545',
        }
        color = colors.get(obj.priority, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 11px;">{}</span>',
            color, obj.get_priority_display()
        )
    priority_badge.short_description = 'Priority'
    priority_badge.admin_order_field = 'priority'
    def location_short(self, obj):
        if obj.location:
            return obj.location[:50] + '...' if len(obj.location) > 50 else obj.location
        return '-'
    location_short.short_description = 'Location'
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'user', 'master', 'master__user'
        )
    def has_add_permission(self, request):
        return request.user.is_superuser
    def has_change_permission(self, request, obj=None):
        return True
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(self.readonly_fields)
        if not request.user.is_superuser:
            readonly_fields.extend(['user', 'master'])
        return readonly_fields

@admin.register(ScheduledOrder)
class ScheduledOrderAdmin(BaseOrderAdmin):
    list_display = [
        'id', 'user_link', 'master_link', 'scheduled_date', 'time_slot',
        'status_badge', 'priority_badge', 'created_at'
    ]
    list_filter = [
        'status', 'priority', 'scheduled_date', 'created_at',
        'master__city', 'master'
    ]
    fieldsets = (
        ('Main information', {
            'fields': ('id', 'order_type', 'user_link', 'text', 'status', 'priority')
        }),
        ('Visit date and time', {
            'fields': ('scheduled_date', 'scheduled_time_start', 'scheduled_time_end'),
            'classes': ('wide',)
        }),
        ('Master and services', {
            'fields': ('master_link', 'category', 'car')
        }),
        ('Master location', {
            'fields': ('location', 'latitude', 'longitude'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    def time_slot(self, obj):
        if obj.scheduled_time_start and obj.scheduled_time_end:
            return f"{obj.scheduled_time_start.strftime('%H:%M')}-{obj.scheduled_time_end.strftime('%H:%M')}"
        return '-'
    time_slot.short_description = 'Visit time'
    time_slot.admin_order_field = 'scheduled_time_start'

@admin.register(SOSOrder)
class SOSOrderAdmin(BaseOrderAdmin):
    list_display = [
        'id', 'user_link', 'master_link', 'location_short',
        'status_badge', 'created_at', 'coordinates'
    ]
    list_filter = [
        'status', 'created_at', 'master__city', 'master'
    ]
    fieldsets = (
        ('Main information', {
            'fields': ('id', 'order_type', 'user_link', 'text', 'status'),
            'classes': ('wide',)
        }),
        ('Client location (GPS)', {
            'fields': ('location', 'latitude', 'longitude'),
            'classes': ('wide',)
        }),
        ('Master and services', {
            'fields': ('master_link', 'category', 'car')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    def coordinates(self, obj):
        if obj.latitude and obj.longitude:
            lat_str = f"{obj.latitude:.4f}"
            lon_str = f"{obj.longitude:.4f}"
            return format_html(
                '<a href="https://www.google.com/maps?q={},{}" target="_blank">{}, {}</a>',
                obj.latitude, obj.longitude, lat_str, lon_str
            )
        return '-'
    coordinates.short_description = 'GPS coordinates'
    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        return readonly_fields

class OrderStatusFilter(admin.SimpleListFilter):
    title = 'Order status'
    parameter_name = 'status'
    def lookups(self, request, model_admin):
        return OrderStatus.choices
    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(status=self.value())
        return queryset

class OrderPriorityFilter(admin.SimpleListFilter):
    title = 'Order priority'
    parameter_name = 'priority'
    def lookups(self, request, model_admin):
        return OrderPriority.choices
    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(priority=self.value())
        return queryset

@admin.register(OrderService)
class OrderServiceAdmin(admin.ModelAdmin):
    list_display = ['id', 'order_link', 'service_name', 'service_price', 'created_at']
    list_filter = ['created_at', 'order__status']
    search_fields = [
        'order__id', 'master_service_item__category__name',
        'order__user__first_name', 'order__user__last_name',
    ]
    readonly_fields = ['id', 'created_at']
    list_per_page = 25
    def order_link(self, obj):
        if obj.order:
            url = reverse('admin:order_order_change', args=[obj.order.id])
            return format_html('<a href="{}">Order #{}</a>', url, obj.order.id)
        return '-'
    order_link.short_description = 'Order'
    order_link.admin_order_field = 'order__id'
    def service_name(self, obj):
        if obj.master_service_item and obj.master_service_item.category_id:
            return obj.master_service_item.category.name
        return '-'
    service_name.short_description = 'Service'
    def service_price(self, obj):
        if obj.master_service_item:
            return str(obj.master_service_item.price)
        return '-'
    service_price.short_description = 'Price'
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'order', 'order__user', 'master_service_item',
            'master_service_item__master_service', 'master_service_item__category',
        )

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['id', 'order_link', 'reviewer_link', 'rating_stars', 'tag_badge', 'created_at']
    list_filter = ['rating', 'tag', 'created_at']
    search_fields = ['order__id', 'reviewer__email', 'reviewer__first_name', 'reviewer__last_name', 'comment']
    readonly_fields = ['id', 'created_at', 'updated_at']
    list_per_page = 25
    fieldsets = (
        ('Main information', {
            'fields': ('id', 'order', 'reviewer', 'rating', 'tag')
        }),
        ('Comment', {
            'fields': ('comment',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    def order_link(self, obj):
        if obj.order:
            url = reverse('admin:order_order_change', args=[obj.order.id])
            return format_html('<a href="{}">Order #{}</a>', url, obj.order.id)
        return '-'
    order_link.short_description = 'Order'
    def reviewer_link(self, obj):
        if obj.reviewer:
            url = reverse('admin:accounts_customuser_change', args=[obj.reviewer.id])
            return format_html('<a href="{}">{}</a>', url, obj.reviewer.get_full_name() or obj.reviewer.email)
        return '-'
    reviewer_link.short_description = 'Review author'
    def rating_stars(self, obj):
        stars = '⭐' * obj.rating
        return format_html('<span style="font-size: 16px;">{}</span>', stars)
    rating_stars.short_description = 'Rating'
    def tag_badge(self, obj):
        colors = {
            'fast_work': '#17a2b8',
            'no_overpay': '#28a745',
            'deadline': '#ffc107',
            'always_available': '#007bff',
            'individual_approach': '#6f42c1',
            'polite': '#fd7e14',
        }
        color = colors.get(obj.tag, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 11px;">{}</span>',
            color, obj.get_tag_display()
        )
    tag_badge.short_description = 'Tag'
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('order', 'reviewer')

@admin.register(UserRating)
class UserRatingAdmin(admin.ModelAdmin):
    list_display = ['id', 'user_link', 'rating_stars', 'average_rating', 'updated_at']
    list_filter = ['updated_at']
    search_fields = ['user__email', 'user__first_name', 'user__last_name']
    readonly_fields = ['id', 'user', 'average_rating', 'updated_at']
    list_per_page = 25
    ordering = ['-average_rating']
    def user_link(self, obj):
        if obj.user:
            url = reverse('admin:accounts_customuser_change', args=[obj.user.id])
            return format_html('<a href="{}">{}</a>', url, obj.user.get_full_name() or obj.user.email)
        return '-'
    user_link.short_description = 'User'
    def rating_stars(self, obj):
        full_stars = int(obj.average_rating)
        stars = '⭐' * full_stars
        return format_html('<span style="font-size: 16px;">{} ({})</span>', stars, obj.average_rating)
    rating_stars.short_description = 'Rating'
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')

admin.site.site_header = "AutoHandy - Administration"
admin.site.site_title = "AutoHandy Admin"
admin.site.index_title = "Order management"
"""
