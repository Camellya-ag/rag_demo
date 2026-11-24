const rawBase = import.meta.env.VITE_API_BASE ?? ''

export const API_BASE = String(rawBase).replace(/\/$/, '')

export const API_TIMEOUT_MS = Number(import.meta.env.VITE_API_TIMEOUT_MS || 30000)

export function apiUrl(path) {
  const normalized = path.startsWith('/') ? path : `/${path}`
  return `${API_BASE}${normalized}`
}

export const API_CONTRACT = {
  health: '/api/health',
  knowledgeSource: '/api/knowledge/source',
  knowledgeDistribution: '/api/knowledge/distribution',
  knowledgeChunk: (id) => `/api/knowledge/chunks/${encodeURIComponent(id)}`,
  knowledgeEstimate: '/api/knowledge/index/estimate',
  knowledgeIndex: '/api/knowledge/index',
  knowledgeJob: (jobId) => `/api/knowledge/index/jobs/${encodeURIComponent(jobId)}`,
  chatQuery: '/api/chat/query',
  chatStop: '/api/chat/stop',
  settingsDefaults: '/api/settings/defaults'
}
