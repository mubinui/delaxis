{{/*
Expand the name of the chart.
*/}}
{{- define "delaxis.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "delaxis.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "delaxis.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "delaxis.labels" -}}
helm.sh/chart: {{ include "delaxis.chart" . }}
{{ include "delaxis.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "delaxis.selectorLabels" -}}
app.kubernetes.io/name: {{ include "delaxis.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "delaxis.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "delaxis.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Database URL
*/}}
{{- define "delaxis.databaseUrl" -}}
{{- if .Values.postgresql.enabled }}
postgresql://{{ .Values.postgresql.auth.username }}:{{ .Values.postgresql.auth.password }}@postgres-service:5432/{{ .Values.postgresql.auth.database }}
{{- else }}
{{- .Values.externalDatabase.url }}
{{- end }}
{{- end }}

{{/*
Redis URL
*/}}
{{- define "delaxis.redisUrl" -}}
{{- if .Values.redis.enabled }}
redis://redis-service:6379/0
{{- else }}
{{- .Values.externalRedis.url }}
{{- end }}
{{- end }}

{{/*
RabbitMQ URL
*/}}
{{- define "delaxis.rabbitmqUrl" -}}
{{- if .Values.rabbitmq.enabled }}
amqp://{{ .Values.rabbitmq.auth.username }}:{{ .Values.rabbitmq.auth.password }}@rabbitmq-service:5672/
{{- else }}
{{- .Values.externalRabbitmq.url }}
{{- end }}
{{- end }}
