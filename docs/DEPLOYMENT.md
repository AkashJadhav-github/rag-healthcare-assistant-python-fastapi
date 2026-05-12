# Deployment Guide

## Local Development (Docker Compose)

### Prerequisites
- Docker Desktop 4.x+
- docker-compose v2+
- OpenAI API key (optional — system works without for testing)

### Quick Start (< 10 minutes)

```bash
# 1. Clone the repo
git clone https://github.com/your-org/rag-healthcare-assistant
cd rag-healthcare-assistant

# 2. Copy and configure environment
cp .env.example .env
# Edit .env and set OPENAI_API_KEY (or ANTHROPIC_API_KEY)

# 3. Start all services
docker-compose up -d

# 4. Verify health
curl http://localhost:8000/api/v1/health

# 5. Load sample documents
python scripts/load_sample_data.py

# 6. Access interactive docs (dev mode)
open http://localhost:8000/docs
```

### Services
| Service | URL |
|---------|-----|
| API | http://localhost:8000 |
| API Docs (dev) | http://localhost:8000/docs |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3001 (admin/admin) |
| Jaeger UI | http://localhost:16686 |

### Default Credentials
- Admin: admin@healthcare.local / Admin@12345!
- Change immediately in production!

---

## Production: AWS EKS Deployment

### Prerequisites
- AWS CLI configured with admin permissions
- kubectl, eksctl, helm installed
- ECR registry created
- Domain name with Route53 hosted zone

### Step 1: Create EKS Cluster

```bash
eksctl create cluster \
  --name healthcare-rag-prod \
  --region us-east-1 \
  --nodegroup-name standard-workers \
  --node-type m6i.2xlarge \
  --nodes 3 \
  --nodes-min 3 \
  --nodes-max 10 \
  --managed \
  --with-oidc \
  --ssh-access \
  --alb-ingress-access
```

### Step 2: Install Cluster Add-ons

```bash
# Metrics server (for HPA)
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# NGINX Ingress Controller
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx --create-namespace

# cert-manager (TLS certificates)
helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager --create-namespace \
  --set installCRDs=true

# AWS Load Balancer Controller
helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=healthcare-rag-prod \
  --set serviceAccount.create=false \
  --set serviceAccount.name=aws-load-balancer-controller
```

### Step 3: Build and Push Container Image

```bash
# Authenticate ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com

# Build
docker build -t rag-healthcare-api:v1.0.0 ./backend

# Tag and push
docker tag rag-healthcare-api:v1.0.0 \
  <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/rag-healthcare-api:v1.0.0
docker push <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/rag-healthcare-api:v1.0.0
```

### Step 4: Configure Secrets

```bash
# Create namespace
kubectl apply -f kubernetes/namespace.yaml

# Create secrets (use AWS Secrets Manager in production)
kubectl create secret generic rag-secrets \
  --from-literal=POSTGRES_USER=healthcare_user \
  --from-literal=POSTGRES_PASSWORD=$(openssl rand -base64 32) \
  --from-literal=SECRET_KEY=$(openssl rand -base64 64) \
  --from-literal=OPENAI_API_KEY=$OPENAI_API_KEY \
  -n healthcare-rag
```

### Step 5: Deploy Application

```bash
kubectl apply -f kubernetes/configmap.yaml
kubectl apply -f kubernetes/statefulset-postgres.yaml
kubectl apply -f kubernetes/statefulset-redis.yaml

# Wait for databases
kubectl rollout status statefulset/postgres -n healthcare-rag
kubectl rollout status statefulset/redis -n healthcare-rag

# Deploy API
kubectl apply -f kubernetes/deployment.yaml
kubectl apply -f kubernetes/service.yaml
kubectl apply -f kubernetes/hpa.yaml

# Verify
kubectl get pods -n healthcare-rag
kubectl logs -l app=rag-api -n healthcare-rag --tail=50
```

### Step 6: Verify Deployment

```bash
# Get ingress external IP
kubectl get ingress -n healthcare-rag

# Test health
curl https://api.healthcare-rag.example.com/api/v1/health/live
```

---

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| SECRET_KEY | Yes | JWT signing key (256-bit) |
| POSTGRES_PASSWORD | Yes | Database password |
| OPENAI_API_KEY | Recommended | OpenAI API for embeddings + LLM |
| ANTHROPIC_API_KEY | Optional | Alternative LLM provider |
| LLM_PROVIDER | No | openai or anthropic (default: openai) |
| ADMIN_EMAIL | No | Initial admin user email |
| ADMIN_PASSWORD | No | Initial admin user password |
| ENCRYPTION_KEY | Yes (prod) | AES-256 key for sensitive data |

---

## Database Backup

```bash
# Manual backup (PostgreSQL)
kubectl exec postgres-0 -n healthcare-rag -- \
  pg_dump -U healthcare_user healthcare_rag | \
  gzip > backup_$(date +%Y%m%d_%H%M%S).sql.gz

# Restore
gunzip -c backup_file.sql.gz | \
  kubectl exec -i postgres-0 -n healthcare-rag -- \
  psql -U healthcare_user healthcare_rag
```

For production: use AWS RDS with automated backups (7-day retention) + point-in-time recovery.
