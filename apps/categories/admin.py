from django.contrib import admin
# from apps.categories.models import Category
# from django.utils.html import mark_safe

"""
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    def get_icon(self, obj):
        if obj.icon:
            return mark_safe(f'<img src="{obj.icon.url}" width="50" height="50" />')
        return '-'
    get_icon.short_description = 'Icon'
    list_display = ['get_icon', 'name', 'type_category', 'service_type', 'created_at']
    list_filter = ['type_category', 'service_type', 'created_at']
    search_fields = ['name', 'service_type']
    ordering = ['-created_at']
    fieldsets = (
        ('Main information', {
            'fields': ('name', 'type_category', 'icon')
        }),
        ('Category linking', {
            'fields': ('service_type',),
            'description': 'Use service_type to link by_order and by_master categories. E.g.: "remont", "diagnostika", "zamena"'
        }),
    )
"""
