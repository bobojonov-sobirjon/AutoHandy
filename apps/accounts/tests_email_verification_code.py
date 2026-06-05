from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import EmailVerificationToken

User = get_user_model()


@override_settings(REQUIRE_EMAIL_VERIFICATION=True, EMAIL_DEBUG_IN_RESPONSE=True)
class EmailVerificationCodeTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='codeuser',
            email='codeuser@example.com',
            password='pass',
            is_email_verified=False,
        )
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
        self.confirm_url = reverse('email_verification_confirm')

    @patch('apps.accounts.email_verification.send_email_verification_message')
    def test_resend_returns_code_in_debug(self, mock_send):
        mock_send.return_value = None
        response = self.client.post(reverse('email_verification_resend'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertIn('verification_code', response.data)
        mock_send.assert_called_once()
        args = mock_send.call_args[0]
        self.assertEqual(args[0], 'codeuser@example.com')
        self.assertEqual(args[1], response.data['verification_code'])

    def test_confirm_with_valid_code(self):
        token = EmailVerificationToken.objects.create(
            user=self.user,
            email=self.user.email,
            code='4821',
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        response = self.client.post(self.confirm_url, {'code': '4821'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_email_verified)
        token.refresh_from_db()
        self.assertTrue(token.is_used)

    def test_confirm_rejects_wrong_code(self):
        EmailVerificationToken.objects.create(
            user=self.user,
            email=self.user.email,
            code='4821',
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        response = self.client.post(self.confirm_url, {'code': '9999'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])

    def test_confirm_rejects_expired_code(self):
        EmailVerificationToken.objects.create(
            user=self.user,
            email=self.user.email,
            code='4821',
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        response = self.client.post(self.confirm_url, {'code': '4821'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('expired', response.data['error'].lower())

    def test_confirm_requires_authentication(self):
        self.client.credentials()
        response = self.client.post(self.confirm_url, {'code': '4821'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
