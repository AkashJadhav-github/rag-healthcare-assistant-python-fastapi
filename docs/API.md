# API Documentation

Base URL: `https://api.healthcare-rag.example.com/api/v1`  
Auth: All endpoints (except `/health/*`) require `Authorization: Bearer <token>`

---

## Authentication

### POST /auth/login
Login and obtain access + refresh tokens.

**Request (form-data)**:
| Field | Type | Description |
|-------|------|-------------|
| username | string | Email address |
| password | string | Password |

**Response 200**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiJ9...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

### GET /auth/me
Returns current user profile.

### POST /auth/logout
Invalidates session cache.

---

## Knowledge

### POST /knowledge/ask
Submit a clinical query and receive a RAG-grounded answer with citations.

**Roles**: viewer, clinician, researcher, admin  
**Rate limit**: 60/minute

**Request**:
```json
{
  "query": "What are the first-line treatments for hypertension in CKD patients?",
  "session_id": "optional-session-uuid",
  "max_sources": 5,
  "include_sources": true,
  "stream": false
}
```

**Response 200**:
```json
{
  "query_id": "uuid",
  "answer": "Based on ACC/AHA guidelines [Source: Clinical Guidelines 2024, Page 12]...\n\n⚠️ Always verify with current clinical guidelines and consult a specialist.",
  "sources": [
    {
      "document_title": "Hypertension Clinical Practice Guidelines 2024",
      "document_id": "uuid",
      "chunk_content": "For CKD with proteinuria, ACEi or ARB is preferred...",
      "similarity_score": 0.923,
      "rank": 1,
      "page_number": 12,
      "section": "Special Populations"
    }
  ],
  "confidence_score": 0.87,
  "latency_ms": 1250,
  "was_cached": false,
  "model_used": "gpt-4-turbo-preview"
}
```

---

### POST /knowledge/ingest
Upload a document for RAG indexing. Processing happens asynchronously.

**Roles**: clinician, researcher, admin  
**Max file size**: 50MB  
**Supported formats**: pdf, docx, txt, md

**Request (multipart/form-data)**:
| Field | Type | Required |
|-------|------|----------|
| file | File | Yes |
| title | string | No (defaults to filename) |
| category | string | No (clinical_guideline, research_paper, hospital_policy, hl7_standard, medication_db, medical_glossary) |
| source | string | No |

**Response 200**:
```json
{
  "document_id": "uuid",
  "title": "ADA Standards of Care 2024",
  "status": "pending",
  "message": "Document queued for processing"
}
```

---

### GET /knowledge/history
Retrieve the current user's query history.

**Query params**: `page` (default 1), `page_size` (default 20)

**Response 200**: Array of query history items with sources count.

---

## Admin

### POST /admin/reindex
Rebuild vector indices for one or all documents. Admin role required.

**Query param**: `document_id` (optional — omit for full reindex)

**Response 200**:
```json
{
  "status": "accepted",
  "message": "Reindexing 42 document(s) in the background",
  "documents_queued": 42
}
```

### GET /admin/stats
System statistics (admin only).

### POST /admin/users
Create a new user account (admin only).

---

## Health

### GET /health
Full system health with component status and latencies.

### GET /health/live
Kubernetes liveness probe — always returns 200 if process is alive.

### GET /health/ready
Kubernetes readiness probe — returns 503 if database is unavailable.

### GET /health/metrics
Prometheus metrics endpoint.

---

## Error Responses

| Code | Meaning |
|------|---------|
| 400 | Bad request (validation error) |
| 401 | Missing or invalid token |
| 403 | Insufficient permissions |
| 404 | Resource not found |
| 413 | File too large |
| 422 | Request validation failed |
| 429 | Rate limit exceeded |
| 500 | Internal server error |

```json
{"detail": "Human-readable error description"}
```
