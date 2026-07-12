from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.master.models import Master
from apps.order.models import Order, OrderStatus, OrderTimeChangeRequest, OrderType, TimeChangeRequestStatus

User = get_user_model()


class OrderTimeChangeFlowTestCase(APITestCase):
    def setUp(self):
        self.driver = User.objects.create_user(username='driver', email='driver@example.com', password='x')
        self.master_user = User.objects.create_user(username='master', email='master@example.com', password='x')
        self.master = Master.objects.create(user=self.master_user)
        tomorrow = (timezone.now() + timedelta(days=1)).date()
        self.order = Order.objects.create(
            user=self.driver,
            master=self.master,
            text='Brake service',
            status=OrderStatus.ACCEPTED,
            order_type=OrderType.STANDARD,
            preferred_date=tomorrow,
            preferred_time_start=time(10, 0),
            preferred_time_end=time(12, 0),
        )

    def test_master_proposes_and_client_approves(self):
        self.client.force_authenticate(user=self.master_user)
        create_url = reverse('order:order-time-change-requests-create', kwargs={'order_id': self.order.pk})
        new_date = self.order.preferred_date
        response = self.client.post(
            create_url,
            {
                'proposed_preferred_date': str(new_date),
                'proposed_preferred_time_start': '14:00:00',
                'proposed_preferred_time_end': '16:00:00',
                'comment': 'Busy in the morning',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        req_id = response.data['id']

        self.client.force_authenticate(user=self.driver)
        approve_url = reverse('order:order-time-change-requests-approve', kwargs={'request_id': req_id})
        response = self.client.post(approve_url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.order.refresh_from_db()
        self.assertEqual(self.order.preferred_time_start, time(14, 0))
        self.assertEqual(self.order.preferred_time_end, time(16, 0))
        req = OrderTimeChangeRequest.objects.get(pk=req_id)
        self.assertEqual(req.status, TimeChangeRequestStatus.APPROVED)

    def test_pending_list_for_client(self):
        OrderTimeChangeRequest.objects.create(
            order=self.order,
            master=self.master,
            previous_preferred_date=self.order.preferred_date,
            previous_preferred_time_start=self.order.preferred_time_start,
            previous_preferred_time_end=self.order.preferred_time_end,
            proposed_preferred_date=self.order.preferred_date,
            proposed_preferred_time_start=time(15, 0),
            proposed_preferred_time_end=time(17, 0),
            status=TimeChangeRequestStatus.PENDING,
        )
        self.client.force_authenticate(user=self.driver)
        url = reverse('order:order-time-change-requests-pending')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_rejects_unchanged_schedule(self):
        self.client.force_authenticate(user=self.master_user)
        create_url = reverse('order:order-time-change-requests-create', kwargs={'order_id': self.order.pk})
        response = self.client.post(
            create_url,
            {
                'proposed_preferred_date': str(self.order.preferred_date),
                'proposed_preferred_time_start': self.order.preferred_time_start.isoformat(),
                'proposed_preferred_time_end': self.order.preferred_time_end.isoformat(),
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_utc_z_times_converted_to_service_timezone(self):
        """Mobile often sends 21:25:00Z for 14:25 America/Los_Angeles (PDT)."""
        self.client.force_authenticate(user=self.master_user)
        create_url = reverse('order:order-time-change-requests-create', kwargs={'order_id': self.order.pk})
        new_date = self.order.preferred_date
        response = self.client.post(
            create_url,
            {
                'proposed_preferred_date': str(new_date),
                # 21:25 UTC == 14:25 PDT in July
                'proposed_preferred_time_start': '21:25:00Z',
                'proposed_preferred_time_end': '21:45:00Z',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['proposed_preferred_time_start'], '14:25:00')
        self.assertEqual(response.data['proposed_preferred_time_end'], '14:45:00')
        self.assertIn('2:25 PM', response.data['proposed_slot_label'])
        self.assertIn('America/Los_Angeles', response.data['schedule_timezone'])
