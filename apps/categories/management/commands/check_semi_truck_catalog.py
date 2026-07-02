"""
Production/local diagnostic: semi-truck categories, API visibility, masters, migrations.

Usage (on server, project root):
    python manage.py check_semi_truck_catalog
    python manage.py check_semi_truck_catalog --base-url https://api.autohandy.app
    python manage.py check_semi_truck_catalog --phone 15555550100
"""
from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Q

from apps.categories.models import Category
from apps.master.models import Master, MasterTowingPricing
from apps.master.towing_types import TowingServiceType


class Command(BaseCommand):
    help = 'Diagnose semi-truck catalog visibility (DB + optional live API + user context).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--base-url',
            default='',
            help='If set, also GET public category APIs (e.g. https://api.autohandy.app).',
        )
        parser.add_argument(
            '--phone',
            default='',
            help='Optional user phone (E.164 digits) to show role/groups (Driver vs Master).',
        )
        parser.add_argument(
            '--timeout',
            type=int,
            default=15,
            help='HTTP timeout seconds for API checks.',
        )

    def handle(self, *args, **options):
        base_url = (options['base_url'] or '').rstrip('/')
        phone = (options['phone'] or '').strip()
        timeout = options['timeout']

        self.stdout.write(self.style.MIGRATE_HEADING('=== Semi-truck catalog diagnostic ===\n'))

        self._check_migrations()
        self._check_database()
        if base_url:
            self._check_api(base_url, timeout)
        else:
            self.stdout.write(
                self.style.WARNING(
                    'Skip live API (pass --base-url https://api.autohandy.app to compare HTTP vs DB).\n'
                )
            )
        if phone:
            self._check_user(phone)
        self._print_why_hidden()

    def _check_migrations(self):
        self.stdout.write(self.style.MIGRATE_HEADING('1. Migrations'))
        required = [
            ('categories', '0017_category_is_truck'),
            ('categories', '0018_seed_truck_roadside_categories'),
            ('order', '0058_order_truck_fields'),
            ('master', '0039_semi_truck_towing_service_type'),
        ]
        with connection.cursor() as cur:
            for app, name in required:
                cur.execute(
                    'SELECT 1 FROM django_migrations WHERE app = %s AND name = %s',
                    [app, name],
                )
                ok = cur.fetchone() is not None
                line = f'  {"OK" if ok else "MISSING"}  {app}.{name}'
                self.stdout.write(self.style.SUCCESS(line) if ok else self.style.ERROR(line))
        self.stdout.write('')

    def _check_database(self):
        self.stdout.write(self.style.MIGRATE_HEADING('2. Database (Category rows)'))

        truck_mains = Category.objects.filter(
            parent__isnull=True,
            type_category=Category.TypeCategory.BY_ORDER,
            is_truck=True,
        ).order_by('id')
        regular_mains = Category.objects.filter(
            parent__isnull=True,
            type_category=Category.TypeCategory.BY_ORDER,
            is_truck=False,
        ).count()

        self.stdout.write(f'  Main by_order (regular, is_truck=false): {regular_mains}')
        self.stdout.write(f'  Main by_order (truck,    is_truck=true):  {truck_mains.count()}')

        if not truck_mains.exists():
            self.stdout.write(self.style.ERROR('  >>> No truck main category in DB — run migrations / admin seed.'))
        else:
            for main in truck_mains:
                subs = Category.objects.filter(parent=main).order_by('id')
                truck_subs = subs.filter(is_truck=True)
                self.stdout.write(
                    f'\n  Truck main: id={main.id} name="{main.name}" sort_order={main.sort_order}'
                )
                self.stdout.write(f'    Subcategories total: {subs.count()} (is_truck=true: {truck_subs.count()})')
                for sub in subs:
                    flag = 'truck' if sub.is_truck else 'NOT_TRUCK'
                    self.stdout.write(f'      - id={sub.id} [{flag}] {sub.name}')

        semi_masters = MasterTowingPricing.objects.filter(
            service_type=TowingServiceType.SEMI_TRUCK,
            is_active=True,
        ).filter(Q(base_fee__gt=0) | Q(price_per_mile__gt=0))
        master_ids = list(semi_masters.values_list('master_id', flat=True).distinct())
        self.stdout.write(
            f'\n  Masters with semi_truck towing rates (active): {len(master_ids)}'
        )
        if master_ids:
            self.stdout.write(f'    master_ids: {master_ids[:20]}')
        else:
            self.stdout.write(
                self.style.WARNING('    >>> Towing estimate will return master_count=0 until masters set semi_truck pricing.')
            )
        self.stdout.write('')

    def _check_api(self, base_url: str, timeout: int):
        self.stdout.write(self.style.MIGRATE_HEADING(f'3. Live API ({base_url})'))

        paths = [
            ('Default home (truck HIDDEN)', '/api/categories/categories/?type=by_order'),
            ('Truck catalog', '/api/categories/categories/?type=by_order&is_truck=true'),
        ]
        truck_main_id = None
        for label, path in paths:
            data = self._http_get(f'{base_url}{path}', timeout)
            if data is None:
                continue
            names = [row.get('name') for row in data]
            truck_rows = [row for row in data if row.get('is_truck')]
            self.stdout.write(f'\n  {label}')
            self.stdout.write(f'    URL: {path}')
            self.stdout.write(f'    count={len(data)} truck_rows={len(truck_rows)}')
            self.stdout.write(f'    names: {names}')
            if 'is_truck=true' in path and data:
                truck_main_id = data[0].get('id')

        if truck_main_id:
            sub_path = f'/api/categories/subcategories/?parent_id={truck_main_id}'
            subs = self._http_get(f'{base_url}{sub_path}', timeout)
            if subs is not None:
                self.stdout.write(f'\n  Truck subcategories (parent_id={truck_main_id})')
                self.stdout.write(f'    URL: {sub_path}')
                for row in subs:
                    self.stdout.write(f'      - id={row.get("id")} {row.get("name")}')
        self.stdout.write('')

    def _check_user(self, phone: str):
        self.stdout.write(self.style.MIGRATE_HEADING(f'4. User context (phone={phone})'))
        User = get_user_model()
        from apps.accounts.services import SMSService

        e164 = SMSService.format_phone_to_e164(phone)
        try:
            user = User.objects.prefetch_related('groups').get(phone_number=e164)
        except User.DoesNotExist:
            self.stdout.write(self.style.WARNING(f'  User not found for {e164}'))
            self.stdout.write('')
            return

        groups = list(user.groups.values_list('name', flat=True))
        self.stdout.write(f'  user_id={user.id} groups={groups}')
        if 'Master' in groups:
            master = Master.objects.filter(user=user).first()
            self.stdout.write(
                f'  Master profile: {"yes id=" + str(master.id) if master else "NO master row"}'
            )
            if master:
                st = MasterTowingPricing.objects.filter(master=master, service_type=TowingServiceType.SEMI_TRUCK)
                self.stdout.write(f'  semi_truck towing pricing rows: {st.count()}')
        self.stdout.write('')

    def _print_why_hidden(self):
        self.stdout.write(self.style.MIGRATE_HEADING('5. Why app may show NO semi-truck'))
        self.stdout.write(
            '  • Default GET /categories/?type=by_order filters is_truck=FALSE (by design).\n'
            '  • Frontend must call ?is_truck=true OR show a Semi Truck entry that does.\n'
            '  • Truck orders do NOT use car_list — use truck_make_model + truck_year.\n'
            '  • Truck towing: POST /api/order/truck/towing/ (not /api/order/towing/).\n'
        )

    def _http_get(self, url: str, timeout: int):
        try:
            req = Request(url, headers={'Accept': 'application/json'})
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except HTTPError as e:
            self.stdout.write(self.style.ERROR(f'    HTTP {e.code} {url}'))
        except URLError as e:
            self.stdout.write(self.style.ERROR(f'    URL error {url}: {e}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'    Error {url}: {e}'))
        return None
