from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.categories.models import Category
from apps.categories.services.home_screen_order import apply_home_screen_category_order


class CategorySortOrderTestCase(APITestCase):
    def setUp(self):
        self.towing = Category.objects.create(
            name='Towing',
            type_category=Category.TypeCategory.BY_ORDER,
            is_towing_entry=True,
            parent=None,
        )
        self.locksmith = Category.objects.create(
            name='Locksmith',
            type_category=Category.TypeCategory.BY_ORDER,
            parent=None,
        )
        self.roadside = Category.objects.create(
            name='Roadside Assistance',
            type_category=Category.TypeCategory.BY_ORDER,
            parent=None,
        )
        self.custom = Category.objects.create(
            name='Custom Request',
            type_category=Category.TypeCategory.BY_ORDER,
            is_custom_request_entry=True,
            parent=None,
        )
        self.truck = Category.objects.create(
            name='Emergency Roadside for Semi Trucks',
            type_category=Category.TypeCategory.BY_ORDER,
            is_truck=True,
            parent=None,
        )

    def test_apply_home_screen_category_order(self):
        result = apply_home_screen_category_order()
        self.assertGreaterEqual(result['matched'], 4)
        self.towing.refresh_from_db()
        self.locksmith.refresh_from_db()
        self.truck.refresh_from_db()
        self.assertEqual(self.towing.sort_order, 1)
        self.assertEqual(self.locksmith.sort_order, 2)
        self.assertEqual(self.truck.sort_order, 15)
        self.assertEqual(self.truck.name, 'Roadside Semi Truck')

    def test_category_list_sorted_by_sort_order(self):
        apply_home_screen_category_order()
        response = self.client.get(reverse('category-list'), {'type': 'by_order'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_name = {row['name']: row for row in response.data}
        self.assertEqual(by_name['Locksmith']['sort_order'], 2)
        self.assertEqual(by_name['Roadside Assistance']['sort_order'], 3)
        towing_rows = [row for row in response.data if row.get('sort_order') == 1]
        self.assertTrue(towing_rows)
        self.assertTrue(any(row['name'] == 'Towing' for row in towing_rows))
