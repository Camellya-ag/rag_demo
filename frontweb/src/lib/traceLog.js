import { PIPELINE_STEPS } from './pipeline'
import { formatCost, formatUnknownNumber } from './format'

const SECRET_KEY_RE =
  /(api[_-]?key|authorization|access[_-]?token|refresh[_-]?token|id[_-]?token|auth[_-]?token|secret|password|bearer|dashscope|credential)/i
const MAX_PROMPT_CHARS = 12000

function isPlainObject(v) {
  return v && typeof v === 'object' && !Array.isArray(v)
}

export function redactSecrets(value, key = '') {
  if (key && SECRET_KEY_RE.test(String(key))) return '[已脱敏]'
  if (Array.isArray(value)) return value.map((item) => redactSecrets(item))
  if (!isPlainObject(value)) return value
  return Object.fromEntries(
    Object.entries(value).map(([k, v]) => [k, SECRET_KEY_RE.test(k) ? '[已脱敏]' : redactSecrets(v, k)])
  )
}

function statusLabel(status) {
  const map = {
    idle: '未执行',
    running: '执行中',
    done: '完成',
    skipped: '已跳过',
    stopped: '已停止',
    unknown: '未知',
    error: '错误'
  }
  return map[status] || status || '未知'
}

function push(lines, text = '') {
  if (text !== '') lines.push(text)
}

function formatRows(title, rows, formatter) {
  const lines = []
  if (!rows?.length) {
    lines.push(`  (${title}：无数据 / 后端未返回)`)
    return lines
  }
  rows.forEach((row, i) => {
    lines.push(`  ${i + 1}. ${formatter(row)}`)
  })
  return lines
}

function formatHitRow(r) {
  const label = r.chapterLabel || r.chapter_title || r.chapterTitle || ''
  const score = r.scoreText ?? r.score ?? '未知'
  return `${r.id} | ${label} | ${score}`
}

function summarizeHits(hits = []) {
  return hits.map((hit, i) => {
    const channel = hit.channel === 'qa_pair' || hit.qaPairHit ? '问答映射' : '原文分块'
    const q = hit.question ? ` | 问答：${hit.question}` : ''
    const map = hit.mappedChunkIds?.length ? ` | 映射片段：${hit.mappedChunkIds.join(',')}` : ''
    const text = hit.chunk?.text ? ` | 摘要：${String(hit.chunk.text).slice(0, 80)}…` : ''
    return `[${hit.rank ?? i + 1}] ${hit.id || '未知ID'} | ${channel} | 分数 ${hit.scoreText ?? '未知'}${q}${map}${text}`
  })
}

function appendStageDetail(stepKey, detail, lines) {
  if (!detail) return
  const safe = redactSecrets(detail)
  if (stepKey === 'rewrite') {
    push(lines, `  原问题：${safe.original ?? '未知'}`)
    push(lines, `  改写后：${safe.rewritten ?? '未知'}`)
    push(lines, `  理由：${safe.reason ?? '未返回'}`)
    push(lines, `  方式：${safe.method ?? '未返回'}`)
    return
  }
  if (stepKey === 'retrieve') {
    const size = safe.indexSize ?? '未知'
    push(lines, `  索引规模：${size} 个分块`)
    push(lines, '  [稠密召回·原问]')
    lines.push(
      ...formatRows('稠密原问', safe.dense_original?.items, formatHitRow)
    )
    push(lines, '  [稠密召回·改写]')
    lines.push(
      ...formatRows('稠密改写', safe.dense_rewritten?.items, formatHitRow)
    )
    push(lines, '  [稀疏召回]')
    lines.push(...formatRows('稀疏', safe.sparse?.items, formatHitRow))
    push(lines, '  [问答对召回]')
    lines.push(...formatRows('问答对', safe.qa_pairs, (r) => `${r.id} | ${r.question || ''} | ${r.scoreText || r.score} | 映射 ${(r.mapped_chunk_ids || r.mappedChunkIds || []).join(',') || '未知'}`))
    if (safe.sparse_queries) push(lines, `  稀疏查询：${JSON.stringify(redactSecrets(safe.sparse_queries))}`)
    return
  }
  if (stepKey === 'fusion') {
    push(lines, `  方法：${safe.method || 'RRF'} · k=${safe.k ?? '未知'}`)
    lines.push(...formatRows('融合', safe.items, (r) => `${r.id} | 稠密${r.denseRank ?? '-'} 稀疏${r.sparseRank ?? '-'} | RRF ${r.scoreText || r.score}`))
    return
  }
  if (stepKey === 'rerank') {
    push(lines, `  模型：${safe.model || '未返回'}`)
    push(lines, `  策略：重排始终启用`)
    if (safe.dropped != null) push(lines, `  过滤：丢弃 ${safe.dropped} 条`)
    lines.push(...formatRows('重排', safe.items, (r) => `${r.id} | 重排 ${r.rerankText || r.rerankScore || '-'} | 融合位 ${r.rank || '-'}`))
    return
  }
  if (stepKey === 'assemble') {
    const ids = safe.ids?.length ? safe.ids.join('、') : '无'
    push(lines, `  入选片段：${ids}`)
    push(lines, `  上下文 tokens：${formatUnknownNumber(safe.tokens)} / 预算 ${formatUnknownNumber(safe.budget)}`)
    const prompt = String(safe.prompt || '')
    if (!prompt) push(lines, '  提示词：未返回')
    else if (prompt.length > MAX_PROMPT_CHARS) {
      push(lines, `  提示词（截断至 ${MAX_PROMPT_CHARS} 字）：\n${prompt.slice(0, MAX_PROMPT_CHARS)}…`)
    } else push(lines, `  提示词：\n${prompt}`)
    return
  }
  if (stepKey === 'generate') {
    push(lines, `  模型：${safe.model || '未知'} | temperature ${safe.temperature ?? '未知'}`)
    push(lines, `  流式：${safe.streaming ? '是' : '否'}`)
    push(lines, `  输入 tokens：${formatUnknownNumber(safe.inputTokens)} | 输出 tokens：${formatUnknownNumber(safe.outputTokens)}`)
    return
  }
  if (stepKey === 'embed') {
    push(lines, `  模型：${safe.model || '未知'} | 维度 ${safe.dim || '未知'}`)
    const queries = Array.isArray(safe.queries)
      ? safe.queries
      : safe.input
        ? [safe.input]
        : []
    if (!queries.length) push(lines, '  查询：未返回')
    else queries.forEach((q, idx) => push(lines, `  查询 ${idx + 1}：${q}`))
    push(lines, `  tokens：${formatUnknownNumber(safe.tokens)}`)
    return
  }
  push(lines, `  详情：${JSON.stringify(safe, null, 2)}`)
}

export function buildTraceLog(context = {}) {
  const trace = context.trace || {}
  const meta = context.meta || {}
  const lines = []
  const started = trace.startedAt ? new Date(trace.startedAt).toISOString() : '未知'
  const finished = trace.finishedAt ? new Date(trace.finishedAt).toISOString() : '未知'

  lines.push('西游问典 · RAG 全链路日志')
  lines.push('='.repeat(48))
  lines.push(`回答状态：${statusLabel(context.status || trace.status)}`)
  lines.push(`用户提问：${trace.query || '未知'}`)
  if (context.error) lines.push(`错误信息：${context.error}`)
  lines.push(`开始时间：${started}`)
  lines.push(`结束时间：${finished}`)
  lines.push('')

  let totalMs = 0
  let totalCost = 0
  let costKnown = true

  lines.push('[执行链路]')
  for (const step of PIPELINE_STEPS) {
    const stage = trace.stages?.[step.key] || { status: 'idle' }
    const ms = Number(stage.ms) || 0
    totalMs += ms
    if (stage.cost === null || stage.cost === undefined || stage.cost === '') {
      // keep
    } else {
      const c = Number(stage.cost)
      if (!Number.isNaN(c)) totalCost += c
      else costKnown = false
    }
    if (stage.cost === null || stage.cost === undefined) costKnown = costKnown && false

    lines.push(`- ${step.name} (${step.key})`)
    lines.push(`  状态：${statusLabel(stage.status)} | 耗时：${ms ? `${ms} ms` : '未知'} | 费用：${formatCost(stage.cost)}`)
    if (stage.summary) lines.push(`  摘要：${stage.summary}`)
    if (stage.detail) appendStageDetail(step.key, stage.detail, lines)
    else if (stage.status && stage.status !== 'idle') lines.push('  详情：未返回')
    lines.push('')
  }

  lines.push('[送入模型的引用片段]')
  const hitLines = summarizeHits(trace.hits || [])
  if (hitLines.length) hitLines.forEach((l) => lines.push(l))
  else lines.push('(无引用片段 / 未返回)')
  lines.push('')

  lines.push('[生成汇总]')
  lines.push(`  总链路耗时（各步相加）：${totalMs ? `${totalMs} ms` : '未知'}`)
  lines.push(`  总链路费用（各步相加）：${costKnown ? formatCost(totalCost) : '无法估算'}`)
  lines.push(`  接口返回延迟：${formatUnknownNumber(meta.latency, ' ms')}`)
  lines.push(`  输出 tokens：${formatUnknownNumber(meta.tokens)}`)
  lines.push(`  问答费用（若返回）：${formatCost(meta.cost)}`)
  if (context.answerText) {
    lines.push('')
    lines.push('[助手回答正文]')
    lines.push(String(context.answerText))
  }
  lines.push('')
  lines.push('— 日志结束（已脱敏，不含密钥/认证信息）—')
  return lines.join('\n')
}

/** 原始全链路日志：完整 trace JSON（密钥字段脱敏），供复制与排查。 */
export function buildRawTraceLog(context = {}) {
  const trace = context.trace || {}
  const payload = {
    type: 'xiyou_rag_trace_raw',
    exportedAt: new Date().toISOString(),
    status: context.status || trace.status || 'unknown',
    error: context.error || null,
    query: trace.query || null,
    meta: redactSecrets(context.meta || {}),
    trace: redactSecrets({
      query: trace.query,
      status: trace.status,
      startedAt: trace.startedAt,
      finishedAt: trace.finishedAt,
      hits: trace.hits,
      stages: trace.stages,
      costs: trace.costs,
      channels: trace.channels,
      errors: trace.errors,
      stopped: trace.stopped
    }),
    answerText: context.answerText || null
  }
  return JSON.stringify(payload, null, 2)
}

export async function copyTraceLog(context = {}) {
  const text = buildRawTraceLog(context)
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return { ok: true, text }
    }
  } catch {
    // fallback below
  }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.left = '-9999px'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    if (ok) return { ok: true, text }
  } catch {
    // manual
  }
  return { ok: false, text }
}
