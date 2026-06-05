from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


class UserWorkshopComplianceAPITestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='master_user',
            email='master@example.com',
            password='pass',
        )
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
        self.url = reverse('user_workshop_compliance')

    def test_put_confirms_compliance(self):
        response = self.client.put(
            self.url,
            {'has_tools_confirmed': True, 'has_licenses_confirmed': True},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.user.refresh_from_db()
        self.assertTrue(self.user.has_tools_confirmed)
        self.assertTrue(self.user.has_licenses_confirmed)
        self.assertIsNotNone(self.user.workshop_compliance_confirmed_at)

    def test_profile_includes_compliance_fields(self):
        self.user.has_tools_confirmed = True
        self.user.has_licenses_confirmed = True
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
