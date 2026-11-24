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
  return { status: 'idle', ms: 0, cost: null, summary: '等待查询', detail: null }
}
