from django import forms
from django.contrib import admin
from django.utils.html import mark_safe

from apps.categories.models import Category, MainCategory, SubCategory


class MainCategoryParentChoiceField(forms.ModelChoiceField):
    """Parent select: show name and type in parentheses."""

    def label_from_instance(self, obj):
        return f'{obj.name} ({obj.get_type_category_display()})'


class SubCategoryAdminForm(forms.ModelForm):
    class Meta:
        model = SubCategory
        fields = ('parent', 'name', 'icon')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        prev = self.fields['parent']
        qs = Category.objects.filter(parent__isnull=True).order_by('type_category', 'name')
        self.fields['parent'] = MainCategoryParentChoiceField(
            queryset=qs,
            required=True,
            label=prev.label,
            help_text=prev.help_text,
            widget=prev.widget,
        )


@admin.register(MainCategory)
class MainCategoryAdmin(admin.ModelAdmin):
    def get_icon(self, obj):
        if obj.icon:
            return mark_safe(f'<img src="{obj.icon.url}" width="50" height="50" />')
        return '-'

    get_icon.short_description = 'Icon'

    list_display = ['get_icon', 'name', 'type_category', 'created_at']
    list_filter = ['type_category', 'created_at']
    search_fields = ['name']
    ordering = ['-created_at']

    fieldsets = (
        (
            'Main information',
            {
                'fields': ('name', 'type_category', 'icon'),
                'description': 'Main categories have no parent. Create subcategories under Sub categories.',
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).filter(parent__isnull=True)

    def save_model(self, request, obj, form, change):
        obj.parent_id = None
        super().save_model(request, obj, form, change)


class SubCategoryParentMainOnlyFilter(admin.SimpleListFilter):
    """List filter: only main categories as parent options (not other subs)."""

    title = 'Parent category'
    parameter_name = 'parent__id__exact'

    def lookups(self, request, model_admin):
        mains = Category.objects.filter(parent__isnull=True).order_by('type_category', 'name')
        return [
            (str(c.pk), f'{c.name} ({c.get_type_category_display()})')
            for c in mains
        ]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(parent_id=self.value())
        return queryset


@admin.register(SubCategory)
class SubCategoryAdmin(admin.ModelAdmin):
    form = SubCategoryAdminForm

    def get_icon(self, obj):
        if obj.icon:
            return mark_safe(f'<img src="{obj.icon.url}" width="50" height="50" />')
        return '-'

    get_icon.short_description = 'Icon'

    list_display = ['get_icon', 'name', 'parent', 'type_category', 'created_at']
    list_filter = ['type_category', SubCategoryParentMainOnlyFilter, 'created_at']
    search_fields = ['name', 'parent__name']
    ordering = ['-created_at']

    fieldsets = (
        (
            'Main information',
            {
                'fields': ('parent', 'name', 'icon'),
                'description': 'Category type is taken from the selected main category automatically.',
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).filter(parent__isnull=False).select_related('parent')

    def save_model(self, request, obj, form, change):
        if obj.parent_id:
            obj.type_category = Category.objects.only('type_category').get(pk=obj.parent_id).type_category
        super().save_model(request, obj, form, change)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'parent':
            kwargs['queryset'] = Category.objects.filter(parent__isnull=True).order_by('type_category', 'name')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Category)
class CategoryAutocompleteAdmin(admin.ModelAdmin):
    """
    Base Category model admin (autocomplete helper for FKs to Category).
    Scoped to by_order categories; hidden from the admin index (Main/Sub category admins stay primary).
    """

    search_fields = ('name', 'parent__name')
    list_display = ('name', 'type_category', 'parent')
    ordering = ('type_category', 'name')

    def has_module_permission(self, request):
        return False

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(type_category=Category.TypeCategory.BY_ORDER).select_related('parent')
