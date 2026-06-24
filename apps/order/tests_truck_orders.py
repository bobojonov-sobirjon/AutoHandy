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
from apps.master.models import Master, MasterService, MasterServiceItems, MasterTowingPricing
from apps.master.towing_types import TowingServiceType
from apps.order.models import Order, OrderType

User = get_user_model()


@override_settings(TOWING_ESTIMATE_RADIUS_MILES=100)
class TruckOrderFlowTestCase(APITestCase):
    def setUp(self):
        self.driver = User.objects.create_user(
            username='truck_driver',
            email='truck_driver@example.com',
            password='pass',
            is_email_verified=True,
        )
        self.master_user = User.objects.create_user(
            username='truck_master',
            email='truck_master@example.com',
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
        self.master_service = MasterService.objects.create(master=self.master)
        MasterTowingPricing.objects.create(
            master=self.master,
            service_type=TowingServiceType.SEMI_TRUCK,
            base_fee=Decimal('200'),
            price_per_mile=Decimal('6'),
            is_active=True,
        )

        self.truck_main = Category.objects.create(
            name='Roadside Semi Truck',
            type_category=Category.TypeCategory.BY_ORDER,
            is_truck=True,
        )
        self.truck_tire = Category.objects.create(
            name='Semi-Truck Tire Replacement',
            type_category=Category.TypeCategory.BY_ORDER,
            parent=self.truck_main,
            is_truck=True,
        )
        self.truck_towing = Category.objects.create(
            name='Semi-Truck Towing',
            type_category=Category.TypeCategory.BY_ORDER,
            parent=self.truck_main,
            is_truck=True,
        )

        MasterServiceItems.objects.create(
            master_service=self.master_service,
            category=self.truck_tire,
            price=Decimal('200'),
        )

        refresh = RefreshToken.for_user(self.driver)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')

    @patch('apps.order.api.serializers.filter_master_ids_meeting_emergency_thresholds', side_effect=lambda q: q)
    @patch('apps.order.api.serializers.activate_pending_master_offer')
    def test_truck_roadside_order_without_car(self, _mock_offer, _mock_filter):
        response = self.client.post(
            reverse('order:truck-order-create'),
            {
                'category_id': self.truck_tire.id,
                'truck_make_model': 'Freightliner Cascadia',
                'truck_year': 2018,
                'location': 'I-80 mile 120',
                'latitude': '41.311100',
                'longitude': '69.279700',
                'timing': 'now',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        order = Order.objects.get(pk=response.data['order']['id'])
        self.assertEqual(order.order_type, OrderType.SOS)
        self.assertEqual(order.truck_make_model, 'Freightliner Cascadia')
        self.assertEqual(order.truck_year, 2018)
        self.assertEqual(list(order.car.all()), [])
        self.assertEqual(response.data['order']['truck']['make_model'], 'Freightliner Cascadia')
        self.assertEqual(response.data['order']['truck']['year'], 2018)

    @patch('apps.order.api.serializers.activate_pending_master_offer')
    def test_truck_towing_estimate(self, _mock_offer):
        response = self.client.post(
            reverse('order:truck-towing-estimate'),
            {
                'latitude': '41.311100',
                'longitude': '69.279700',
                'distance_miles': '10',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['service_type'], TowingServiceType.SEMI_TRUCK)
        self.assertEqual(response.data['masters'][0]['pricing']['total_price'], '260.00')

    @patch('apps.order.api.serializers.activate_pending_master_offer')
    def test_truck_towing_order_with_pricing(self, _mock_offer):
        response = self.client.post(
            reverse('order:truck-towing-create'),
            {
                'category_id': self.truck_towing.id,
                'master_id': self.master.id,
                'truck_make_model': 'Kenworth T680',
                'truck_year': 2020,
                'location': 'Pickup yard',
                'latitude': '41.311100',
                'longitude': '69.279700',
                'delivery_location': 'Repair shop',
                'delivery_latitude': '41.320000',
                'delivery_longitude': '69.290000',
                'timing': 'now',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        order = Order.objects.get(pk=response.data['order']['id'])
        self.assertEqual(order.order_type, OrderType.TOWING)
        self.assertEqual(order.towing_trip_type, TowingServiceType.SEMI_TRUCK)
        self.assertEqual(order.truck_make_model, 'Kenworth T680')
        self.assertIsNotNone(order.towing_total)
        self.assertIn(self.truck_towing.id, order.category.values_list('id', flat=True))

    def test_truck_endpoint_rejects_towing_category(self):
        response = self.client.post(
            reverse('order:truck-order-create'),
            {
                'category_id': self.truck_towing.id,
                'truck_make_model': 'Freightliner Cascadia',
                'location': 'Highway',
                'latitude': '41.311100',
                'longitude': '69.279700',
                'timing': 'now',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('category_id', response.data)
