"""Stripe Customer bootstrap for the authenticated user (client or master profile)."""
from __future__ import annotations

from drf_spectacular.utils import extend_schema
from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payment.services.stripe_cards import StripeCardError, ensure_stripe_customer_id


class StripeCustomerView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary='Stripe Customer (cus_…)',
        tags=['Stripe — Driver'],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'status': {'type': 'string'},
                    'data': {
                        'type': 'object',
                        'properties': {
                            'stripe_customer_id': {'type': 'string'},
                            'created': {'type': 'boolean'},
                            'stripe_publishable_key': {'type': 'string'},
                        },
                    },
                },
            },
            503: {'type': 'object'},
        },
    )
    def get(self, request):
        if not (getattr(settings, 'STRIPE_SECRET_KEY', '') or '').strip():
            return Response(
                {'status': 'error', 'message': 'Stripe is not configured on the server.'},
                status=503,
            )
        try:
            cus, created = ensure_stripe_customer_id(request.user)
        except StripeCardError as e:
            return Response({'status': 'error', 'message': e.message}, status=503)
        pk = (getattr(settings, 'STRIPE_PUBLISHABLE_KEY', '') or '').strip()
        return Response(
            {
                'status': 'success',
                'data': {
                    'stripe_customer_id': cus,
                    'created': created,
                    'stripe_publishable_key': pk,
                },
            }
        )
