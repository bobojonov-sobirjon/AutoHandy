from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.master.models import Master
from apps.order.api.order_list_serializers import OrderListSerializer
from apps.order.api.order_list_query import optimize_orders_list_queryset, prepare_orders_page_for_serialization
from apps.order.models import Order, OrderStatus, OrderType

User = get_user_model()


class OrderListSerializerSpeedShapeTestCase(TestCase):
    def setUp(self):
        self.driver = User.objects.create_user(
            username='list_drv',
            email='list_drv@example.com',
            password='pass',
            first_name='Anton',
            last_name='Kuznetsov',
        )
        self.master_user = User.objects.create_user(
            username='list_mst',
            email='list_mst@example.com',
            password='pass',
            first_name='Vitalii',
            last_name='Petrov',
        )
        self.master = Master.objects.create(user=self.master_user)
        self.orders = [
            Order.objects.create(
                user=self.driver,
                master=self.master,
                text=f'Job {i}',
                status=OrderStatus.COMPLETED if i % 2 == 0 else OrderStatus.PENDING,
                order_type=OrderType.STANDARD,
            )
            for i in range(5)
        ]

    def test_list_serializer_masks_names_and_has_card_fields(self):
        factory = APIRequestFactory()
        request = factory.get('/api/order/by-user/')
        force_authenticate(request, user=self.driver)
        request.user = self.driver
        qs = optimize_orders_list_queryset(Order.objects.filter(user=self.driver))
        page = list(qs)
        prepare_orders_page_for_serialization(page)
        data = OrderListSerializer(page, many=True, context={'request': request}).data
        self.assertEqual(len(data), 5)
        row = data[0]
        self.assertIn('pricing', row)
        self.assertIn('total', row['pricing'])
        self.assertIn('master', row)
        self.assertEqual(row['master']['user']['full_name'], 'Vitalii P')
        # Heavy nested keys must not appear on list cards.
        self.assertNotIn('services', row)
        self.assertNotIn('workflow', row)
        self.assertNotIn('cancellation', row)
        self.assertNotIn('order_images', row)
