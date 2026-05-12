# RAG Healthcare Knowledge Assistant

Production-ready Retrieval-Augmented Generation (RAG) system for healthcare domain knowledge.
Provides accurate, cited clinical answers from your medical knowledge base with HIPAA compliance.

## Architecture

- **Backend**: Python FastAPI with async I/O
- **RAG Framework**: LangChain + custom hybrid retrieval
- **Vector DB**: PostgreSQL 16 + pgvector (IVFFlat index)
- **LLM**: OpenAI GPT-4 / Anthropic Claude (configurable)
- **Embeddings**: OpenAI text-embedding-ada-002 (1536 dims)
- **Cache**: Redis 7 (query responses + rate limiting)
- **Deployment**: Docker Compose (dev) / Kubernetes (prod)
- **Monitoring**: Prometheus + Grafana + Jaeger

## Quick Start

```bash
# 1. Clone
git clone https://github.com/your-org/rag-healthcare-assistant
cd rag-healthcare-assistant

# 2. Configure
cp .env.example .env
# Set OPENAI_API_KEY in .env

# 3. Start
docker-compose up -d

# 4. Verify
curl http://localhost:8000/api/v1/health

# 5. Load sample data
pip install httpx
python scripts/load_sample_data.py

# 6. Query
curl -X POST http://localhost:8000/api/v1/auth/login \
  -d "username=admin@healthcare.local&password=Admin@12345!"
# Use returned token:
curl -X POST http://localhost:8000/api/v1/knowledge/ask \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"query": "What are first-line treatments for hypertension?"}'
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/login` | Get JWT token |
| POST | `/api/v1/knowledge/ask` | RAG query with citations |
| POST | `/api/v1/knowledge/ingest` | Upload document for indexing |
| GET | `/api/v1/knowledge/history` | Query history |
| GET | `/api/v1/health` | System health |
| POST | `/api/v1/admin/reindex` | Rebuild vector indices |
| GET | `/api/v1/health/metrics` | Prometheus metrics |

## User Roles

| Role | Permissions |
|------|-------------|
| `viewer` | Query only |
| `clinician` | Query + upload documents |
| `researcher` | Query + upload + view all history |
| `admin` | Full access including reindex, user management |

## Running Tests

```bash
# Install test dependencies
cd backend && pip install -r requirements.txt

# RAG unit tests (no DB required)
cd rag && python -m pytest tests/ -v

# Backend tests (requires PostgreSQL + Redis)
cd backend && python -m pytest tests/ -v --cov=app --cov-report=term-missing
```

## Performance Targets

| Metric | Target |
|--------|--------|
| Query latency (p95) | < 2 seconds |
| Embedding generation (1000 docs) | < 60 seconds |
| Concurrent users | 500+ |
| Uptime SLA | 99.9% |
| Test coverage | > 80% |

## Security & HIPAA Compliance

- AES-256 encryption at rest, TLS 1.3 in transit
- JWT authentication with 30-minute token expiry
- RBAC for all endpoints
- PII/PHI detection and masking in queries and responses
- Complete audit trail (every query, document access, admin action)
- Rate limiting (60 req/min per user)
- Prompt injection sanitization

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — System design and data flow
- [API Reference](docs/API.md) — All endpoints with examples
- [Deployment Guide](docs/DEPLOYMENT.md) — Local and AWS EKS deployment
- [Operational Runbook](docs/RUNBOOK.md) — On-call procedures
- [Architecture Decisions](docs/DECISIONS.md) — Technology choices rationale

## Project Structure

```
rag-healthcare-assistant/
├── backend/app/          FastAPI application
│   ├── api/v1/          REST endpoints (knowledge, admin, auth, health)
│   ├── core/            Security, RBAC
│   ├── db/              Database engine and session management
│   ├── models/          SQLAlchemy ORM models
│   ├── services/        Redis cache, Prometheus metrics
│   └── middleware/      Rate limiting
├── rag/                  RAG pipeline
│   ├── pipeline.py      Orchestration
│   ├── ingestion.py     Document parsing and indexing
│   ├── retrieval.py     Hybrid semantic+keyword search
│   ├── generation.py    LLM response generation
│   ├── chunking.py      Medical-aware text chunking
│   ├── embeddings.py    Embedding service
│   ├── query_enhancer.py Medical synonym expansion
│   └── pii_detector.py  PHI masking
├── kubernetes/           K8s manifests (Deployment, HPA, StatefulSets)
├── monitoring/           Prometheus + alerting rules
├── sample_data/          Synthetic healthcare documents
├── scripts/              DB init, data loading, performance testing
├── docs/                 Architecture, API, deployment, runbook docs
├── .github/workflows/    CI/CD (GitHub Actions)
└── docker-compose.yml    Local development stack
```
