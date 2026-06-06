"""Enable django-import-export on every Django admin ModelAdmin."""
from __future__ import annotations

from django.apps import apps
from django.contrib import admin
from import_export.admin import ImportExportMixin, ImportExportModelAdmin


def _already_has_import_export(admin_class: type) -> bool:
    return issubclass(admin_class, ImportExportMixin)


def _patch_registered_admins() -> int:
    """Wrap existing ModelAdmin classes with ImportExportMixin."""
    patched = 0
    for model, admin_instance in list(admin.site._registry.items()):
        admin_class = type(admin_instance)
        if _already_has_import_export(admin_class):
            continue

        new_admin_class = type(
            admin_class.__name__,
            (ImportExportMixin, admin_class),
            {},
        )
        admin.site.unregister(model)
        admin.site.register(model, new_admin_class)
        patched += 1
    return patched


def _build_default_admin(model):
    """Minimal ImportExportModelAdmin for models not yet in admin."""
    meta = model._meta
    list_display = ['id', '_object_repr']
    for name in ('name', 'title', 'order_number', 'email', 'status', 'created_at'):
        if name in [f.name for f in meta.fields]:
            list_display.append(name)
    list_display = list(dict.fromkeys(list_display))[:10]

    search_fields = [
        f.name
        for f in meta.fields
        if f.name in {'id', 'name', 'email', 'phone_number', 'order_number', 'text', 'code', 'token'}
        or getattr(f, 'get_internal_type', lambda: '')() in {'CharField', 'TextField', 'EmailField'}
    ][:6]

    ordering = ['-created_at'] if 'created_at' in [f.name for f in meta.fields] else ['-id']

    def _object_repr(self, obj):
        return str(obj)

    _object_repr.short_description = str(meta.verbose_name)

    attrs = {
        'list_display': tuple(list_display),
        'search_fields': tuple(search_fields),
        'ordering': ordering,
        'list_per_page': 50,
        '_object_repr': _object_repr,
    }
    class_name = f'{model.__name__}ImportExportAdmin'
    return type(class_name, (ImportExportModelAdmin,), attrs)


def _register_missing_models() -> int:
    """Register concrete models that have no admin yet."""
    registered = 0
    skip_labels = {
        'auth.group',
        'auth.permission',
        'contenttypes.contenttype',
        'sessions.session',
        'sites.site',
        'admin.logentry',
    }
    for model in apps.get_models():
        if model._meta.abstract or model._meta.auto_created:
            continue
        if model._meta.label_lower in skip_labels:
            continue
        if model in admin.site._registry:
            continue
        admin_class = _build_default_admin(model)
        admin.site.register(model, admin_class)
        registered += 1
    return registered


def setup_import_export_admin() -> None:
    """Apply import/export to all admin entries (idempotent for mixin check)."""
    _patch_registered_admins()
    _register_missing_models()
