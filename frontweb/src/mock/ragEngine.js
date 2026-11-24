import { chunks, chunkById, SOURCE_FILE } from '../data/knowledge'
import { qaPairs } from '../data/qa'

export const PIPELINE_STEPS = [
  { key: 'rewrite', name: '查询改写' },
  { key: 'embed', name: '向量化' },
  { key: 'retrieve', name: '稠密 + 稀疏召回' },
  { key: 'fusion', name: '融合' },
  { key: 'rerank', name: '重排' },
  { key: 'assemble', name: '组装上下文' },
  { key: 'generate', name: '生成' }
]

export function emptyStage() {
  return { status: 'idle', ms: 0, cost: 0, summary: '等待查询', detail: null }
}

export function formatCost(value) {
  const n = Number(value) || 0
  if (n === 0) return '¥0'
  return `¥${n.toFixed(6)}`
}

export const defaultSettings = {
  topK: 4,
  threshold: 0.35,
  rerank: true,
  temperature: 0.3,
  model: 'mock-llm-7b',
  chunkSize: 512,
  chunkOverlap: 64,
  streaming: true,
  systemPrompt: '你是《西游记》阅读助手。请严格依据检索到的原文片段回答问题，回答末尾用 [n] 标注引用来源。若片段不足以回答，请如实说明。'
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

function hashText(text) {
  let h = 2166136261
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return Math.abs(h)
}

function seeded(seed) {
  let s = seed || 1
  return () => {
    s = (s * 1664525 + 1013904223) % 4294967296
    return s / 4294967296
  }
}

function bigrams(text) {
  const cleaned = String(text || '').replace(/[\s\W_]/g, '')
  const result = []
  for (let i = 0; i < cleaned.length - 1; i++) result.push(cleaned.slice(i, i + 2))
  return result
}

function dice(a, b) {
  if (!a.length || !b.length) return 0
  const setB = new Set(b)
  let hit = 0
  for (const g of a) if (setB.has(g)) hit++
  return (2 * hit) / (a.length + b.length)
}

function normalize(text) {
  return String(text || '').replace(/[\s，。？！、；：""''《》\[\](),.?!"-]/g, '').toLowerCase()
}

/** 把用户问题匹配到预设问答，返回命中分 */
export function matchQuestion(query) {
  const q = normalize(query)
  const qGram = bigrams(q)
  let best = null
  let bestScore = 0

  for (const item of qaPairs) {
    let score = 0
    // 关键词直接命中权重最高
    for (const kw of item.keywords) {
      const nk = normalize(kw)
      if (q.includes(nk)) score += Math.min(0.42, 0.16 + nk.length * 0.045)
      else score += dice(qGram, bigrams(nk)) * 0.16
    }
    // 与标准问法的整体相似度
    score += dice(qGram, bigrams(normalize(item.question))) * 0.46
    if (score > bestScore) {
      bestScore = score
      best = item
    }
  }
  return { item: best, score: Math.min(1, bestScore) }
}

/** 无预设命中时，按原文片段做关键词召回（模拟向量检索） */
function fallbackHits(query, count) {
  const q = normalize(query)
  const qGram = bigrams(q)
  return chunks
    .map((chunk) => {
      const kwScore = chunk.keywords.reduce((sum, kw) => {
        const nk = normalize(kw)
        if (!nk) return sum
        return sum + (q.includes(nk) ? 0.3 : dice(qGram, bigrams(nk)) * 0.12)
      }, 0)
      const textScore = dice(qGram, bigrams(chunk.text)) * 0.35
      return { id: chunk.id, score: Math.min(0.92, 0.34 + kwScore + textScore) }
    })
    .sort((a, b) => b.score - a.score)
    .slice(0, count)
}

function buildFallbackAnswer(query, hits, settings) {
  if (!hits.length) {
    return `我没有在《西游记》知识库中找到足够相关的内容。所有片段与问题「${query}」的相似度都低于当前阈值 **${settings.threshold.toFixed(2)}**。\n\n可以尝试换一种问法，或在设置中降低相似度阈值后重新检索。`
  }
  const top = chunkById[hits[0].id]
  const excerpt = top.text.length > 130 ? top.text.slice(0, 130) + '……' : top.text
  return `知识库中没有与「${query}」完全对应的问答，以下是**语义最相关**的原文片段，供你参考：\n\n> ${excerpt} [1]\n\n这段出自**第 ${top.chapter} 回**。如果你想了解更具体的情节，可以换个关键词再问一次，或参考下方推荐问题。`
}

function tokenize(answer) {
  return answer.match(/\[\d+\]|[\s\S]{1,3}/g) || []
}

const EMBED_MODEL = 'bge-large-zh-v1.5'
const RERANK_MODEL = 'bge-reranker-large'
const EMBED_DIM = 1024
const RRF_K = 60
const CANDIDATE_N = 8
const PRICE = {
  embedPerK: 0.0007,
  rerankPerK: 0.0008,
  genInPerK: 0.0008,
  genOutPerK: 0.002
}

function yuan(tokens, perK) {
  return Math.round((tokens / 1000) * perK * 1e6) / 1e6
}

function countTokens(text) {
  return Math.max(1, Math.ceil(String(text || '').length * 0.7))
}

function snippetOf(text, n = 28) {
  const s = String(text || '').replace(/\s+/g, '')
  return s.length > n ? `${s.slice(0, n)}…` : s
}

function expandShortName(text, short, full) {
  const prefix = full.slice(0, full.length - short.length)
  return text.replace(new RegExp(short, 'g'), (matched, offset, src) => {
    if (offset >= prefix.length && src.slice(offset - prefix.length, offset) === prefix) return matched
    return full
  })
}

function rewriteQuery(query) {
  const original = String(query || '').trim()
  let text = original
  const notes = []
  const stripped = text.replace(/^(请问|问一下|我想知道|帮我看看|帮我|告诉我)/, '').trim()
  if (stripped && stripped !== text) {
    text = stripped
    notes.push('去掉口语前缀')
  }
  const noTail = text.replace(/[吗呢啊呀？?]+$/g, '').trim()
  if (noTail && noTail !== text) {
    text = noTail
    notes.push('去掉句末语气词')
  }
  const expanded = expandShortName(expandShortName(expandShortName(text, '悟空', '孙悟空'), '八戒', '猪八戒'), '悟净', '沙悟净')
    .replace(/唐僧/g, '唐三藏')
  if (expanded !== text) {
    text = expanded
    notes.push('简称补成书中全名')
  }
  return {
    original,
    rewritten: text || original,
    reason: notes.length ? notes.join('，') : '问句已经具体，规则改写保持原句',
    method: '规则改写'
  }
}

function vectorPreview(text) {
  const rand = seeded(hashText(text) || 1)
  return Array.from({ length: 8 }, () => Number((rand() * 2 - 1).toFixed(4)))
}

function denseScore(query, chunk) {
  const q = normalize(query)
  const qGram = bigrams(q)
  const kwScore = chunk.keywords.reduce((sum, kw) => {
    const nk = normalize(kw)
    if (!nk) return sum
    return sum + (q.includes(nk) ? 0.28 : dice(qGram, bigrams(nk)) * 0.1)
  }, 0)
  return Math.min(0.99, 0.18 + kwScore + dice(qGram, bigrams(chunk.text)) * 0.55)
}

function sparseScore(query, chunk) {
  const q = normalize(query)
  const grams = [...new Set(bigrams(q))]
  const doc = normalize(`${chunk.text}${chunk.keywords.join('')}`)
  let overlap = 0
  for (const gram of grams) if (doc.includes(gram)) overlap++
  const kwHits = chunk.keywords.filter((kw) => q.includes(normalize(kw))).length
  const tf = overlap / Math.sqrt(Math.max(20, doc.length) / 80)
  return Number((tf * 2.4 + kwHits * 1.6).toFixed(3))
}

function asCandidate(chunk, score, rank) {
  return {
    id: chunk.id,
    rank,
    chapter: chunk.chapter,
    chapterLabel: `第 ${chunk.chapter} 回`,
    snippet: snippetOf(chunk.text),
    tokens: chunk.tokens,
    score,
    scoreText: Number(score).toFixed(3)
  }
}

function topCandidates(scored, count) {
  return scored
    .slice()
    .sort((a, b) => b.score - a.score)
    .slice(0, count)
    .map((item, index) => asCandidate(item.chunk, item.score, index + 1))
}

function buildChannels(query, match) {
  const denseMap = new Map()
  if (match.item && match.score >= 0.3) {
    for (const hit of match.item.hits) {
      const chunk = chunkById[hit.id]
      if (chunk) denseMap.set(hit.id, { chunk, score: hit.score })
    }
  }
  for (const chunk of chunks) {
    if (!denseMap.has(chunk.id)) denseMap.set(chunk.id, { chunk, score: denseScore(query, chunk) })
  }
  return {
    dense: topCandidates([...denseMap.values()], CANDIDATE_N),
    sparse: topCandidates(chunks.map((chunk) => ({ chunk, score: sparseScore(query, chunk) })), CANDIDATE_N)
  }
}

function fuse(dense, sparse) {
  const denseById = new Map(dense.map((item) => [item.id, item]))
  const sparseById = new Map(sparse.map((item) => [item.id, item]))
  const ids = new Set([...denseById.keys(), ...sparseById.keys()])
  return [...ids]
    .map((id) => {
      const denseHit = denseById.get(id)
      const sparseHit = sparseById.get(id)
      const chunk = chunkById[id]
      const score = (denseHit ? 1 / (RRF_K + denseHit.rank) : 0) + (sparseHit ? 1 / (RRF_K + sparseHit.rank) : 0)
      return {
        id,
        chapter: chunk.chapter,
        chapterLabel: `第 ${chunk.chapter} 回`,
        snippet: snippetOf(chunk.text),
        tokens: chunk.tokens,
        denseRank: denseHit?.rank || null,
        sparseRank: sparseHit?.rank || null,
        denseScore: denseHit?.score ?? null,
        score: Number(score.toFixed(6)),
        scoreText: score.toFixed(4)
      }
    })
    .sort((a, b) => b.score - a.score)
    .map((row, index) => ({ ...row, rank: index + 1 }))
}

function rerankRows(fused, query, settings, match) {
  const preset = new Map()
  if (match.item && match.score >= 0.3) {
    for (const hit of match.item.hits) preset.set(hit.id, hit.score)
  }
  const floor = preset.size ? Math.min(...preset.values()) : 1
  const rows = fused
    .map((row) => {
      const chunk = chunkById[row.id]
      const score = preset.has(row.id)
        ? preset.get(row.id)
        : Math.min(Math.max(0.05, floor - 0.08), denseScore(query, chunk) * 0.5)
      return { ...row, rerankScore: Number(score.toFixed(3)), rerankText: score.toFixed(3) }
    })
    .sort((a, b) => b.rerankScore - a.rerankScore)
    .map((row, index) => ({ ...row, rerankRank: index + 1 }))
  return {
    rows,
    dropped: rows.filter((row) => row.rerankScore < settings.threshold).length
  }
}

function orderWithoutRerank(fused, match) {
  if (!(match.item && match.score >= 0.3)) return fused
  const order = new Map(match.item.hits.map((hit, index) => [hit.id, index]))
  return fused.slice().sort((a, b) => (order.get(a.id) ?? 99) - (order.get(b.id) ?? 99))
}

function selectHits(rows, settings) {
  return rows
    .filter((row) => {
      const score = settings.rerank ? row.rerankScore : (row.denseScore ?? 0)
      return score >= settings.threshold
    })
    .slice(0, settings.topK)
    .map((row, index) => {
      const chunk = chunkById[row.id]
      const score = settings.rerank ? row.rerankScore : (row.denseScore ?? row.score)
      return {
        id: row.id,
        rank: index + 1,
        score,
        scoreText: Number(score).toFixed(3),
        chunk: { ...chunk, chapterTitle: `第 ${chunk.chapter} 回` }
      }
    })
}

function buildPrompt(query, hits, settings) {
  const context = hits.length
    ? hits.map((hit, index) => `[${index + 1}] ${hit.chunk.chapterTitle} ${hit.id}\n${hit.chunk.text}`).join('\n\n')
    : '（没有片段通过阈值）'
  const prompt = `${settings.systemPrompt}\n\n检索片段：\n${context}\n\n问题：${query}`
  return {
    ids: hits.map((hit) => hit.id),
    tokens: countTokens(prompt),
    budget: settings.chunkSize * Math.max(hits.length, 1),
    prompt
  }
}

/**
 * 模拟混合检索 RAG 链路。
 * callbacks: { onStage(key, patch), onHits(hits), onToken(text), onAnswer(answer) }
 * control: { cancelled: boolean } 用于中止生成
 */
export async function runRagPipeline(query, settings, callbacks, control = {}) {
  const rand = seeded(hashText(query))
  const t = (min, max) => Math.round(min + rand() * (max - min))
  const stage = (key, patch) => callbacks.onStage?.(key, patch)
  let current = ''

  const begin = (key, summary) => {
    current = key
    stage(key, { status: 'running', summary, ms: 0, cost: 0, detail: null })
  }
  const aborted = () => {
    if (!control.cancelled) return false
    if (current) stage(current, { status: 'stopped', summary: '已停止' })
    return true
  }

  const rewritten = rewriteQuery(query)
  begin('rewrite', rewritten.method)
  await sleep(t(160, 260))
  if (aborted()) return
  stage('rewrite', {
    status: 'done',
    ms: t(8, 24),
    cost: 0,
    summary: rewritten.rewritten === rewritten.original ? '保持原句' : '已改写问句',
    detail: rewritten
  })

  const embedTokens = countTokens(rewritten.rewritten)
  const embedCost = yuan(embedTokens, PRICE.embedPerK)
  begin('embed', `${EMBED_MODEL} · ${EMBED_DIM} 维`)
  await sleep(t(220, 360))
  if (aborted()) return
  stage('embed', {
    status: 'done',
    ms: t(36, 88),
    cost: embedCost,
    summary: `${embedTokens} tokens · ${formatCost(embedCost)}`,
    detail: {
      model: EMBED_MODEL,
      dim: EMBED_DIM,
      input: rewritten.rewritten,
      preview: vectorPreview(rewritten.rewritten),
      tokens: embedTokens,
      price: `¥${PRICE.embedPerK.toFixed(4)} / 千 tokens`
    }
  })

  begin('retrieve', `检索 ${SOURCE_FILE.chunkCount.toLocaleString('zh-CN')} 个分块`)
  await sleep(t(280, 460))
  if (aborted()) return
  const match = matchQuestion(rewritten.rewritten)
  const channels = buildChannels(rewritten.rewritten, match)
  stage('retrieve', {
    status: 'done',
    ms: t(70, 150),
    cost: 0,
    summary: `稠密 ${channels.dense.length} 条 · 稀疏 ${channels.sparse.length} 条`,
    detail: {
      indexSize: SOURCE_FILE.chunkCount,
      dense: { metric: '余弦相似度', items: channels.dense },
      sparse: { metric: 'BM25', items: channels.sparse }
    }
  })

  begin('fusion', `RRF · k=${RRF_K}`)
  await sleep(t(120, 200))
  if (aborted()) return
  const fused = fuse(channels.dense, channels.sparse)
  stage('fusion', {
    status: 'done',
    ms: t(4, 16),
    cost: 0,
    summary: `合并 ${fused.length} 条候选`,
    detail: { method: 'RRF', k: RRF_K, items: fused }
  })

  if (!settings.rerank) {
    stage('rerank', {
      status: 'skipped',
      ms: 0,
      cost: 0,
      summary: '已在设置中关闭重排序',
      detail: {
        skipped: true,
        model: RERANK_MODEL,
        threshold: settings.threshold,
        dropped: 0,
        items: fused
      }
    })
  } else {
    begin('rerank', `${RERANK_MODEL} · 精排候选`)
    await sleep(t(240, 420))
    if (aborted()) return
  }
  const ranked = rerankRows(fused, rewritten.rewritten, settings, match)
  const contextPool = settings.rerank ? ranked.rows : orderWithoutRerank(fused, match)
  const hits = selectHits(contextPool, settings)
  if (settings.rerank) {
    const rerankTokens = embedTokens + ranked.rows.reduce((sum, row) => sum + (row.tokens || 0), 0)
    const rerankCost = yuan(rerankTokens, PRICE.rerankPerK)
    stage('rerank', {
      status: 'done',
      ms: t(40, 110),
      cost: rerankCost,
      summary: `丢掉 ${ranked.dropped} 条 · ${formatCost(rerankCost)}`,
      detail: {
        skipped: false,
        model: RERANK_MODEL,
        threshold: settings.threshold,
        dropped: ranked.dropped,
        tokens: rerankTokens,
        price: `¥${PRICE.rerankPerK.toFixed(4)} / 千 tokens`,
        items: ranked.rows
      }
    })
  }
  callbacks.onHits?.(hits)

  const packed = buildPrompt(rewritten.rewritten, hits, settings)
  begin('assemble', hits.length ? `入选 ${hits.length} 个片段` : '没有片段过阈值')
  await sleep(t(120, 200))
  if (aborted()) return
  stage('assemble', {
    status: 'done',
    ms: t(3, 12),
    cost: 0,
    summary: `${packed.tokens} tokens`,
    detail: packed
  })

  const answer = match.item && match.score >= 0.3
    ? match.item.answer
    : buildFallbackAnswer(query, hits, settings)
  const outputTokens = countTokens(answer)
  const genCost = yuan(packed.tokens, PRICE.genInPerK) + yuan(outputTokens, PRICE.genOutPerK)
  begin('generate', `${settings.model} · temperature ${settings.temperature}`)
  await sleep(t(160, 280))
  if (aborted()) return

  if (settings.streaming) {
    const tokens = tokenize(answer)
    for (let i = 0; i < tokens.length; i++) {
      if (aborted()) return
      callbacks.onToken?.(tokens[i])
      await sleep(tokens[i].startsWith('[') ? 36 : t(16, 30))
    }
  } else {
    callbacks.onToken?.(answer)
  }
  stage('generate', {
    status: 'done',
    ms: t(480, 980),
    cost: genCost,
    summary: `输出 ${outputTokens} tokens · ${formatCost(genCost)}`,
    detail: {
      model: settings.model,
      temperature: settings.temperature,
      streaming: settings.streaming,
      inputTokens: packed.tokens,
      outputTokens,
      priceIn: `¥${PRICE.genInPerK.toFixed(4)} / 千 tokens`,
      priceOut: `¥${PRICE.genOutPerK.toFixed(4)} / 千 tokens`
    }
  })
  callbacks.onAnswer?.({
    text: answer,
    hits,
    usedIds: new Set(hits.map((hit) => hit.id)),
    followUps: match.item?.followUps || [
      '孙悟空是怎么诞生的？',
      '唐僧师徒取经经历了多少难？'
    ],
    latency: t(1600, 2800),
    tokens: outputTokens,
    cost: genCost
  })
}

/** 高亮片段中命中查询的词 */
export function highlightTerms(text, query) {
  const terms = [...new Set(
    (query.match(/[一-龥]{2,4}/g) || []).concat(
      (query.match(/[a-zA-Z0-9]{2,}/g) || [])
    )
  )]
    .filter((w) => w.length >= 2)
    .sort((a, b) => b.length - a.length)
    .slice(0, 8)
  if (!terms.length) return text
  const escaped = terms.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  const re = new RegExp(`(${escaped.join('|')})`, 'g')
  return text.replace(re, '<mark>$1</mark>')
}
