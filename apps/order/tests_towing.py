from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.categories.models import Category
from apps.master.models import Master, MasterTowingPricing
from apps.master.towing_types import TowingServiceType
from apps.order.models import Order, OrderType
from apps.order.services.towing_pricing import (
    build_master_towing_pricing_payload,
    calculate_towing_price,
    calculate_towing_price_for_service,
    resolve_towing_distance_miles,
)

User = get_user_model()


@override_settings(TOWING_ESTIMATE_RADIUS_MILES=100)
class TowingFlowTestCase(APITestCase):
    def setUp(self):
        self.driver = User.objects.create_user(
            username='driver1',
            email='driver1@example.com',
            password='pass',
            is_email_verified=True,
        )
        self.master_user = User.objects.create_user(
            username='master1',
            email='master1@example.com',
            password='pass',
            is_email_verified=True,
        )
        master_group, _ = Group.objects.get_or_create(name='Master')
        self.master_user.groups.add(master_group)

        self.master = Master.objects.create(
            user=self.master_user,
            latitude=Decimal('41.310000'),
            longitude=Decimal('69.280000'),
            service_area_radius_miles=100,
        )
        self.local_pricing = MasterTowingPricing.objects.create(
            master=self.master,
            service_type=TowingServiceType.LOCAL,
            base_fee=Decimal('80'),
            price_per_mile=Decimal('5'),
            minimum_fee=Decimal('100'),
            is_active=True,
        )
        self.long_pricing = MasterTowingPricing.objects.create(
            master=self.master,
            service_type=TowingServiceType.LONG_DISTANCE,
            base_fee=Decimal('120'),
            price_per_mile=Decimal('4'),
            minimum_fee=Decimal('100'),
            is_active=True,
        )

        self.towing_category = Category.objects.create(
            name='Towing',
            type_category=Category.TypeCategory.BY_ORDER,
            is_towing_entry=True,
        )

        from apps.car.models import Car

        self.car = Car.objects.create(
            user=self.driver,
            brand='Toyota',
            model='Camry',
            year=2020,
        )

        refresh = RefreshToken.for_user(self.driver)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')

    def test_calculate_towing_price_example(self):
        result = calculate_towing_price(
            base_fee=Decimal('80'),
            price_per_mile=Decimal('5'),
            minimum_fee=Decimal('100'),
            distance_miles=Decimal('20'),
            service_type=TowingServiceType.LOCAL,
        )
        self.assertEqual(result['total_price'], '180.00')
        self.assertEqual(result['service_type'], TowingServiceType.LOCAL)

    def test_long_distance_pricing_breakdown(self):
        result = calculate_towing_price_for_service(self.long_pricing, Decimal('60'))
        self.assertEqual(result['service_type'], TowingServiceType.LONG_DISTANCE)
        self.assertEqual(result['base_fee'], '120.00')
        self.assertEqual(result['total_price'], '360.00')

    def test_towing_estimate_long_distance(self):
        response = self.client.post(
            reverse('order:towing-estimate'),
            {
                'service_type': TowingServiceType.LONG_DISTANCE,
                'latitude': '41.311100',
                'longitude': '69.279700',
                'distance_miles': '60',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['service_type'], TowingServiceType.LONG_DISTANCE)
        self.assertEqual(response.data['masters'][0]['pricing']['total_price'], '360.00')

    def test_resolve_distance_from_explicit_miles(self):
        miles = resolve_towing_distance_miles(
            pickup_lat=41.31,
            pickup_lon=69.28,
            distance_miles=Decimal('20'),
        )
        self.assertEqual(miles, Decimal('20.00'))

    def test_towing_estimate_lists_master_for_local(self):
        response = self.client.post(
            reverse('order:towing-estimate'),
            {
                'service_type': TowingServiceType.LOCAL,
                'latitude': '41.311100',
                'longitude': '69.279700',
                'distance_miles': '20',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['master_count'], 1)
        self.assertEqual(response.data['masters'][0]['pricing']['total_price'], '180.00')

    def test_create_towing_order_local(self):
        response = self.client.post(
            reverse('order:towing-create'),
            {
                'service_type': TowingServiceType.LOCAL,
                'master_id': self.master.id,
                'car_list': [self.car.id],
                'location': 'Pickup address',
                'latitude': '41.311100',
                'longitude': '69.279700',
                'distance_miles': '20',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        order = Order.objects.get(pk=response.data['order']['id'])
        self.assertEqual(order.order_type, OrderType.TOWING)
        self.assertEqual(order.towing_trip_type, TowingServiceType.LOCAL)
        self.assertEqual(order.towing_total, Decimal('180.00'))
        self.assertEqual(response.data['order']['towing']['service_type'], TowingServiceType.LOCAL)

    def test_master_towing_pricing_payload_has_all_services(self):
        payload = build_master_towing_pricing_payload(
            self.master.id,
            list(self.master.towing_pricing_items.all()),
        )
        self.assertEqual(len(payload['services']), 4)
        self.assertTrue(payload['configured'])

    @patch('apps.order.services.notifications.send_fcm_to_user_devices')
    def test_create_towing_order_sends_push_notifications(self, mock_fcm):
        mock_fcm.return_value = 1
        response = self.client.post(
            reverse('order:towing-create'),
            {
                'service_type': TowingServiceType.LOCAL,
                'master_id': self.master.id,
                'car_list': [self.car.id],
                'location': 'Pickup address',
                'latitude': '41.311100',
                'longitude': '69.279700',
                'distance_miles': '20',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_master_can_set_towing_pricing_bulk(self):
        other_master = Master.objects.create(
            user=self.master_user,
            latitude=Decimal('41.320000'),
            longitude=Decimal('69.290000'),
        )
        refresh = RefreshToken.for_user(self.master_user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
        response = self.client.put(
            reverse('master-towing-pricing'),
            {
                'master_id': other_master.id,
                'services': [
                    {
                        'service_type': TowingServiceType.LOCAL,
                        'base_fee': '90',
                        'price_per_mile': '6',
                        'minimum_fee': '120',
                        'is_active': True,
                    },
                    {
                        'service_type': TowingServiceType.MOTORCYCLE,
                        'base_fee': '50',
                        'price_per_mile': '3',
                        'minimum_fee': '70',
                        'is_active': True,
                    },
                ],
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        local = MasterTowingPricing.objects.get(
            master=other_master,
            service_type=TowingServiceType.LOCAL,
        )
        motorcycle = MasterTowingPricing.objects.get(
            master=other_master,
            service_type=TowingServiceType.MOTORCYCLE,
        )
        self.assertEqual(local.base_fee, Decimal('90'))
        self.assertEqual(motorcycle.price_per_mile, Decimal('3'))
        self.assertEqual(len(response.data['services']), 4)
