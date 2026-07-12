"""Diagnose Fuel Delivery catalog, master equipment, and order readiness (prod support)."""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from apps.categories.models import Category
from apps.categories.services.fuel_delivery_catalog import (
    FUEL_DELIVERY_CATEGORY_NAME,
    fuel_delivery_category_ids,
    is_fuel_delivery_category,
)
from apps.master.models import Master, MasterServiceItems
from apps.order.models import Order
from apps.order.services.sos_master_queue import build_sos_master_id_queue


class Command(BaseCommand):
    help = (
        'Inspect Fuel Delivery setup: categories, master containers, SOS queue, and a sample order. '
        'Use when client reports Fuel Delivery does not work while other services do.'
    )

    def add_arguments(self, parser):
        parser.add_argument('order_id', type=int, nargs='?', help='Optional order id to inspect')
        parser.add_argument('--master-id', type=int, default=0, help='Inspect one master profile')
        parser.add_argument(
            '--lat',
            type=float,
            default=None,
            help='Client latitude for SOS queue dry-run',
        )
        parser.add_argument(
            '--lon',
            type=float,
            default=None,
            help='Client longitude for SOS queue dry-run',
        )
        parser.add_argument(
            '--list-masters',
            action='store_true',
            help='List masters with Fuel Delivery skill (+ container status)',
        )

    def handle(self, *args, **options):
        order_id = options.get('order_id')
        master_id = int(options.get('master_id') or 0)
        lat = options.get('lat')
        lon = options.get('lon')
        list_masters = bool(options.get('list_masters'))

        self._print_categories()
        fuel_ids = fuel_delivery_category_ids()
        if not fuel_ids:
            self.stdout.write(self.style.ERROR(
                'BLOCKER: no category named exactly "Fuel Delivery" (by_order). '
                'Create/rename the category in admin.'
            ))
            return

        if list_masters or (not order_id and not master_id and lat is None):
            self._list_masters(fuel_ids)

        if master_id:
            self._print_master(master_id, fuel_ids)

        if order_id:
            self._print_order(order_id, fuel_ids)

        if lat is not None and lon is not None:
            self._print_sos_queue(fuel_ids, lat, lon)
        elif lat is not None or lon is not None:
            raise CommandError('Provide both --lat and --lon')

    def _print_categories(self) -> None:
        self.stdout.write('=== Fuel Delivery categories ===')
        rows = Category.objects.filter(name__iexact=FUEL_DELIVERY_CATEGORY_NAME)
        if not rows.exists():
            self.stdout.write(self.style.ERROR(f'No Category with name="{FUEL_DELIVERY_CATEGORY_NAME}"'))
            # hint: similar names
            similar = Category.objects.filter(
                Q(name__icontains='fuel') | Q(name__icontains='gasoline') | Q(name__icontains='дизел')
            ).values_list('id', 'name', 'type_category')[:20]
            if similar:
                self.stdout.write('Similar categories:')
                for cid, name, tc in similar:
                    self.stdout.write(f'  id={cid} name={name!r} type={tc}')
            return

        for cat in rows:
            ok = is_fuel_delivery_category(cat)
            mark = 'OK' if ok and cat.type_category == Category.TypeCategory.BY_ORDER else 'WARN'
            self.stdout.write(
                f'  [{mark}] id={cat.id} name={cat.name!r} type={cat.type_category} '
                f'parent={cat.parent_id} is_truck={getattr(cat, "is_truck", None)}'
            )
        self.stdout.write(f'fuel_delivery_category_ids: {fuel_delivery_category_ids()}')
        self.stdout.write('')

    def _list_masters(self, fuel_ids: list[int]) -> None:
        self.stdout.write('=== Masters with Fuel Delivery skill ===')
        items = (
            MasterServiceItems.objects.filter(category_id__in=fuel_ids)
            .select_related('master_service__master__user', 'category')
            .order_by('master_service__master_id')
        )
        if not items.exists():
            self.stdout.write(self.style.WARNING(
                'No MasterServiceItems for Fuel Delivery. Masters never activated this skill.'
            ))
            self.stdout.write('')
            return

        active = 0
        inactive = 0
        for item in items:
            master = item.master_service.master
            gas = bool(item.has_gas_container_2gal)
            diesel = bool(item.has_diesel_container_2gal)
            is_active = gas and diesel
            if is_active:
                active += 1
                style = self.style.SUCCESS
                status = 'ACTIVE'
            else:
                inactive += 1
                style = self.style.ERROR
                status = 'INACTIVE (need both containers)'
            phone = getattr(master.user, 'phone', '') or '-'
            self.stdout.write(style(
                f'  master_id={master.id} user={master.user_id} phone={phone} '
                f'cat={item.category_id} price={item.price} '
                f'gas2gal={gas} diesel2gal={diesel} -> {status}'
            ))
        self.stdout.write(f'Total skill lines: {items.count()} | active={active} | inactive={inactive}')
        if active == 0:
            self.stdout.write(self.style.ERROR(
                'BLOCKER: zero masters have BOTH 2-gal gas + diesel containers. '
                'SOS Fuel Delivery orders will find no masters; standard with master_id will 400.'
            ))
        self.stdout.write('')

    def _print_master(self, master_id: int, fuel_ids: list[int]) -> None:
        self.stdout.write(f'=== Master {master_id} ===')
        try:
            master = Master.objects.select_related('user').get(pk=master_id)
        except Master.DoesNotExist as exc:
            raise CommandError(f'Master {master_id} not found') from exc

        self.stdout.write(f'user_id={master.user_id} phone={getattr(master.user, "phone", "") or "-"}')
        mlat, mlon = master.get_work_location_for_distance()
        self.stdout.write(f'work_location={mlat},{mlon} radius_km={master.max_order_distance_km()}')

        items = MasterServiceItems.objects.filter(
            master_service__master_id=master_id,
            category_id__in=fuel_ids,
        ).select_related('category')
        if not items.exists():
            self.stdout.write(self.style.ERROR('No Fuel Delivery skill on this master.'))
            self.stdout.write('')
            return

        for item in items:
            gas = bool(item.has_gas_container_2gal)
            diesel = bool(item.has_diesel_container_2gal)
            self.stdout.write(
                f'  item_id={item.id} cat={item.category_id}({item.category.name}) '
                f'price={item.price} gas={gas} diesel={diesel} '
                f'active={gas and diesel}'
            )
        self.stdout.write('')

    def _print_order(self, order_id: int, fuel_ids: list[int]) -> None:
        self.stdout.write(f'=== Order {order_id} ===')
        try:
            order = Order.objects.select_related('user', 'master', 'master__user').get(pk=order_id)
        except Order.DoesNotExist as exc:
            raise CommandError(f'Order {order_id} not found') from exc

        cat_ids = list(order.category.values_list('id', flat=True))
        has_fuel = bool(set(cat_ids).intersection(fuel_ids))
        self.stdout.write(f'order_number={order.order_number} status={order.status} type={order.order_type}')
        self.stdout.write(f'categories={cat_ids} includes_fuel_delivery={has_fuel}')
        self.stdout.write(f'fuel_delivery_type={order.fuel_delivery_type or "-"}')
        self.stdout.write(f'master_id={order.master_id or "-"}')
        self.stdout.write(f'lat/lon={order.latitude},{order.longitude}')

        issues: list[str] = []
        if has_fuel and not order.fuel_delivery_type:
            issues.append('MISSING_FUEL_TYPE on order (client may not have sent fuel_type)')
        if has_fuel and order.master_id:
            item = MasterServiceItems.objects.filter(
                master_service__master_id=order.master_id,
                category_id__in=fuel_ids,
            ).first()
            if not item:
                issues.append('ASSIGNED_MASTER_HAS_NO_FUEL_SKILL')
            elif not (item.has_gas_container_2gal and item.has_diesel_container_2gal):
                issues.append('ASSIGNED_MASTER_CONTAINERS_INCOMPLETE')

        from apps.order.models import OrderService

        for os_row in OrderService.objects.filter(order=order).select_related(
            'master_service_item__category'
        ):
            cat = os_row.master_service_item.category if os_row.master_service_item_id else None
            self.stdout.write(
                f'  OrderService id={os_row.id} cat={getattr(cat, "name", None)} '
                f'fuel_type={os_row.fuel_type or "-"} unit_price={os_row.unit_price}'
            )
            if cat and is_fuel_delivery_category(cat) and not os_row.fuel_type:
                issues.append(f'ORDER_SERVICE_{os_row.id}_MISSING_FUEL_TYPE')

        if issues:
            self.stdout.write(self.style.ERROR('ISSUES:'))
            for i in issues:
                self.stdout.write(self.style.ERROR(f'  - {i}'))
        else:
            self.stdout.write(self.style.SUCCESS('No fuel-specific issues on this order row.'))
        self.stdout.write('')

    def _print_sos_queue(self, fuel_ids: list[int], lat: float, lon: float) -> None:
        self.stdout.write(f'=== SOS queue dry-run at {lat},{lon} ===')
        queue = build_sos_master_id_queue(lat, lon, fuel_ids)
        self.stdout.write(f'masters in queue for Fuel Delivery only: {queue}')
        if not queue:
            self.stdout.write(self.style.ERROR(
                'BLOCKER: empty SOS queue — no nearby master with BOTH containers + work location + radius.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(f'{len(queue)} master(s) available for Fuel Delivery SOS.'))
        self.stdout.write('')
