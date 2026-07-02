"""
Why POST /api/order/truck/ returns "No semi-truck service providers..."?

Checks each gate: service-items skill, GPS, distance, emergency rate floors.

Usage:
    python manage.py check_semi_truck_providers --master-phone 12797580037
    python manage.py check_semi_truck_providers --master-phone 12797580037 --category-id 110 --lat 38.5 --lon -121.4
    python manage.py check_semi_truck_providers --list-truck-masters
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.accounts.services import SMSService
from apps.categories.models import Category
from apps.master.models import Master, MasterServiceItems, MasterTowingPricing
from apps.master.services.geo import haversine_distance_km, km_to_miles
from apps.master.services.rates import master_acceptance_rate_percent, master_completion_rate_percent
from apps.master.towing_types import TowingServiceType
from apps.order.services.sos_master_queue import build_sos_master_id_queue
from apps.order.services.sos_rotation import filter_master_ids_meeting_emergency_thresholds


class Command(BaseCommand):
    help = 'Diagnose why semi-truck roadside/towing has no nearby providers for a master.'

    def add_arguments(self, parser):
        parser.add_argument('--master-phone', default='', help='Master user phone (digits).')
        parser.add_argument('--driver-phone', default='', help='Optional driver phone for context.')
        parser.add_argument(
            '--category-id',
            type=int,
            default=0,
            help='Truck subcategory id (e.g. 110=tire, 109=towing). Default: first non-towing truck sub.',
        )
        parser.add_argument('--lat', type=float, default=None, help='Order latitude (driver GPS).')
        parser.add_argument('--lon', type=float, default=None, help='Order longitude (driver GPS).')
        parser.add_argument(
            '--list-truck-masters',
            action='store_true',
            help='List all masters with any truck category in service-items.',
        )

    def handle(self, *args, **options):
        if options['list_truck_masters']:
            self._list_truck_masters()
            return

        phone = (options['master_phone'] or '').strip()
        if not phone:
            self.stdout.write(self.style.ERROR('Pass --master-phone 12797580037 (or --list-truck-masters)'))
            return

        category_id = int(options['category_id'] or 0)
        if not category_id:
            cat = (
                Category.objects.filter(is_truck=True, parent__isnull=False)
                .exclude(name__icontains='towing')
                .order_by('id')
                .first()
            )
            if not cat:
                cat = Category.objects.filter(is_truck=True, parent__isnull=False).order_by('id').first()
            category_id = cat.id if cat else 0

        if not category_id:
            self.stdout.write(self.style.ERROR('No truck subcategory in DB.'))
            return

        lat = options['lat']
        lon = options['lon']

        self.stdout.write(self.style.MIGRATE_HEADING('=== Semi-truck provider diagnostic ===\n'))
        self._print_thresholds()
        self._print_category(category_id)

        driver_phone = (options['driver_phone'] or '').strip()
        if driver_phone:
            self._print_user('Driver', driver_phone)

        master = self._resolve_master(phone)
        if not master:
            return

        self._check_master_profile(master, category_id, lat, lon)
        self._check_queue(category_id, lat, lon, master.id)

    def _print_thresholds(self):
        min_acc = int(getattr(settings, 'EMERGENCY_ACCEPTANCE_RATE_MIN', 90))
        min_comp = int(getattr(settings, 'EMERGENCY_COMPLETION_RATE_MIN', 90))
        self.stdout.write(
            f'Emergency floors: acceptance>={min_acc}%  completion>={min_comp}%  '
            f'(new masters with 0 offers => acceptance 0% => BLOCKED)\n'
        )

    def _print_category(self, category_id: int):
        cat = Category.objects.filter(pk=category_id).first()
        if not cat:
            self.stdout.write(self.style.ERROR(f'category_id={category_id} NOT FOUND'))
            return
        is_towing = 'towing' in (cat.name or '').lower()
        self.stdout.write(
            f'Category: id={cat.id} name="{cat.name}" is_truck={cat.is_truck} parent={cat.parent_id}'
        )
        if is_towing:
            self.stdout.write(
                self.style.WARNING(
                    '  >>> Towing subcategory uses POST /api/order/truck/towing/ + semi_truck pricing, '
                    'NOT service-items roadside queue.\n'
                )
            )
        else:
            self.stdout.write(
                '  Roadside needs MasterServiceItems (service-items API) for this category_id.\n'
            )

    def _resolve_master(self, phone: str) -> Master | None:
        User = get_user_model()
        e164 = SMSService.format_phone_to_e164(phone)
        self.stdout.write(f'\nMaster phone normalized: {e164}')
        try:
            user = User.objects.prefetch_related('groups').get(phone_number=e164)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'  User NOT FOUND for phone {e164}'))
            return None

        groups = list(user.groups.values_list('name', flat=True))
        self.stdout.write(f'  user_id={user.id} groups={groups}')
        master = Master.objects.filter(user=user).first()
        if not master:
            self.stdout.write(self.style.ERROR('  Master profile row NOT FOUND (user has no Master record)'))
            return None
        self.stdout.write(f'  master_id={master.id}')
        return master

    def _print_user(self, label: str, phone: str):
        User = get_user_model()
        e164 = SMSService.format_phone_to_e164(phone)
        u = User.objects.filter(phone_number=e164).first()
        self.stdout.write(f'{label}: {e164} -> {"user_id=" + str(u.id) if u else "NOT FOUND"}')

    def _check_master_profile(self, master: Master, category_id: int, lat: float | None, lon: float | None):
        self.stdout.write(self.style.MIGRATE_HEADING('\n--- Master checks ---'))

        items = MasterServiceItems.objects.filter(
            master_service__master=master,
            category_id=category_id,
        ).select_related('category')
        self.stdout.write(f'1. Service-items for category {category_id}: {items.count()}')
        for it in items:
            self.stdout.write(f'     - price={it.price} category="{it.category.name}"')

        towing = MasterTowingPricing.objects.filter(
            master=master,
            service_type=TowingServiceType.SEMI_TRUCK,
            is_active=True,
        )
        self.stdout.write(f'2. semi_truck towing pricing rows: {towing.count()}')
        for p in towing:
            self.stdout.write(f'     - base_fee={p.base_fee} price_per_mile={p.price_per_mile}')

        if not items.exists():
            self.stdout.write(
                self.style.ERROR(
                    '   FAIL: No MasterServiceItems for this category. '
                    'Master app -> service-items -> add Semi-Truck Tire (or matching subcategory).'
                )
            )
            truck_cats = MasterServiceItems.objects.filter(
                master_service__master=master,
                category__is_truck=True,
            ).values_list('category_id', 'category__name')
            if truck_cats:
                self.stdout.write(f'   (Master HAS other truck skills: {list(truck_cats)})')

        mlat, mlon = master.get_work_location_for_distance()
        self.stdout.write(f'3. GPS: lat={mlat} lon={mlon} radius_miles={master.service_area_radius_miles}')
        if mlat is None or mlon is None:
            self.stdout.write(self.style.ERROR('   FAIL: Master has no work location coordinates.'))

        if lat is not None and lon is not None and mlat is not None:
            dist_km = haversine_distance_km(lat, lon, mlat, mlon)
            max_km = float(master.max_order_distance_km())
            dist_mi = km_to_miles(dist_km)
            ok = dist_km <= max_km
            self.stdout.write(
                f'4. Distance order({lat},{lon}) -> master: {dist_mi:.2f} mi ({dist_km:.2f} km) '
                f'max={max_km:.2f} km -> {"OK" if ok else "FAIL (too far)"}'
            )
        else:
            self.stdout.write(
                '4. Distance: skip (pass --lat --lon from driver app request to test proximity)'
            )

        acc = master_acceptance_rate_percent(master)
        comp = master_completion_rate_percent(master)
        min_acc = int(getattr(settings, 'EMERGENCY_ACCEPTANCE_RATE_MIN', 90))
        min_comp = int(getattr(settings, 'EMERGENCY_COMPLETION_RATE_MIN', 90))
        rates_ok = acc >= min_acc and comp >= min_comp
        self.stdout.write(f'5. Rates: acceptance={acc}% completion={comp}% -> {"OK" if rates_ok else "FAIL"}')
        if not rates_ok:
            self.stdout.write(
                self.style.ERROR(
                    f'   FAIL: Emergency SOS requires >={min_acc}% acceptance AND >={min_comp}% completion. '
                    'Brand-new masters start at 0% acceptance until they accept/decline offers.'
                )
            )

    def _check_queue(self, category_id: int, lat: float | None, lon: float | None, master_id: int):
        self.stdout.write(self.style.MIGRATE_HEADING('\n--- API queue simulation (POST /api/order/truck/) ---'))
        if lat is None or lon is None:
            m = Master.objects.get(pk=master_id)
            wlat, wlon = m.get_work_location_for_distance()
            if wlat is not None:
                lat, lon = float(wlat), float(wlon)
                self.stdout.write(f'Using master location as order GPS: {lat}, {lon}')
            else:
                self.stdout.write(self.style.WARNING('Pass --lat and --lon to simulate driver location.'))
                return

        raw = build_sos_master_id_queue(lat, lon, [category_id])
        filtered = filter_master_ids_meeting_emergency_thresholds(raw)
        self.stdout.write(f'build_sos_master_id_queue: {raw[:20]} (total={len(raw)})')
        self.stdout.write(f'after emergency rate filter: {filtered[:20]} (total={len(filtered)})')
        if master_id in raw:
            self.stdout.write(self.style.SUCCESS(f'master_id={master_id} IN geographic/skill queue'))
        else:
            self.stdout.write(self.style.ERROR(f'master_id={master_id} NOT in geographic/skill queue'))
        if master_id in filtered:
            self.stdout.write(self.style.SUCCESS(f'master_id={master_id} WOULD receive roadside SOS'))
        else:
            self.stdout.write(self.style.ERROR(f'master_id={master_id} BLOCKED after rate filter'))

        if not filtered:
            self.stdout.write(
                self.style.ERROR(
                    '\n>>> API returns 400: "No semi-truck service providers are available..."'
                )
            )

    def _list_truck_masters(self):
        self.stdout.write(self.style.MIGRATE_HEADING('Masters with truck service-items:'))
        rows = (
            MasterServiceItems.objects.filter(category__is_truck=True)
            .select_related('master_service__master__user', 'category')
            .order_by('master_service__master_id', 'category_id')
        )
        if not rows.exists():
            self.stdout.write('  (none)')
        current_mid = None
        for row in rows:
            m = row.master_service.master
            if m.id != current_mid:
                current_mid = m.id
                phone = getattr(m.user, 'phone_number', None)
                self.stdout.write(f'\n  master_id={m.id} phone={phone} lat={m.latitude} lon={m.longitude}')
            self.stdout.write(f'    - cat {row.category_id}: {row.category.name}')
