"""Fix PostgreSQL id sequences after manual imports / restores."""
from __future__ import annotations

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import connection


def reset_pk_sequence(model) -> tuple[str, int] | None:
    pk = model._meta.pk
    if pk is None or pk.get_internal_type() not in ('AutoField', 'BigAutoField'):
        return None
    table = model._meta.db_table
    column = pk.column
    qn = connection.ops.quote_name
    table_sql = qn(table)
    column_sql = qn(column)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT setval(
                pg_get_serial_sequence(%s, %s),
                COALESCE((SELECT MAX({column_sql}) FROM {table_sql}), 1),
                true
            )
            """,
            [table, column],
        )
        cursor.execute(
            "SELECT currval(pg_get_serial_sequence(%s, %s))",
            [table, column],
        )
        current = cursor.fetchone()[0]
    return table, int(current)


def fix_truck_subcategory_flags() -> int:
    from apps.categories.models import Category

    return Category.objects.filter(parent__is_truck=True, is_truck=False).update(is_truck=True)


class Command(BaseCommand):
    help = (
        'Reset PostgreSQL PK sequences to MAX(id). '
        'Fixes IntegrityError: duplicate key ... categories_category_pkey after DB restore.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--app',
            default='categories',
            help='Only reset models for this app label (default: categories).',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Reset sequences for all managed models.',
        )

        parser.add_argument(
            '--fix-truck-subs',
            action='store_true',
            help='Set is_truck=true on subcategories whose parent is a truck main category.',
        )

    def handle(self, *args, **options):
        if options['all']:
            models = [m for m in apps.get_models() if m._meta.managed]
        else:
            app_label = options['app']
            models = apps.get_app_config(app_label).get_models()

        seen_tables: set[str] = set()
        for model in models:
            table = model._meta.db_table
            if table in seen_tables:
                continue
            seen_tables.add(table)
            result = reset_pk_sequence(model)
            if result is None:
                continue
            table, current = result
            self.stdout.write(self.style.SUCCESS(f'{table}: sequence -> {current}'))

        if options['fix_truck_subs']:
            n = fix_truck_subcategory_flags()
            self.stdout.write(self.style.SUCCESS(f'Updated is_truck on {n} subcategory row(s).'))
