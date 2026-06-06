from django.apps import AppConfig


class ProjectConfig(AppConfig):
    """Project-level hooks (must be last in INSTALLED_APPS)."""

    name = 'config'
    label = 'project_config'
    verbose_name = 'Project configuration'

    def ready(self):
        from config.import_export_admin import setup_import_export_admin

        setup_import_export_admin()
