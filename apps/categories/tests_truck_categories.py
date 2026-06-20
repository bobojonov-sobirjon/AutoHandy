from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.categories.models import Category


class TruckCategoryTestCase(APITestCase):
    def setUp(self):
        self.truck_main = Category.objects.create(
            name='Emergency Roadside for Semi Trucks',
            type_category=Category.TypeCategory.BY_ORDER,
            is_truck=True,
        )
        self.truck_sub = Category.objects.create(
            name='Jump Start',
            type_category=Category.TypeCategory.BY_ORDER,
            parent=self.truck_main,
            is_truck=True,
        )
        self.car_main = Category.objects.create(
            name='Roadside Help',
            type_category=Category.TypeCategory.BY_ORDER,
            is_truck=False,
        )

    def test_main_list_hides_truck_by_default(self):
        url = reverse('category-list')
        response = self.client.get(url, {'type': 'by_order'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [row['name'] for row in response.data]
        self.assertIn('Roadside Help', names)
        self.assertNotIn('Emergency Roadside for Semi Trucks', names)

    def test_main_list_truck_filter(self):
        url = reverse('category-list')
        response = self.client.get(url, {'type': 'by_order', 'is_truck': 'true'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(all(row['is_truck'] for row in response.data))
        names = [row['name'] for row in response.data]
        self.assertIn('Emergency Roadside for Semi Trucks', names)

    def test_subcategories_for_truck_parent(self):
        url = reverse('subcategory-list')
        response = self.client.get(url, {'parent_id': self.truck_main.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], 'Jump Start')
        self.assertTrue(response.data[0]['is_truck'])

    def test_subcategories_for_towing_entry_parent(self):
        towing = Category.objects.create(
            name='Towing',
            type_category=Category.TypeCategory.BY_ORDER,
            is_towing_entry=True,
        )
        Category.objects.create(
            name='Local towing',
            type_category=Category.TypeCategory.BY_ORDER,
            parent=towing,
        )
        url = reverse('subcategory-list')
        response = self.client.get(url, {'parent_id': towing.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], 'Local towing')
