from django.core.management.base import BaseCommand

from apps.categories.services.home_screen_order import apply_home_screen_category_order


class Command(BaseCommand):
    help = 'Assign home-screen sort_order values to main by_order categories.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report matches without saving changes.',
        )

    def handle(self, *args, **options):
        result = apply_home_screen_category_order(dry_run=options['dry_run'])
        self.stdout.write(
            self.style.SUCCESS(
                f"matched={result['matched']} updated={result['updated']} renamed={result['renamed']}"
            )
        )
