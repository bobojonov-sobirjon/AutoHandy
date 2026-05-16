"""Master: bootstrap Stripe Connect Express + hosted onboarding (like GET stripe-customer for drivers)."""
from __future__ import annotations

from urllib.parse import urlparse

from django.conf import settings
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.master.models import Master
from apps.master.permissions import IsMasterGroup
from apps.payment.services.stripe_connect_link import StripeConnectLinkError, fetch_connect_account_public_summary
from apps.payment.services.stripe_connect_onboarding import (
    create_account_onboarding_url,
    ensure_express_connect_account_for_master,
)


def _resolve_onboarding_urls(data: dict) -> tuple[str, str]:
    """Return (refresh_url, return_url) from POST body or settings."""
    ret = (data.get('return_url') or getattr(settings, 'STRIPE_CONNECT_ONBOARDING_RETURN_URL', '') or '').strip()
    ref = (data.get('refresh_url') or getattr(settings, 'STRIPE_CONNECT_ONBOARDING_REFRESH_URL', '') or '').strip()
    if not ret or not ref:
        raise serializers.ValidationError(
            {
                'return_url': 'return_url and refresh_url are required (or set STRIPE_CONNECT_ONBOARDING_RETURN_URL '
                'and STRIPE_CONNECT_ONBOARDING_REFRESH_URL in server settings).',
                'refresh_url': 'Same as return_url.',
            }
        )
    for label, u in (('return_url', ret), ('refresh_url', ref)):
        parsed = urlparse(u)
        if parsed.scheme not in ('https', 'http'):
            raise serializers.ValidationError({label: 'URL must use http or https.'})
        if parsed.scheme == 'http' and (parsed.hostname or '') not in ('localhost', '127.0.0.1'):
            raise serializers.ValidationError(
                {label: 'http:// is only allowed for localhost or 127.0.0.1; use https in production.'}
            )
    return ref, ret


class MasterStripeConnectOnboardingSerializer(serializers.Serializer):
    """Optional overrides; otherwise use Django settings."""

    return_url = serializers.URLField(required=False, allow_blank=True)
    refresh_url = serializers.URLField(required=False, allow_blank=True)


class MasterStripeConnectOnboardingView(APIView):
    """
    **GET** — ``stripe_connect_account_id`` + Stripe readiness (same shape as summary helpers).

    **POST** — create **Express** Connect account if missing, then return **onboarding URL** for the master
    to open in a browser / WebView (Stripe-hosted). After completion, payouts use this ``acct_`` automatically.
    """

    permission_classes = [IsAuthenticated, IsMasterGroup]

    @extend_schema(
        summary='Stripe Connect onboarding — status',
        tags=['Stripe — Master'],
        responses={200: {'type': 'object'}},
    )
    def get(self, request):
        master = request.user.master_profiles.first()
        if not master:
            return Response({'error': 'Master profile not found'}, status=status.HTTP_404_NOT_FOUND)
        acct = (master.stripe_connect_account_id or '').strip()
        if not acct:
            return Response(
                {
                    'stripe_connect_account_id': None,
                    'account': None,
                    'onboarding_complete': False,
                    'stripe_publishable_key': (getattr(settings, 'STRIPE_PUBLISHABLE_KEY', '') or '').strip(),
                }
            )
        try:
            summary = fetch_connect_account_public_summary(acct)
        except StripeConnectLinkError as e:
            return Response(
                {
                    'stripe_connect_account_id': acct,
                    'account': None,
                    'onboarding_complete': False,
                    'error': e.message,
                    'stripe_publishable_key': (getattr(settings, 'STRIPE_PUBLISHABLE_KEY', '') or '').strip(),
                },
                status=status.HTTP_200_OK,
            )
        complete = bool(summary.get('details_submitted')) and bool(summary.get('payouts_enabled'))
        return Response(
            {
                'stripe_connect_account_id': acct,
                'account': summary,
                'onboarding_complete': complete,
                'stripe_publishable_key': (getattr(settings, 'STRIPE_PUBLISHABLE_KEY', '') or '').strip(),
            }
        )

    @extend_schema(
        summary='Stripe Connect onboarding — start / resume (returns Stripe-hosted URL)',
        tags=['Stripe — Master'],
        request=MasterStripeConnectOnboardingSerializer,
        examples=[
            OpenApiExample(
                'With app deep links',
                value={
                    'return_url': 'https://app.example.com/master/stripe/onboarding/return',
                    'refresh_url': 'https://app.example.com/master/stripe/onboarding/refresh',
                },
                request_only=True,
            ),
        ],
        responses={200: {'type': 'object'}, 400: {'type': 'object'}, 503: {'type': 'object'}},
    )
    def post(self, request):
        if not (getattr(settings, 'STRIPE_SECRET_KEY', '') or '').strip():
            return Response(
                {'error': 'Stripe is not configured on the server.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        master = request.user.master_profiles.first()
        if not master:
            return Response({'error': 'Master profile not found'}, status=status.HTTP_404_NOT_FOUND)

        ser = MasterStripeConnectOnboardingSerializer(data=request.data or {})
        ser.is_valid(raise_exception=True)
        try:
            refresh_url, return_url = _resolve_onboarding_urls(ser.validated_data)
        except serializers.ValidationError as e:
            return Response(e.detail, status=status.HTTP_400_BAD_REQUEST)

        try:
            acct, created = ensure_express_connect_account_for_master(master)
            url = create_account_onboarding_url(account_id=acct, refresh_url=refresh_url, return_url=return_url)
        except StripeConnectLinkError as e:
            return Response({'error': e.message}, status=status.HTTP_400_BAD_REQUEST)

        pk = (getattr(settings, 'STRIPE_PUBLISHABLE_KEY', '') or '').strip()
        return Response(
            {
                'status': 'success',
                'data': {
                    'stripe_connect_account_id': acct,
                    'connect_account_created': created,
                    'onboarding_url': url,
                    'stripe_publishable_key': pk,
                },
            },
            status=status.HTTP_200_OK,
        )
