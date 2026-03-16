from django.urls import path
from apps.categories.views import CategoryListAPIView

urlpatterns = [
    path('categories/', CategoryListAPIView.as_view(), name='category-list'),
]