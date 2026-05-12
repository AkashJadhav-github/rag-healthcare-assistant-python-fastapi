# Architecture — RAG Healthcare Knowledge Assistant

## 1. High-Level System Design

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Internet / VPN                               │
└─────────────────────────────┬───────────────────────────────────────┘
                               │ HTTPS (TLS 1.3)
                    ┌──────────▼──────────┐
                    │   Load Balancer /   │
                    │   API Gateway /     │
                    │   Nginx Ingress     │
                    └──────────┬──────────┘
                               │
         ┌─────────────────────▼───────────────────────┐
         │              FastAPI Backend (3+ replicas)   │
         │  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
         │  │  Auth &  │  │ Knowledge│  │  Admin   │   │
         │  │  JWT/RBAC│  │  /ask    │  │  /reindex│   │
         │  └────┬─────┘  └────┬─────┘  └─────┬────┘   │
         └───────┼─────────────┼──────────────┼─────────┘
                 │             │              │
         ┌───────▼─────────────▼──────────────▼─────────┐
         │                RAG Pipeline                    │
         │  ┌────────────┐  ┌─────────────┐             │
         │  │Query Enhance│  │ PII Masking │             │
         │  └────────────┘  └─────────────┘             │
         │  ┌────────────┐  ┌─────────────┐             │
         │  │ Embeddings │  │  Retrieval  │             │
         │  │(ada-002)   │  │(Hybrid/RRF) │             │
         │  └────────────┘  └─────────────┘             │
         │  ┌────────────────────────────────┐          │
         │  │     LLM Generation (GPT-4)     │          │
         │  │     + Source Citations          │          │
         │  └────────────────────────────────┘          │
         └───────────────────────────────────────────────┘
                 │             │              │
    ┌────────────▼──┐   ┌──────▼───┐   ┌─────▼────────┐
    │  PostgreSQL   │   │  Redis   │   │   Observ.    │
    │  + pgvector   │   │  Cache   │   │   Stack      │
    │  (embeddings, │   │  (query  │   │  Prometheus  │
    │  audit, users)│   │  cache,  │   │  Grafana     │
    │               │   │  sessions│   │  Jaeger      │
    └───────────────┘   └──────────┘   └──────────────┘
```

## 2. Component Responsibilities

| Component | Responsibility |
|-----------|---------------|
| **FastAPI Backend** | REST API, JWT auth, RBAC, request routing, audit trail |
| **RAG Pipeline** | Query enhancement, chunking, embedding, retrieval, generation |
| **PostgreSQL + pgvector** | Document metadata, user data, audit logs, vector embeddings |
| **Redis** | Query response cache, session tokens, rate limiting counters |
| **LLM (GPT-4/Claude)** | Generates grounded clinical answers with source citations |
| **Embedding Service** | Converts text to dense vectors (OpenAI ada-002 or local) |
| **Prometheus/Grafana** | Metrics collection, SLI dashboards, alerting |
| **Jaeger** | Distributed request tracing across services |

## 3. Data Flow

### Query Path (POST /api/v1/knowledge/ask)
```
User Request → JWT Verify → Rate Limit → Cache Check →
  PII Mask Query → Enhance Query → Embed Query →
  Hybrid Search (Vector + Keyword) → RRF Fusion →
  LLM Generation (GPT-4 + context) → PII Mask Response →
  Cache Response → Audit Log → Return with Citations
```

### Ingestion Path (POST /api/v1/knowledge/ingest)
```
Upload File → Auth + RBAC → Validate Format/Size →
  Background Task → Parse Document (PDF/DOCX/TXT) →
  Medical Chunking (1000 tok, 200 overlap) →
  Batch Embedding (ada-002, 50 chunks/batch) →
  Store in pgvector → Update Document Status
```

## 4. Database Schema

### Key Tables

**users** — Authentication and RBAC  
**documents** — Document metadata and ingestion status  
**document_chunks** — Text chunks with pgvector embedding column  
**query_logs** — Query history, latency, LLM usage  
**query_sources** — Source citations per query  
**audit_logs** — HIPAA-compliant access trail  

### Vector Index (pgvector)
```sql
CREATE INDEX ON document_chunks
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);
```

## 5. Security Architecture

- **Transport**: TLS 1.3 end-to-end
- **Authentication**: JWT (RS256), 30-min access token + 7-day refresh
- **Authorization**: RBAC (admin, clinician, researcher, viewer)
- **Data at rest**: PostgreSQL TDE + filesystem encryption (AES-256)
- **PII Protection**: Regex-based PHI detection before LLM and in responses
- **Prompt Injection**: Query sanitization strips system prompt override attempts
- **Rate Limiting**: Redis-backed per-IP + per-user limits
- **Audit Trail**: Every query, document access, admin action logged with IP, timestamp, user

## 6. Scalability Strategy

- **Horizontal scaling**: FastAPI stateless — scale via HPA (3→20 replicas)
- **Connection pooling**: SQLAlchemy async pool (20 connections per pod)
- **Cache**: Redis reduces LLM calls by ~30-40% for repeated queries
- **Batch embeddings**: Process 50 chunks concurrently per document
- **Vector index**: IVFFlat with 100 lists; upgrade to HNSW at >1M chunks
- **Read replicas**: Add PostgreSQL read replica for query-heavy load

## 7. Failure Scenarios

| Failure | Mitigation |
|---------|-----------|
| LLM API down | Fallback to raw retrieval result; circuit breaker |
| Redis down | Degrade gracefully (disable cache, continue) |
| PostgreSQL down | Health probe fails; K8s stops routing traffic |
| Embedding API down | Fall back to local sentence-transformers model |
| High latency | HPA scales up pods; cache absorbs repeat queries |
