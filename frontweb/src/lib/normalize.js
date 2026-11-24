function pick(obj, keys, fallback = null) {
  for (const key of keys) {
    if (obj?.[key] !== undefined && obj?.[key] !== null) return obj[key]
  }
  return fallback
}

export function normalizeSource(raw = {}) {
  const qa = raw.qa_pairs || raw.qaPairs || {}
  return {
    name: pick(raw, ['name', 'file_name'], '西游记.txt'),
    author: pick(raw, ['author'], '吴承恩（明）'),
    size: pick(raw, ['size', 'file_size_label'], '—'),
    chapters: Number(pick(raw, ['chapters', 'chapter_count'], 0)) || 0,
    chunkCount: Number(pick(raw, ['chunkCount', 'chunk_count', 'chunks'], 0)) || 0,
    embeddingModel: pick(raw, ['embeddingModel', 'embedding_model'], 'text-embedding-v4'),
    dimension: Number(pick(raw, ['dimension', 'vector_dim'], 1024)) || 1024,
    indexedAt: pick(raw, ['indexedAt', 'indexed_at'], '—'),
    chunkSize: Number(pick(raw, ['chunkSize', 'chunk_size'], 512)) || 512,
    chunkOverlap: Number(pick(raw, ['chunkOverlap', 'chunk_overlap'], 64)) || 64,
    status: pick(raw, ['status', 'index_status'], 'unknown'),
    activeVersion: pick(raw, ['activeVersion', 'active_version'], null),
    buildingVersion: pick(raw, ['buildingVersion', 'building_version'], null),
    qaPairCount: Number(pick(qa, ['loaded', 'count'], pick(raw, ['qa_pair_count', 'qaPairCount'], 0))) || 0,
    qaPairsEnabled: Boolean(pick(qa, ['enabled'], raw.qa_pairs_enabled ?? true))
  }
}

export function normalizeDistribution(raw = []) {
  if (!Array.isArray(raw)) return []
  return raw.map((item) => ({
    label: item.label || item.name || '未命名',
    value: Number(item.value ?? item.count ?? 0) || 0
  }))
}

export function normalizeChunk(raw = {}) {
  const chapter = Number(raw.chapter ?? raw.chapter_no ?? 0) || 0
  const chapterTitle = raw.chapterTitle || raw.chapter_title || (chapter ? `第 ${chapter} 回` : '未知回目')
  return {
    id: raw.id || raw.chunk_id || '',
    chapter,
    chapterTitle,
    tokens: Number(raw.tokens ?? raw.token_count ?? 0) || 0,
    text: raw.text || raw.content || '',
    score: raw.score ?? null,
    scoreText: raw.scoreText || (raw.score != null ? Number(raw.score).toFixed(3) : null)
  }
}

export function normalizeHit(raw = {}, index = 0) {
  const channel = raw.channel || raw.source_type || (raw.question ? 'qa_pair' : 'chunk')
  const chunk = normalizeChunk(raw.chunk || raw)
  const score = Number(raw.score ?? raw.rerank_score ?? raw.dense_score ?? 0)
  return {
    id: raw.id || chunk.id,
    rank: Number(raw.rank ?? index + 1),
    score,
    scoreText: raw.scoreText || Number(score).toFixed(3),
    channel,
    question: raw.question || '',
    mappedChunkIds: raw.mapped_chunk_ids || raw.mappedChunkIds || [],
    qaPairHit: Boolean(raw.qa_pair_hit || raw.qaPairHit),
    chunk
  }
}

function normalizeEstimateStage(stage = {}) {
  const key = stage.key || stage.name
  const labelMap = {
    embedding: '原文分块向量化',
    chunk_embed: '原文分块向量化',
    qa_generate: '问答对生成',
    qa_gen: '问答对生成',
    qa_pair_gen: '问答对生成',
    qa_embed: '问答对向量化',
    qa_index: '问答对入库'
  }
  const cost = stage.cost ?? stage.amount ?? (stage.cost_breakdown?.amount ?? null)
  return {
    key,
    label: stage.label || stage.title || labelMap[key] || key,
    cost,
    usage: stage.usage || stage.summary || '',
    usage_known: stage.usage_known ?? stage.usageKnown
  }
}

export function normalizeEstimate(raw = {}) {
  const estimate = raw.estimate || raw
  const stages = Array.isArray(estimate.stages) ? estimate.stages : []
  return {
    mode: estimate.mode || raw.mode || 'rebuild',
    chunkCount: Number(estimate.chunkCount ?? estimate.chunk_count ?? 0) || 0,
    qaPairCount: Number(estimate.qaPairCount ?? estimate.qa_pair_count ?? 0) || 0,
    totalCost: estimate.totalCost ?? estimate.total_cost ?? null,
    currency: estimate.currency || 'CNY',
    warning: estimate.warning || '',
    note: estimate.note || estimate.summary || '',
    requiresConfirmation: Boolean(
      estimate.requires_confirmation ?? estimate.requiresConfirmation ?? ['initial', 'rebuild'].includes(estimate.mode || raw.mode)
    ),
    estimateId: estimate.estimate_id || estimate.estimateId || '',
    stages: stages.map(normalizeEstimateStage)
  }
}

export function normalizeIndexJob(raw = {}) {
  const status = raw.status || 'queued'
  const stages = Array.isArray(raw.stages) ? raw.stages : []
  return {
    id: raw.id || raw.job_id || raw.task_id || '',
    status: status === 'succeeded' ? 'completed' : status,
    progress: Number(raw.progress ?? 0) || 0,
    message: raw.message || raw.summary || '',
    costSoFar: raw.costSoFar ?? raw.cost_so_far ?? null,
    currentStage: raw.current_stage || raw.currentStage || '',
    activeVersion: raw.activeVersion ?? raw.active_version ?? null,
    buildingVersion: raw.buildingVersion ?? raw.building_version ?? null,
    switched: Boolean(raw.switched),
    error: raw.error || '',
    stages: stages.map(normalizeEstimateStage)
  }
}

export function normalizeSettings(raw = {}, fallback = {}) {
  return {
    ...fallback,
    ...raw,
    topK: Number(raw.topK ?? raw.top_k ?? fallback.topK ?? 4),
    temperature: Number(raw.temperature ?? fallback.temperature ?? 0.3),
    model: raw.model || fallback.model || 'qwen-plus',
    chunkSize: Number(raw.chunkSize ?? raw.chunk_size ?? fallback.chunkSize ?? 512),
    chunkOverlap: Number(raw.chunkOverlap ?? raw.chunk_overlap ?? fallback.chunkOverlap ?? 64),
    streaming: raw.streaming ?? fallback.streaming ?? true,
    systemPrompt: raw.systemPrompt || raw.system_prompt || fallback.systemPrompt || ''
  }
}
