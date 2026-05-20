from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.order.models import Order, OrderPaymentType, OrderStatus
from apps.order.api.serializers import OrderSerializer
from apps.payment.api.serializers import SavedCardCreateSerializer, SavedCardDefaultSerializer, SavedCardSerializer
from apps.payment.models import SavedCard, SavedCardHolderRole
from apps.payment.services.checkout_fees import compute_marketplace_checkout
from apps.payment.services.stripe_cards import StripeCardError, detach_card, save_payment_method_for_user, set_default_card


def _saved_cards_forbidden_for_master(request):
    """Product flow: only drivers (clients) use saved cards; masters use Stripe Connect."""
    if request.user.groups.filter(name='Master').exists():
        return Response(
            {
                'error': 'Saved cards are for drivers (clients). Masters use direct deposit: '
                'POST /api/master/stripe-connect/bank-account/.',
            },
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


class SavedCardListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Stripe — Driver'],
        summary='List saved cards (driver / client role)',
        description='Returns cards for the **client** holder role. Masters do not use this flow for payouts (use Stripe — Master Connect).',
        responses={200: SavedCardSerializer(many=True), 403: {'type': 'object'}},
    )
    def get(self, request):
        denied = _saved_cards_forbidden_for_master(request)
        if denied is not None:
            return denied
        qs = (
            SavedCard.objects.filter(user=request.user, is_active=True, holder_role=SavedCardHolderRole.CLIENT)
            .order_by('-is_default', '-id')
        )
        return Response(SavedCardSerializer(qs, many=True).data)

    @extend_schema(
        tags=['Stripe — Driver'],
        summary='Add saved card (driver / client role)',
        description='**Client** PaymentMethod. Not part of master Connect onboarding.',
        request=SavedCardCreateSerializer,
        responses={201: SavedCardSerializer, 403: {'type': 'object'}},
    )
    def post(self, request):
        denied = _saved_cards_forbidden_for_master(request)
        if denied is not None:
            return denied
        ser = SavedCardCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            sc = save_payment_method_for_user(
                user=request.user,
                payment_method_id=ser.validated_data['payment_method_id'],
                stripe_customer_id=ser.validated_data.get('stripe_customer_id') or None,
            )
        except StripeCardError as e:
            return Response({'error': e.message}, status=status.HTTP_400_BAD_REQUEST)
        return Response(SavedCardSerializer(sc).data, status=status.HTTP_201_CREATED)


class SavedCardDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Stripe — Driver'],
        summary='Set default saved card',
        description='**Client** cards only for this product flow.',
        request=SavedCardDefaultSerializer,
        responses={200: SavedCardSerializer, 403: {'type': 'object'}},
    )
    def put(self, request, pk):
        denied = _saved_cards_forbidden_for_master(request)
        if denied is not None:
            return denied
        if not request.data.get('is_default'):
            return Response({'error': 'Only is_default: true is supported'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            sc = set_default_card(request.user, int(pk))
        except SavedCard.DoesNotExist:
            return Response({'error': 'Card not found'}, status=status.HTTP_404_NOT_FOUND)
        return Response(SavedCardSerializer(sc).data)

    @extend_schema(
        tags=['Stripe — Driver'],
        summary='Remove saved card',
        responses={204: None, 403: {'type': 'object'}},
    )
    def delete(self, request, pk):
        denied = _saved_cards_forbidden_for_master(request)
        if denied is not None:
            return denied
        try:
            detach_card(request.user, int(pk))
        except SavedCard.DoesNotExist:
            return Response({'error': 'Card not found'}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class OrderPaymentCardPatchView(APIView):
    """Order owner: attach a saved client card (required before complete; all orders are card-paid)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Stripe — Driver'],
        request={'application/json': {'type': 'object', 'required': ['card_id'], 'properties': {'card_id': {'type': 'integer'}}}},
        responses={200: OrderSerializer},
    )
    def patch(self, request, order_id):
        try:
            oid = int(order_id)
        except (TypeError, ValueError):
            return Response({'error': 'Invalid order_id'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            order = Order.objects.get(pk=oid)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)
        if order.user_id != request.user.id:
            return Response({'detail': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
        if order.status in (OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.REJECTED):
            return Response({'error': 'Cannot change payment on finished orders'}, status=status.HTTP_400_BAD_REQUEST)
        card_id = request.data.get('card_id')
        try:
            cid = int(card_id)
        except (TypeError, ValueError):
            return Response({'error': 'card_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            card = SavedCard.objects.get(pk=cid, user=request.user, is_active=True, holder_role=SavedCardHolderRole.CLIENT)
        except SavedCard.DoesNotExist:
            return Response({'error': 'Card not found or not a client card'}, status=status.HTTP_404_NOT_FOUND)
        order.saved_card = card
        order.payment_type = OrderPaymentType.CARD
        order.save(update_fields=['saved_card', 'payment_type', 'updated_at'])
        return Response(OrderSerializer(order, context={'request': request}).data)


class OrderCheckoutPreviewView(APIView):
    """Optional: preview customer total / master payout for an order (owner or assigned master)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=['Stripe — Driver', 'Stripe — Master'])
    def get(self, request, order_id):
        try:
            order = Order.objects.get(pk=int(order_id))
        except (TypeError, ValueError, Order.DoesNotExist):
            return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)
        master = request.user.master_profiles.first()
        allowed = order.user_id == request.user.id or (master and order.master_id == master.id)
        if not allowed:
            return Response({'detail': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
        return Response({'checkout': compute_marketplace_checkout(order)})
