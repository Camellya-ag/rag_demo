import { API_TIMEOUT_MS, apiUrl } from './config'

export class ApiError extends Error {
  constructor(message, { status = 0, code = 'api_error', details = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

async function parseBody(response) {
  const contentType = response.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    try {
      return await response.json()
    } catch {
      return null
    }
  }
  const text = await response.text()
  return text || null
}

function pickMessage(payload, fallback) {
  if (!payload) return fallback
  if (typeof payload === 'string') return payload
  return payload.message || payload.detail || payload.error || fallback
}

export async function request(path, options = {}) {
  const { method = 'GET', body, headers, signal, timeout = API_TIMEOUT_MS } = options
  const controller = new AbortController()
  const timer = timeout > 0 ? setTimeout(() => controller.abort(), timeout) : null

  if (signal) {
    if (signal.aborted) controller.abort()
    else signal.addEventListener('abort', () => controller.abort(), { once: true })
  }

  try {
    const response = await fetch(apiUrl(path), {
      method,
      headers: {
        Accept: 'application/json',
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...headers
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal
    })

    const payload = await parseBody(response)
    if (!response.ok) {
      throw new ApiError(pickMessage(payload, `请求失败（${response.status}）`), {
        status: response.status,
        details: payload
      })
    }
    return payload
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (error?.name === 'AbortError') {
      throw new ApiError('请求已取消', { code: 'aborted' })
    }
    throw new ApiError('无法连接后端服务，请确认 API 地址与运行状态', {
      code: 'network_error',
      details: error?.message
    })
  } finally {
    if (timer) clearTimeout(timer)
  }
}
