from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model
from unittest.mock import patch, MagicMock
import json

User = get_user_model()


class LoginViewTestCase(APITestCase):
    """Тесты для LoginView с поддержкой email и телефона"""
    
    def setUp(self):
        """Настройка тестовых данных"""
        self.login_url = reverse('login')
        
        # Создаем тестового пользователя с email
        self.user_with_email = User.objects.create_user(
            username='testuser_email',
            email='test@example.com',
            phone_number='998901234567',
            first_name='Test',
            last_name='User'
        )
        
        # Создаем тестового пользователя с телефоном
        self.user_with_phone = User.objects.create_user(
            username='testuser_phone',
            email='phone@example.com',
            phone_number='79123456789',
            first_name='Phone',
            last_name='User'
        )
    
    @patch('apps.accounts.services.SMSService.send_sms_code')
    def test_login_with_phone_number(self, mock_send_sms):
        """Тест входа с номером телефона"""
        mock_send_sms.return_value = {
            'success': True,
            'message': 'SMS код отправлен',
            'identifier': '998901234567',
            'identifier_type': 'phone',
            'phone': '998901234567',
            'user_exists': True,
            'status_code': status.HTTP_200_OK
        }
        
        data = {'identifier': '998901234567'}
        response = self.client.post(self.login_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertEqual(response.data['identifier_type'], 'phone')
        self.assertTrue(response.data['user_exists'])
        mock_send_sms.assert_called_once_with('998901234567', 'phone')
    
    @patch('apps.accounts.services.SMSService.send_sms_code')
    def test_login_with_email(self, mock_send_sms):
        """Тест входа с email"""
        mock_send_sms.return_value = {
            'success': True,
            'message': 'SMS код отправлен',
            'identifier': 'test@example.com',
            'identifier_type': 'email',
            'phone': '998901234567',
            'user_exists': True,
            'status_code': status.HTTP_200_OK
        }
        
        data = {'identifier': 'test@example.com'}
        response = self.client.post(self.login_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertEqual(response.data['identifier_type'], 'email')
        self.assertTrue(response.data['user_exists'])
        mock_send_sms.assert_called_once_with('test@example.com', 'email')
    
    def test_login_with_invalid_identifier(self):
        """Тест с неверным идентификатором"""
        data = {'identifier': 'invalid_identifier'}
        response = self.client.post(self.login_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
        self.assertIn('errors', response.data)
    
    def test_login_with_empty_identifier(self):
        """Тест с пустым идентификатором"""
        data = {'identifier': ''}
        response = self.client.post(self.login_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])


class CheckSMSCodeViewTestCase(APITestCase):
    """Тесты для CheckSMSCodeView с поддержкой email и телефона"""
    
    def setUp(self):
        """Настройка тестовых данных"""
        self.check_sms_url = reverse('check_sms_code')
        
        # Создаем тестового пользователя
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            phone_number='998901234567',
            first_name='Test',
            last_name='User'
        )
    
    @patch('apps.accounts.services.SMSService.verify_sms_code')
    def test_verify_sms_code_with_phone(self, mock_verify_sms):
        """Тест проверки SMS кода с номером телефона"""
        mock_verify_sms.return_value = {
            'success': True,
            'message': 'Успешный вход',
            'user': self.user,
            'user_created': False,
            'tokens': {
                'access': 'test_access_token',
                'refresh': 'test_refresh_token'
            },
            'status_code': status.HTTP_200_OK
        }
        
        data = {
            'identifier': '998901234567',
            'sms_code': '1234'
        }
        response = self.client.post(self.check_sms_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        mock_verify_sms.assert_called_once_with('998901234567', '1234', 'phone')
    
    @patch('apps.accounts.services.SMSService.verify_sms_code')
    def test_verify_sms_code_with_email(self, mock_verify_sms):
        """Тест проверки SMS кода с email"""
        mock_verify_sms.return_value = {
            'success': True,
            'message': 'Успешный вход',
            'user': self.user,
            'user_created': False,
            'tokens': {
                'access': 'test_access_token',
                'refresh': 'test_refresh_token'
            },
            'status_code': status.HTTP_200_OK
        }
        
        data = {
            'identifier': 'test@example.com',
            'sms_code': '1234'
        }
        response = self.client.post(self.check_sms_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        mock_verify_sms.assert_called_once_with('test@example.com', '1234', 'email')
    
    def test_verify_sms_code_with_invalid_data(self):
        """Тест с неверными данными"""
        data = {
            'identifier': 'invalid_identifier',
            'sms_code': '1234'
        }
        response = self.client.post(self.check_sms_url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])


class IdentifierSerializerTestCase(TestCase):
    """Тесты для IdentifierSerializer"""
    
    def test_validate_phone_number_uzbekistan(self):
        """Тест валидации узбекского номера"""
        from .serializers import IdentifierSerializer
        
        # Тест с +998
        data = {'identifier': '+998901234567'}
        serializer = IdentifierSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data['identifier']['type'], 'phone')
        self.assertEqual(serializer.validated_data['identifier']['value'], '998901234567')
        
        # Тест без +
        data = {'identifier': '998901234567'}
        serializer = IdentifierSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data['identifier']['type'], 'phone')
        self.assertEqual(serializer.validated_data['identifier']['value'], '998901234567')
    
    def test_validate_phone_number_russia(self):
        """Тест валидации российского номера"""
        from .serializers import IdentifierSerializer
        
        # Тест с +7
        data = {'identifier': '+79123456789'}
        serializer = IdentifierSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data['identifier']['type'], 'phone')
        self.assertEqual(serializer.validated_data['identifier']['value'], '79123456789')
        
        # Тест с 8
        data = {'identifier': '89123456789'}
        serializer = IdentifierSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data['identifier']['type'], 'phone')
        self.assertEqual(serializer.validated_data['identifier']['value'], '79123456789')
    
    def test_validate_email(self):
        """Тест валидации email"""
        from .serializers import IdentifierSerializer
        
        data = {'identifier': 'test@example.com'}
        serializer = IdentifierSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data['identifier']['type'], 'email')
        self.assertEqual(serializer.validated_data['identifier']['value'], 'test@example.com')
    
    def test_validate_invalid_identifier(self):
        """Тест с неверным идентификатором"""
        from .serializers import IdentifierSerializer
        
        data = {'identifier': 'invalid_identifier'}
        serializer = IdentifierSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('identifier', serializer.errors)
