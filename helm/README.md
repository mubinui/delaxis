# Delaxis Helm Chart

Helm chart for deploying the Delaxis on Kubernetes.

## TL;DR

```bash
helm install delaxis ./delaxis \
  --namespace delaxis \
  --create-namespace \
  --set secrets.openrouterApiKey=your-key
```

## Introduction

This chart bootstraps an Delaxis deployment on a Kubernetes cluster using the Helm package manager.

## Prerequisites

- Kubernetes 1.27+
- Helm 3.12+
- PV provisioner support in the underlying infrastructure (for persistent storage)

## Installing the Chart

### From Local Directory

```bash
helm install delaxis ./delaxis \
  --namespace delaxis \
  --create-namespace \
  --values ./delaxis/values-prod.yaml
```

### With Custom Values

```bash
helm install delaxis ./delaxis \
  --namespace delaxis \
  --create-namespace \
  --set image.tag=v1.0.0 \
  --set replicaCount=5 \
  --set secrets.openrouterApiKey=$OPENROUTER_API_KEY
```

### Development Environment

```bash
helm install delaxis-dev ./delaxis \
  --namespace delaxis-dev \
  --create-namespace \
  --values ./delaxis/values-dev.yaml
```

### Production Environment

```bash
helm install delaxis-prod ./delaxis \
  --namespace delaxis-prod \
  --create-namespace \
  --values ./delaxis/values-prod.yaml \
  --set secrets.openrouterApiKey=$OPENROUTER_API_KEY \
  --set secrets.openaiApiKey=$OPENAI_API_KEY \
  --set secrets.jwtSecretKey=$JWT_SECRET \
  --set secrets.encryptionKey=$ENCRYPTION_KEY
```

## Uninstalling the Chart

```bash
helm uninstall delaxis -n delaxis
```

This removes all the Kubernetes components associated with the chart and deletes the release.

## Configuration

### Global Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `replicaCount` | Number of replicas | `3` |
| `image.repository` | Image repository | `delaxis` |
| `image.tag` | Image tag | `latest` |
| `image.pullPolicy` | Image pull policy | `IfNotPresent` |

### Application Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `config.logLevel` | Log level (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| `config.maxConcurrentSessions` | Maximum concurrent sessions | `100` |
| `config.agentTimeoutSeconds` | Agent timeout in seconds | `300` |
| `config.apiWorkers` | Number of API workers | `4` |

### Service Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `service.type` | Service type | `ClusterIP` |
| `service.port` | Service port | `8000` |
| `service.metricsPort` | Metrics port | `9090` |

### Ingress Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `ingress.enabled` | Enable ingress | `true` |
| `ingress.className` | Ingress class name | `nginx` |
| `ingress.hosts[0].host` | Hostname | `delaxis.example.com` |
| `ingress.tls[0].secretName` | TLS secret name | `delaxis-tls` |

### Resource Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `resources.limits.cpu` | CPU limit | `1000m` |
| `resources.limits.memory` | Memory limit | `2Gi` |
| `resources.requests.cpu` | CPU request | `250m` |
| `resources.requests.memory` | Memory request | `512Mi` |

### Autoscaling Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `autoscaling.enabled` | Enable HPA | `true` |
| `autoscaling.minReplicas` | Minimum replicas | `3` |
| `autoscaling.maxReplicas` | Maximum replicas | `10` |
| `autoscaling.targetCPUUtilizationPercentage` | Target CPU % | `70` |
| `autoscaling.targetMemoryUtilizationPercentage` | Target memory % | `80` |

### PostgreSQL Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `postgresql.enabled` | Enable PostgreSQL | `true` |
| `postgresql.auth.username` | Database username | `orchestrator` |
| `postgresql.auth.password` | Database password | `orchestrator_pass` |
| `postgresql.auth.database` | Database name | `delaxis` |
| `postgresql.primary.persistence.size` | Storage size | `20Gi` |

### Redis Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `redis.enabled` | Enable Redis | `true` |
| `redis.master.persistence.size` | Storage size | `5Gi` |

### RabbitMQ Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `rabbitmq.enabled` | Enable RabbitMQ | `true` |
| `rabbitmq.auth.username` | RabbitMQ username | `orchestrator` |
| `rabbitmq.auth.password` | RabbitMQ password | `orchestrator_pass` |
| `rabbitmq.persistence.size` | Storage size | `10Gi` |

### Secrets Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `secrets.openrouterApiKey` | OpenRouter API key | `""` |
| `secrets.openaiApiKey` | OpenAI API key | `""` |
| `secrets.jwtSecretKey` | JWT secret key | `""` |
| `secrets.encryptionKey` | Encryption key | `""` |

### External Secrets

| Parameter | Description | Default |
|-----------|-------------|---------|
| `externalSecrets.enabled` | Use external secret management | `false` |
| `externalSecrets.backend` | Secret backend (aws-secrets-manager, azure-key-vault) | `aws-secrets-manager` |
| `externalSecrets.region` | AWS region | `us-east-1` |

## Examples

### Minimal Installation

```bash
helm install delaxis ./delaxis \
  --set secrets.openrouterApiKey=sk-or-v1-xxxxx
```

### Production Installation with External Secrets

```bash
helm install delaxis-prod ./delaxis \
  --namespace delaxis-prod \
  --create-namespace \
  --values ./delaxis/values-prod.yaml \
  --set externalSecrets.enabled=true \
  --set externalSecrets.backend=aws-secrets-manager \
  --set externalSecrets.secretName=delaxis/prod/secrets
```

### High Availability Setup

```bash
helm install delaxis ./delaxis \
  --set replicaCount=5 \
  --set autoscaling.minReplicas=5 \
  --set autoscaling.maxReplicas=20 \
  --set resources.limits.cpu=2000m \
  --set resources.limits.memory=4Gi \
  --set postgresql.primary.persistence.size=100Gi \
  --set redis.master.persistence.size=20Gi
```

### Development Setup (Minimal Resources)

```bash
helm install delaxis-dev ./delaxis \
  --namespace delaxis-dev \
  --create-namespace \
  --values ./delaxis/values-dev.yaml
```

## Upgrading

### Upgrade to New Version

```bash
helm upgrade delaxis ./delaxis \
  --namespace delaxis \
  --values ./delaxis/values-prod.yaml \
  --reuse-values
```

### Upgrade with New Image

```bash
helm upgrade delaxis ./delaxis \
  --namespace delaxis \
  --set image.tag=v1.1.0 \
  --reuse-values
```

### Upgrade Configuration Only

```bash
helm upgrade delaxis ./delaxis \
  --namespace delaxis \
  --set config.maxConcurrentSessions=500 \
  --reuse-values
```

## Rollback

```bash
# View release history
helm history delaxis -n delaxis

# Rollback to previous version
helm rollback delaxis -n delaxis

# Rollback to specific revision
helm rollback delaxis 3 -n delaxis
```

## Verification

### Check Deployment Status

```bash
# Get release status
helm status delaxis -n delaxis

# Get all resources
helm get all delaxis -n delaxis

# Get values
helm get values delaxis -n delaxis
```

### Test Deployment

```bash
# Port forward to service
kubectl port-forward -n delaxis svc/delaxis 8000:8000

# Test health endpoint
curl http://localhost:8000/health

# Test metrics
curl http://localhost:9090/metrics
```

## Customization

### Custom Values File

Create a custom `my-values.yaml`:

```yaml
replicaCount: 5

image:
  tag: v1.0.0

config:
  logLevel: INFO
  maxConcurrentSessions: 500

resources:
  limits:
    cpu: 2000m
    memory: 4Gi
  requests:
    cpu: 500m
    memory: 1Gi

ingress:
  hosts:
    - host: delaxis.mycompany.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: mycompany-tls
      hosts:
        - delaxis.mycompany.com

postgresql:
  primary:
    persistence:
      size: 100Gi

secrets:
  openrouterApiKey: ${OPENROUTER_API_KEY}
  openaiApiKey: ${OPENAI_API_KEY}
```

Install with custom values:

```bash
helm install delaxis ./delaxis \
  --namespace delaxis \
  --create-namespace \
  --values my-values.yaml
```

## Troubleshooting

### View Logs

```bash
# Application logs
kubectl logs -n delaxis -l app.kubernetes.io/name=delaxis -f

# PostgreSQL logs
kubectl logs -n delaxis -l app=postgres -f

# Redis logs
kubectl logs -n delaxis -l app=redis -f
```

### Debug Deployment

```bash
# Get pod status
kubectl get pods -n delaxis

# Describe pod
kubectl describe pod -n delaxis <pod-name>

# Get events
kubectl get events -n delaxis --sort-by='.lastTimestamp'

# Execute shell in pod
kubectl exec -n delaxis -it deployment/delaxis -- /bin/sh
```

### Common Issues

1. **ImagePullBackOff**: Check image repository and tag
2. **CrashLoopBackOff**: Check logs for errors, verify secrets
3. **Pending Pods**: Check PVC status, storage class availability
4. **Service Unavailable**: Check ingress configuration, DNS

See [Troubleshooting Guide](../docs/troubleshooting.md) for more details.

## Additional Resources

- [Deployment Guide](../docs/deployment-guide.md)
- [Environment Variables](../docs/environment-variables.md)
- [Troubleshooting](../docs/troubleshooting.md)
- [Helm Documentation](https://helm.sh/docs/)
