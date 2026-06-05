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
from apps.order.models import Order, OrderType
from apps.order.services.towing_pricing import calculate_towing_price, resolve_towing_distance_miles

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
        MasterTowingPricing.objects.create(
            master=self.master,
            base_fee=Decimal('80'),
            price_per_mile=Decimal('5'),
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
        )
        self.assertEqual(result['total_price'], '180.00')
        self.assertEqual(result['mileage_charge'], '100.00')

    def test_resolve_distance_from_explicit_miles(self):
        miles = resolve_towing_distance_miles(
            pickup_lat=41.31,
            pickup_lon=69.28,
            distance_miles=Decimal('20'),
        )
        self.assertEqual(miles, Decimal('20.00'))

    def test_towing_estimate_lists_master(self):
        response = self.client.post(
            reverse('order:towing-estimate'),
            {
                'latitude': '41.311100',
                'longitude': '69.279700',
                'distance_miles': '20',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['distance_miles'], '20.00')
        self.assertEqual(response.data['master_count'], 1)
        self.assertEqual(response.data['masters'][0]['master_id'], self.master.id)
        self.assertEqual(response.data['masters'][0]['pricing']['total_price'], '180.00')

    def test_create_towing_order(self):
        response = self.client.post(
            reverse('order:towing-create'),
            {
                'master_id': self.master.id,
                'car_list': [self.car.id],
                'location': 'Pickup address',
                'latitude': '41.311100',
                'longitude': '69.279700',
                'delivery_location': 'Delivery address',
                'delivery_latitude': '41.350000',
                'delivery_longitude': '69.300000',
                'distance_miles': '20',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        order = Order.objects.get(pk=response.data['order']['id'])
        self.assertEqual(order.order_type, OrderType.TOWING)
        self.assertEqual(order.master_id, self.master.id)
        self.assertEqual(order.towing_total, Decimal('180.00'))
        self.assertTrue(order.category.filter(is_towing_entry=True).exists())
        self.assertEqual(response.data['order']['towing']['total_price'], '180.00')

    @patch('apps.order.services.notifications.send_fcm_to_user_devices')
    def test_create_towing_order_sends_push_notifications(self, mock_fcm):
        mock_fcm.return_value = 1
        response = self.client.post(
            reverse('order:towing-create'),
            {
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
        self.assertGreaterEqual(mock_fcm.call_count, 2)
        kinds = {call.kwargs.get('data', {}).get('kind') for call in mock_fcm.call_args_list}
        self.assertIn('towing_created', kinds)
        self.assertIn('order_new', kinds)
        order_types = {
            call.kwargs.get('data', {}).get('order_type')
            for call in mock_fcm.call_args_list
            if call.kwargs.get('data', {}).get('order_type')
        }
        self.assertIn('towing', order_types)

    def test_master_can_set_towing_pricing(self):
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
                'base_fee': '90',
                'price_per_mile': '6',
                'minimum_fee': '120',
                'is_active': True,
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        pricing = MasterTowingPricing.objects.get(master=other_master)
        self.assertEqual(pricing.base_fee, Decimal('90'))
        self.assertEqual(pricing.price_per_mile, Decimal('6'))
