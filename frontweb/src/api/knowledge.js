import { API_CONTRACT } from './config'
import { request } from './http'
import {
  normalizeChunk,
  normalizeDistribution,
  normalizeEstimate,
  normalizeIndexJob,
  normalizeSource
} from '../lib/normalize'

export async function fetchHealth() {
  return request(API_CONTRACT.health)
}

export async function fetchKnowledgeSource() {
  const payload = await request(API_CONTRACT.knowledgeSource)
  return normalizeSource(payload?.source || payload)
}

export async function fetchKnowledgeDistribution() {
  const payload = await request(API_CONTRACT.knowledgeDistribution)
  const rows = payload?.items || payload?.distribution || payload || []
  return normalizeDistribution(rows)
}

export async function fetchChunkDetail(id) {
  const payload = await request(API_CONTRACT.knowledgeChunk(id))
  return normalizeChunk(payload?.chunk || payload)
}

export async function estimateIndex({ mode = 'rebuild' } = {}) {
  const payload = await request(API_CONTRACT.knowledgeEstimate, {
    method: 'POST',
    body: { mode }
  })
  return normalizeEstimate(payload)
}

export async function startIndex({ mode = 'rebuild', confirmed = true } = {}) {
  const payload = await request(API_CONTRACT.knowledgeIndex, {
    method: 'POST',
    body: { mode, confirmed }
  })
  return normalizeIndexJob(payload?.job || payload)
}

export async function fetchIndexJob(jobId) {
  const payload = await request(API_CONTRACT.knowledgeJob(jobId))
  return normalizeIndexJob(payload?.job || payload)
}
