from django.urls import path
from apps.categories.views import CategoryListAPIView, SubCategoryListAPIView

urlpatterns = [
    path('categories/', CategoryListAPIView.as_view(), name='category-list'),
    path('subcategories/', SubCategoryListAPIView.as_view(), name='subcategory-list'),
]