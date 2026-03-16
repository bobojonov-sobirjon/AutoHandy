from django.contrib import admin
# from .models import Car
# from apps.categories.models import Category

"""
@admin.register(Car)
class CarAdmin(admin.ModelAdmin):
    list_display = [
        'brand', 'model', 'category', 'year', 'user', 'created_at'
    ]
    list_filter = [
        'category', 'brand', 'year', 'created_at'
    ]
    search_fields = [
        'brand', 'model', 'user__phone_number', 'user__first_name', 'user__last_name'
    ]
    ordering = ['-created_at']
    fieldsets = (
        ('Main information', {
            'fields': ('brand', 'model', 'category', 'year')
        }),
        ('User', {
            'fields': ('user',)
        }),
        ('Dates', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ['created_at', 'updated_at']
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'category':
            kwargs['queryset'] = Category.objects.filter(type_category='by_car')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
"""
