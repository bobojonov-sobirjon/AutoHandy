"""Master: completed order payments + Stripe Connect balance transaction ledger."""
from __future__ import annotations

from django.core.paginator import EmptyPage, Paginator
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.master.models import Master
from apps.master.permissions import IsMasterGroup
from apps.order.models import Order, OrderStatus
from apps.payment.services.connect_balance import list_connect_balance_transactions


class MasterCheckoutHistoryView(APIView):
    """
    Paginated **completed** orders for this master (card charges from our DB) plus a slice of
    **Stripe BalanceTransaction** lines for the connected account (full money ledger on Stripe).
    """

    permission_classes = [IsAuthenticated, IsMasterGroup]

    @extend_schema(
        summary='Checkout / payment history (orders + Stripe ledger)',
        tags=['Stripe — Master'],
        parameters=[
            OpenApiParameter(name='page', type=int, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name='page_size', type=int, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(
                name='stripe_tx_limit',
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description='BalanceTransaction rows (1–100, default 30)',
            ),
            OpenApiParameter(
                name='stripe_starting_after',
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Stripe BalanceTransaction id for pagination (txn_…)',
            ),
        ],
        responses={200: {'type': 'object'}},
    )
    def get(self, request):
        master = request.user.master_profiles.first()
        if not master:
            return Response({'error': 'Master profile not found'}, status=status.HTTP_404_NOT_FOUND)

        try:
            page = max(1, int(request.query_params.get('page', 1)))
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = int(request.query_params.get('page_size', 20))
        except (TypeError, ValueError):
            page_size = 20
        page_size = max(1, min(page_size, 100))

        try:
            tx_limit = int(request.query_params.get('stripe_tx_limit', 30))
        except (TypeError, ValueError):
            tx_limit = 30
        tx_limit = max(1, min(tx_limit, 100))
        stripe_after = (request.query_params.get('stripe_starting_after') or '').strip() or None

        acct = (getattr(master, 'stripe_connect_account_id', '') or '').strip()

        qs = (
            Order.objects.filter(master=master, status=OrderStatus.COMPLETED)
            .order_by('-updated_at')
            .only(
                'id',
                'order_number',
                'stripe_payment_intent_id',
                'stripe_payment_status',
                'stripe_payment_amount_cents',
                'stripe_payment_currency',
                'stripe_payment_error',
                'updated_at',
            )
        )
        paginator = Paginator(qs, page_size)
        if paginator.count == 0:
            p_obj_list = []
            page_num = 1
            total_pages = 0
        else:
            try:
                p = paginator.page(page)
            except EmptyPage:
                p = paginator.page(paginator.num_pages)
            p_obj_list = list(p.object_list)
            page_num = p.number
            total_pages = paginator.num_pages

        order_rows = []
        for o in p_obj_list:
            order_rows.append(
                {
                    'order_id': o.id,
                    'order_number': o.order_number,
                    'stripe_payment_intent_id': o.stripe_payment_intent_id or None,
                    'stripe_payment_status': o.stripe_payment_status,
                    'stripe_payment_amount_cents': o.stripe_payment_amount_cents,
                    'stripe_payment_currency': (o.stripe_payment_currency or '').upper() or None,
                    'stripe_payment_error': (o.stripe_payment_error or '')[:500] or None,
                    'completed_at': o.updated_at.isoformat() if o.updated_at else None,
                }
            )

        stripe_tx: list = []
        stripe_tx_has_more = False
        stripe_tx_next: str | None = None
        if acct:
            stripe_tx, stripe_tx_has_more, stripe_tx_next = list_connect_balance_transactions(
                acct,
                limit=tx_limit,
                starting_after=stripe_after,
            )

        return Response(
            {
                'stripe_connect_account_id': acct or None,
                'orders': {
                    'count': paginator.count,
                    'page': page_num,
                    'page_size': page_size,
                    'total_pages': total_pages,
                    'results': order_rows,
                },
                'stripe_balance_transactions': {
                    'results': stripe_tx,
                    'has_more': stripe_tx_has_more,
                    'starting_after_next': stripe_tx_next,
                },
            }
        )
