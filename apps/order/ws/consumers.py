import asyncio
import json
import logging
import time

from channels.db import database_sync_to_async
from django.core.serializers.json import DjangoJSONEncoder
from channels.generic.websocket import AsyncWebsocketConsumer

# Throttle DB sweeps when many masters hold SOS WS open (one effective sweep per interval per process).
_LAST_STALE_OFFER_SWEEP_MONO = 0.0

logger = logging.getLogger(__name__)


@database_sync_to_async
def _expire_stale_master_offers_sync():
    from apps.order.services.offer_expiry import expire_stale_master_offers

    return expire_stale_master_offers()


async def _throttled_stale_offer_sweep():
    """Calls expire_stale_master_offers if SOS_WEBSOCKET_STALE_SWEEP_SEC > 0 and interval elapsed."""
    global _LAST_STALE_OFFER_SWEEP_MONO

    from django.conf import settings

    interval = int(getattr(settings, 'SOS_WEBSOCKET_STALE_SWEEP_SEC', 0) or 0)
    if interval <= 0:
        return
    now = time.monotonic()
    if now - _LAST_STALE_OFFER_SWEEP_MONO < interval:
        return
    _LAST_STALE_OFFER_SWEEP_MONO = now
    await _expire_stale_master_offers_sync()


class MasterSosConsumer(AsyncWebsocketConsumer):
    """
    Masters subscribe for real-time SOS offers.
    ws/wss://host/ws/sos/master/?token=<JWT>

    If Celery countdown tasks fail (common on Windows prefork), settings
    SOS_WEBSOCKET_STALE_SWEEP_SEC runs expire_stale_master_offers on a throttled
    timer while the connection stays open so the SOS ring can advance.
    """

    async def connect(self):
        user = self.scope.get('user')
        if not user or not user.is_authenticated:
            logger.warning(
                'WS /ws/sos/master/CLOSE 4001: token yo‘q, yaroqsiz yoki muddati o‘tgan JWT '
                '(query: ?token=<access>), yoki foydalanuvchi aniqlanmadi'
            )
            await self.close(code=4001)
            return
        if not await self._user_in_master_role_group(user.id):
            logger.warning(
                'WS /ws/sos/master/CLOSE 4003: user_id=%s — Django guruhida “Master” yo‘q '
                '(SMS/check-sms da role=Master bo‘lishi kerak). Driver akkaunti ulanmaydi.',
                getattr(user, 'id', None),
            )
            await self.close(code=4003)
            return
        self.group_name = f'master_sos_{user.id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send(
            text_data=json.dumps(
                {'type': 'connected', 'channel': 'sos_incoming_orders'},
            )
        )
        from django.conf import settings

        if int(getattr(settings, 'SOS_WEBSOCKET_STALE_SWEEP_SEC', 0) or 0) > 0:
            self._stale_sweep_task = asyncio.create_task(self._stale_sweep_loop())
        else:
            self._stale_sweep_task = None

    async def disconnect(self, close_code):
        t = getattr(self, '_stale_sweep_task', None)
        if t:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        try:
            data = json.loads(text_data)
            if data.get('type') == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))
        except json.JSONDecodeError:
            pass

    async def sos_order_push(self, event):
        await self.send(
            text_data=json.dumps(
                {'type': 'sos_order_offer', 'data': event['payload']},
            )
        )

    async def custom_request_push(self, event):
        await self.send(
            text_data=json.dumps(
                {'type': 'custom_request_job', 'data': event['payload']},
            )
        )

    async def _stale_sweep_loop(self):
        """Wake periodically; throttled sweep advances SOS ring when master_response_deadline passed."""
        from django.conf import settings

        interval = max(int(getattr(settings, 'SOS_WEBSOCKET_STALE_SWEEP_SEC', 8) or 8), 2)
        tick = min(5, interval)
        try:
            while True:
                await asyncio.sleep(tick)
                await _throttled_stale_offer_sweep()
        except asyncio.CancelledError:
            return

    @database_sync_to_async
    def _user_in_master_role_group(self, user_id: int) -> bool:
        """
        Same notion of “master” as HTTP: user must be in Django group ``Master``.
        A ``Master`` workshop row may be created later via POST /api/master/masters/;
        geo broadcasts still only hit users who have coordinates on that row.
        """
        from django.contrib.auth import get_user_model

        return (
            get_user_model()
            .objects.filter(pk=user_id, groups__name='Master')
            .exists()
        )


class RiderCustomRequestConsumer(AsyncWebsocketConsumer):
    """
    Drivers subscribe for real-time price offers on custom-request orders.
    ws/wss://host/ws/custom-request/rider/?token=<JWT>
    """

    async def connect(self):
        user = self.scope.get('user')
        if not user or not user.is_authenticated:
            await self.close(code=4001)
            return
        self.group_name = f'rider_custom_request_{user.id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send(
            text_data=json.dumps(
                {'type': 'connected', 'channel': 'custom_request_offers'},
            )
        )

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        try:
            data = json.loads(text_data)
            if data.get('type') == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))
        except json.JSONDecodeError:
            pass

    async def rider_custom_request_offer(self, event):
        await self.send(
            text_data=json.dumps(
                {'type': 'custom_request_offer', 'data': event['payload']},
                cls=DjangoJSONEncoder,
            )
        )
