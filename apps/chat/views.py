from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q, Max
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from .models import ChatRoom, ChatMessage
from .serializers import (
    ChatRoomSerializer, ChatMessageSerializer,
    CreateChatRoomSerializer, SendMessageSerializer
)


class ChatPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class ChatRoomListCreateView(APIView):
    """
    API for listing chats and creating a new chat
    """
    permission_classes = [IsAuthenticated]
    pagination_class = ChatPagination

    @extend_schema(
        summary="Get chat list",
        description="""
## Get all chats for the current user

Returns list of chat rooms with:
- Participants
- Last message
- Unread message count
- Sorted by last activity

## Response:
```json
[
  {
    "id": 1,
    "participants": [...],
    "other_participant": {
      "id": 5,
      "full_name": "John",
      "avatar": "..."
    },
    "last_message": {
      "text": "Hello! How are you?",
      "created_at": "2026-01-31T10:00:00Z"
    },
    "unread_count": 3,
    "created_at": "2026-01-30T10:00:00Z"
  }
]
```
        """,
        tags=['Chat'],
        responses={
            200: ChatRoomSerializer(many=True),
            401: {'description': 'Not authenticated'}
        }
    )
    def get(self, request):
        """Get chat list"""
        rooms = ChatRoom.objects.filter(
            participants=request.user
        ).prefetch_related('participants', 'messages').distinct()

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(rooms, request)
        if page is not None:
            serializer = ChatRoomSerializer(page, many=True, context={'request': request})
            return paginator.get_paginated_response(serializer.data)

        serializer = ChatRoomSerializer(rooms, many=True, context={'request': request})
        return Response(serializer.data)

    @extend_schema(
        summary="Create new chat",
        description="""
## Create a new chat room

Creates a chat between the current user and the specified participant.
If chat already exists, returns the existing chat.

## Request Body:
```json
{
  "participant_id": 5
}
```

## Response:
```json
{
  "id": 1,
  "participants": [...],
  "other_participant": {...},
  "last_message": null,
  "unread_count": 0,
  "created_at": "2026-01-31T10:00:00Z"
}
```
        """,
        tags=['Chat'],
        request=CreateChatRoomSerializer,
        responses={
            201: ChatRoomSerializer,
            400: {'description': 'Validation error'},
            401: {'description': 'Not authenticated'}
        }
    )
    def post(self, request):
        """Create new chat"""
        serializer = CreateChatRoomSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        participant_id = serializer.validated_data['participant_id']

        existing_room = ChatRoom.objects.filter(
            participants=request.user
        ).filter(
            participants=participant_id
        ).first()

        if existing_room:
            result_serializer = ChatRoomSerializer(existing_room, context={'request': request})
            return Response(result_serializer.data, status=status.HTTP_200_OK)

        room = ChatRoom.objects.create(initiator=request.user)
        room.participants.add(request.user, participant_id)

        result_serializer = ChatRoomSerializer(room, context={'request': request})
        return Response(result_serializer.data, status=status.HTTP_201_CREATED)


class ChatRoomDetailView(APIView):
    """
    API for chat detail
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get chat details",
        description="Returns chat room information",
        tags=['Chat'],
        responses={
            200: ChatRoomSerializer,
            403: {'description': 'Access denied'},
            404: {'description': 'Chat not found'}
        }
    )
    def get(self, request, room_id):
        """Get chat details"""
        try:
            room = ChatRoom.objects.get(id=room_id)

            if not room.participants.filter(id=request.user.id).exists():
                return Response(
                    {'error': 'You do not have access to this chat'},
                    status=status.HTTP_403_FORBIDDEN
                )

            serializer = ChatRoomSerializer(room, context={'request': request})
            return Response(serializer.data)

        except ChatRoom.DoesNotExist:
            return Response(
                {'error': 'Chat not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class ChatMessagesView(APIView):
    """
    API for getting chat messages and sending new ones
    """
    permission_classes = [IsAuthenticated]
    pagination_class = ChatPagination

    @extend_schema(
        summary="Get chat messages",
        description="""
## Get chat message history

Returns list of messages with pagination.

## Query Parameters:
- `page`: Page number (default: 1)
- `page_size`: Messages per page (default: 20, max: 100)

## Response:
```json
{
  "count": 150,
  "next": "...",
  "previous": "...",
  "results": [
    {
      "id": 1,
      "sender": {...},
      "message_type": "text",
      "text": "Hello!",
      "is_read": true,
      "created_at": "2026-01-31T10:00:00Z"
    }
  ]
}
```
        """,
        tags=['Chat'],
        responses={
            200: ChatMessageSerializer(many=True),
            403: {'description': 'Access denied'},
            404: {'description': 'Chat not found'}
        }
    )
    def get(self, request, room_id):
        """Get chat messages"""
        try:
            room = ChatRoom.objects.get(id=room_id)

            if not room.participants.filter(id=request.user.id).exists():
                return Response(
                    {'error': 'You do not have access to this chat'},
                    status=status.HTTP_403_FORBIDDEN
                )

            messages = room.messages.select_related('sender').order_by('-created_at')

            paginator = self.pagination_class()
            page = paginator.paginate_queryset(messages, request)
            if page is not None:
                serializer = ChatMessageSerializer(page, many=True, context={'request': request})
                return paginator.get_paginated_response(serializer.data)

            serializer = ChatMessageSerializer(messages, many=True, context={'request': request})
            return Response(serializer.data)

        except ChatRoom.DoesNotExist:
            return Response(
                {'error': 'Chat not found'},
                status=status.HTTP_404_NOT_FOUND
            )

    @extend_schema(
        summary="Send message",
        description="""
## Send a new message to chat

Supported message types:
- `text`: Text message
- `image`: Image
- `file`: File
- `audio`: Audio message

## Request Body (FormData for files):
```
room: 1
message_type: "text"
text: "Hello!"
```

Or for image:
```
room: 1
message_type: "image"
image: <file>
```
        """,
        tags=['Chat'],
        request=SendMessageSerializer,
        responses={
            201: ChatMessageSerializer,
            400: {'description': 'Validation error'},
            403: {'description': 'Access denied'},
            404: {'description': 'Chat not found'}
        }
    )
    def post(self, request, room_id):
        """Send message"""
        try:
            room = ChatRoom.objects.get(id=room_id)

            if not room.participants.filter(id=request.user.id).exists():
                return Response(
                    {'error': 'You do not have access to this chat'},
                    status=status.HTTP_403_FORBIDDEN
                )

            data = request.data.copy()
            data['room'] = room.id

            serializer = SendMessageSerializer(data=data, context={'request': request})
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            message = serializer.save(sender=request.user)

            room.save()

            result_serializer = ChatMessageSerializer(message, context={'request': request})
            return Response(result_serializer.data, status=status.HTTP_201_CREATED)

        except ChatRoom.DoesNotExist:
            return Response(
                {'error': 'Chat not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class MarkAsReadView(APIView):
    """
    API for marking messages as read
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Mark messages as read",
        description="""
## Mark all chat messages as read

Marks all unread messages in the chat as read.
        """,
        tags=['Chat'],
        responses={
            200: {'description': 'Messages marked as read'},
            403: {'description': 'Access denied'},
            404: {'description': 'Chat not found'}
        }
    )
    def post(self, request, room_id):
        """Mark as read"""
        try:
            room = ChatRoom.objects.get(id=room_id)

            if not room.participants.filter(id=request.user.id).exists():
                return Response(
                    {'error': 'You do not have access to this chat'},
                    status=status.HTTP_403_FORBIDDEN
                )

            updated_count = room.messages.filter(
                is_read=False
            ).exclude(
                sender=request.user
            ).update(is_read=True)

            return Response({
                'message': f'{updated_count} messages marked as read'
            })

        except ChatRoom.DoesNotExist:
            return Response(
                {'error': 'Chat not found'},
                status=status.HTTP_404_NOT_FOUND
            )
