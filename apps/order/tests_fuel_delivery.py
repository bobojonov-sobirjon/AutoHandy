from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.categories.models import Category
from apps.master.models import Master, MasterService, MasterServiceItems
from apps.order.models import FuelDeliveryType, Order, OrderService

User = get_user_model()


class FuelDeliveryFlowTestCase(APITestCase):
    def setUp(self):
        self.driver = User.objects.create_user(
            username='driver_fd',
            email='driver_fd@example.com',
            password='pass',
            is_email_verified=True,
        )
        self.master_user = User.objects.create_user(
            username='master_fd',
            email='master_fd@example.com',
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

        self.roadside_parent = Category.objects.create(
            name='Roadside Assistance',
            type_category=Category.TypeCategory.BY_ORDER,
        )
        self.fuel_category = Category.objects.create(
            name='Fuel Delivery',
            type_category=Category.TypeCategory.BY_ORDER,
            parent=self.roadside_parent,
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

        master_refresh = RefreshToken.for_user(self.master_user)
        self.master_client = self.client_class()
        self.master_client.credentials(HTTP_AUTHORIZATION=f'Bearer {master_refresh.access_token}')

    def _create_fuel_skill(self, *, gas=True, diesel=True, price='100.00'):
        return MasterServiceItems.objects.create(
            master_service=self.master_service,
            category=self.fuel_category,
            price=Decimal(price),
            has_gas_container_2gal=gas,
            has_diesel_container_2gal=diesel,
        )

    def test_master_can_save_fuel_delivery_without_containers_inactive(self):
        """Omitted / partial flags default to false; skill saves but is not active."""
        response = self.master_client.post(
            '/api/master/service-items/',
            {
                'master_id': self.master.id,
                'services': [
                    {
                        'category': self.fuel_category.id,
                        'price': 100,
                    },
                ],
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        item = MasterServiceItems.objects.get(
            master_service=self.master_service,
            category=self.fuel_category,
        )
        self.assertFalse(item.has_gas_container_2gal)
        self.assertFalse(item.has_diesel_container_2gal)
        self.assertFalse(item.fuel_delivery_is_active())

        response_partial = self.master_client.post(
            '/api/master/service-items/',
            {
                'master_id': self.master.id,
                'services': [
                    {
                        'category': self.fuel_category.id,
                        'price': 100,
                        'has_gas_container_2gal': True,
                        'has_diesel_container_2gal': False,
                    },
                ],
            },
            format='json',
        )
        self.assertEqual(response_partial.status_code, status.HTTP_201_CREATED)
        item.refresh_from_db()
        self.assertTrue(item.has_gas_container_2gal)
        self.assertFalse(item.has_diesel_container_2gal)
        self.assertFalse(item.fuel_delivery_is_active())

    def test_master_can_activate_fuel_delivery_with_both_containers(self):
        response = self.master_client.post(
            '/api/master/service-items/',
            {
                'master_id': self.master.id,
                'services': [
                    {
                        'category': self.fuel_category.id,
                        'price': 100,
                        'has_gas_container_2gal': True,
                        'has_diesel_container_2gal': True,
                    },
                ],
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        groups = response.data['master_service_items']
        items = groups[0]['items']
        fuel_line = next(i for i in items if i['category_id'] == self.fuel_category.id)
        self.assertTrue(fuel_line['fuel_delivery_active'])

    @patch('apps.order.api.serializers.activate_pending_master_offer')
    def test_standard_order_requires_fuel_type_for_fuel_delivery(self, _mock_offer):
        self._create_fuel_skill()
        response = self.client.post(
            reverse('order:standard-order-create'),
            {
                'master_id': self.master.id,
                'text': 'Need fuel',
                'location': 'Highway',
                'latitude': '41.311100',
                'longitude': '69.279700',
                'car_list': [self.car.id],
                'category_list': [self.fuel_category.id],
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('fuel_type', response.data)

    @patch('apps.order.api.serializers.activate_pending_master_offer')
    def test_standard_order_stores_fuel_type_on_order_and_service_line(self, _mock_offer):
        self._create_fuel_skill()
        response = self.client.post(
            reverse('order:standard-order-create'),
            {
                'master_id': self.master.id,
                'text': 'Need fuel',
                'location': 'Highway',
                'latitude': '41.311100',
                'longitude': '69.279700',
                'car_list': [self.car.id],
                'category_list': [self.fuel_category.id],
                'fuel_type': FuelDeliveryType.GASOLINE,
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        order_data = response.data['order']
        order = Order.objects.get(pk=order_data['id'])
        self.assertEqual(order.fuel_delivery_type, FuelDeliveryType.GASOLINE)

        os_row = OrderService.objects.get(order=order)
        self.assertEqual(os_row.fuel_type, FuelDeliveryType.GASOLINE)

        service_line = order_data['services'][0]['items'][0]
        self.assertEqual(service_line['fuel_type'], FuelDeliveryType.GASOLINE)
        self.assertEqual(service_line['fuel_type_display'], 'Gasoline')
        self.assertIn('Delivery of 2 gallons of fuel', service_line['fuel_delivery_summary'])

    @patch('apps.order.api.serializers.activate_pending_master_offer')
    def test_standard_order_rejects_master_without_fuel_containers(self, _mock_offer):
        self._create_fuel_skill(gas=False, diesel=False)
        response = self.client.post(
            reverse('order:standard-order-create'),
            {
                'master_id': self.master.id,
                'text': 'Need fuel',
                'location': 'Highway',
                'latitude': '41.311100',
                'longitude': '69.279700',
                'car_list': [self.car.id],
                'category_list': [self.fuel_category.id],
                'fuel_type': FuelDeliveryType.DIESEL,
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('master_id', response.data)
