from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from unittest.mock import patch

from apps.accounts.services import SMSService
from apps.accounts.store_review import (
    get_store_review_otp_for_phone,
    is_store_review_otp_for_phone,
    is_store_review_phone,
    validate_store_review_role,
)

User = get_user_model()

STORE_REVIEW_SETTINGS = {
    'STORE_REVIEW_DRIVER_PHONE': '15555550100',
    'STORE_REVIEW_DRIVER_OTP': '4242',
    'STORE_REVIEW_MASTER_PHONE': '15555550101',
    'STORE_REVIEW_MASTER_OTP': '5353',
}


@override_settings(**STORE_REVIEW_SETTINGS)
class StoreReviewOTPTestCase(TestCase):
    def test_store_review_phones_and_role_specific_otp(self):
        self.assertTrue(is_store_review_phone('15555550100'))
        self.assertTrue(is_store_review_phone('15555550101'))
        self.assertEqual(get_store_review_otp_for_phone('15555550100'), '4242')
        self.assertEqual(get_store_review_otp_for_phone('15555550101'), '5353')
        self.assertTrue(is_store_review_otp_for_phone('15555550100', '4242', 'Driver'))
        self.assertTrue(is_store_review_otp_for_phone('15555550101', '5353', 'Master'))
        self.assertFalse(is_store_review_otp_for_phone('15555550100', '5353', 'Driver'))
        self.assertFalse(is_store_review_otp_for_phone('15555550101', '4242', 'Master'))
        self.assertFalse(is_store_review_phone('998901234567'))

    def test_validate_store_review_role(self):
        self.assertIsNone(validate_store_review_role('15555550100', 'Driver'))
        self.assertIsNotNone(validate_store_review_role('15555550100', 'Master'))
        self.assertIsNone(validate_store_review_role('15555550101', 'Master'))
        self.assertIsNotNone(validate_store_review_role('15555550101', 'Driver'))

    @patch('apps.accounts.services.SMSService.send_sms_via_twilio')
    def test_send_sms_driver_uses_driver_code(self, mock_twilio):
        result = SMSService.send_sms_code('15555550100', 'phone', 'Driver')
        self.assertTrue(result['success'])
        self.assertEqual(result['sms_code'], '4242')
        mock_twilio.assert_not_called()

    @patch('apps.accounts.services.SMSService.send_sms_via_twilio')
    def test_send_sms_master_uses_master_code(self, mock_twilio):
        result = SMSService.send_sms_code('15555550101', 'phone', 'Master')
        self.assertTrue(result['success'])
        self.assertEqual(result['sms_code'], '5353')
        mock_twilio.assert_not_called()

    @patch('apps.accounts.services.SMSService.send_sms_via_twilio')
    def test_send_sms_rejects_wrong_role(self, mock_twilio):
        result = SMSService.send_sms_code('15555550100', 'phone', 'Master')
        self.assertFalse(result['success'])
        mock_twilio.assert_not_called()

    @patch('apps.accounts.services.SMSService.send_sms_via_twilio')
    def test_verify_driver_accepts_fixed_code_without_prior_send(self, mock_twilio):
        result = SMSService.verify_sms_code('15555550100', '4242', 'phone', 'Driver')
        self.assertTrue(result['success'])
        self.assertTrue(result.get('user_created', False))

    @patch('apps.accounts.services.SMSService.send_sms_via_twilio')
    def test_verify_master_accepts_fixed_code_without_prior_send(self, mock_twilio):
        result = SMSService.verify_sms_code('15555550101', '5353', 'phone', 'Master')
        self.assertTrue(result['success'])
        self.assertTrue(result.get('user_created', False))

    @patch('apps.accounts.services.SMSService.send_sms_via_twilio')
    def test_verify_rejects_cross_role_otp(self, mock_twilio):
        result = SMSService.verify_sms_code('15555550100', '5353', 'phone', 'Driver')
        self.assertFalse(result['success'])


@override_settings(**STORE_REVIEW_SETTINGS)
class AccountDeleteAPITestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='delete_me',
            email='delete@example.com',
            phone_number='15555550999',
            first_name='Del',
            last_name='Me',
        )
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')

    def test_account_delete_endpoint(self):
        url = reverse('account_delete')
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())

    def test_user_delete_endpoint(self):
        user = User.objects.create_user(
            username='delete_me2',
            email='delete2@example.com',
            phone_number='15555550998',
        )
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
        url = reverse('user_details')
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(User.objects.filter(pk=user.pk).exists())
