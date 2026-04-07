# 11 — API Reference

Base URL: `http://localhost:8000/api/v1`

Interactive docs (Swagger UI): `http://localhost:8000/docs`

All endpoints except `/auth/register` and `/auth/login` require a Bearer token:
```
Authorization: Bearer <access_token>
```

---

## Authentication

### POST /auth/register
Create a new student account.

**Request:**
```json
{
  "email": "student@example.com",
  "password": "mypassword123",
  "full_name": "John Doe"
}
```

**Response (201):**
```json
{
  "id": "uuid",
  "email": "student@example.com",
  "full_name": "John Doe",
  "role": "student",
  "is_active": true,
  "created_at": "2024-01-01T10:00:00Z"
}
```

**Errors:**
- `409` — email already registered

---

### POST /auth/login
Authenticate and receive JWT tokens.

**Request:**
```json
{
  "email": "admin@studyrag.com",
  "password": "admin123"
}
```

**Response (200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Errors:**
- `401` — invalid credentials
- `403` — account is blocked

Access token expires in 60 minutes. Refresh token expires in 7 days.

---

### POST /auth/refresh
Exchange a refresh token for a new token pair. The old refresh token is revoked.

**Request:**
```json
{
  "refresh_token": "eyJ..."
}
```

**Response (200):** Same format as `/auth/login`

---

### GET /auth/me
Return the currently authenticated user.

**Response (200):** Same format as user object in register response.

---

## Documents

All document endpoints require authentication. Upload and delete require admin or staff role.

### POST /documents/upload
Upload a document for processing.

**Request:** `multipart/form-data`
| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `file` | File | Yes | PDF, DOCX, TXT, or MD; max 50 MB |
| `document_type` | string | Yes | `notes`, `university_exam`, or `syllabus` |
| `subject_name` | string | No | For exams — the subject name |
| `subject_code` | string | No | For exams — the subject code |

**Response (201):**
```json
{
  "document_id": "uuid",
  "filename": "data_comms_notes.pdf",
  "document_type": "notes",
  "status": "pending",
  "task_id": "celery-task-uuid",
  "message": "Document queued for processing."
}
```

---

### GET /documents/{document_id}/status
Check the processing status of a document.

**Response (200):**
```json
{
  "document_id": "uuid",
  "status": "indexed",
  "filename": "data_comms_notes.pdf",
  "document_type": "notes",
  "subject_name": "Data Communications and Computer Networks",
  "subject_code": null,
  "page_count": 335,
  "chunk_count": 334,
  "created_at": "2024-01-01T10:00:00Z",
  "error_message": null
}
```

**Status values:**
- `pending` — waiting for Celery worker to pick up
- `processing` — being processed right now
- `indexed` — successfully processed, searchable
- `failed` — processing failed (see `error_message`)

---

### GET /documents/
List all documents with optional filtering.

**Query parameters:**
- `page` (default: 1)
- `page_size` (default: 20)
- `document_type` — filter by type

**Response (200):**
```json
{
  "documents": [ { ...status_response... } ],
  "total": 5,
  "page": 1,
  "page_size": 20
}
```

---

### DELETE /documents/{document_id}
Delete a document and all its associated chunks/notes/syllabus entries. Also deletes the file from GCS. Admin only.

**Response:** `204 No Content`

---

## Chat

### POST /chat/conversations
Create a new conversation.

**Request:**
```json
{
  "title": "My First Chat",
  "session_type": "permanent"
}
```

**Response (201):**
```json
{
  "id": "uuid",
  "title": "My First Chat",
  "session_type": "permanent",
  "summary": null,
  "created_at": "2024-01-01T10:00:00Z",
  "message_count": 0
}
```

---

### GET /chat/conversations
List all conversations for the current user.

**Query parameters:** `page`, `page_size`

**Response (200):** Array of conversation objects.

---

### GET /chat/conversations/{conversation_id}
Get full conversation history.

**Response (200):**
```json
{
  "conversation": { ...conversation_object... },
  "messages": [
    {
      "id": "uuid",
      "role": "user",
      "content": "What is k-means clustering?",
      "created_at": "2024-01-01T10:00:00Z"
    },
    {
      "id": "uuid",
      "role": "assistant",
      "content": "K-means clustering is an unsupervised algorithm...",
      "created_at": "2024-01-01T10:00:02Z"
    }
  ]
}
```

---

### POST /chat/query
Send a message and receive a complete RAG answer.

**Request:**
```json
{
  "conversation_id": "uuid",
  "message": "What questions appeared in the exam from unit 3 of Machine Learning?"
}
```

**Response (200):**
```json
{
  "message_id": "uuid",
  "conversation_id": "uuid",
  "answer": "Based on the exam papers, the following questions appeared from Unit 3 (Unsupervised learning):\n\n**Part B — Q3 (10 marks):** Explain k-means clustering with an example...\n\n[Exam Q1]",
  "intent": "cross_reference",
  "sources": [
    {
      "chunk_id": "uuid",
      "source_type": "exam",
      "subject_name": "Machine Learning",
      "subject_code": "6CAI4-02",
      "excerpt": "[Subject: Machine Learning | Part B | Q3 | 10 marks]\nExplain k-means clustering...",
      "relevance_score": 0.8234
    },
    {
      "chunk_id": "uuid",
      "source_type": "notes",
      "subject_name": "Machine Learning",
      "subject_code": null,
      "excerpt": "K-means is an iterative algorithm that partitions data into k clusters...",
      "relevance_score": 0.7812
    }
  ],
  "model_used": "gemini-2.5-pro",
  "latency_ms": 4821
}
```

**Errors:**
- `404` — conversation not found (or belongs to another user)
- `429` — rate limit exceeded (60 requests/minute for authenticated users)

---

### POST /chat/query/stream
Send a message and receive a streaming response via Server-Sent Events.

**Request:** Same as `/chat/query`

**Response:** `text/event-stream`

Token chunks arrive as:
```
data: {"token": "Based"}
data: {"token": " on"}
data: {"token": " the"}
...
data: {"done": true}
```

On error:
```
data: {"error": "description"}
```

---

## Admin

All admin endpoints require `role = admin` or `role = staff`.

### GET /admin/users
List all users.

**Query parameters:** `page`, `page_size`

**Response (200):** Array of user objects.

---

### PATCH /admin/users/{user_id}/role
Change a user's role. Cannot change your own role.

**Request:**
```json
{ "role": "staff" }
```

**Response (200):** Updated user object.

---

### PATCH /admin/users/{user_id}/block
Block or unblock a user. Cannot block yourself.

**Request:**
```json
{ "is_active": false, "reason": "Violated terms of service" }
```

**Response (200):** Updated user object.

---

### GET /admin/users/{user_id}/conversations
View all conversations belonging to a user (for monitoring).

**Response (200):** Array of conversation objects.

---

### GET /admin/conversations/{conversation_id}
View full conversation history of any user.

**Response (200):** Same as `GET /chat/conversations/{id}`.

---

### GET /admin/stats
System-wide statistics.

**Response (200):**
```json
{
  "total_users": 45,
  "total_documents": 12,
  "total_conversations": 234,
  "total_messages": 1872
}
```

---

## Health Check

### GET /health

```json
{ "status": "ok", "version": "1.0.0" }
```

---

## Error Response Format

All errors follow Pydantic v2's format:

**Standard error:**
```json
{ "detail": "Error message here" }
```

**Validation error (422):**
```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "message"],
      "msg": "String should have at least 1 character",
      "input": "",
      "ctx": { "min_length": 1 }
    }
  ]
}
```

> **Frontend note:** Always check if `detail` is a string or an array before displaying it.

---

## Rate Limits

| Endpoint group | Limit |
|---------------|-------|
| `/auth/register`, `/auth/login`, `/auth/refresh` | 10 requests/minute per IP |
| All authenticated endpoints | 60 requests/minute per user |
| `/documents/upload` | 10 requests/minute per user |

Rate limit exceeded returns `429 Too Many Requests`.
