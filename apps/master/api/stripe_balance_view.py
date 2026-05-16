"""Master: Stripe Connect available / pending balance + recent payouts."""
from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.master.models import Master
from apps.master.permissions import IsMasterGroup
from apps.payment.services.connect_balance import StripeConnectBalanceError, fetch_connect_balance_and_payouts


class MasterStripeBalanceView(APIView):
    """
    Earnings from **card** orders (with Connect destination) land in the master's **Stripe Connect**
    balance — first *pending*, then *available*. Automatic bank payouts (e.g. weekly Monday) are
    configured in Stripe for that `acct_…`; this endpoint **reads** Stripe only.
    """

    permission_classes = [IsAuthenticated, IsMasterGroup]

    @extend_schema(
        summary='Stripe Connect balance & recent payouts',
        tags=['Stripe — Master'],
        responses={200: {'type': 'object'}},
    )
    def get(self, request):
        master = request.user.master_profiles.first()
        if not master:
            return Response({'error': 'Master profile not found'}, status=status.HTTP_404_NOT_FOUND)
        acct = (getattr(master, 'stripe_connect_account_id', None) or '').strip()
        if not acct:
            return Response(
                {
                    'error': 'Stripe Connect is not linked for this master.',
                    'hint': 'POST /api/master/stripe-connect/ with stripe_connect_account_id (acct_…) after Connect onboarding.',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            data = fetch_connect_balance_and_payouts(stripe_connect_account_id=acct)
        except StripeConnectBalanceError as e:
            return Response({'error': e.message}, status=status.HTTP_400_BAD_REQUEST)
        return Response(data)
