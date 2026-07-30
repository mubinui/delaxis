# Kubernetes Deployment Manifests

This directory contains Kubernetes manifests for deploying the Delaxis.

## Quick Start

```bash
# Create namespace
kubectl apply -f namespace.yaml

# Apply configurations
kubectl apply -f configmap.yaml
kubectl apply -f secret.yaml

# Deploy infrastructure
kubectl apply -f postgres-statefulset.yaml
kubectl apply -f redis-statefulset.yaml
kubectl apply -f rabbitmq-statefulset.yaml

# Deploy services
kubectl apply -f service.yaml

# Deploy application
kubectl apply -f deployment.yaml

# Configure ingress
kubectl apply -f ingress.yaml

# Enable autoscaling
kubectl apply -f hpa.yaml

# Apply network policies (optional)
kubectl apply -f networkpolicy.yaml
```

## Files

- **namespace.yaml** - Creates the `delaxis` namespace
- **configmap.yaml** - Application configuration (non-sensitive)
- **secret.yaml** - Sensitive configuration (API keys, passwords)
- **deployment.yaml** - Main application deployment with init containers
- **service.yaml** - Services for all components
- **ingress.yaml** - Ingress configuration with TLS
- **postgres-statefulset.yaml** - PostgreSQL StatefulSet
- **redis-statefulset.yaml** - Redis StatefulSet
- **rabbitmq-statefulset.yaml** - RabbitMQ StatefulSet
- **hpa.yaml** - Horizontal Pod Autoscaler
- **networkpolicy.yaml** - Network policies for security

## Prerequisites

- Kubernetes cluster 1.27+
- kubectl configured
- Ingress controller (NGINX recommended)
- cert-manager (for TLS certificates)
- Storage class for persistent volumes

## Configuration

### Update Secrets

Before deploying, update `secret.yaml` with your actual credentials:

```bash
# Generate base64 encoded values
echo -n "your-api-key" | base64

# Or use kubectl to create secret
kubectl create secret generic delaxis-secrets \
  --from-literal=OPENROUTER_API_KEY=your-key \
  --from-literal=OPENAI_API_KEY=your-key \
  --from-literal=JWT_SECRET_KEY=your-secret \
  --from-literal=ENCRYPTION_KEY=your-key \
  -n delaxis --dry-run=client -o yaml > secret.yaml
```

### Update Ingress

Edit `ingress.yaml` to set your domain:

```yaml
spec:
  tls:
  - hosts:
    - your-domain.com
    secretName: delaxis-tls
  rules:
  - host: your-domain.com
```

## Verification

```bash
# Check all pods are running
kubectl get pods -n delaxis

# Check services
kubectl get svc -n delaxis

# Check ingress
kubectl get ingress -n delaxis

# View logs
kubectl logs -n delaxis -l app=delaxis -f

# Test health endpoint
kubectl port-forward -n delaxis svc/delaxis 8000:8000
curl http://localhost:8000/health
```

## Scaling

### Manual Scaling

```bash
kubectl scale deployment delaxis -n delaxis --replicas=5
```

### Autoscaling

The HPA automatically scales based on CPU and memory:

```bash
# Check HPA status
kubectl get hpa -n delaxis

# Describe HPA
kubectl describe hpa delaxis-hpa -n delaxis
```

## Maintenance

### Database Migrations

```bash
# Run migrations
kubectl exec -n delaxis -it deployment/delaxis -- alembic upgrade head

# Check current version
kubectl exec -n delaxis -it deployment/delaxis -- alembic current
```

### Backup

```bash
# Backup PostgreSQL
kubectl exec -n delaxis statefulset/postgres -- pg_dump -U delaxis delaxis > backup.sql

# Backup Redis
kubectl exec -n delaxis statefulset/redis -- redis-cli SAVE
kubectl cp delaxis/redis-0:/data/dump.rdb ./redis-backup.rdb
```

### Updates

```bash
# Update image
kubectl set image deployment/delaxis \
  delaxis=delaxis:v1.1.0 \
  -n delaxis

# Check rollout status
kubectl rollout status deployment/delaxis -n delaxis

# Rollback if needed
kubectl rollout undo deployment/delaxis -n delaxis
```

## Monitoring

### Prometheus

Add ServiceMonitor for Prometheus Operator:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: delaxis
  namespace: delaxis
spec:
  selector:
    matchLabels:
      app: delaxis
  endpoints:
  - port: metrics
    interval: 30s
```

### Grafana

Import the dashboard:

```bash
kubectl create configmap grafana-dashboard-delaxis \
  --from-file=../dashboards/delaxis.json \
  -n monitoring
```

## Troubleshooting

See [Troubleshooting Guide](../docs/troubleshooting.md) for common issues.

### Quick Checks

```bash
# Check pod status
kubectl get pods -n delaxis

# View pod logs
kubectl logs -n delaxis <pod-name>

# Describe pod
kubectl describe pod -n delaxis <pod-name>

# Check events
kubectl get events -n delaxis --sort-by='.lastTimestamp'

# Execute commands in pod
kubectl exec -n delaxis -it deployment/delaxis -- /bin/sh
```

## Cleanup

```bash
# Delete all resources
kubectl delete namespace delaxis

# Or delete individually
kubectl delete -f .
```

## Security

### Network Policies

Network policies restrict traffic between pods:

```bash
# Apply network policies
kubectl apply -f networkpolicy.yaml

# Test connectivity
kubectl run -n delaxis test-pod --image=busybox --rm -it -- sh
```

### RBAC

The deployment uses a dedicated ServiceAccount with minimal permissions.

### Secrets Management

For production, use external secret management:

- AWS Secrets Manager
- Azure Key Vault
- HashiCorp Vault
- Kubernetes External Secrets Operator

## Additional Resources

- [Deployment Guide](../docs/deployment-guide.md)
- [Environment Variables](../docs/environment-variables.md)
- [Troubleshooting](../docs/troubleshooting.md)
