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
    build_pricing_examples,
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
            base_fee=Decimal('100'),
            price_per_mile=Decimal('3'),
            is_active=True,
        )
        self.long_pricing = MasterTowingPricing.objects.create(
            master=self.master,
            service_type=TowingServiceType.LONG_DISTANCE,
            base_fee=Decimal('120'),
            price_per_mile=Decimal('4'),
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

    def test_simple_formula_examples(self):
        result = calculate_towing_price(
            base_fee=Decimal('100'),
            price_per_mile=Decimal('3'),
            distance_miles=Decimal('10'),
        )
        self.assertEqual(result['total_price'], '130.00')

        result20 = calculate_towing_price(
            base_fee=Decimal('100'),
            price_per_mile=Decimal('3'),
            distance_miles=Decimal('20'),
        )
        self.assertEqual(result20['total_price'], '160.00')

        result50 = calculate_towing_price(
            base_fee=Decimal('100'),
            price_per_mile=Decimal('3'),
            distance_miles=Decimal('50'),
        )
        self.assertEqual(result50['total_price'], '250.00')

    def test_pricing_examples_for_master_ui(self):
        examples = build_pricing_examples(100, 3)
        self.assertEqual(len(examples), 3)
        self.assertEqual(examples[0]['total_price'], '130.00')
        self.assertIn('10.00 mi:', examples[0]['label'])

    def test_master_payload_includes_examples(self):
        payload = build_master_towing_pricing_payload(
            self.master.id,
            list(self.master.towing_pricing_items.all()),
        )
        local = next(s for s in payload['services'] if s['service_type'] == TowingServiceType.LOCAL)
        self.assertEqual(len(local['examples']), 3)
        self.assertEqual(local['examples'][0]['total_price'], '130.00')
        self.assertIn('pricing_formula', payload)

    def test_long_distance_pricing_breakdown(self):
        result = calculate_towing_price_for_service(self.long_pricing, Decimal('60'))
        self.assertEqual(result['total_price'], '360.00')

    def test_resolve_distance_from_pickup_to_dropoff(self):
        miles = resolve_towing_distance_miles(
            pickup_lat=41.31,
            pickup_lon=69.28,
            delivery_lat=41.35,
            delivery_lon=69.30,
        )
        self.assertGreater(miles, 0)

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
        self.assertEqual(response.data['masters'][0]['pricing']['total_price'], '160.00')
        self.assertNotIn('minimum_fee', response.data['masters'][0]['pricing'])

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
                'delivery_latitude': '41.350000',
                'delivery_longitude': '69.300000',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        order = Order.objects.get(pk=response.data['order']['id'])
        self.assertEqual(order.towing_total, order.towing_base_fee + order.towing_distance_miles * order.towing_price_per_mile)
        self.assertIsNone(order.towing_minimum_fee)

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
                        'base_fee': '100',
                        'price_per_mile': '3',
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
        self.assertEqual(local.base_fee, Decimal('100'))
        self.assertEqual(response.data['services'][0]['examples'][0]['total_price'], '130.00')
