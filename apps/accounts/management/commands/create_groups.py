from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group


class Command(BaseCommand):
    help = 'Создание групп пользователей Driver и Master'

    def handle(self, *args, **options):
        # Создание группы Driver
        driver_group, created = Group.objects.get_or_create(name='Driver')
        if created:
            self.stdout.write(
                self.style.SUCCESS('Группа Driver создана')
            )
        else:
            self.stdout.write(
                self.style.WARNING('Группа Driver уже существует')
            )

        # Создание группы Master
        master_group, created = Group.objects.get_or_create(name='Master')
        if created:
            self.stdout.write(
                self.style.SUCCESS('Группа Master создана')
            )
        else:
            self.stdout.write(
                self.style.WARNING('Группа Master уже существует')
            )

        self.stdout.write(
            self.style.SUCCESS('Группы пользователей готовы!')
        )
