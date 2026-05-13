import time
from functools import wraps

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

registry = CollectorRegistry(auto_describe=True)

# Counters
query_total = Counter(
    "rag_queries_total",
    "Total number of queries",
    ["status", "cached"],
    registry=registry,
)
ingest_total = Counter(
    "rag_ingest_total",
    "Total document ingestion requests",
    ["status", "file_type"],
    registry=registry,
)
auth_total = Counter("rag_auth_total", "Authentication attempts", ["status"], registry=registry)
error_total = Counter("rag_errors_total", "Total errors", ["error_type"], registry=registry)

# Histograms
query_latency = Histogram(
    "rag_query_latency_seconds",
    "Query end-to-end latency",
    buckets=[0.1, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0],
    registry=registry,
)
embedding_latency = Histogram(
    "rag_embedding_latency_seconds",
    "Embedding generation latency",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0],
    registry=registry,
)
retrieval_latency = Histogram(
    "rag_retrieval_latency_seconds",
    "Vector search latency",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0],
    registry=registry,
)
llm_latency = Histogram(
    "rag_llm_latency_seconds",
    "LLM generation latency",
    buckets=[0.1, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0],
    registry=registry,
)

# Gauges
active_users = Gauge("rag_active_users", "Currently active users", registry=registry)
documents_indexed = Gauge("rag_documents_indexed_total", "Total indexed documents", registry=registry)
vector_store_size = Gauge("rag_vector_store_chunks", "Number of vector chunks", registry=registry)


def track_query_latency(func):  # pragma: no cover
    @wraps(func)
    async def wrapper(*args, **kwargs):  # pragma: no cover
        start = time.time()
        try:
            result = await func(*args, **kwargs)
            query_total.labels(status="success", cached="false").inc()
            return result
        except Exception as e:
            query_total.labels(status="error", cached="false").inc()
            error_total.labels(error_type=type(e).__name__).inc()
            raise
        finally:
            query_latency.observe(time.time() - start)

    return wrapper
