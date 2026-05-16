from __future__ import annotations

from rest_framework import serializers

from apps.payment.models import SavedCard


class SavedCardSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavedCard
        fields = (
            'id',
            'holder_role',
            'brand',
            'last4',
            'exp_month',
            'exp_year',
            'funding',
            'is_default',
            'created_at',
        )
        read_only_fields = fields


class SavedCardCreateSerializer(serializers.Serializer):
    payment_method_id = serializers.CharField(max_length=64, required=True)
    stripe_customer_id = serializers.CharField(max_length=64, required=False, allow_blank=True)


class SavedCardDefaultSerializer(serializers.Serializer):
    is_default = serializers.BooleanField()
