from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


@override_settings(REQUIRE_EMAIL_VERIFICATION=True)
class EmailVerificationRequiredTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='unverified',
            email='unverified@example.com',
            password='pass',
            is_email_verified=False,
        )
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')

    def test_blocks_order_api_until_verified(self):
        response = self.client.get('/api/order/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        payload = response.json()
        self.assertEqual(payload.get('error'), 'email_verification_required')

    def test_allows_profile_read(self):
        response = self.client.get(reverse('user_details'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['user']['requires_email_verification'])

    @patch('apps.accounts.email_verification.send_email_verification_message')
    def test_resend_verification_email(self, mock_send):
        mock_send.return_value = None
        url = reverse('email_verification_resend')
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        mock_send.assert_called_once()

    def test_verified_user_can_access_orders(self):
        self.user.is_email_verified = True
        self.user.save(update_fields=['is_email_verified'])
        response = self.client.get('/api/order/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
