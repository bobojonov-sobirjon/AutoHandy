from django.core.management.base import BaseCommand
from apps.master.models import Service, ServiceType


class Command(BaseCommand):
    help = 'Populate database with sample services'

    def handle(self, *args, **options):
        """Create sample services based on the images provided"""
        
        services_data = [
            # Сезонная смена шин
            {
                'name': 'Сезонная смена шин',
                'description': 'Смена шин с летних на зимние или наоборот',
                'base_price': 2100.00,
                'price_from': True,
                'currency': 'RUB',
                'category': ServiceType.TIRE_REPAIR,
                'is_active': True
            },
            # Сезонная смена шин для микроавтобусов
            {
                'name': 'Сезонная смена шин для микроавтобусов',
                'description': 'Смена шин для микроавтобусов и коммерческого транспорта',
                'base_price': 4000.00,
                'price_from': True,
                'currency': 'RUB',
                'category': ServiceType.TIRE_REPAIR,
                'is_active': True
            },
            # Сезонное хранение 4-х шин
            {
                'name': 'Сезонное хранение 4-х шин',
                'description': 'Хранение снятых шин в течение сезона',
                'base_price': 3500.00,
                'price_from': False,
                'currency': 'RUB',
                'category': ServiceType.TIRE_REPAIR,
                'is_active': True
            },
            # Балансировка
            {
                'name': 'Балансировка (цена за 1 колесо)',
                'description': 'Балансировка колес для обеспечения равномерного износа',
                'base_price': 200.00,
                'price_from': True,
                'currency': 'RUB',
                'category': ServiceType.TIRE_REPAIR,
                'is_active': True
            },
            # Поставить кордовую латку
            {
                'name': 'Поставить кордовую латку',
                'description': 'Ремонт прокола шины с помощью кордовой латки',
                'base_price': 700.00,
                'price_from': True,
                'currency': 'RUB',
                'category': ServiceType.TIRE_REPAIR,
                'is_active': True
            },
            # Замена 4-х вентилей
            {
                'name': 'Замена 4-х вентилей',
                'description': 'Замена всех вентилей на колесах',
                'base_price': 200.00,
                'price_from': False,
                'currency': 'RUB',
                'category': ServiceType.TIRE_REPAIR,
                'is_active': True
            },
            # Дополнительные услуги
            {
                'name': 'Диагностика электроники',
                'description': 'Комплексная диагностика электронных систем автомобиля',
                'base_price': 1500.00,
                'price_from': True,
                'currency': 'RUB',
                'category': ServiceType.DIAGNOSTICS,
                'is_active': True
            },
            {
                'name': 'Замена масла',
                'description': 'Замена моторного масла и фильтра',
                'base_price': 800.00,
                'price_from': True,
                'currency': 'RUB',
                'category': ServiceType.SERVICE,
                'is_active': True
            },
            {
                'name': 'Автомойка',
                'description': 'Комплексная мойка автомобиля',
                'base_price': 500.00,
                'price_from': True,
                'currency': 'RUB',
                'category': ServiceType.CAR_WASH,
                'is_active': True
            },
            {
                'name': 'Буксировка',
                'description': 'Буксировка автомобиля до места ремонта',
                'base_price': 2000.00,
                'price_from': True,
                'currency': 'RUB',
                'category': ServiceType.TOWING,
                'is_active': True
            }
        ]
        
        created_count = 0
        for service_data in services_data:
            service, created = Service.objects.get_or_create(
                name=service_data['name'],
                defaults=service_data
            )
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f'Created service: {service.name}')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'Service already exists: {service.name}')
                )
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully created {created_count} new services')
        )


