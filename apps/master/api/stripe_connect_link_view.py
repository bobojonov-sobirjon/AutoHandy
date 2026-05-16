"""Master: link Stripe Connect account (acct_…) used as PaymentIntent destination."""
from __future__ import annotations

from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.master.models import Master
from apps.master.permissions import IsMasterGroup
from apps.payment.services.stripe_connect_link import StripeConnectLinkError, fetch_connect_account_public_summary


class MasterStripeConnectAccountLinkSerializer(serializers.Serializer):
    stripe_connect_account_id = serializers.CharField(
        max_length=64,
        min_length=6,
        help_text='Stripe Connect account id from Dashboard or onboarding (acct_…).',
    )


class MasterStripeConnectLinkView(APIView):
    """
    Link the logged-in master's profile to a Stripe Connect account.
    Card order charges use ``transfer_data.destination`` to this ``acct_`` when set on ``Order.master``.
    """

    permission_classes = [IsAuthenticated, IsMasterGroup]

    @extend_schema(
        summary='Stripe Connect — current link status',
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
                    'linked': False,
                    'stripe_connect_account_id': None,
                    'account': None,
                }
            )
        try:
            summary = fetch_connect_account_public_summary(acct)
        except StripeConnectLinkError as e:
            return Response(
                {
                    'linked': True,
                    'stripe_connect_account_id': acct,
                    'load_error': True,
                    'error': e.message,
                },
                status=status.HTTP_200_OK,
            )
        return Response(
            {
                'linked': True,
                'stripe_connect_account_id': acct,
                'account': summary,
            }
        )

    @extend_schema(
        summary='Stripe Connect — link acct_… to this master',
        tags=['Stripe — Master'],
        request=MasterStripeConnectAccountLinkSerializer,
        examples=[
            OpenApiExample(
                'Link account',
                value={'stripe_connect_account_id': 'acct_1AbCdEfGhIjKlMn'},
                request_only=True,
            ),
        ],
        responses={
            200: {'type': 'object'},
            400: {'type': 'object'},
            409: {'type': 'object'},
        },
    )
    def post(self, request):
        master = request.user.master_profiles.first()
        if not master:
            return Response({'error': 'Master profile not found'}, status=status.HTTP_404_NOT_FOUND)

        ser = MasterStripeConnectAccountLinkSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        raw = ser.validated_data['stripe_connect_account_id'].strip()

        try:
            summary = fetch_connect_account_public_summary(raw)
        except StripeConnectLinkError as e:
            return Response({'error': e.message}, status=status.HTTP_400_BAD_REQUEST)

        acct = summary['id']
        taken = (
            Master.objects.filter(stripe_connect_account_id=acct)
            .exclude(pk=master.pk)
            .exists()
        )
        if taken:
            return Response(
                {'error': 'This Connect account is already linked to another master profile.'},
                status=status.HTTP_409_CONFLICT,
            )

        master.stripe_connect_account_id = acct
        master.save(update_fields=['stripe_connect_account_id', 'updated_at'])

        return Response(
            {
                'linked': True,
                'stripe_connect_account_id': acct,
                'account': summary,
                'message': 'Stripe Connect account linked. Card order payouts will use this acct as destination.',
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary='Stripe Connect — unlink (clear acct from profile)',
        tags=['Stripe — Master'],
        responses={200: {'type': 'object'}},
    )
    def delete(self, request):
        master = request.user.master_profiles.first()
        if not master:
            return Response({'error': 'Master profile not found'}, status=status.HTTP_404_NOT_FOUND)
        if not (master.stripe_connect_account_id or '').strip():
            return Response({'linked': False, 'message': 'Nothing to unlink.'}, status=status.HTTP_200_OK)
        master.stripe_connect_account_id = ''
        master.save(update_fields=['stripe_connect_account_id', 'updated_at'])
        return Response(
            {
                'linked': False,
                'stripe_connect_account_id': None,
                'message': 'Stripe Connect account unlinked from this master profile.',
            },
            status=status.HTTP_200_OK,
        )
