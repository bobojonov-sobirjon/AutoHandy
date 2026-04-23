# Chat (Admin + Push)

This app provides 1:1 chat between users via:

- **REST** endpoints in `apps/chat/views.py` (sending messages, listing rooms/messages)
- **WebSocket** consumer in `apps/chat/consumers.py` (real-time updates)
- **Push notifications** via `apps/order/services/notifications.py` (`kind=chat_message`)

## WebSocket

### URL

- **Connect**: `ws://<host>/ws/chat/<room_id>/`
- **Auth**: JWT is expected via query string (handled by `TokenAuthMiddleware` in `config/asgi.py`).

Example:

- `ws://127.0.0.1:8001/ws/chat/123/?token=<JWT>`

### Incoming client messages (JSON)

The consumer expects JSON frames with a `type` field.

#### 1) Send a text message (saved by WebSocket)

```json
{
  "type": "chat_message",
  "message_type": "text",
  "text": "Hello!"
}
```

#### 1b) Send image / file / audio via WebSocket (base64)

You can send binary payloads directly over WebSocket using base64.

**Image (single):**

```json
{
  "type": "chat_message",
  "message_type": "image",
  "text": "optional caption",
  "image_name": "photo.jpg",
  "image_base64": "<BASE64 or data:image/jpeg;base64,...>"
}
```

**File:**

```json
{
  "type": "chat_message",
  "message_type": "file",
  "text": "optional description",
  "file_name": "document.pdf",
  "file_base64": "<BASE64>"
}
```

**Audio:**

```json
{
  "type": "chat_message",
  "message_type": "audio",
  "audio_name": "voice.m4a",
  "audio_base64": "<BASE64>"
}
```

**Limits:** by default the server accepts up to **5 MB** per uploaded file (`CHAT_WS_MAX_UPLOAD_BYTES`).

#### 1c) Multiple images via WebSocket (gallery / batch)

Send `message_type=image` with an `images` array. The backend will create **multiple** messages (one per image)
but will return/broadcast a **single** message object with `images: [...]` (gallery).

```json
{
  "type": "chat_message",
  "message_type": "image",
  "text": "optional caption (applied to each)",
  "images": [
    { "name": "1.jpg", "base64": "<BASE64>" },
    { "name": "2.jpg", "base64": "<BASE64>" }
  ]
}
```

#### 2) Broadcast an already-uploaded attachment (REST → WS)

For `image`, `file`, `audio` messages, upload the message via REST first (so the binary is stored),
then broadcast it over WebSocket by passing the created `message_id`.

```json
{
  "type": "chat_message",
  "message_id": 555
}
```

#### 3) Typing indicator

```json
{
  "type": "typing",
  "is_typing": true
}
```

#### 4) Read receipt

```json
{
  "type": "read_receipt",
  "message_id": 555
}
```

### Outgoing server events (JSON)

#### Chat message broadcast

```json
{
  "type": "chat_message",
  "message": {
    "id": 555,
    "room_id": 123,
    "sender": { "id": 4, "full_name": "..." },
    "message_type": "image",
    "text": "",
    "file": null,
    "image": "https://.../media/chat/images/...",
    "audio": null,
    "is_read": false,
    "created_at": "2026-04-23T09:10:00Z"
  }
}
```

#### Chat message batch (multiple images)

When you send multiple images, the server broadcasts a single `chat_message` event where the `message`
has an `images` field (gallery).

```json
{
  "type": "chat_message",
  "message": {
    "id": 10,
    "room_id": 1,
    "message_type": "image",
    "text": "optional caption",
    "image": null,
    "images": [
      { "id": 10, "image_name": "1.jpg", "image": "https://.../1.jpg" },
      { "id": 11, "image_name": "2.jpg", "image": "https://.../2.jpg" }
    ]
  }
}
```

#### ACK back to sender

Every successful send returns an ACK to the sender:

```json
{
  "type": "chat_message_ack",
  "messages": [ { "...message payload..." } ],
  "ack": true
}
```

#### Typing broadcast

```json
{
  "type": "typing",
  "user_id": 4,
  "is_typing": true
}
```

#### Read receipt broadcast

```json
{
  "type": "read_receipt",
  "message_id": 555,
  "user_id": 4
}
```

## REST (optional fallback)

If you don't want to send base64 over WebSocket (or you hit size limits), you can upload attachments via REST.
After REST creates the `ChatMessage`, broadcast the returned `message_id` over WebSocket (see above).

Relevant endpoints are in `apps/chat/urls.py`:

- `GET/POST /api/chat/rooms/`
- `GET /api/chat/rooms/<room_id>/`
- `GET/POST /api/chat/rooms/<room_id>/messages/`
- `POST /api/chat/rooms/<room_id>/mark-read/`

### Send image / file / audio (single)

Use **`multipart/form-data`** on:

- `POST /api/chat/rooms/<room_id>/messages/`

#### Image

Form fields:

- `message_type`: `image`
- `image`: `<file>`

Optional:

- `text`: caption (optional)

#### File

Form fields:

- `message_type`: `file`
- `file`: `<file>`

Optional:

- `text`: description (optional)

#### Audio

Form fields:

- `message_type`: `audio`
- `audio`: `<file>`

After REST returns `id` (message id), broadcast over WS:

```json
{ "type": "chat_message", "message_id": 555 }
```

### Multiple images (gallery)

If you prefer REST for uploads, you can still send multiple images by creating multiple messages
via REST (one image per request) and broadcasting each `message_id` over WebSocket.

## Admin panel

Chat models are available in Django Admin:

- **Chat rooms**: `ChatRoom`
  - Shows participants, initiator, timestamps
  - Includes **inline messages** (latest first)
  - Shows linked **Order** (and order type) if the room was auto-created for an order
  - Messages are shown **inline** (no separate ChatMessage section in the menu)

Admin configuration lives in `apps/chat/admin.py`.

## Data model

- `ChatRoom`
  - `participants` (many-to-many users)
  - `initiator` (user who started the room; optional)
- `ChatMessage`
  - `room` (FK)
  - `sender` (FK)
  - `message_type`: `text | image | file | audio`
  - Optional media fields: `image`, `file`, `audio`

## Push payload shape

When a message is sent, the other participant receives an FCM push with:

- `kind`: `chat_message`
- `room_id`, `message_id`, `message_type`

