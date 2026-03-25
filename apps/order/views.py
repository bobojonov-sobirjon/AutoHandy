from rest_framework import status, filters
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from django.contrib.auth import get_user_model

from apps.categories.query import order_by_order_category_smart_q

from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes

from .models import Order, OrderStatus, OrderType, Rating, OrderService, Review, ReviewTag
from .serializers import (
    OrderSerializer, OrderCreateSerializer, OrderUpdateSerializer,
    AddServicesToOrderSerializer, OrderServiceSerializer, AddMastersToOrderSerializer,
    ReviewSerializer, ReviewCreateSerializer
)
from .permissions import IsOrderOwnerOrMaster, IsOrderOwner, IsMaster
from apps.master.models import Master
from apps.master.serializers import MasterSerializer
from apps.accounts.models import UserBalance

User = get_user_model()


class OrderPagination(PageNumberPagination):
    """Pagination for orders"""
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


class ScheduledOrderCreateView(APIView):
    """Create scheduled order (Order by Date)"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Create scheduled order (Order by Date)",
        description="""
# Scheduled order (Order by Date)

This endpoint creates a **scheduled order** when the client:
- Selects master/workshop in advance
- Selects visit date and time slot (e.g. 10:00-11:00)
- Specifies required services

## When to use

- Planned maintenance (oil change, tire fitting, diagnostics)
- Booking a specific time
- Client has chosen a workshop from the list

Do NOT use for **emergencies** (use `/api/order/sos/`).

## Required fields

- **order_type**: always "scheduled"
- **text**: service description
- **car_list**: list of client car IDs [1, 2]
- **category_list**: list of service category IDs [1, 2]
- **master_id**: selected master/workshop ID
- **scheduled_date**: visit date (YYYY-MM-DD)
- **scheduled_time_start**, **scheduled_time_end**: time slot (HH:MM)
- **location**, **latitude**, **longitude**: workshop address and coordinates

## Validation

1. Visit date must not be in the past
2. Start time must be before end time
3. Distance to master <= 50 km
        """,
        tags=['Orders'],
        request={
            'application/json': {
                'type': 'object',
                'required': ['order_type', 'master_id', 'scheduled_date', 'scheduled_time_start', 'scheduled_time_end', 'text', 'location', 'latitude', 'longitude', 'car_list', 'category_list'],
                'properties': {
                    'order_type': {'type': 'string', 'enum': ['scheduled'], 'description': 'Order type (always "scheduled")', 'example': 'scheduled'},
                    'master_id': {'type': 'integer', 'description': 'Master/workshop ID (required)', 'example': 5},
                    'scheduled_date': {'type': 'string', 'format': 'date', 'description': 'Visit date (YYYY-MM-DD)', 'example': '2026-01-30'},
                    'scheduled_time_start': {'type': 'string', 'format': 'time', 'description': 'Start time (HH:MM)', 'example': '14:00'},
                    'scheduled_time_end': {'type': 'string', 'format': 'time', 'description': 'End time (HH:MM)', 'example': '15:00'},
                    'text': {'type': 'string', 'description': 'Service description', 'example': 'Oil and filter change'},
                    'location': {'type': 'string', 'description': 'Workshop address', 'example': 'Auto Service, Main St. 15'},
                    'latitude': {'type': 'number', 'description': 'Workshop latitude', 'example': 41.3111},
                    'longitude': {'type': 'number', 'description': 'Workshop longitude', 'example': 69.2797},
                    'car_list': {'type': 'array', 'items': {'type': 'integer'}, 'description': 'List of car IDs', 'example': [2]},
                    'category_list': {'type': 'array', 'items': {'type': 'integer'}, 'description': 'List of category IDs', 'example': [1]}
                }
            }
        },
        responses={
            201: {
                'description': 'Order created successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'message': 'Your order has been created and sent to the master',
                            'order': {
                                'id': 123,
                                'order_type': 'scheduled',
                                'status': 'pending',
                                'scheduled_date': '2026-01-30',
                                'scheduled_time_start': '14:00',
                                'scheduled_time_end': '15:00',
                                'master': {'id': 5, 'name': 'Auto Service'},
                                'text': 'Oil and filter change'
                            }
                        }
                    }
                }
            },
            400: {
                'description': 'Validation error',
                'content': {
                    'application/json': {
                        'examples': {
                            'missing_master': {
                                'summary': 'Master not specified',
                                'value': {'master_id': ['Master is required for scheduled order']}
                            },
                            'missing_date': {
                                'summary': 'Date not specified',
                                'value': {'scheduled_date': ['Visit date is required for scheduled order']}
                            },
                            'past_date': {
                                'summary': 'Date in past',
                                'value': {'scheduled_date': ['Visit date cannot be in the past']}
                            },
                            'distance_error': {
                                'summary': 'Master too far',
                                'value': {'master_id': ['Selected master is too far (150.5 km). Maximum distance: 50 km.']}
                            }
                        }
                    }
                }
            },
            401: {'description': 'Not authenticated'}
        }
    )
    def post(self, request):
        """Create scheduled order"""
        data = request.data.copy()
        data['order_type'] = OrderType.SCHEDULED

        serializer = OrderCreateSerializer(data=data)
        if serializer.is_valid():
            order = serializer.save(user=request.user)
            order_serializer = OrderSerializer(order)
            return Response({
                'message': 'Your order has been created and sent to the master',
                'order': order_serializer.data
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SOSOrderCreateView(APIView):
    """Create SOS order (emergency assistance)"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Create SOS order (emergency assistance)",
        description="""
# SOS order (Emergency assistance)

This endpoint creates an **emergency order** when the client:
- Is in an **emergency** (car broke down, flat tire, etc.)
- Needs **immediate assistance**
- Sends current **GPS location**
- System finds nearest available masters within radius

## When to use

- Car broke down on the road
- Flat tire on the highway
- Engine won't start
- Any emergency requiring immediate help

Do NOT use for **planned work** (use `/api/order/scheduled/`).

## Required fields

- **order_type**: always "sos"
- **master_id**: master/workshop ID (required)
- **text**: problem description
- **priority**: "low" or "high"
- **car_list**, **category_list**: car and category IDs
- **location**, **latitude**, **longitude**: current location (GPS)

## Validation

- Distance to master <= 50 km
- Selected master receives notification
        """,
        tags=['Orders'],
        request={
            'application/json': {
                'type': 'object',
                'required': ['order_type', 'master_id', 'priority', 'text', 'location', 'latitude', 'longitude', 'car_list', 'category_list'],
                'properties': {
                    'order_type': {'type': 'string', 'enum': ['sos'], 'description': 'Order type (always "sos")', 'example': 'sos'},
                    'master_id': {'type': 'integer', 'description': 'Master/workshop ID (required)', 'example': 5},
                    'priority': {'type': 'string', 'enum': ['low', 'high'], 'description': 'Order priority: low or high', 'example': 'high'},
                    'text': {'type': 'string', 'description': 'Problem description', 'example': 'Flat tire on highway'},
                    'location': {'type': 'string', 'description': 'Current location description', 'example': 'Highway M39, km 45, near Shell station'},
                    'latitude': {'type': 'number', 'description': 'Current latitude (GPS)', 'example': 41.2548},
                    'longitude': {'type': 'number', 'description': 'Current longitude (GPS)', 'example': 69.2107},
                    'car_list': {'type': 'array', 'items': {'type': 'integer'}, 'description': 'List of car IDs', 'example': [2]},
                    'category_list': {'type': 'array', 'items': {'type': 'integer'}, 'description': 'List of category IDs', 'example': [1]}
                }
            }
        },
        responses={
            201: {
                'description': 'SOS order created successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'message': 'Your emergency order has been sent to the master',
                            'order': {
                                'id': 456,
                                'order_type': 'sos',
                                'status': 'pending',
                                'priority': 'high',
                                'master': {'id': 5, 'name': 'Auto Service'},
                                'location': 'Highway M39, km 45',
                                'latitude': 41.2548,
                                'longitude': 69.2107,
                                'text': 'Flat front right tire'
                            }
                        }
                    }
                }
            },
            400: {
                'description': 'Validation error',
                'content': {
                    'application/json': {
                        'examples': {
                            'missing_master': {
                                'summary': 'Master not specified',
                                'value': {'master_id': ['Master is required for SOS order']}
                            },
                            'missing_location': {
                                'summary': 'Location not specified',
                                'value': {'latitude': ['This field is required'], 'longitude': ['This field is required']}
                            },
                            'distance_error': {
                                'summary': 'Master too far',
                                'value': {'master_id': ['Selected master is too far (150.5 km). Maximum distance: 50 km.']}
                            }
                        }
                    }
                }
            },
            401: {'description': 'Not authenticated'}
        }
    )
    def post(self, request):
        """Create SOS order"""
        data = request.data.copy()
        data['order_type'] = OrderType.SOS

        serializer = OrderCreateSerializer(data=data)
        if serializer.is_valid():
            order = serializer.save(user=request.user)
            order_serializer = OrderSerializer(order)
            return Response({
                'message': 'Your emergency order has been created and sent to the master',
                'order': order_serializer.data
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AvailableTimeSlotsView(APIView):
    """Get available time slots for master on a given date"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get available time slots for booking",
        description="""
# Available time slots

Returns a list of time slots (every 2 hours) for booking with a master on a given date.

## Required parameters

- **master_id** (query) - Master/workshop ID
- **date** (query) - Date in YYYY-MM-DD format (e.g. 2026-01-30)

## Response format

Each slot has: **start**, **end** (HH:MM), **available** (true/false), **order_id** (if occupied).
        """,
        tags=['Orders'],
        parameters=[
            OpenApiParameter(
                name='master_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Master ID (required). Example: 5',
                required=True
            ),
            OpenApiParameter(
                name='date',
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                description='Date for slot check (YYYY-MM-DD). Example: 2026-01-30',
                required=True
            ),
        ],
        responses={
            200: {
                'description': 'List of available time slots',
                'content': {
                    'application/json': {
                        'example': {
                            'date': '2026-01-30',
                            'master_id': 5,
                            'master_name': 'Auto Service',
                            'working_hours': '09:00-18:00',
                            'slots': [
                                {
                                    'start': '09:00',
                                    'end': '11:00',
                                    'available': True
                                },
                                {
                                    'start': '11:00',
                                    'end': '13:00',
                                    'available': False,
                                    'order_id': 123
                                },
                                {
                                    'start': '13:00',
                                    'end': '15:00',
                                    'available': True
                                }
                            ]
                        }
                    }
                }
            },
            400: {
                'description': 'Validation error',
                'content': {
                    'application/json': {
                        'examples': {
                            'missing_params': {
                                'summary': 'Missing parameters',
                                'value': {'error': 'master_id and date are required'}
                            },
                            'invalid_date': {
                                'summary': 'Invalid date format',
                                'value': {'error': 'Invalid date format. Use YYYY-MM-DD'}
                            }
                        }
                    }
                }
            },
            404: {
                'description': 'Master not found',
                'content': {
                    'application/json': {
                        'example': {'error': 'Master not found'}
                    }
                }
            }
        }
    )
    def get(self, request):
        """Get available time slots"""
        from datetime import datetime, timedelta, time

        # Get parameters
        master_id = request.query_params.get('master_id')
        date_str = request.query_params.get('date')
        
        # Validate parameters
        if not master_id or not date_str:
            return Response(
                {'error': 'master_id and date are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate date
        try:
            check_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return Response(
                {'error': 'Invalid date format. Use YYYY-MM-DD (e.g. 2026-01-30)'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get master
        try:
            master = Master.objects.get(id=master_id)
        except Master.DoesNotExist:
            return Response(
                {'error': 'Master not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        from apps.master.models import MasterBusySlot, MasterScheduleDay

        day_row = MasterScheduleDay.objects.filter(master=master, date=check_date).first()
        schedule_source = 'master_schedule_day' if day_row else 'working_time_fallback'
        if day_row:
            start_hour, start_minute = day_row.start_time.hour, day_row.start_time.minute
            end_hour, end_minute = day_row.end_time.hour, day_row.end_time.minute
            working_hours_display = (
                f'{day_row.start_time.strftime("%H:%M")}-{day_row.end_time.strftime("%H:%M")}'
            )
        else:
            working_time = master.working_time or '09:00-18:00'
            working_hours_display = working_time
            try:
                start_time_str, end_time_str = working_time.split('-')
                start_hour, start_minute = map(int, start_time_str.strip().split(':'))
                end_hour, end_minute = map(int, end_time_str.strip().split(':'))
            except Exception:
                start_hour, start_minute = 9, 0
                end_hour, end_minute = 18, 0

        slots = []
        current_hour = start_hour
        current_minute = start_minute
        while current_hour < end_hour:
            slot_start = time(current_hour, current_minute)
            next_hour = current_hour + 2
            next_minute = current_minute
            if next_hour > end_hour or (next_hour == end_hour and next_minute > end_minute):
                break
            slot_end = time(next_hour, next_minute)
            slots.append({
                'start': slot_start.strftime('%H:%M'),
                'end': slot_end.strftime('%H:%M'),
            })
            current_hour = next_hour
            current_minute = next_minute

        busy_qs = MasterBusySlot.objects.filter(master=master, date=check_date)
        busy_list = list(busy_qs)

        for slot in slots:
            slot_start_time = datetime.strptime(slot['start'], '%H:%M').time()
            slot_end_time = datetime.strptime(slot['end'], '%H:%M').time()
            slot['available'] = True
            slot.pop('order_id', None)
            for block in busy_list:
                if block.start_time < slot_end_time and block.end_time > slot_start_time:
                    slot['available'] = False
                    if block.order_id:
                        slot['order_id'] = block.order_id
                    break

        return Response({
            'date': date_str,
            'master_id': master.id,
            'master_name': master.name or master.user.get_full_name(),
            'working_hours': working_hours_display,
            'schedule_source': schedule_source,
            'slots': slots,
        })


class OrderListCreateView(APIView):
    """Order list"""
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'priority', 'master']
    search_fields = ['text', 'location', 'user__first_name', 'user__last_name', 'user__email']
    ordering_fields = ['created_at', 'updated_at', 'status', 'priority']
    ordering = ['-created_at']

    def get_queryset(self):
        user = self.request.user
        
        # If user is master, show orders assigned to them
        master = user.master_profiles.first()
        if master:
            return Order.objects.filter(master=master)
        
        # If regular user, show only their orders
        return Order.objects.filter(user=user)

    @extend_schema(
        summary="Получить список заказов",
        description="Возвращает список заказов с возможностью фильтрации, поиска и сортировки",
        tags=['Orders'],
        parameters=[
            {'name': 'status', 'in': 'query', 'description': 'Фильтр по статусу заказа', 'type': 'string', 'enum': [choice[0] for choice in OrderStatus.choices]},
            {'name': 'priority', 'in': 'query', 'description': 'Фильтр по приоритету заказа', 'type': 'string', 'enum': ['low', 'high']},
            {'name': 'master', 'in': 'query', 'description': 'Фильтр по мастеру (ID мастера)', 'type': 'integer'},
            {'name': 'search', 'in': 'query', 'description': 'Поиск по тексту заказа, местоположению или имени пользователя', 'type': 'string'},
            {'name': 'ordering', 'in': 'query', 'description': 'Сортировка по полю (created_at, updated_at, status, priority)', 'type': 'string', 'enum': ['created_at', '-created_at', 'updated_at', '-updated_at', 'status', '-status', 'priority', '-priority']},
        ],
        responses={
            200: OrderSerializer(many=True),
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        }
    )
    def get(self, request):
        """Get order list"""
        queryset = self.get_queryset()

        # Apply filters
        queryset = self.apply_filters(queryset, request)
        
        serializer = OrderSerializer(queryset, many=True)
        return Response(serializer.data)

    def apply_filters(self, queryset, request):
        """Apply filters to queryset"""
        # Filter by status
        if 'status' in request.query_params:
            queryset = queryset.filter(status=request.query_params['status'])
        
        # Filter by priority
        if 'priority' in request.query_params:
            queryset = queryset.filter(priority=request.query_params['priority'])
        
        # Filter by master
        if 'master' in request.query_params:
            queryset = queryset.filter(master=request.query_params['master'])
        
        # Search
        if 'search' in request.query_params:
            search_term = request.query_params['search']
            queryset = queryset.filter(
                Q(text__icontains=search_term) |
                Q(location__icontains=search_term) |
                Q(user__first_name__icontains=search_term) |
                Q(user__last_name__icontains=search_term) |
                Q(user__email__icontains=search_term)
            )
        
        # Ordering
        ordering = request.query_params.get('ordering', '-created_at')
        if ordering in self.ordering_fields:
            queryset = queryset.order_by(ordering)
        else:
            queryset = queryset.order_by(*self.ordering)
        
        return queryset


class OrderDetailView(APIView):
    """Order detail, update and delete"""
    permission_classes = [IsAuthenticated, IsOrderOwnerOrMaster]

    def get_object(self, order_id):
        """Get order object"""
        try:
            order = Order.objects.get(id=order_id)
            # Check access
            self.check_object_permissions(self.request, order)
            return order
        except Order.DoesNotExist:
            return None

    @extend_schema(
        summary="Get order details",
        description="Returns detailed information about a specific order",
        tags=['Orders'],
        parameters=[
            {'name': 'id', 'in': 'path', 'description': 'Order ID', 'type': 'integer', 'required': True},
        ],
        responses={
            200: OrderSerializer,
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        }
    )
    def get(self, request, id):
        """Get order details"""
        order = self.get_object(id)
        if not order:
            return Response(
                {'error': 'Order not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = OrderSerializer(order)
        return Response(serializer.data)

    @extend_schema(
        summary="Полное обновление заказа",
        description="Полностью обновляет все поля заказа. "
                  "Fields: text, location, priority (low/high), status (pending, in_progress, completed, cancelled, rejected), latitude, longitude, master (ID).",
        tags=['Orders'],
        parameters=[
            {'name': 'id', 'in': 'path', 'description': 'Order ID', 'type': 'integer', 'required': True},
        ],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'text': {'type': 'string', 'description': 'Order description', 'example': 'Need help with wheel replacement'},
                    'status': {'type': 'string', 'enum': ['pending', 'in_progress', 'completed', 'cancelled', 'rejected'], 'description': 'Order status', 'example': 'in_progress'},
                    'priority': {'type': 'string', 'enum': ['low', 'high'], 'description': 'Order priority', 'example': 'high'},
                    'location': {'type': 'string', 'description': 'Address or place description', 'example': 'Main St. 15'},
                    'latitude': {'type': 'number', 'description': 'Latitude (-90 to 90)', 'example': 41.3111},
                    'longitude': {'type': 'number', 'description': 'Longitude (-180 to 180)', 'example': 69.2797},
                    'master': {'type': 'integer', 'description': 'Master ID', 'example': 1}
                }
            }
        },
        responses={
            200: OrderSerializer,
            400: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        }
    )
    def put(self, request, id):
        """Full order update"""
        order = self.get_object(id)
        if not order:
            return Response(
                {'error': 'Order not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = OrderUpdateSerializer(order, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="Частичное обновление заказа",
        description="Частично обновляет поля заказа. Можно указать только те поля, которые нужно обновить. "
                  "Fields: text, location, priority (low/high), status (pending, in_progress, completed, cancelled, rejected), latitude, longitude, master (ID).",
        tags=['Orders'],
        parameters=[
            {'name': 'id', 'in': 'path', 'description': 'Order ID', 'type': 'integer', 'required': True},
        ],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'text': {'type': 'string', 'description': 'Order description', 'example': 'Need help with wheel replacement'},
                    'status': {'type': 'string', 'enum': ['pending', 'in_progress', 'completed', 'cancelled', 'rejected'], 'description': 'Order status', 'example': 'in_progress'},
                    'priority': {'type': 'string', 'enum': ['low', 'high'], 'description': 'Order priority', 'example': 'high'},
                    'location': {'type': 'string', 'description': 'Address or place description', 'example': 'Main St. 15'},
                    'latitude': {'type': 'number', 'description': 'Latitude (-90 to 90)', 'example': 41.3111},
                    'longitude': {'type': 'number', 'description': 'Longitude (-180 to 180)', 'example': 69.2797},
                    'master': {'type': 'integer', 'description': 'Master ID', 'example': 1}
                }
            }
        },
        responses={
            200: OrderSerializer,
            400: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        }
    )
    def patch(self, request, id):
        """Partial order update"""
        order = self.get_object(id)
        if not order:
            return Response(
                {'error': 'Order not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = OrderUpdateSerializer(order, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="Удалить заказ",
        description="Удаляет заказ из системы",
        tags=['Orders'],
        parameters=[
            {'name': 'id', 'in': 'path', 'description': 'Order ID', 'type': 'integer', 'required': True},
        ],
        responses={
            204: {'description': 'Заказ успешно удален'},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        }
    )
    def delete(self, request, id):
        """Delete order"""
        order = self.get_object(id)
        if not order:
            return Response(
                {'error': 'Order not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        order.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class OrdersByUserView(APIView):
    """
    API для получения заказов текущего пользователя
    """
    permission_classes = [IsAuthenticated]
    pagination_class = OrderPagination
    
    @extend_schema(
        summary="Получить заказы текущего пользователя",
        description="""
## Описание
Возвращает все заказы текущего авторизованного пользователя (user берется из header/token).

## Фильтры (все необязательные)

### 1. Статус заказа (status)
- Значения: pending, in_progress, completed, cancelled, rejected
- Пример: `status=in_progress`

### 2. Приоритет (priority)
- Значения: low (низкий), high (высокий)
- Пример: `priority=high`

### 3. Тип проблемы (category)
- ID категории типа **by_order**
- Использует **smart filter** через дерево parent категории
- Пример: `category=1` — заказы с той же категорией, соседями (общий parent), родителем или дочерними

### 4. Район (location)
- Поиск по адресу заказа
- Пример: `location=Ташкент` или `location=Навои`
- Поиск нечувствителен к регистру

### 5. Тип ТС (car_category)
- ID категории машины типа **by_car**
- Прямой фильтр по ID
- Пример: `car_category=3` (где 3 - это "Легковой")

### 6. Тип заказа (order_type)
- Фильтр по типу заказа
- Значения: `scheduled` (запланированный) или `sos` (экстренный)
- Пример: `order_type=scheduled` - показывает только запланированные заказы
- Пример: `order_type=sos` - показывает только SOS заказы

### 7. Имя мастера (name)
- Поиск по имени мастера
- Пример: `name=Алексей`

## Pagination
- По умолчанию 10 заказов на страницу
- Можно изменить через `page_size` (макс. 100)

## Примеры запросов

**Базовый:**
```
GET /api/order/by-user/
```

**С фильтром по статусу:**
```
GET /api/order/by-user/?status=in_progress
```

**С фильтром по проблеме (smart filter):**
```
GET /api/order/by-user/?category=1
```

**С несколькими фильтрами:**
```
GET /api/order/by-user/?status=pending&priority=high&category=1&location=Ташкент
```

**Только запланированные заказы (Order by Date):**
```
GET /api/order/by-user/?order_type=scheduled
```

**Только SOS заказы (экстренные):**
```
GET /api/order/by-user/?order_type=sos
```

**Запланированные заказы со статусом pending:**
```
GET /api/order/by-user/?order_type=scheduled&status=pending
```
        """,
        tags=['Orders'],
        parameters=[
            OpenApiParameter(name='status', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, description='Фильтр по статусу заказа', required=False, enum=[choice[0] for choice in OrderStatus.choices]),
            OpenApiParameter(name='priority', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, description='Фильтр по приоритету (low, high)', required=False, enum=['low', 'high']),
            OpenApiParameter(name='category', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, description='Фильтр по типу проблемы. ID категории by_order. Smart filter по parent-дереву.', required=False),
            OpenApiParameter(name='location', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, description='Фильтр по району (поиск по адресу заказа)', required=False),
            OpenApiParameter(name='car_category', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, description='Фильтр по типу ТС (ID категории машины типа by_car)', required=False),
            OpenApiParameter(name='order_type', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, description='Фильтр по типу заказа (scheduled - запланированные, sos - экстренные)', required=False, enum=['scheduled', 'sos']),
            OpenApiParameter(name='name', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, description='Поиск по имени мастера', required=False),
            OpenApiParameter(name='page', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, description='Номер страницы для пагинации', required=False),
            OpenApiParameter(name='page_size', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, description='Количество заказов на странице (макс. 100)', required=False),
        ],
        responses={
            200: OrderSerializer(many=True),
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        }
    )
    def get(self, request):
        """Получить заказы текущего пользователя"""
        orders = Order.objects.filter(user=request.user)
        
        # Фильтр по статусу
        status_filter = request.query_params.get('status')
        if status_filter:
            orders = orders.filter(status=status_filter)
        
        # Фильтр по приоритету
        priority_filter = request.query_params.get('priority')
        if priority_filter:
            orders = orders.filter(priority=priority_filter)
        
        # Фильтр по типу заказа (scheduled или sos)
        order_type_filter = request.query_params.get('order_type')
        if order_type_filter:
            if order_type_filter in ['scheduled', 'sos']:
                orders = orders.filter(order_type=order_type_filter)
        
        # Smart фильтр по категории проблемы (Тип проблемы)
        category_filter = request.query_params.get('category')
        if category_filter:
            try:
                from apps.categories.models import Category
                category_id = int(category_filter)
                category = Category.objects.get(id=category_id)
                
                if category.type_category == 'by_order':
                    orders = orders.filter(order_by_order_category_smart_q(category))
                else:
                    # Для других типов - прямой фильтр по ID
                    orders = orders.filter(category__id=category_id)
                    
            except Category.DoesNotExist:
                pass
            except (ValueError, TypeError):
                pass
        
        # Фильтр по району/местоположению (Районы)
        location_filter = request.query_params.get('location')
        if location_filter:
            orders = orders.filter(location__icontains=location_filter)
        
        # Фильтр по типу ТС (категория машины)
        car_category_filter = request.query_params.get('car_category')
        if car_category_filter:
            try:
                car_category_id = int(car_category_filter)
                orders = orders.filter(car__category__id=car_category_id)
            except (ValueError, TypeError):
                pass
        
        # Фильтр по имени мастера
        name = request.query_params.get('name')
        if name:
            orders = orders.filter(
                Q(master__user__first_name__icontains=name) |
                Q(master__user__last_name__icontains=name) |
                Q(master__user__get_full_name__icontains=name)
            )
        
        # Убираем дубликаты и сортируем
        orders = orders.distinct().order_by('-created_at')
        
        # Применяем пагинацию
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(orders, request)
        if page is not None:
            serializer = OrderSerializer(page, many=True, context={'request': request})
            return paginator.get_paginated_response(serializer.data)
        
        serializer = OrderSerializer(orders, many=True, context={'request': request})
        return Response(serializer.data)


class OrdersByMasterView(APIView):
    """
    API для получения заказов текущего мастера
    """
    permission_classes = [IsAuthenticated]
    pagination_class = OrderPagination
    
    @extend_schema(
        summary="Получить заказы текущего мастера",
        description="""
## Описание
Возвращает список заказов, назначенных текущему мастеру (master берется из header/token).

## Фильтры (все необязательные)

### 1. Статус заказа (status)
- Значения: pending, in_progress, completed, cancelled, rejected
- Пример: `status=in_progress`

### 2. Приоритет (priority)
- Значения: low (низкий), high (высокий)
- Пример: `priority=high`

### 3. Тип проблемы (category)
- ID категории типа **by_order**
- Использует **smart filter** через дерево parent категории
- Пример: `category=1` — заказы с той же категорией, соседями (общий parent), родителем или дочерними

### 4. Район (location)
- Поиск по адресу заказа
- Пример: `location=Ташкент` или `location=Навои`
- Поиск нечувствителен к регистру

### 5. Тип ТС (car_category)
- ID категории машины типа **by_car**
- Прямой фильтр по ID
- Пример: `car_category=3` (где 3 - это "Легковой")

### 6. Географическая область (4 точки)
- Фильтр по координатам (полигон)
- Требуется указать все 4 точки
- Пример: `point1_lat=41.3&point1_lon=69.2&point2_lat=...`

### 7. Новые заказы (is_new)
- Фильтр для отображения новых заказов
- Значение: `true` или `false`
- Показывает заказы где master=null И masters пустой
- Пример: `is_new=true`

### 8. В работе (is_work)
- Фильтр для заказов в работе
- Значение: `true` или `false`
- Показывает заказы текущего мастера со статусом IN_PROGRESS
- Пример: `is_work=true`

### 9. Архив (is_archive)
- Фильтр для завершенных заказов
- Значение: `true` или `false`
- Показывает заказы текущего мастера со статусом COMPLETED
- Пример: `is_archive=true`

### 10. Тип заказа (order_type)
- Фильтр по типу заказа
- Значения: `scheduled` (запланированный) или `sos` (экстренный)
- Пример: `order_type=scheduled` - показывает только запланированные заказы
- Пример: `order_type=sos` - показывает только SOS заказы

## Pagination
- По умолчанию 10 заказов на страницу
- Можно изменить через `page_size` (макс. 100)

## Примеры запросов

**Базовый:**
```
GET /api/order/by-master/
```

**Новые заказы:**
```
GET /api/order/by-master/?is_new=true
```

**Заказы в работе:**
```
GET /api/order/by-master/?is_work=true
```

**Завершенные заказы (архив):**
```
GET /api/order/by-master/?is_archive=true
```

**С фильтром по статусу:**
```
GET /api/order/by-master/?status=in_progress
```

**С фильтром по проблеме (smart filter):**
```
GET /api/order/by-master/?category=1
```

**С несколькими фильтрами:**
```
GET /api/order/by-master/?status=pending&priority=high&category=1&location=Ташкент
```

**Только запланированные заказы (Order by Date):**
```
GET /api/order/by-master/?order_type=scheduled
```

**Только SOS заказы (экстренные):**
```
GET /api/order/by-master/?order_type=sos
```

**Запланированные заказы со статусом pending:**
```
GET /api/order/by-master/?order_type=scheduled&status=pending
```
        """,
        tags=['Orders'],
        parameters=[
            OpenApiParameter(name='status', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, description='Фильтр по статусу заказа', required=False, enum=[choice[0] for choice in OrderStatus.choices]),
            OpenApiParameter(name='priority', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, description='Фильтр по приоритету (low, high)', required=False, enum=['low', 'high']),
            OpenApiParameter(name='category', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, description='Фильтр по типу проблемы. ID категории by_order. Smart filter по parent-дереву.', required=False),
            OpenApiParameter(name='location', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, description='Фильтр по району (поиск по адресу заказа)', required=False),
            OpenApiParameter(name='car_category', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, description='Фильтр по типу ТС (ID категории машины типа by_car)', required=False),
            # Координаты полигона (4 точки)
            OpenApiParameter(name='point1_lat', type=OpenApiTypes.FLOAT, location=OpenApiParameter.QUERY, description='Широта точки 1 (для географического фильтра)', required=False),
            OpenApiParameter(name='point1_lon', type=OpenApiTypes.FLOAT, location=OpenApiParameter.QUERY, description='Долгота точки 1', required=False),
            OpenApiParameter(name='point2_lat', type=OpenApiTypes.FLOAT, location=OpenApiParameter.QUERY, description='Широта точки 2', required=False),
            OpenApiParameter(name='point2_lon', type=OpenApiTypes.FLOAT, location=OpenApiParameter.QUERY, description='Долгота точки 2', required=False),
            OpenApiParameter(name='point3_lat', type=OpenApiTypes.FLOAT, location=OpenApiParameter.QUERY, description='Широта точки 3', required=False),
            OpenApiParameter(name='point3_lon', type=OpenApiTypes.FLOAT, location=OpenApiParameter.QUERY, description='Долгота точки 3', required=False),
            OpenApiParameter(name='point4_lat', type=OpenApiTypes.FLOAT, location=OpenApiParameter.QUERY, description='Широта точки 4', required=False),
            OpenApiParameter(name='point4_lon', type=OpenApiTypes.FLOAT, location=OpenApiParameter.QUERY, description='Долгота точки 4', required=False),
            OpenApiParameter(name='is_new', type=OpenApiTypes.BOOL, location=OpenApiParameter.QUERY, description='Новые заказы (master=null и masters пустой)', required=False),
            OpenApiParameter(name='is_work', type=OpenApiTypes.BOOL, location=OpenApiParameter.QUERY, description='Заказы в работе (status=IN_PROGRESS)', required=False),
            OpenApiParameter(name='is_archive', type=OpenApiTypes.BOOL, location=OpenApiParameter.QUERY, description='Завершенные заказы (status=COMPLETED)', required=False),
            OpenApiParameter(name='order_type', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, description='Фильтр по типу заказа (scheduled - запланированные, sos - экстренные)', required=False, enum=['scheduled', 'sos']),
            OpenApiParameter(name='page', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, description='Номер страницы для пагинации', required=False),
            OpenApiParameter(name='page_size', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, description='Количество заказов на странице (макс. 100)', required=False),
        ],
        responses={
            200: OrderSerializer(many=True),
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
        }
    )
    def get(self, request):
        """Получить заказы текущего мастера в области"""
        # Проверяем, что пользователь является мастером
        try:
            master = request.user.master_profiles.first()
            if not master:
                return Response(
                    {'error': 'Пользователь не является мастером'}, 
                    status=status.HTTP_403_FORBIDDEN
                )
        except AttributeError:
            return Response(
                {'error': 'Пользователь не является мастером'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Получаем заказы для текущего мастера через foreign key
        orders = Order.objects.filter(master=master)
        
        # Фильтр is_new - новые заказы (master=null и masters пустой)
        is_new = request.query_params.get('is_new', '').lower() == 'true'
        if is_new:
            from django.db.models import Count
            # Показываем заказы без мастера
            orders = Order.objects.annotate(
                masters_count=Count('masters')
            ).filter(
                master__isnull=True,
                masters_count=0
            )
        
        # Фильтр is_work - заказы в работе (IN_PROGRESS)
        is_work = request.query_params.get('is_work', '').lower() == 'true'
        if is_work:
            orders = Order.objects.filter(master=master, status=OrderStatus.IN_PROGRESS)
        
        # Фильтр is_archive - завершенные заказы (COMPLETED)
        is_archive = request.query_params.get('is_archive', '').lower() == 'true'
        if is_archive:
            orders = Order.objects.filter(master=master, status=OrderStatus.COMPLETED)
        
        # Фильтр по статусу
        status_filter = request.query_params.get('status')
        if status_filter:
            orders = orders.filter(status=status_filter)
        
        # Фильтр по приоритету
        priority_filter = request.query_params.get('priority')
        if priority_filter:
            orders = orders.filter(priority=priority_filter)
        
        # Фильтр по типу заказа (scheduled или sos)
        order_type_filter = request.query_params.get('order_type')
        if order_type_filter:
            if order_type_filter in ['scheduled', 'sos']:
                orders = orders.filter(order_type=order_type_filter)
        
        # Smart фильтр по категории проблемы (Тип проблемы)
        category_filter = request.query_params.get('category')
        if category_filter:
            try:
                from apps.categories.models import Category
                category_id = int(category_filter)
                category = Category.objects.get(id=category_id)
                
                if category.type_category == 'by_order':
                    orders = orders.filter(order_by_order_category_smart_q(category))
                else:
                    # Для других типов - прямой фильтр по ID
                    orders = orders.filter(category__id=category_id)
                    
            except Category.DoesNotExist:
                pass
            except (ValueError, TypeError):
                pass
        
        # Фильтр по району/местоположению (Районы)
        location_filter = request.query_params.get('location')
        if location_filter:
            orders = orders.filter(location__icontains=location_filter)
        
        # Фильтр по типу ТС (категория машины)
        car_category_filter = request.query_params.get('car_category')
        if car_category_filter:
            try:
                car_category_id = int(car_category_filter)
                orders = orders.filter(car__category__id=car_category_id)
            except (ValueError, TypeError):
                pass
        
        # Фильтр по локации: 4 точки полигона (bounding box)
        area_filter = _get_area_filter_for_orders(request)
        if area_filter:
            # Faqat koordinatalari bo'lgan orderlarni filter qilamiz
            orders = orders.filter(
                latitude__isnull=False,
                longitude__isnull=False,
                **area_filter
            )
        
        # Убираем дубликаты и сортируем
        orders = orders.distinct().order_by('-created_at')
        
        # Применяем пагинацию
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(orders, request)
        if page is not None:
            serializer = OrderSerializer(page, many=True, context={'request': request})
            return paginator.get_paginated_response(serializer.data)
        
        serializer = OrderSerializer(orders, many=True, context={'request': request})
        return Response(serializer.data)


class UpdateOrderStatusView(APIView):
    """
    API для обновления статуса заказа
    """
    permission_classes = [IsAuthenticated, IsOrderOwnerOrMaster]
    
    @extend_schema(
        summary="Обновить статус заказа",
        description="Обновляет статус заказа на новый. "
                  "Статусы: pending - ожидает, in_progress - в работе, completed - завершен, cancelled - отменен, rejected - отклонен. "
                  "Доступно только владельцу заказа или мастеру.",
        tags=['Orders'],
        parameters=[
            {'name': 'order_id', 'in': 'path', 'description': 'Order ID', 'type': 'integer', 'required': True},
        ],
        request={
            'application/json': {
                'type': 'object',
                'required': ['status'],
                'properties': {
                    'status': {
                        'type': 'string',
                        'enum': ['pending', 'in_progress', 'completed', 'cancelled', 'rejected'],
                        'description': 'Статус заказа: pending (Ожидает), in_progress (В работе), completed (Завершен), cancelled (Отменен), rejected (Отклонен)',
                        'example': 'in_progress'
                    }
                }
            }
        },
        responses={
            200: OrderSerializer,
            400: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        }
    )
    def post(self, request, order_id):
        """Обновить статус заказа"""
        try:
            order = Order.objects.get(id=order_id)
            new_status = request.data.get('status')
            
            if not new_status:
                return Response(
                    {'error': 'Статус обязателен'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if new_status not in [choice[0] for choice in OrderStatus.choices]:
                return Response(
                    {'error': 'Недопустимый статус'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            order.status = new_status
            order.save()
            
            serializer = OrderSerializer(order)
            return Response(serializer.data)
        
        except Order.DoesNotExist:
            return Response(
                {'error': 'Order not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )


class AcceptOrderView(APIView):
    """
    API для принятия заказа в работу
    """
    permission_classes = [IsAuthenticated, IsMaster]
    
    @extend_schema(
        summary="Принять заказ в работу",
        description="""
Принимает заказ в работу с проверкой минимального баланса **мастера** (1000 ₽) и списанием 200 ₽ за каждый заказ.

## Проверки баланса мастера:
1. **Минимальный баланс**: У мастера на балансе должно быть минимум 1000 ₽
2. **Списание за заказ**: С баланса мастера спишется 200 ₽ при принятии заказа

## Response при ошибке баланса:
```json
{
  "error": "Описание ошибки",
  "current_balance": 500.00,
  "required_balance": 1000
}
```

**Важно:** Проверяется баланс **мастера**, который принимает заказ, а не клиента!
        """,
        tags=['Orders'],
        parameters=[
            {'name': 'order_id', 'in': 'path', 'description': 'Order ID', 'type': 'integer', 'required': True},
        ],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'message': {'type': 'string'},
                    'order': {'type': 'object'},
                    'balance_after': {'type': 'number'}
                }
            },
            400: {
                'type': 'object',
                'properties': {
                    'error': {'type': 'string'},
                    'current_balance': {'type': 'number'},
                    'required_balance': {'type': 'number'},
                    'required_amount': {'type': 'number'}
                }
            },
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        }
    )
    def post(self, request, order_id):
        """Принять заказ в работу"""
        try:
            order = Order.objects.get(id=order_id)
            
            # Проверяем, что заказ не назначен другому мастеру
            master = request.user.master_profiles.first()
            if order.master and order.master.id != master.id:
                return Response(
                    {'error': 'Заказ уже назначен другому мастеру'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Проверяем, что заказ не истек
            if order.is_expired():
                order.mark_as_cancelled_if_expired()
                return Response(
                    {'error': 'Заказ истек и был отменен'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Проверяем баланс мастера (кто принимает заказ)
            user_balance = UserBalance.get_or_create_balance(request.user)
            if not user_balance.has_minimum_balance(1000):
                return Response({
                    'error': 'На балансе должно быть минимум 1000 ₽, чтобы брать заказы в работу',
                    'current_balance': float(user_balance.amount),
                    'required_balance': 1000
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Проверяем, может ли пользователь позволить себе заказ (200 ₽)
            if not user_balance.can_afford_order(200):
                return Response({
                    'error': 'Недостаточно средств для принятия заказа. Требуется 200 ₽',
                    'current_balance': float(user_balance.amount),
                    'required_amount': 200
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Списываем 200 ₽ с баланса
            if user_balance.deduct_amount(200):
                # Назначаем заказ текущему мастеру и меняем статус
                order.master = master
                order.status = OrderStatus.IN_PROGRESS
                order.save()
                
                # Обновляем баланс после списания
                user_balance.refresh_from_db()
                
                serializer = OrderSerializer(order)
                return Response({
                    'message': 'Заказ взят в работу. 200 ₽ были списаны с баланса.',
                    'order': serializer.data,
                    'balance_after': float(user_balance.amount)
                })
            else:
                return Response({
                    'error': 'Ошибка при списании средств с баланса',
                    'current_balance': float(user_balance.amount)
                }, status=status.HTTP_400_BAD_REQUEST)
        
        except Order.DoesNotExist:
            return Response(
                {'error': 'Order not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )


class CompleteOrderView(APIView):
    """
    API для завершения заказа (отметка как выполненного)
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="Завершить заказ",
        description="""
## Описание
Завершает заказ, устанавливая статус **COMPLETED** (Завершен).

## 🎯 Когда использовать?
- ✅ Работа по заказу выполнена
- ✅ Клиент доволен результатом
- ✅ Заказ готов к закрытию
- ✅ Можно оставить рейтинг и отзыв

## Требования:
- Заказ должен существовать
- Пользователь должен быть авторизован

## Пример запроса:
```
POST /api/order/5/complete/
```

## Response:
```json
{
  "message": "Заказ успешно завершен",
  "order": {
    "id": 5,
    "status": "completed",
    "status_display": "Завершен",
    "user": {...},
    "master": {...},
    "text": "Замена масла",
    "created_at": "2026-01-30T10:00:00Z"
  }
}
```

## Workflow:
1. Мастер завершает работу по заказу
2. Отправляет POST запрос на `/api/order/{order_id}/complete/`
3. Заказ переходит в статус **COMPLETED**
4. Клиент может оставить рейтинг и отзыв
        """,
        tags=['Orders'],
        parameters=[
            {'name': 'order_id', 'in': 'path', 'description': 'Order ID', 'type': 'integer', 'required': True},
        ],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'message': {'type': 'string', 'example': 'Заказ успешно завершен'},
                    'order': {'$ref': '#/components/schemas/Order'}
                }
            },
            404: {
                'type': 'object',
                'properties': {'error': {'type': 'string', 'example': 'Заказ не найден'}}
            },
            401: {
                'type': 'object',
                'properties': {'detail': {'type': 'string', 'example': 'Authentication credentials were not provided.'}}
            },
        }
    )
    def post(self, request, order_id):
        """Завершить заказ (установить статус COMPLETED)"""
        try:
            order = Order.objects.get(id=order_id)
            
            # Устанавливаем статус COMPLETED
            order.status = OrderStatus.COMPLETED
            order.save()
            
            serializer = OrderSerializer(order, context={'request': request})
            return Response({
                'message': 'Заказ успешно завершен',
                'order': serializer.data
            }, status=status.HTTP_200_OK)
        
        except Order.DoesNotExist:
            return Response(
                {'error': 'Order not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )


class CreateReviewView(APIView):
    """
    API для создания отзыва о заказе и мастерах
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="Создать отзыв о заказе",
        description="""
## Описание
Создает отзыв о выполненном заказе. Рейтинг автоматически применяется ко всем мастерам, 
назначенным на заказ (главный мастер и все мастера из списка).

## 🎯 Когда использовать?
- ✅ После завершения заказа (status = COMPLETED)
- ✅ Клиент хочет оценить работу мастера
- ✅ Один раз на заказ (повторные отзывы запрещены)

## Request Body
- `order_id`: ID завершенного заказа (обязательно)
- `rating`: Рейтинг от 1 до 5 (обязательно)
- `comment`: Текст отзыва (необязательно)
- `tag`: Что понравилось в работе мастера - выберите ОДНО (обязательно):
  - `fast_work` - Оперативная работа
  - `no_overpay` - Без переплат
  - `deadline` - Соблюдение сроков
  - `always_available` - Всегда на связи
  - `individual_approach` - Индивидуальный подход
  - `polite` - Вежливость

## Пример запроса:
```json
{
  "order_id": 5,
  "rating": 5,
  "comment": "Отличная работа! Быстро и качественно.",
  "tag": "fast_work"
}
```

## Response:
```json
{
  "message": "Отзыв успешно создан. Рейтинг применен к мастерам.",
  "review": {
    "id": 1,
    "order": 5,
    "rating": 5,
    "comment": "Отличная работа!",
    "tag": "fast_work",
    "tag_display": "Оперативная работа",
    "created_at": "2026-01-31T10:00:00Z"
  }
}
```

## Что происходит автоматически:
1. ✅ Отзыв сохраняется в БД
2. ✅ Рейтинг применяется ко ВСЕМ мастерам из заказа:
   - Главный мастер (order.master)
   - Все мастера из списка (order.masters)
3. ✅ Обновляется средний рейтинг каждого мастера
4. ✅ Рейтинг появляется в профиле мастера
        """,
        tags=['Orders'],
        request=ReviewCreateSerializer,
        responses={
            201: ReviewSerializer,
            400: {
                'type': 'object',
                'properties': {'error': {'type': 'string'}},
                'examples': {
                    'not_completed': {'value': {'error': 'Отзыв можно оставить только для завершенного заказа'}},
                    'already_exists': {'value': {'error': 'Отзыв для этого заказа уже оставлен'}}
                }
            },
            404: {
                'type': 'object',
                'properties': {'error': {'type': 'string'}},
                'example': {'error': 'Order not found'}
            },
            401: {
                'type': 'object',
                'properties': {'detail': {'type': 'string'}}
            },
        }
    )
    def post(self, request):
        """Создать отзыв о заказе"""
        serializer = ReviewCreateSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        order_id = serializer.validated_data['order_id']
        rating = serializer.validated_data['rating']
        comment = serializer.validated_data.get('comment', '')
        tag = serializer.validated_data['tag']
        
        try:
            order = Order.objects.get(id=order_id)
            
            # Создаем отзыв
            review = Review.objects.create(
                order=order,
                reviewer=request.user,
                rating=rating,
                comment=comment,
                tag=tag
            )
            
            # Рейтинг автоматически применится ко всем мастерам через save() метод
            
            result_serializer = ReviewSerializer(review)
            return Response({
                'message': 'Отзыв успешно создан. Рейтинг применен к мастерам.',
                'review': result_serializer.data
            }, status=status.HTTP_201_CREATED)
        
        except Order.DoesNotExist:
            return Response(
                {'error': 'Order not found'},
                status=status.HTTP_404_NOT_FOUND
            )


def _get_area_filter_for_orders(request):
    """Получение фильтра по прямоугольной области для orders_by_master - Order model ichidagi lat/long bilan"""
    # Получаем параметры точек
    point_params = {
        'point1': (request.query_params.get('point1_lat'), request.query_params.get('point1_lon')),
        'point2': (request.query_params.get('point2_lat'), request.query_params.get('point2_lon')),
        'point3': (request.query_params.get('point3_lat'), request.query_params.get('point3_lon')),
        'point4': (request.query_params.get('point4_lat'), request.query_params.get('point4_lon'))
    }
    
    # Проверяем, что все параметры переданы
    all_params = [param for point in point_params.values() for param in point]
    
    # Agar heч qanday parametr berilmagan bo'lsa, None qaytar
    if not any(all_params):
        return None
    
    # Agar ba'zi parametrlar berilgan bo'lsa, lekin barchasi emas bo'lsa, None qaytar
    if not all(all_params):
        return None
    
    # Валидируем и преобразуем координаты
    points = []
    for point_name, (lat_str, lon_str) in point_params.items():
        try:
            lat = float(lat_str)
            lon = float(lon_str)
            # Order model uchun coordinate validation
            if not (-90 <= lat <= 90):
                return None
            if not (-180 <= lon <= 180):
                return None
            points.append((lat, lon))
        except (ValueError, TypeError):
            return None
    
    # Вычисляем границы прямоугольника
    lats = [point[0] for point in points]
    lons = [point[1] for point in points]
    
    min_lat = min(lats)
    max_lat = max(lats)
    min_lon = min(lons)
    max_lon = max(lons)
    
    # Order model ichidagi latitude va longitude bilan filter qilamiz
    return {
        'latitude__gte': min_lat,
        'latitude__lte': max_lat,
        'longitude__gte': min_lon,
        'longitude__lte': max_lon
    }


class AvailableOrdersForMasterView(APIView):
    """
    API для получения доступных заказов для мастера
    Показывает заказы без назначенного мастера в радиусе от мастера
    """
    permission_classes = [IsAuthenticated]
    pagination_class = OrderPagination
    
    def calculate_distance(self, lat1, lon1, lat2, lon2):
        """
        Вычисление расстояния между двумя точками по формуле Haversine
        Возвращает расстояние в километрах
        """
        from math import radians, sin, cos, sqrt, atan2
        
        # Радиус Земли в километрах
        R = 6371.0
        
        # Конвертируем градусы в радианы
        lat1_rad = radians(lat1)
        lon1_rad = radians(lon1)
        lat2_rad = radians(lat2)
        lon2_rad = radians(lon2)
        
        # Разница координат
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad
        
        # Формула Haversine
        a = sin(dlat / 2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2)**2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        
        distance = R * c
        return distance
    
    @extend_schema(
        summary="Получить доступные заказы для мастера",
        description="""
## Описание
Возвращает список доступных заказов (без назначенного мастера) в радиусе от местоположения мастера.

## Обязательные параметры
- **master_id** - ID мастера (координаты берутся из профиля мастера)

## Необязательные параметры
- **radius** - Радиус поиска в километрах (по умолчанию 10 км, можно увеличить до 50+ км)

## Фильтры (все необязательные)

### 1. Тип проблемы (category)
- ID категории типа **by_order**
- Использует **smart filter** через дерево parent категории
- Пример: `category=1` — заказы с той же категорией, соседями (общий parent), родителем или дочерними

### 2. Район (location)
- Поиск по адресу заказа
- Пример: `location=Ташкент` или `location=Навои`
- Поиск нечувствителен к регистру (case-insensitive)

### 3. Тип ТС (car_category)
- ID категории машины типа **by_car**
- Прямой фильтр по ID
- Пример: `car_category=3` (где 3 - это "Легковой")

### 4. Приоритет (priority)
- Уровень приоритета заказа
- Значения: `low` (низкий) или `high` (высокий)
- Пример: `priority=high`

## Логика работы
1. Берутся координаты мастера из его профиля (Master.latitude, Master.longitude)
2. Фильтруются заказы где master=null И masters пустой список
3. Применяются дополнительные фильтры (category, location, car_category, priority)
4. Вычисляется расстояние от мастера до каждого заказа (Haversine formula)
5. Фильтруются заказы в пределах указанного радиуса
6. Сортировка по расстоянию (ближайшие сначала)

## Pagination
- По умолчанию 10 заказов на страницу
- Можно изменить через `page_size` (макс. 100)
- Навигация через `page` (номер страницы)

## Примеры запросов

**Базовый (только обязательные параметры):**
```
GET /api/order/available/?master_id=5
```

**С радиусом:**
```
GET /api/order/available/?master_id=5&radius=20
```

**С фильтром по проблеме:**
```
GET /api/order/available/?master_id=5&radius=15&category=1
```

**С несколькими фильтрами:**
```
GET /api/order/available/?master_id=5&radius=15&category=1&location=Ташкент&car_category=3&priority=high
```

**С пагинацией:**
```
GET /api/order/available/?master_id=5&radius=10&page=2&page_size=20
```
        """,
        tags=['Orders'],
        parameters=[
            OpenApiParameter(
                name='master_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='ID мастера (обязательно). Координаты берутся из профиля мастера.',
                required=True
            ),
            OpenApiParameter(
                name='radius',
                type=OpenApiTypes.FLOAT,
                location=OpenApiParameter.QUERY,
                description='Радиус поиска в километрах. По умолчанию 10 км. Можно указать от 1 до 100 км.',
                required=False
            ),
            OpenApiParameter(
                name='category',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Фильтр по типу проблемы. ID категории by_order. Smart filter по parent-дереву.',
                required=False
            ),
            OpenApiParameter(
                name='location',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Фильтр по району. Поиск по адресу заказа (например: "Ташкент", "Навои", "ул. Амира Темура").',
                required=False
            ),
            OpenApiParameter(
                name='car_category',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Фильтр по типу ТС. ID категории машины типа by_car (например: 3 для "Легковой").',
                required=False
            ),
            OpenApiParameter(
                name='priority',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Фильтр по приоритету. Допустимые значения: "low" (низкий) или "high" (высокий).',
                required=False
            ),
            OpenApiParameter(
                name='page',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Номер страницы для пагинации. Начинается с 1.',
                required=False
            ),
            OpenApiParameter(
                name='page_size',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Количество заказов на странице. По умолчанию 10, максимум 100.',
                required=False
            ),
        ],
        responses={
            200: {
                'description': 'Успешный ответ с пагинацией',
                'content': {
                    'application/json': {
                        'example': {
                            'count': 5,
                            'next': 'http://localhost:8000/api/order/available/?master_id=5&page=2',
                            'previous': None,
                            'results': [
                                {
                                    'id': 10,
                                    'user': {
                                        'id': 4,
                                        'private_id': '829137',
                                        'full_name': 'Иван Иванов',
                                        'phone_number': '998914495644',
                                        'email': 'ivan@example.com',
                                        'avatar': 'http://localhost:8000/media/avatars/avatar.jpg'
                                    },
                                    'car_data': [
                                        {
                                            'id': 2,
                                            'brand': 'Toyota',
                                            'model': 'Camry',
                                            'year': 2020,
                                            'category': {'id': 3, 'name': 'Легковой', 'type_category': 'by_car'}
                                        }
                                    ],
                                    'category_data': [
                                        {
                                            'id': 1,
                                            'name': 'Пробито колесо',
                                            'type_category': 'by_order',
                                            'parent': None
                                        }
                                    ],
                                    'text': 'Нужна помощь с заменой колеса',
                                    'status': 'pending',
                                    'priority': 'high',
                                    'location': 'ул. Навои, д. 15, Ташкент',
                                    'latitude': '41.3111000',
                                    'longitude': '69.2797000',
                                    'master': None,
                                    'masters': [],
                                    'distance': 2.35,
                                    'created_at': '2026-01-21T12:00:00Z',
                                    'updated_at': '2026-01-21T12:00:00Z'
                                }
                            ]
                        }
                    }
                }
            },
            400: {
                'description': 'Ошибка валидации параметров',
                'content': {
                    'application/json': {
                        'examples': {
                            'missing_master_id': {
                                'summary': 'Не указан master_id',
                                'value': {'error': 'Параметр master_id обязателен'}
                            },
                            'invalid_format': {
                                'summary': 'Неверный формат параметров',
                                'value': {'error': 'Неверный формат параметров'}
                            },
                            'no_coordinates': {
                                'summary': 'У мастера нет координат',
                                'value': {'error': 'У мастера не указаны координаты'}
                            }
                        }
                    }
                }
            },
            401: {
                'description': 'Не авторизован',
                'content': {
                    'application/json': {
                        'example': {'detail': 'Authentication credentials were not provided.'}
                    }
                }
            },
            404: {
                'description': 'Мастер не найден',
                'content': {
                    'application/json': {
                        'example': {'error': 'Master not found'}
                    }
                }
            },
        }
    )
    def get(self, request):
        """Получить доступные заказы для мастера"""
        # Получаем параметры
        master_id = request.query_params.get('master_id')
        radius = request.query_params.get('radius', 10)  # По умолчанию 10 км
        
        # Валидация обязательных параметров
        if not master_id:
            return Response(
                {'error': 'Параметр master_id обязателен'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            master_id = int(master_id)
            radius = float(radius)
        except (ValueError, TypeError):
            return Response(
                {'error': 'Неверный формат параметров'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Проверяем существование мастера
        try:
            master = Master.objects.get(id=master_id)
        except Master.DoesNotExist:
            return Response(
                {'error': 'Master not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Получаем координаты мастера
        if not master.latitude or not master.longitude:
            return Response(
                {'error': 'У мастера не указаны координаты'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        master_lat = float(master.latitude)
        master_long = float(master.longitude)
        
        # Получаем заказы без назначенного мастера
        # master=null И masters пустой (ManyToMany)
        from django.db.models import Count
        
        orders = Order.objects.annotate(
            masters_count=Count('masters')
        ).filter(
            master__isnull=True,
            masters_count=0,
            latitude__isnull=False,
            longitude__isnull=False
        )
        
        # Применяем дополнительные фильтры
        category_filter = request.query_params.get('category')
        location_filter = request.query_params.get('location')
        car_category_filter = request.query_params.get('car_category')
        priority_filter = request.query_params.get('priority')
        
        # Smart фильтр по категории проблемы (Тип проблемы)
        if category_filter:
            try:
                from apps.categories.models import Category
                category_id = int(category_filter)
                category = Category.objects.get(id=category_id)
                
                if category.type_category == 'by_order':
                    orders = orders.filter(order_by_order_category_smart_q(category))
                else:
                    # Для других типов - прямой фильтр по ID
                    orders = orders.filter(category__id=category_id)
                    
            except Category.DoesNotExist:
                pass
            except (ValueError, TypeError):
                pass
        
        # Фильтр по району (location)
        if location_filter:
            orders = orders.filter(location__icontains=location_filter)
        
        # Smart фильтр по типу ТС (car_category)
        if car_category_filter:
            try:
                from apps.categories.models import Category
                car_cat_id = int(car_category_filter)
                car_category = Category.objects.get(id=car_cat_id)
                
                # Прямой фильтр по ID категории машины
                orders = orders.filter(car__category__id=car_cat_id)
                
            except Category.DoesNotExist:
                pass
            except (ValueError, TypeError):
                pass
        
        # Фильтр по приоритету
        if priority_filter:
            orders = orders.filter(priority=priority_filter)
        
        # Убираем дубликаты после фильтров
        orders = orders.distinct()
        
        # Вычисляем расстояние и фильтруем по радиусу
        filtered_orders = []
        for order in orders:
            distance = self.calculate_distance(
                master_lat, master_long,
                float(order.latitude), float(order.longitude)
            )
            
            if distance <= radius:
                # Добавляем расстояние как атрибут
                order.distance = round(distance, 2)
                filtered_orders.append(order)
        
        # Сортируем по расстоянию (ближайшие сначала)
        filtered_orders.sort(key=lambda x: x.distance)
        
        # Применяем пагинацию
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(filtered_orders, request)
        if page is not None:
            serializer = OrderSerializer(page, many=True, context={'request': request})
            return paginator.get_paginated_response(serializer.data)
        
        serializer = OrderSerializer(filtered_orders, many=True, context={'request': request})
        return Response(serializer.data)


class AddServicesToOrderView(APIView):
    """
    API для добавления услуг к заказу
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="Добавить услуги к заказу",
        description="""
## Описание
Добавляет выбранные услуги мастера к заказу.

## Request Body
- `order_id`: ID заказа
- `services_list`: Список ID услуг мастера (MasterServiceItems)
- `discount`: Скидка на заказ (необязательно, по умолчанию 0.00)

## Пример запроса:
```json
{
  "order_id": 5,
  "services_list": [1, 2, 3, 4, 5],
  "discount": 150.00
}
```

## Response
Возвращает список добавленных услуг с полной информацией о каждой услуге.
        """,
        tags=['Orders'],
        request=AddServicesToOrderSerializer,
        responses={
            201: OrderServiceSerializer(many=True),
            400: {
                'type': 'object',
                'properties': {
                    'error': {'type': 'string'}
                },
                'examples': {
                    'application/json': {
                        'example': {'error': 'Заказ с ID 999 не найден'}
                    }
                }
            },
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        }
    )
    def post(self, request):
        """Добавить услуги к заказу"""
        serializer = AddServicesToOrderSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        order_id = serializer.validated_data['order_id']
        services_list = serializer.validated_data['services_list']
        discount = serializer.validated_data.get('discount', 0.00)
        
        # Получаем заказ
        try:
            order = Order.objects.get(id=order_id)
        except Order.DoesNotExist:
            return Response(
                {'error': f'Заказ с ID {order_id} не найден'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Обновляем скидку в заказе
        order.discount = discount
        order.save()
        
        # Создаем связи OrderService
        from apps.master.models import MasterServiceItems
        created_services = []
        
        for service_id in services_list:
            try:
                service_item = MasterServiceItems.objects.get(id=service_id)
                # Используем get_or_create чтобы избежать дубликатов
                order_service, created = OrderService.objects.get_or_create(
                    order=order,
                    master_service_item=service_item
                )
                created_services.append(order_service)
            except MasterServiceItems.DoesNotExist:
                continue
        
        # Сериализуем результат
        result_serializer = OrderServiceSerializer(created_services, many=True)
        return Response(result_serializer.data, status=status.HTTP_201_CREATED)


class MasterServicesListView(APIView):
    """
    API для получения услуг мастера
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="Получить услуги мастера",
        description="""
## Описание
Возвращает список всех услуг (MasterServiceItems) для указанного мастера.
Формат ответа аналогичен формату в detail мастера.

## Параметры
- `master_id`: ID мастера (обязательный)

## Пример запроса:
```
GET /api/order/services-list/?master_id=5
```

## Response
Возвращает навыки мастера: подкатегория каталога (by_order) + цена мастера.
        """,
        tags=['Orders'],
        parameters=[
            OpenApiParameter(
                name='master_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='ID мастера',
                required=True
            ),
        ],
        responses={
            200: {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'integer'},
                        'category': {'type': 'integer'},
                        'service_name': {'type': 'string'},
                        'parent_category_id': {'type': 'integer', 'nullable': True},
                        'parent_category_name': {'type': 'string', 'nullable': True},
                        'price': {'type': 'number'},
                        'master_service': {'type': 'integer'},
                    }
                },
                'example': [
                    {
                        'id': 1,
                        'category': 12,
                        'service_name': 'Headlight Restoration',
                        'parent_category_id': 3,
                        'parent_category_name': 'Lights',
                        'price': 100.0,
                        'master_service': 5,
                    }
                ]
            },
            400: {
                'type': 'object',
                'properties': {'error': {'type': 'string'}},
                'example': {'error': 'Параметр master_id обязателен'}
            },
            404: {
                'type': 'object',
                'properties': {'error': {'type': 'string'}},
                'example': {'error': 'Master not found'}
            },
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        }
    )
    def get(self, request):
        """Получить услуги мастера"""
        master_id = request.query_params.get('master_id')
        
        if not master_id:
            return Response(
                {'error': 'Параметр master_id обязателен'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            master_id = int(master_id)
        except ValueError:
            return Response(
                {'error': 'Неверный формат master_id'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Проверяем существование мастера
        try:
            master = Master.objects.get(id=master_id)
        except Master.DoesNotExist:
            return Response(
                {'error': 'Master not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Получаем все MasterServiceItems для этого мастера
        from apps.master.models import MasterServiceItems, MasterService
        from apps.master.serializers import MasterServiceItemsSerializer
        
        # Находим все MasterService для этого мастера
        master_services = MasterService.objects.filter(master=master)
        
        # Получаем все items этих services
        service_items = MasterServiceItems.objects.filter(
            master_service__in=master_services
        ).select_related('category', 'master_service')
        
        # Сериализуем
        serializer = MasterServiceItemsSerializer(service_items, many=True)
        return Response(serializer.data)


class AddMastersToOrderView(APIView):
    """
    API для добавления мастеров к заказу
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="Добавить мастеров к заказу",
        description="""
## Описание
Добавляет выбранных пользователей-мастеров к заказу.
Эти мастера будут назначены на заказ и получат уведомление.

## Request Body
- `order_id`: ID заказа (обязательно)
- `master_ids`: Список ID пользователей-мастеров [1, 2, 3, ...] (обязательно)

## Пример запроса:
```json
{
  "order_id": 5,
  "master_ids": [1, 2, 3]
}
```

## Response
Возвращает обновленный заказ со списком назначенных мастеров.

## 🎯 Когда использовать?
- Когда нужно назначить несколько мастеров на один заказ
- Когда мастер хочет делегировать заказ своим сотрудникам
- Для командной работы над сложным заказом
        """,
        tags=['Orders'],
        request=AddMastersToOrderSerializer,
        responses={
            200: OrderSerializer,
            400: {
                'type': 'object',
                'properties': {'error': {'type': 'string'}},
                'example': {'error': 'Заказ с ID 999 не найден'}
            },
            404: {
                'type': 'object',
                'properties': {'error': {'type': 'string'}},
                'example': {'error': 'Order not found'}
            },
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        }
    )
    def post(self, request):
        """Добавить мастеров к заказу"""
        serializer = AddMastersToOrderSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        order_id = serializer.validated_data['order_id']
        master_ids = serializer.validated_data['master_ids']
        
        # Получаем заказ
        try:
            order = Order.objects.get(id=order_id)
        except Order.DoesNotExist:
            return Response(
                {'error': f'Заказ с ID {order_id} не найден'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Добавляем мастеров к заказу (ManyToMany)
        for master_id in master_ids:
            try:
                user = User.objects.get(id=master_id)
                order.masters.add(user)
            except User.DoesNotExist:
                continue
        
        # Возвращаем обновленный заказ
        order.refresh_from_db()
        result_serializer = OrderSerializer(order, context={'request': request})
        return Response(result_serializer.data, status=status.HTTP_200_OK)
