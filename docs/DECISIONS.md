# Architecture Decision Records

## ADR-001: PostgreSQL + pgvector over Dedicated Vector DB

**Status**: Accepted  
**Date**: 2024-01

**Context**: We needed a vector database for storing and querying medical text embeddings. Options: Pinecone (managed), Weaviate (self-hosted), Milvus (self-hosted), pgvector.

**Decision**: Use PostgreSQL with the pgvector extension.

**Reasons**:
- Single database reduces operational complexity (no separate vector DB cluster to manage)
- ACID transactions: vector storage and metadata stay consistent
- JOINs: can combine vector similarity with SQL filters (user, category, status) in one query
- pg_trgm + pgvector = hybrid search in a single query
- Existing PostgreSQL operational expertise (backups, HA, monitoring)
- For <10M vectors, IVFFlat/HNSW performance is competitive with dedicated solutions

**Trade-off**: At 50M+ vectors, Pinecone/Weaviate would outperform. Migration path exists.

---

## ADR-002: FastAPI over Django/Flask

**Status**: Accepted  
**Date**: 2024-01

**Decision**: Use FastAPI for the backend.

**Reasons**:
- Native async support (asyncio) — critical for concurrent LLM API calls
- Pydantic v2 for automatic request/response validation with type hints
- Auto-generated OpenAPI/Swagger documentation
- Excellent performance (Starlette base, comparable to Node.js)
- Python ecosystem fits LangChain/embedding libraries natively

---

## ADR-003: OpenAI ada-002 + GPT-4 as Primary, with Fallback

**Status**: Accepted  
**Date**: 2024-01

**Decision**: Primary: OpenAI (ada-002 embeddings + GPT-4 generation). Secondary: Anthropic Claude. Config-driven to switch.

**Reasons**:
- GPT-4 provides best accuracy for complex clinical reasoning
- ada-002 embeddings: 1536 dimensions, cost-effective, well-tested at scale
- Fallback to Claude for cost optimization or OpenAI outages
- `LLM_PROVIDER` env var allows switching without code changes
- Open-source fallback (sentence-transformers) ensures operation without API keys

**Trade-off**: OpenAI dependency and cost. Mitigation: response caching reduces API calls significantly.

---

## ADR-004: Overlapping Chunk Strategy (1000 tokens, 200 overlap)

**Status**: Accepted  
**Date**: 2024-01

**Decision**: Chunk clinical documents at 1000 tokens with 200-token overlap between consecutive chunks.

**Reasons**:
- 1000 tokens balances context richness vs. embedding quality (too large = noisy embeddings)
- 200-token overlap ensures clinical context that spans chunk boundaries is captured
- Sentence-boundary awareness prevents splitting clinical statements mid-sentence
- Medical abbreviation handling prevents incorrect sentence splitting on "Dr." "vs." etc.

---

## ADR-005: Redis for Cache + Rate Limiting

**Status**: Accepted  
**Date**: 2024-01

**Decision**: Redis for query response caching (1800s TTL) and rate limiting counters.

**Reasons**:
- Identical queries (common in clinical settings) don't need LLM re-invocation
- ~30-40% cache hit rate expected for common clinical queries
- Redis atomic increment for rate limiting (no race conditions)
- Sub-millisecond lookups vs LLM latency of 1-3 seconds
- Cache degrades gracefully (service continues without Redis)

---

## ADR-006: Hybrid Search with RRF Fusion

**Status**: Accepted  
**Date**: 2024-01

**Decision**: Combine pgvector cosine similarity (semantic) with pg_trgm trigram similarity (keyword) using Reciprocal Rank Fusion.

**Reasons**:
- Semantic search catches conceptual matches (MI = myocardial infarction)
- Keyword search catches exact medical codes, drug names, lab values
- RRF fusion is parameter-free and robust — no need to tune weighting coefficients
- Clinical queries often mix semantic intent with specific term lookups

---

## ADR-007: Kubernetes on AWS EKS

**Status**: Accepted  
**Date**: 2024-01

**Decision**: Deploy on AWS EKS with HPA, StatefulSets for databases.

**Reasons**:
- HIPAA-eligible AWS infrastructure (BAA available)
- EKS simplifies K8s control plane management
- HPA allows scaling 3→20 pods based on CPU/memory
- StatefulSets ensure stable network IDs for PostgreSQL and Redis
- AWS RDS (managed PostgreSQL) can replace StatefulSet PostgreSQL for production HA
