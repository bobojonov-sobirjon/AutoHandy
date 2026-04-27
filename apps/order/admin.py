from django.contrib import admin
from django import forms
from django.db.models import Count
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe

import json

from .models import (
    CustomRequestOffer,
    CustomRequestOrder,
    MasterOrderCancellation,
    Order,
    OrderImage,
    OrderService,
    OrderStatus,
    OrderType,
    OrderWorkCompletionImage,
    OrderPriority,
    Rating,
    Review,
    StandardOrder,
    SOSOrder,
    UserRating,
)


class PartsPurchaseRequiredJsonWidget(forms.Widget):
    """
    Admin UI for Order.parts_purchase_required_json.
    Renders a small table editor and stores value as JSON in a hidden textarea.
    """

    def render(self, name, value, attrs=None, renderer=None):
        attrs = attrs or {}
        wid = attrs.get('id') or f'id_{name}'

        raw = value
        if raw in (None, ''):
            items = []
        elif isinstance(raw, str):
            try:
                items = json.loads(raw)
            except Exception:
                items = []
        else:
            items = raw

        if not isinstance(items, list):
            items = []

        canonical: list[dict] = []
        for x in items:
            if not isinstance(x, dict):
                continue
            canonical.append(
                {
                    'vehicle_vin': (x.get('vehicle_vin') or x.get('vehicle vin') or '').strip(),
                    'part_name': (x.get('part_name') or x.get('part name') or '').strip(),
                    'is_address': bool(x.get('is_address', x.get('is_addess', False))),
                }
            )

        safe_json = json.dumps(canonical, ensure_ascii=False)
        html = f"""
<div class="parts-json-editor" data-field-id="{wid}">
  <textarea id="{wid}" name="{name}" style="display:none;">{safe_json}</textarea>
  <div style="margin: 4px 0 10px 0; display:flex; gap:10px; align-items:center;">
    <button type="button" class="button" data-action="add">Add part</button>
    <span style="color:#666; font-size:12px;">Rows are saved as JSON (hidden).</span>
  </div>
  <div style="overflow:auto;">
    <table class="parts-json-table" style="border-collapse:collapse; width:100%; min-width:720px;">
      <thead>
        <tr>
          <th style="text-align:left; padding:6px; border-bottom:1px solid #ddd;">Vehicle VIN</th>
          <th style="text-align:left; padding:6px; border-bottom:1px solid #ddd;">Part name</th>
          <th style="text-align:left; padding:6px; border-bottom:1px solid #ddd;">Knows where to buy (is_address)</th>
          <th style="padding:6px; border-bottom:1px solid #ddd;">&nbsp;</th>
        </tr>
      </thead>
      <tbody data-role="rows"></tbody>
    </table>
  </div>
</div>
<script>
(function() {{
  const root = document.querySelector('.parts-json-editor[data-field-id="{wid}"]');
  if (!root) return;
  const textarea = root.querySelector('textarea#{wid}');
  const tbody = root.querySelector('tbody[data-role="rows"]');
  const addBtn = root.querySelector('button[data-action="add"]');

  function parseValue() {{
    try {{
      const v = (textarea.value || '[]').trim();
      const parsed = JSON.parse(v || '[]');
      return Array.isArray(parsed) ? parsed : [];
    }} catch (e) {{
      return [];
    }}
  }}

  function serialize() {{
    const rows = Array.from(tbody.querySelectorAll('tr[data-row="1"]'));
    const out = rows.map(tr => {{
      const vin = (tr.querySelector('input[data-k="vehicle_vin"]').value || '').trim();
      const name = (tr.querySelector('input[data-k="part_name"]').value || '').trim();
      const isAddr = !!tr.querySelector('input[data-k="is_address"]').checked;
      return {{ vehicle_vin: vin, part_name: name, is_address: isAddr }};
    }});
    textarea.value = JSON.stringify(out);
  }}

  function escapeAttr(s) {{
    return String(s || '').replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
  }}

  function mkRow(item) {{
    const vin = (item && (item.vehicle_vin || item['vehicle vin'])) ? String(item.vehicle_vin || item['vehicle vin']) : '';
    const pn = (item && (item.part_name || item['part name'])) ? String(item.part_name || item['part name']) : '';
    const ia = !!(item && (item.is_address ?? item.is_addess));
    const tr = document.createElement('tr');
    tr.setAttribute('data-row', '1');
    tr.innerHTML = `
      <td style="padding:6px; border-bottom:1px solid #eee;">
        <input type="text" data-k="vehicle_vin" maxlength="17" style="width: 98%;" value="${{escapeAttr(vin)}}">
      </td>
      <td style="padding:6px; border-bottom:1px solid #eee;">
        <input type="text" data-k="part_name" maxlength="100" style="width: 98%;" value="${{escapeAttr(pn)}}">
      </td>
      <td style="padding:6px; border-bottom:1px solid #eee;">
        <label style="display:flex; gap:8px; align-items:center;">
          <input type="checkbox" data-k="is_address" ${{ia ? 'checked' : ''}}>
          <span style="color:#444;">Yes</span>
        </label>
      </td>
      <td style="padding:6px; border-bottom:1px solid #eee; text-align:right;">
        <button type="button" class="button" data-action="del">Remove</button>
      </td>
    `;
    tr.addEventListener('input', serialize, true);
    tr.addEventListener('change', serialize, true);
    tr.querySelector('button[data-action="del"]').addEventListener('click', function() {{
      tr.remove();
      serialize();
    }});
    return tr;
  }}

  function renderAll() {{
    tbody.innerHTML = '';
    const items = parseValue();
    if (!items.length) {{
      tbody.appendChild(mkRow({{ vehicle_vin: '', part_name: '', is_address: false }}));
    }} else {{
      items.forEach(it => tbody.appendChild(mkRow(it)));
    }}
    serialize();
  }}

  addBtn.addEventListener('click', function() {{
    tbody.appendChild(mkRow({{ vehicle_vin: '', part_name: '', is_address: false }}));
    serialize();
  }});

  renderAll();
}})();
</script>
"""
        return mark_safe(html)


class OrderAdminForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = '__all__'
        widgets = {
            'parts_purchase_required_json': PartsPurchaseRequiredJsonWidget(),
        }


class OrderImageInline(admin.TabularInline):
    model = OrderImage
    extra = 0
    readonly_fields = ['created_at']


class OrderWorkCompletionImageInline(admin.TabularInline):
    model = OrderWorkCompletionImage
    extra = 0
    readonly_fields = ['created_at']


class OrderServiceInline(admin.TabularInline):
    model = OrderService
    extra = 0
    raw_id_fields = ['master_service_item']
    readonly_fields = ['created_at']


class CustomRequestOfferInline(admin.TabularInline):
    """Price offers from masters on a custom-request order (only on Custom request orders admin)."""

    model = CustomRequestOffer
    extra = 0
    raw_id_fields = ['master']
    fields = ['master', 'price', 'created_at', 'updated_at']
    readonly_fields = ['created_at', 'updated_at']


class BaseOrderAdmin(admin.ModelAdmin):
    form = OrderAdminForm
    list_per_page = 25
    list_max_show_all = 200
    save_on_top = True
    filter_horizontal = ('car', 'category')
    search_fields = [
        'id',
        'text',
        'location',
        'user__first_name',
        'user__last_name',
        'user__email',
        'user__phone_number',
        'master__user__first_name',
        'master__user__last_name',
        'master__user__email',
    ]
    readonly_fields = [
        'id',
        'order_number',
        'created_at',
        'updated_at',
        'user_link',
        'master_link',
    ]
    inlines = [OrderImageInline, OrderWorkCompletionImageInline, OrderServiceInline]

    def user_link(self, obj):
        if not obj.user_id:
            return '—'
        url = reverse('admin:accounts_customuser_change', args=[obj.user_id])
        label = obj.user.get_full_name() or obj.user.email or obj.user.phone_number or obj.user_id
        return format_html('<a href="{}">{}</a>', url, label)

    user_link.short_description = 'User'
    user_link.admin_order_field = 'user__first_name'

    def master_link(self, obj):
        if not obj.master_id:
            return '—'
        url = reverse('admin:master_master_change', args=[obj.master_id])
        return format_html('<a href="{}">{}</a>', url, obj.master)

    master_link.short_description = 'Master'
    master_link.admin_order_field = 'master__user__first_name'

    def assigned_master(self, obj):
        """Who accepted / is assigned on this order (`order.master` FK)."""
        if not obj.master_id:
            return format_html(
                '<span style="color:#888;" title="No master yet — pending / open">{}</span>',
                '— pending',
            )
        m = obj.master
        url = reverse('admin:master_master_change', args=[m.pk])
        u = m.user
        name = (u.get_full_name() or u.email or u.phone_number or str(u.pk)).strip()
        return format_html(
            '<a href="{}" title="Master ID {}">{}</a>',
            url,
            m.pk,
            name,
        )

    assigned_master.short_description = 'Assigned master'
    assigned_master.admin_order_field = 'master__user__first_name'

    def status_badge(self, obj):
        colors = {
            OrderStatus.PENDING: '#ffc107',
            OrderStatus.ACCEPTED: '#0d6efd',
            OrderStatus.ON_THE_WAY: '#6610f2',
            OrderStatus.ARRIVED: '#6f42c1',
            OrderStatus.IN_PROGRESS: '#17a2b8',
            OrderStatus.COMPLETED: '#28a745',
            OrderStatus.CANCELLED: '#6c757d',
            OrderStatus.REJECTED: '#dc3545',
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background-color:{};color:#fff;padding:3px 8px;border-radius:3px;font-size:11px;">{}</span>',
            color,
            obj.get_status_display(),
        )

    status_badge.short_description = 'Status'
    status_badge.admin_order_field = 'status'

    def priority_badge(self, obj):
        colors = {
            OrderPriority.LOW: '#28a745',
            OrderPriority.HIGH: '#dc3545',
        }
        color = colors.get(obj.priority, '#6c757d')
        return format_html(
            '<span style="background-color:{};color:#fff;padding:3px 8px;border-radius:3px;font-size:11px;">{}</span>',
            color,
            obj.get_priority_display(),
        )

    priority_badge.short_description = 'Priority'
    priority_badge.admin_order_field = 'priority'

    def location_short(self, obj):
        if not obj.location:
            return '—'
        t = (obj.location or '').strip()
        return (t[:60] + '…') if len(t) > 60 else t

    location_short.short_description = 'Location'

    def coords_link(self, obj):
        if obj.latitude is None or obj.longitude is None:
            return '—'
        lat, lon = float(obj.latitude), float(obj.longitude)
        return format_html(
            '<a href="https://www.google.com/maps?q={},{}" target="_blank" rel="noopener">{}, {}</a>',
            lat,
            lon,
            round(lat, 5),
            round(lon, 5),
        )

    coords_link.short_description = 'Map'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'master', 'master__user')

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_readonly_fields(self, request, obj=None):
        ro = list(self.readonly_fields)
        if not request.user.is_superuser:
            ro.extend(['user', 'master'])
        return ro


@admin.register(Order)
class OrderAdmin(BaseOrderAdmin):
    date_hierarchy = 'created_at'
    list_display = [
        'order_number',
        'order_type',
        'user_link',
        'assigned_master',
        'status_badge',
        'priority_badge',
        'location_short',
        'coords_link',
        'created_at',
    ]
    list_filter = [
        'status',
        'priority',
        'order_type',
        'location_source',
        'parts_purchase_required',
        ('created_at', admin.DateFieldListFilter),
    ]
    fieldsets = (
        (
            'Main',
            {
                'fields': (
                    'id',
                    'order_number',
                    'order_type',
                    'user',
                    'master',
                    'text',
                    'status',
                    'priority',
                    'discount',
                )
            },
        ),
        (
            'Location',
            {
                'fields': (
                    'location',
                    'location_source',
                    'latitude',
                    'longitude',
                    'preferred_date',
                    'preferred_time_start',
                    'preferred_time_end',
                )
            },
        ),
        (
            'SOS queue',
            {
                'fields': (
                    'sos_offer_queue',
                    'sos_offer_index',
                    'master_response_deadline',
                ),
                'classes': ('collapse',),
            },
        ),
        (
            'Workflow & deadlines',
            {
                'fields': (
                    'accepted_at',
                    'on_the_way_at',
                    'estimated_arrival_at',
                    'eta_minutes',
                    'arrived_at',
                    'work_started_at',
                    'expiration_time',
                    'client_penalty_free_cancel_unlocked',
                ),
                'classes': ('collapse',),
            },
        ),
        (
            'Other',
            {
                'fields': ('parts_purchase_required', 'parts_purchase_required_json', 'car', 'category'),
            },
        ),
        (
            'Timestamps',
            {
                'fields': ('created_at', 'updated_at'),
                'classes': ('collapse',),
            },
        ),
    )


@admin.register(StandardOrder)
class StandardOrderAdmin(BaseOrderAdmin):
    list_display = [
        'order_number',
        'user_link',
        'assigned_master',
        'location_short',
        'status_badge',
        'priority_badge',
        'created_at',
    ]
    list_filter = [
        'status',
        'priority',
        ('created_at', admin.DateFieldListFilter),
    ]
    date_hierarchy = 'created_at'

    fieldsets = (
        (
            'Main',
            {
                'fields': (
                    'id',
                    'order_number',
                    'order_type',
                    'user',
                    'master',
                    'text',
                    'status',
                    'priority',
                    'discount',
                )
            },
        ),
        (
            'Location',
            {
                'fields': (
                    'location',
                    'location_source',
                    'latitude',
                    'longitude',
                    'preferred_date',
                    'preferred_time_start',
                    'preferred_time_end',
                ),
                'classes': ('collapse',),
            },
        ),
        (
            'Workflow',
            {
                'fields': (
                    'accepted_at',
                    'master_response_deadline',
                    'on_the_way_at',
                    'estimated_arrival_at',
                    'eta_minutes',
                    'arrived_at',
                    'work_started_at',
                    'expiration_time',
                ),
                'classes': ('collapse',),
            },
        ),
        (
            'Other',
            {'fields': ('parts_purchase_required', 'parts_purchase_required_json', 'car', 'category')},
        ),
        (
            'Timestamps',
            {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)},
        ),
    )


@admin.register(SOSOrder)
class SOSOrderAdmin(BaseOrderAdmin):
    list_display = [
        'order_number',
        'user_link',
        'assigned_master',
        'location_short',
        'coords_link',
        'status_badge',
        'sos_ring',
        'master_response_deadline',
        'created_at',
    ]
    list_filter = [
        'status',
        ('created_at', admin.DateFieldListFilter),
    ]
    date_hierarchy = 'created_at'

    fieldsets = (
        (
            'SOS',
            {
                'fields': (
                    'id',
                    'order_number',
                    'order_type',
                    'user',
                    'master',
                    'text',
                    'status',
                    'priority',
                    'sos_offer_queue',
                    'sos_offer_index',
                    'master_response_deadline',
                )
            },
        ),
        (
            'GPS',
            {
                'fields': (
                    'location',
                    'location_source',
                    'latitude',
                    'longitude',
                )
            },
        ),
        (
            'Workflow',
            {
                'fields': (
                    'accepted_at',
                    'on_the_way_at',
                    'estimated_arrival_at',
                    'eta_minutes',
                    'arrived_at',
                    'work_started_at',
                    'expiration_time',
                ),
                'classes': ('collapse',),
            },
        ),
        (
            'Other',
            {'fields': ('parts_purchase_required', 'parts_purchase_required_json', 'discount', 'car', 'category')},
        ),
        (
            'Timestamps',
            {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)},
        ),
    )

    def sos_ring(self, obj):
        q = obj.sos_offer_queue or []
        i = obj.sos_offer_index or 0
        if not q:
            return '—'
        return format_html(
            '<span title="queue">{} / {}</span> (idx {})',
            len(q),
            ', '.join(str(x) for x in q[:8]) + ('…' if len(q) > 8 else ''),
            i,
        )

    sos_ring.short_description = 'SOS queue'


@admin.register(CustomRequestOrder)
class CustomRequestOrderAdmin(BaseOrderAdmin):
    inlines = [CustomRequestOfferInline, OrderImageInline, OrderWorkCompletionImageInline, OrderServiceInline]

    list_display = [
        'order_number',
        'user_link',
        'assigned_master',
        'offers_count',
        'location_short',
        'status_badge',
        'priority_badge',
        'created_at',
    ]
    list_filter = [
        'status',
        'priority',
        ('created_at', admin.DateFieldListFilter),
    ]
    date_hierarchy = 'created_at'

    fieldsets = (
        (
            'Custom request',
            {
                'fields': (
                    'id',
                    'order_number',
                    'order_type',
                    'user',
                    'master',
                    'text',
                    'status',
                    'priority',
                    'discount',
                )
            },
        ),
        (
            'Location',
            {
                'fields': (
                    'location',
                    'location_source',
                    'latitude',
                    'longitude',
                    'preferred_date',
                    'preferred_time_start',
                    'preferred_time_end',
                ),
                'classes': ('collapse',),
            },
        ),
        (
            'Workflow',
            {
                'fields': (
                    'accepted_at',
                    'master_response_deadline',
                    'on_the_way_at',
                    'estimated_arrival_at',
                    'eta_minutes',
                    'arrived_at',
                    'work_started_at',
                    'expiration_time',
                ),
                'classes': ('collapse',),
            },
        ),
        (
            'Other',
            {'fields': ('parts_purchase_required', 'parts_purchase_required_json', 'car', 'category')},
        ),
        (
            'Timestamps',
            {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)},
        ),
    )

    def offers_count(self, obj):
        return getattr(obj, '_offers_count', 0)

    offers_count.short_description = 'Offers'

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(_offers_count=Count('custom_request_offers', distinct=True))
        )


@admin.register(OrderService)
class OrderServiceAdmin(admin.ModelAdmin):
    list_display = ['order_link', 'service_name', 'service_price', 'created_at']
    list_filter = ['created_at', 'order__status', 'order__order_type']
    search_fields = [
        'order__id',
        'master_service_item__category__name',
        'order__user__email',
        'order__user__phone_number',
    ]
    raw_id_fields = ['order', 'master_service_item']
    readonly_fields = ['id', 'created_at']
    list_per_page = 50

    def order_link(self, obj):
        if obj.order_id:
            url = reverse('admin:order_order_change', args=[obj.order_id])
            return format_html('<a href="{}">#{}</a>', url, obj.order_id)
        return '—'

    order_link.short_description = 'Order'
    order_link.admin_order_field = 'order__id'

    def service_name(self, obj):
        msi = obj.master_service_item
        if msi and msi.category_id:
            return msi.category.name
        return '—'

    service_name.short_description = 'Service'

    def service_price(self, obj):
        if obj.master_service_item_id:
            return str(obj.master_service_item.price)
        return '—'

    service_price.short_description = 'Price'

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                'order',
                'order__user',
                'master_service_item',
                'master_service_item__category',
            )
        )


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['order_link', 'reviewer_link', 'rating_stars', 'tags_short', 'created_at']
    list_filter = ['rating', ('created_at', admin.DateFieldListFilter)]
    search_fields = ['order__id', 'reviewer__email', 'reviewer__phone_number', 'comment']
    readonly_fields = ['id', 'created_at', 'updated_at']
    raw_id_fields = ['order', 'reviewer']
    list_per_page = 25
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Main', {'fields': ('id', 'order', 'reviewer', 'rating', 'tags')}),
        ('Comment', {'fields': ('comment',)}),
        ('Timestamps', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    def order_link(self, obj):
        oid = obj.order_id
        url = reverse('admin:order_order_change', args=[oid])
        return format_html('<a href="{}">#{}</a>', url, oid)

    order_link.short_description = 'Order'

    def reviewer_link(self, obj):
        if obj.reviewer_id:
            url = reverse('admin:accounts_customuser_change', args=[obj.reviewer_id])
            label = obj.reviewer.get_full_name() or obj.reviewer.email
            return format_html('<a href="{}">{}</a>', url, label)
        return '—'

    reviewer_link.short_description = 'Author'

    def rating_stars(self, obj):
        return format_html('<span style="font-size:14px;">{}</span>', '⭐' * int(obj.rating))

    rating_stars.short_description = 'Rating'

    def tags_short(self, obj):
        tags = obj.tags or []
        if not tags:
            return '—'
        return format_html(
            '<span style="font-size:11px;">{}</span>',
            ', '.join(tags),
        )

    tags_short.short_description = 'Tags'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('order', 'reviewer')


@admin.register(UserRating)
class UserRatingAdmin(admin.ModelAdmin):
    list_display = ['user_link', 'average_rating', 'updated_at']
    list_filter = [('updated_at', admin.DateFieldListFilter)]
    search_fields = ['user__email', 'user__phone_number', 'user__first_name', 'user__last_name']
    readonly_fields = ['id', 'user', 'average_rating', 'updated_at']
    raw_id_fields = ['user']
    ordering = ['-average_rating']

    def user_link(self, obj):
        if obj.user_id:
            url = reverse('admin:accounts_customuser_change', args=[obj.user_id])
            label = obj.user.get_full_name() or obj.user.email
            return format_html('<a href="{}">{}</a>', url, label)
        return '—'

    user_link.short_description = 'User'

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')


@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = ['order_id', 'user', 'master', 'rating', 'created_at']
    list_filter = ['rating', ('created_at', admin.DateFieldListFilter)]
    search_fields = ['order__id', 'user__email', 'comment']
    raw_id_fields = ['order', 'user', 'master']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'created_at'


@admin.register(MasterOrderCancellation)
class MasterOrderCancellationAdmin(admin.ModelAdmin):
    list_display = ['order_id', 'master_id', 'reason', 'created_at']
    list_filter = ['reason', ('created_at', admin.DateFieldListFilter)]
    raw_id_fields = ['master', 'order']
    readonly_fields = ['created_at']
    search_fields = ['order__id', 'master__user__email']
    date_hierarchy = 'created_at'
