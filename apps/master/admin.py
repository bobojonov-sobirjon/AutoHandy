from django.contrib import admin
# from django import forms
# from .models import Master, MasterService, MasterServiceItems, MasterEmployee
# from apps.categories.models import Category

"""
class MasterAdminForm(forms.ModelForm):
    class Meta:
        model = Master
        fields = '__all__'
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'category' in self.fields:
            self.fields['category'].queryset = Category.objects.filter(type_category='by_master')
    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            instance.save()
        return instance

class MasterServiceItemsInline(admin.TabularInline):
    model = MasterServiceItems
    extra = 1
    fields = ['name', 'price_from', 'price_to', 'category']
    ordering = ['-created_at']
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'category':
            kwargs['queryset'] = Category.objects.filter(type_category='by_master')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

@admin.register(Master)
class MasterAdmin(admin.ModelAdmin):
    form = MasterAdminForm
    def get_category(self, obj):
        return ", ".join([category.name for category in obj.category.all()])
    get_category.short_description = 'Category'
    list_display = [
        'full_name', 'name', 'phone_number', 'city', 'get_category', 'latitude', 'longitude', 'created_at'
    ]
    list_filter = [
        'city', 'created_at'
    ]
    search_fields = [
        'user__phone_number', 'user__first_name', 'user__last_name',
        'name', 'city'
    ]
    ordering = ['-created_at']
    fieldsets = (
        ('User', {
            'fields': ('user', 'name', 'category', 'description')
        }),
        ('Location', {
            'fields': ('city', 'address', 'latitude', 'longitude')
        }),
        ('Contact information', {
            'fields': ('phone', 'working_time')
        }),
        ('Bank details', {
            'fields': ('card_number', 'card_expiry_month', 'card_expiry_year', 'card_cvv'),
            'classes': ('collapse',)
        }),
        ('Finance', {
            'fields': ('balance', 'reserved_amount'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'last_activity'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ['created_at', 'updated_at', 'last_activity']
    def full_name(self, obj):
        return obj.full_name
    full_name.short_description = 'Full name'
    def phone_number(self, obj):
        return obj.phone_number
    phone_number.short_description = 'Phone'
    def services_display(self, obj):
        from .models import MasterService
        master_services = MasterService.objects.filter(master=obj)
        return f"{master_services.count()} services"
    services_display.short_description = 'Services'

@admin.register(MasterService)
class MasterServiceAdmin(admin.ModelAdmin):
    list_display = ['master__address', 'master__city', 'master', 'items_count', 'created_at']
    list_filter = ['created_at']
    search_fields = ['master__user__phone_number', 'master__user__first_name']
    ordering = ['-created_at']
    inlines = [MasterServiceItemsInline]
    def items_count(self, obj):
        return obj.master_service_items.count()
    items_count.short_description = 'Item count'

@admin.register(MasterEmployee)
class MasterEmployeeAdmin(admin.ModelAdmin):
    list_display = ('id', 'master', 'employee', 'added_at')
    list_filter = ('added_at',)
    search_fields = ('master__user__email', 'employee__email', 'employee__phone_number')
    readonly_fields = ('added_at',)
    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields + ('master', 'employee')
        return self.readonly_fields
"""
