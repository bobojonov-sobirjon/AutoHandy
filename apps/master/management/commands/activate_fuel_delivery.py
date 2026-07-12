"""Activate Fuel Delivery skill for a master (prod/support test helper)."""
from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from apps.categories.services.fuel_delivery_catalog import fuel_delivery_category_ids
from apps.master.models import Master, MasterService, MasterServiceItems
from apps.order.services.sos_master_queue import build_sos_master_id_queue


class Command(BaseCommand):
    help = (
        'Create/update Fuel Delivery MasterServiceItems for a master with both 2-gal containers. '
        'Use to verify Fuel Delivery flow when no masters have activated the skill yet.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--master-id',
            type=int,
            default=5,
            help='Master primary key (default: 5)',
        )
        parser.add_argument(
            '--price',
            type=str,
            default='25.00',
            help='Fuel Delivery price (default: 25.00)',
        )
        parser.add_argument(
            '--category-id',
            type=int,
            default=0,
            help='Fuel Delivery category id (default: auto-detect)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would change without saving',
        )

    def handle(self, *args, **options):
        master_id = int(options['master_id'])
        price = Decimal(str(options['price']))
        dry = bool(options['dry_run'])
        category_id = int(options.get('category_id') or 0)

        try:
            master = Master.objects.select_related('user').get(pk=master_id)
        except Master.DoesNotExist as exc:
            raise CommandError(f'Master {master_id} not found') from exc

        fuel_ids = fuel_delivery_category_ids()
        if not fuel_ids:
            raise CommandError('No Fuel Delivery category in catalog (name must be "Fuel Delivery").')

        if category_id:
            if category_id not in fuel_ids:
                raise CommandError(f'category_id={category_id} is not a Fuel Delivery category. Valid: {fuel_ids}')
            target_cat_id = category_id
        else:
            # Prefer non-truck car Fuel Delivery if multiple exist
            target_cat_id = fuel_ids[0]

        self.stdout.write(f'master_id={master.id} user_id={master.user_id}')
        self.stdout.write(f'category_id={target_cat_id} price={price}')
        self.stdout.write('containers: gas=True diesel=True')

        if dry:
            self.stdout.write(self.style.WARNING('DRY RUN — nothing saved'))
            return

        ms, created_ms = MasterService.objects.get_or_create(master=master)
        item, created = MasterServiceItems.objects.update_or_create(
            master_service=ms,
            category_id=target_cat_id,
            defaults={
                'price': price,
                'has_gas_container_2gal': True,
                'has_diesel_container_2gal': True,
            },
        )

        self.stdout.write(
            self.style.SUCCESS(
                f'{"Created" if created else "Updated"} MasterServiceItems id={item.id} '
                f'(MasterService {"created" if created_ms else "existing"} id={ms.id})'
            )
        )
        self.stdout.write(
            f'active={item.fuel_delivery_is_active()} '
            f'gas={item.has_gas_container_2gal} diesel={item.has_diesel_container_2gal}'
        )

        mlat, mlon = master.get_work_location_for_distance()
        if mlat is not None and mlon is not None:
            queue = build_sos_master_id_queue(float(mlat), float(mlon), [target_cat_id])
            self.stdout.write(f'SOS queue at master location: {queue}')
            if master.id in queue:
                self.stdout.write(self.style.SUCCESS('OK — master is in Fuel Delivery SOS queue.'))
            else:
                self.stdout.write(self.style.WARNING(
                    'Master skill is active but not in queue at own pin '
                    '(check radius / location). Try client coords near the master.'
                ))
        else:
            self.stdout.write(self.style.WARNING('Master has no work location — SOS queue will stay empty.'))

        self.stdout.write('')
        self.stdout.write('Verify:')
        self.stdout.write('  python manage.py check_fuel_delivery --list-masters')
        if mlat is not None:
            self.stdout.write(
                f'  python manage.py check_fuel_delivery --lat {mlat} --lon {mlon}'
            )
