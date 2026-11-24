import { API_CONTRACT, apiUrl } from './config'
import { ApiError, request } from './http'
import { normalizeHit } from '../lib/normalize'
import { normalizeStagePatch } from '../lib/trace'

function toEventPacket(eventName, data) {
  if (!data || typeof data !== 'object') return null
  if (data.type) return data
  if (eventName) return { type: eventName, ...data }
  return data
}

function parseSseChunk(buffer, onEvent) {
  const parts = buffer.split('\n\n')
  const rest = parts.pop() || ''
  for (const block of parts) {
    const lines = block.split('\n')
    let eventName = 'message'
    const dataLines = []
    for (const line of lines) {
      if (line.startsWith('event:')) eventName = line.slice(6).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
    }
    if (!dataLines.length) continue
    try {
      const payload = JSON.parse(dataLines.join('\n'))
      const packet = toEventPacket(eventName, payload)
      if (packet) onEvent(packet)
    } catch {
      onEvent({ type: eventName, data: dataLines.join('\n') })
    }
  }
  return rest
}

export async function streamChatQuery(payload, handlers = {}, signal) {
  const response = await fetch(apiUrl(API_CONTRACT.chatQuery), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream, application/x-ndjson, application/json'
    },
    body: JSON.stringify(payload),
    signal
  })

  if (!response.ok) {
    let detail = null
    try {
      detail = await response.json()
    } catch {
      detail = await response.text()
    }
    throw new ApiError(detail?.message || detail?.detail || `问答请求失败（${response.status}）`, {
      status: response.status,
      details: detail
    })
  }

  const contentType = response.headers.get('content-type') || ''
  if (!contentType.includes('json') && response.body) {
    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      buffer = parseSseChunk(buffer, (packet) => dispatchPacket(packet, handlers))
    }
    if (buffer.trim()) parseSseChunk(`${buffer}\n\n`, (packet) => dispatchPacket(packet, handlers))
    return
  }

  const payloadJson = await response.json()
  const events = payloadJson?.events || [payloadJson]
  for (const packet of events) dispatchPacket(packet, handlers)
}

function dispatchPacket(packet, handlers) {
  if (!packet) return
  const type = packet.type
  if (type === 'stage') {
    const key = packet.key || packet.stage
    if (key) handlers.onStage?.(key, normalizeStagePatch(packet))
    return
  }
  if (type === 'hits') {
    const list = (packet.hits || packet.items || []).map((item, index) => normalizeHit(item, index))
    handlers.onHits?.(list)
    return
  }
  if (type === 'token') {
    handlers.onToken?.(packet.text ?? packet.token ?? '')
    return
  }
  if (type === 'trace') {
    handlers.onTrace?.(packet.trace || packet)
    return
  }
  if (type === 'answer') {
    const hits = (packet.hits || []).map((item, index) => normalizeHit(item, index))
    const meta = packet.meta || {}
    handlers.onAnswer?.({ ...packet, hits, meta, trace: packet.trace || meta.trace || null })
    return
  }
  if (type === 'done') {
    handlers.onDone?.(packet)
    return
  }
  if (type === 'error') {
    handlers.onError?.(new ApiError(packet.message || '后端返回错误', { details: packet }))
  }
}

export async function stopChatQuery(requestId) {
  if (!requestId) return null
  return request(API_CONTRACT.chatStop, {
    method: 'POST',
    body: { request_id: requestId }
  })
}
