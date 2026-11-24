import { PIPELINE_STEPS, emptyStage } from './pipeline'

export function createEmptyStages() {
  return Object.fromEntries(PIPELINE_STEPS.map((step) => [step.key, emptyStage()]))
}

export function createMessageTrace(query) {
  return {
    query: String(query || ''),
    stages: createEmptyStages(),
    hits: [],
    status: 'running',
    startedAt: Date.now(),
    finishedAt: null
  }
}

export function hasTraceContent(trace) {
  if (!trace) return false
  if (trace.hits?.length) return true
  return PIPELINE_STEPS.some((step) => {
    const status = trace.stages?.[step.key]?.status
    return status && status !== 'idle'
  })
}

export function finalizeTrace(trace, status = 'done') {
  if (!trace) return null
  trace.status = status
  trace.finishedAt = Date.now()
  return trace
}

export function normalizeStagePatch(packet = {}) {
  const source = packet.patch || packet
  return {
  status: source.status || 'idle',
  ms: Number(source.ms ?? 0) || 0,
  cost: source.cost ?? null,
  summary: source.summary || '',
  detail: source.detail ?? null
  }
}

export function mergeBackendTrace(trace, backendTrace = {}) {
  if (!trace || !backendTrace) return trace
  if (backendTrace.query) trace.query = backendTrace.query
  if (Array.isArray(backendTrace.hits)) trace.hits = backendTrace.hits
  if (backendTrace.stages && typeof backendTrace.stages === 'object') {
    for (const [key, patch] of Object.entries(backendTrace.stages)) {
      if (!trace.stages[key]) trace.stages[key] = emptyStage()
      Object.assign(trace.stages[key], normalizeStagePatch({ patch }))
    }
  }
  return trace
}

export function snapshotTrace(trace) {
  if (!trace) return null
  const cloneDetail = (value) => (value && typeof value === 'object' ? JSON.parse(JSON.stringify(value)) : value)
  return {
    query: trace.query,
    status: trace.status,
    startedAt: trace.startedAt,
    finishedAt: trace.finishedAt,
    hits: (trace.hits || []).map((hit) => JSON.parse(JSON.stringify(hit))),
    stages: Object.fromEntries(
      Object.entries(trace.stages || {}).map(([key, stage]) => [
        key,
        {
          ...stage,
          detail: cloneDetail(stage.detail)
        }
      ])
    )
  }
}
