from django.test import SimpleTestCase, RequestFactory
from django.contrib.auth.models import AnonymousUser

from apps.accounts.display_name import (
    apply_customer_name_privacy_to_user_data,
    customer_display_name,
    masked_master_full_name,
    should_mask_master_name_for_request,
)


class CustomerDisplayNameTests(SimpleTestCase):
    def test_latin_names(self):
        self.assertEqual(customer_display_name('John', 'Wright'), 'John W.')
        self.assertEqual(customer_display_name('Anton', 'Kolesnikov'), 'Anton K.')

    def test_cyrillic_names(self):
        self.assertEqual(customer_display_name('Антон', 'Колесников'), 'Антон К.')

    def test_first_name_only(self):
        self.assertEqual(customer_display_name('Anton', ''), 'Anton')

    def test_mask_user_payload(self):
        class U:
            first_name = 'Anton'
            last_name = 'Kolesnikov'
            phone_number = '+123'
            email = None

        out = apply_customer_name_privacy_to_user_data(
            {'first_name': 'Anton', 'last_name': 'Kolesnikov', 'phone_number': '+123'},
            U(),
        )
        self.assertEqual(out['display_name'], 'Anton K.')
        self.assertEqual(out['first_name'], 'Anton')
        self.assertEqual(out['last_name'], 'K.')

    def test_master_sees_own_full_name(self):
        rf = RequestFactory()

        class User:
            id = 5
            is_authenticated = True

        request = rf.get('/')
        request.user = User()
        self.assertFalse(should_mask_master_name_for_request(request, 5))

    def test_masked_full_name_for_customers(self):
        class MasterUser:
            first_name = 'Anton'
            last_name = 'Kolesnikov'

        self.assertEqual(masked_master_full_name(MasterUser()), 'Anton K.')

    def test_customer_masks_name(self):
        rf = RequestFactory()

        class User:
            id = 1
            is_authenticated = True

        request = rf.get('/')
        request.user = User()
        self.assertTrue(should_mask_master_name_for_request(request, 5))

    def test_anonymous_masks_name(self):
        rf = RequestFactory()
        request = rf.get('/')
        request.user = AnonymousUser()
        self.assertTrue(should_mask_master_name_for_request(request, 5))
