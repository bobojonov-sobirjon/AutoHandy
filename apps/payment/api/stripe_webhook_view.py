"""Stripe webhooks (Identity verification sessions)."""
from __future__ import annotations

from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payment.services.stripe_client import stripe_configured, stripe_sdk
from apps.payment.services.stripe_identity import handle_stripe_identity_webhook_event


@method_decorator(csrf_exempt, name='dispatch')
class StripeWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        summary='Stripe webhook',
        description=(
            'Optional: receives Stripe Identity events when `STRIPE_WEBHOOK_SECRET` is set. '
            'Without a secret, returns 200 and does nothing — mobile should poll '
            'GET /api/master/stripe-identity/status/ instead.'
        ),
        tags=['Stripe — Webhooks'],
        request={'application/json': {'type': 'object'}},
        responses={200: {'type': 'object'}, 400: {'type': 'object'}, 503: {'type': 'object'}},
    )
    def post(self, request):
        if not stripe_configured():
            return Response(
                {'error': 'Stripe is not configured on the server.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        payload = request.body
        sig_header = (request.META.get('HTTP_STRIPE_SIGNATURE') or '').strip()
        webhook_secret = (getattr(settings, 'STRIPE_WEBHOOK_SECRET', '') or '').strip()
        if not webhook_secret:
            return Response(
                {
                    'received': True,
                    'webhooks_disabled': True,
                    'message': 'STRIPE_WEBHOOK_SECRET not set; use GET /api/master/stripe-identity/status/ to sync.',
                }
            )
        if not sig_header:
            return Response({'error': 'Missing Stripe-Signature header.'}, status=status.HTTP_400_BAD_REQUEST)

        stripe = stripe_sdk()
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except ValueError:
            return Response({'error': 'Invalid payload.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001 — stripe.error.SignatureVerificationError
            msg = str(getattr(exc, 'user_message', None) or getattr(exc, 'message', None) or exc)
            return Response({'error': msg or 'Invalid signature.'}, status=status.HTTP_400_BAD_REQUEST)

        event_dict = event.to_dict() if hasattr(event, 'to_dict') else dict(event)
        handle_stripe_identity_webhook_event(event=event_dict)
        return Response({'received': True})
