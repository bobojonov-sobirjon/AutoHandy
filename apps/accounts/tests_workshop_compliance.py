from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import WorkshopComplianceAuditLog

User = get_user_model()


class UserWorkshopComplianceAPITestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='master_user',
            email='master@example.com',
            password='pass',
        )
        self.user.is_email_verified = True
        self.user.save(update_fields=['is_email_verified'])
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
        self.url = reverse('user_workshop_compliance')

    def test_get_returns_unchecked_by_default(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['locked'])
        self.assertFalse(response.data['has_tools_confirmed'])
        self.assertFalse(response.data['has_licenses_confirmed'])
        self.assertIsNone(response.data['workshop_compliance_confirmed_at'])

    def test_put_confirms_compliance(self):
        response = self.client.put(
            self.url,
            {'has_tools_confirmed': True, 'has_licenses_confirmed': True},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertTrue(response.data['locked'])
        self.user.refresh_from_db()
        self.assertTrue(self.user.has_tools_confirmed)
        self.assertTrue(self.user.has_licenses_confirmed)
        self.assertIsNotNone(self.user.workshop_compliance_confirmed_at)
        self.assertEqual(WorkshopComplianceAuditLog.objects.filter(user=self.user).count(), 1)

    def test_get_after_confirm_shows_locked_checked(self):
        self.client.put(
            self.url,
            {'has_tools_confirmed': True, 'has_licenses_confirmed': True},
            format='json',
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['locked'])
        self.assertTrue(response.data['has_tools_confirmed'])
        self.assertTrue(response.data['has_licenses_confirmed'])
        self.assertIsNotNone(response.data['workshop_compliance_confirmed_at'])

    def test_reconfirm_is_idempotent_and_keeps_original_timestamp(self):
        first = self.client.put(
            self.url,
            {'has_tools_confirmed': True, 'has_licenses_confirmed': True},
            format='json',
        )
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        original_at = self.user.workshop_compliance_confirmed_at

        second = self.client.put(
            self.url,
            {'has_tools_confirmed': True, 'has_licenses_confirmed': True},
            format='json',
        )
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertTrue(second.data['locked'])
        self.user.refresh_from_db()
        self.assertEqual(self.user.workshop_compliance_confirmed_at, original_at)
        # Only one audit row for first confirmation
        self.assertEqual(WorkshopComplianceAuditLog.objects.filter(user=self.user).count(), 1)

    def test_profile_includes_compliance_fields(self):
        self.user.has_tools_confirmed = True
        self.user.has_licenses_confirmed = True
        self.user.workshop_compliance_confirmed_at = timezone.now()
        self.user.save()
        response = self.client.get(reverse('user_details'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user = response.data['user']
        self.assertTrue(user['has_tools_confirmed'])
        self.assertTrue(user['has_licenses_confirmed'])

    def test_put_rejects_false_confirmations(self):
        response = self.client.put(
            self.url,
            {'has_tools_confirmed': False, 'has_licenses_confirmed': True},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
