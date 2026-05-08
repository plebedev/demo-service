{{- define "text-tools.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "text-tools.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s" (default .Release.Name (include "text-tools.name" .)) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "text-tools.labels" -}}
app.kubernetes.io/name: {{ include "text-tools.name" . }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "text-tools.selectorLabels" -}}
app.kubernetes.io/name: {{ include "text-tools.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
