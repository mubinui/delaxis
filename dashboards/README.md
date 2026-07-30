# Grafana Dashboards

This directory contains Grafana dashboard templates for monitoring the Delaxis.

## Available Dashboards

### delaxis.json

Main dashboard for monitoring the Delaxis with the following panels:

#### HTTP Metrics
- **HTTP Request Rate**: Requests per second across all endpoints
- **HTTP Request Duration (p95)**: 95th percentile latency for HTTP requests
- **HTTP Error Rate (5xx)**: Rate of 5xx errors by endpoint

#### Agent Metrics
- **Agent Conversation Rate**: Rate of agent conversations by pattern and workflow
- **Agent Conversation Duration (p95)**: 95th percentile duration for agent conversations
- **Agent Error Rate**: Rate of agent errors by agent ID and error type

#### LLM Metrics
- **LLM API Call Rate**: Rate of LLM API calls by provider and model
- **LLM Token Usage Rate**: Token usage rate by provider, model, and type (prompt/completion)
- **Total LLM Cost**: Cumulative cost of LLM API calls in USD

#### Infrastructure Metrics
- **Cache Hit Rate**: Cache hit rate by cache type (session, embedding, llm)

## Installation

### Prerequisites

1. Prometheus configured to scrape metrics from the Delaxis at `/metrics` endpoint
2. Grafana instance with Prometheus datasource configured

### Import Dashboard

1. Open Grafana UI
2. Navigate to Dashboards → Import
3. Upload `delaxis.json` or paste its contents
4. Select your Prometheus datasource
5. Click Import

### Configure Prometheus Scraping

Add the following to your Prometheus configuration:

```yaml
scrape_configs:
  - job_name: 'delaxis'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
    scrape_interval: 15s
```

## Dashboard Panels

### Key Metrics to Monitor

1. **Request Rate**: Monitor traffic patterns and identify peak usage times
2. **Request Duration**: Track API performance and identify slow endpoints
3. **Error Rate**: Monitor service health and identify issues
4. **Agent Conversation Duration**: Track agent performance and identify bottlenecks
5. **LLM Cost**: Monitor spending on LLM API calls
6. **Cache Hit Rate**: Optimize caching strategy based on hit rates

### Alerting Recommendations

Consider setting up alerts for:

- HTTP error rate > 5%
- HTTP request duration p95 > 2s
- Agent error rate > 1%
- Cache hit rate < 50%
- LLM cost growth rate exceeding budget

## Customization

The dashboard can be customized to add:

- Additional panels for specific metrics
- Custom time ranges and refresh intervals
- Alert rules and annotations
- Variables for filtering by workflow, agent, or provider

## Troubleshooting

### No Data Showing

1. Verify Prometheus is scraping the `/metrics` endpoint
2. Check that the Delaxis is running and exposing metrics
3. Verify the Prometheus datasource is configured correctly in Grafana
4. Check the time range in the dashboard

### Missing Metrics

1. Ensure the application is generating traffic to populate metrics
2. Verify that the metric names match those defined in `src/observability/metrics.py`
3. Check Prometheus targets page to ensure scraping is successful

## Requirements

This dashboard satisfies the following requirements:
- 14.5: Provide Grafana dashboard templates for key metrics
