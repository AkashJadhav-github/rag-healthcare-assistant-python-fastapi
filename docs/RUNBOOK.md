# Operational Runbook — RAG Healthcare Assistant

## On-Call Contacts
- Primary: Platform Team Slack `#healthcare-rag-oncall`
- Escalation: `engineering-oncall@healthcare.example.com`
- Dashboard: Grafana at `https://grafana.healthcare-rag.example.com`

---

## Common Alerts and Response

### ALERT: HighQueryLatency (p95 > 2s)

1. Check Grafana → RAG Overview → Query Latency panel
2. Check LLM API status: `curl https://status.openai.com/api/v2/status.json`
3. Check Redis cache hit rate: if low, cache may have been flushed
4. Check PostgreSQL query times: `kubectl exec postgres-0 -- psql -U healthcare_user -c "SELECT query, mean_exec_time FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10"`
5. If LLM API is slow: switch to Anthropic by updating `LLM_PROVIDER=anthropic` in ConfigMap and rolling restart

### ALERT: HighErrorRate (> 5%)

1. Check logs: `kubectl logs -l app=rag-api -n healthcare-rag --tail=100 | grep ERROR`
2. Check `rag_errors_total` metric by `error_type` label in Prometheus
3. Common causes: OpenAI rate limit, database connection exhausted, invalid input
4. OpenAI rate limit: check X-RateLimit headers in logs; increase cache TTL temporarily

### ALERT: DatabaseDown

1. `kubectl get pods -n healthcare-rag | grep postgres`
2. If pod not running: `kubectl describe pod postgres-0 -n healthcare-rag`
3. Check PVC: `kubectl get pvc -n healthcare-rag`
4. If storage full: `kubectl exec postgres-0 -- df -h`
5. Emergency: switch API to read-only mode via feature flag; restore from latest backup

### ALERT: APIDown

1. `kubectl get pods -n healthcare-rag`
2. Check recent deployments: `kubectl rollout history deployment/rag-api -n healthcare-rag`
3. If bad deployment: `kubectl rollout undo deployment/rag-api -n healthcare-rag`
4. Check resources: `kubectl top pods -n healthcare-rag`

---

## Scaling Operations

### Manual Scale Up
```bash
kubectl scale deployment/rag-api --replicas=10 -n healthcare-rag
```

### Check HPA Status
```bash
kubectl describe hpa rag-api-hpa -n healthcare-rag
```

---

## Reindexing Documents

Trigger via API (Admin role required):
```bash
curl -X POST https://api.healthcare-rag.example.com/api/v1/admin/reindex \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Monitor: `kubectl logs -l app=rag-api -n healthcare-rag | grep reindex`

---

## Log Queries (Structured JSON)

```bash
# Find all failed queries in last hour
kubectl logs -l app=rag-api -n healthcare-rag | \
  jq 'select(.event=="query_failed")'

# Find slow requests (>1500ms)
kubectl logs -l app=rag-api -n healthcare-rag | \
  jq 'select(.latency_ms > 1500)'

# Audit trail for specific user
kubectl logs -l app=rag-api -n healthcare-rag | \
  jq 'select(.user_id == "UUID-HERE")'
```

---

## HIPAA Incident Response

If PHI exposure suspected:
1. Immediately notify Privacy Officer
2. Preserve audit logs: `kubectl exec postgres-0 -- psql -c "COPY audit_logs TO '/tmp/audit_export.csv' CSV HEADER"`
3. Review `audit_logs` table for the time window
4. Check if PII masking was applied: search logs for `phi_masked=true`
5. Notify affected parties per HIPAA Breach Notification Rule (within 60 days)

---

## Performance Tuning

### Vector Search Performance
If retrieval >200ms:
```sql
-- Rebuild IVFFlat index
DROP INDEX IF EXISTS document_chunks_embedding_idx;
CREATE INDEX document_chunks_embedding_idx
  ON document_chunks
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 200);
```

### Cache Hit Rate
Monitor: `rag_queries_total{cached="true"}` / `rag_queries_total`
If <20%: consider increasing `CACHE_TTL_SECONDS` (max 7200s = 2h)

### Database Connections
Monitor: `pg_stat_activity` — if connections approach max, increase pool size or add PgBouncer.
