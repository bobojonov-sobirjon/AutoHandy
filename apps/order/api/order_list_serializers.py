"""Lean serializers for order list endpoints (by-user / by-master / GET /api/order/)."""
from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.accounts.display_name import customer_display_name, public_person_display_name
from apps.order.models import Order, OrderStatus, OrderStripePaymentStatus, OrderType
from apps.order.services.order_pricing import get_cached_order_pricing
from apps.order.services.status_workflow import order_master_distance_mi
from config.wgs84 import WGS84_COORD_DECIMAL_KWARGS


def _money(v) -> str:
    return format(Decimal(str(v if v is not None else 0)), 'f')


def _avatar_url(request, user) -> str | None:
    avatar = getattr(user, 'avatar', None)
    if not avatar:
        return None
    try:
        url = avatar.url
    except ValueError:
        return None
    if request is not None:
        try:
            from apps.categories.media_urls import absolute_media_path

            return absolute_media_path(request, url)
        except Exception:
            return request.build_absolute_uri(url) if hasattr(request, 'build_absolute_uri') else url
    return url


class OrderListSerializer(serializers.ModelSerializer):
    """
    Fast list card payload — avoids nested MasterSerializer / UserDetailsSerializer.
    Detail endpoint keeps full OrderSerializer.
    """

    status_display = serializers.CharField(source='get_status_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)
    order_type_display = serializers.CharField(source='get_order_type_display', read_only=True)
    user = serializers.SerializerMethodField()
    master = serializers.SerializerMethodField()
    car_data = serializers.SerializerMethodField()
    category_data = serializers.SerializerMethodField()
    pricing = serializers.SerializerMethodField()
    tip = serializers.SerializerMethodField()
    post_completion = serializers.SerializerMethodField()
    timestamps = serializers.SerializerMethodField()
    towing = serializers.SerializerMethodField()
    truck = serializers.SerializerMethodField()
    chat_room_id = serializers.IntegerField(read_only=True)
    latitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS, required=False, allow_null=True)
    longitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS, required=False, allow_null=True)

    class Meta:
        model = Order
        fields = [
            'id',
            'order_number',
            'order_type',
            'order_type_display',
            'status',
            'status_display',
            'priority',
            'priority_display',
            'text',
            'location',
            'latitude',
            'longitude',
            'preferred_date',
            'preferred_time_start',
            'preferred_time_end',
            'user',
            'master',
            'car_data',
            'category_data',
            'pricing',
            'tip',
            'post_completion',
            'timestamps',
            'towing',
            'truck',
            'fuel_delivery_type',
            'chat_room_id',
            'payment_type',
        ]

    def _master_card_cache(self) -> dict:
        return self.context.setdefault('_list_master_card_by_id', {})

    def get_user(self, obj):
        u = obj.user
        if not u:
            return None
        request = self.context.get('request')
        viewer = getattr(request, 'user', None) if request is not None else None
        # Master viewing customer → mask surname; owner viewing self → full name OK.
        if viewer and getattr(viewer, 'is_authenticated', False) and viewer.id == u.id:
            full_name = u.get_full_name() or u.email or ''
            last_name = u.last_name or ''
        else:
            full_name = public_person_display_name(u)
            last = (u.last_name or '').strip()
            last_name = last[0].upper() if last else ''
        return {
            'id': u.id,
            'first_name': (u.first_name or '').strip(),
            'last_name': last_name,
            'full_name': full_name,
            'avatar': _avatar_url(request, u),
        }

    def get_master(self, obj):
        if not obj.master_id or not obj.master:
            return None
        cache = self._master_card_cache()
        mid = obj.master_id
        if mid in cache:
            card = dict(cache[mid])
        else:
            m = obj.master
            mu = m.user
            request = self.context.get('request')
            viewer = getattr(request, 'user', None) if request is not None else None
            # Privacy: other party sees "Anton K"; master sees own full name.
            if viewer and getattr(viewer, 'is_authenticated', False) and viewer.id == mu.id:
                full_name = mu.get_full_name() or mu.email or ''
            else:
                full_name = customer_display_name(
                    mu.first_name,
                    mu.last_name,
                    fallback=(mu.email or ''),
                )
            card = {
                'id': m.id,
                'user': {
                    'id': mu.id,
                    'first_name': (mu.first_name or '').strip(),
                    'full_name': full_name,
                    'avatar': _avatar_url(request, mu),
                },
                'completed_orders_count': int(getattr(m, 'completed_orders_count', 0) or 0),
            }
            cache[mid] = card
            card = dict(card)

        dist_mi = order_master_distance_mi(obj)
        if dist_mi is not None:
            card['distance'] = float(dist_mi)
        return card

    def get_car_data(self, obj):
        cars = list(obj.car.all())
        return [
            {
                'id': c.id,
                'brand': c.brand,
                'model': c.model,
                'year': c.year,
                'category': c.category.name if getattr(c, 'category', None) else None,
            }
            for c in cars
        ]

    def get_category_data(self, obj):
        """Flat list of category names for list cards (not full parent/items tree)."""
        cats = list(obj.category.all())
        out = []
        for c in cats:
            parent = getattr(c, 'parent', None)
            out.append(
                {
                    'id': c.id,
                    'name': c.name,
                    'parent_id': parent.id if parent else None,
                    'parent_name': parent.name if parent else None,
                }
            )
        return out

    def get_pricing(self, obj):
        br = get_cached_order_pricing(obj, self.context)
        return {
            'total': _money(br.get('total')),
            'work_total': _money(br.get('work_total', br.get('total'))),
            'subtotal': _money(br.get('subtotal')),
            'discount_applied': _money(br.get('discount_applied')),
            'penalty_total': _money(br.get('penalty_total', 0)),
            'extra_money': _money(br.get('extra_money', 0)),
            'car_count': int(br.get('car_count') or 1),
        }

    def get_tip(self, obj):
        tip = getattr(obj, 'tip_amount', None)
        if tip is None:
            return None
        tip_d = Decimal(str(tip))
        if tip_d <= 0:
            if getattr(obj, 'tip_declined', False):
                return {'declined': True, 'amount': '0.00', 'includes_tip': False}
            return None
        return {
            'amount': _money(tip_d),
            'includes_tip': True,
            'declined': False,
        }

    def get_post_completion(self, obj):
        """Lightweight flags only — no tip-preset fee math."""
        request = self.context.get('request')
        if not request or not getattr(request.user, 'is_authenticated', False):
            return None
        if obj.user_id != request.user.id:
            return None
        if obj.status != OrderStatus.COMPLETED:
            return None
        has_review = False
        try:
            has_review = obj.review is not None
        except Exception:
            has_review = False
        tip_paid = bool(
            getattr(obj, 'tip_stripe_payment_status', None) == OrderStripePaymentStatus.SUCCEEDED
        )
        tip_declined = bool(getattr(obj, 'tip_declined', False))
        return {
            'needs_review': not has_review,
            'needs_tip_prompt': (not tip_paid) and (not tip_declined),
            'has_review': has_review,
            'tip_paid': tip_paid,
            'tip_declined': tip_declined,
        }

    def get_timestamps(self, obj):
        return {
            'created_at': obj.created_at,
            'updated_at': obj.updated_at,
            'accepted_at': obj.accepted_at,
        }

    def get_towing(self, obj):
        if obj.order_type != OrderType.TOWING:
            return None
        return {
            'distance_miles': (
                _money(obj.towing_distance_miles) if obj.towing_distance_miles is not None else None
            ),
            'total_price': _money(obj.towing_total) if obj.towing_total is not None else None,
        }

    def get_truck(self, obj):
        from apps.order.services.truck_orders import truck_payload_from_order

        return truck_payload_from_order(obj)
