{{- define "mirofish.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "mirofish.fullname" -}}
{{- printf "%s" .Release.Name -}}
{{- end -}}

{{- define "mirofish.labels" -}}
app.kubernetes.io/name: {{ include "mirofish.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}
