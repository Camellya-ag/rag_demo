<script setup>
import { computed, ref, watch } from 'vue'
import { highlightTerms } from '../lib/highlight'
import { formatCost } from '../lib/format'
import { PIPELINE_STEPS } from '../lib/pipeline'

const props = defineProps({
  embedded: { type: Boolean, default: false },
  expandAll: { type: Boolean, default: false },
  hits: { type: Array, default: () => [] },
  stages: { type: Object, required: true },
  query: { type: String, default: '' },
  busy: { type: Boolean, default: false }
})
const emit = defineEmits(['focus-hit'])

const openKey = ref('')
const collapsedKeys = ref(new Set())
const dialogVisible = ref(false)
const dialogTitle = ref('')
const dialogKind = ref('')
const dialogDetail = ref(null)

const autoExpandAll = computed(() => props.expandAll || props.embedded)

watch(() => props.stages, (stages) => {
  const running = PIPELINE_STEPS.find((step) => stages[step.key]?.status === 'running')
  if (running && !autoExpandAll.value) {
    openKey.value = running.key
    return
  }
  const idle = PIPELINE_STEPS.every((step) => (stages[step.key]?.status || 'idle') === 'idle')
  if (idle) {
    openKey.value = ''
    collapsedKeys.value = new Set()
  }
}, { deep: true })

function toggle(key) {
  if (autoExpandAll.value) {
    const next = new Set(collapsedKeys.value)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    collapsedKeys.value = next
    return
  }
  openKey.value = openKey.value === key ? '' : key
}

function isStepOpen(key) {
  const status = stageOf(key).status || 'idle'
  if (status === 'idle') return false
  if (autoExpandAll.value) return !collapsedKeys.value.has(key)
  if (status === 'running') return true
  return openKey.value === key
}

function stageOf(key) {
  return props.stages[key] || {}
}

function statusText(step) {
  const stage = stageOf(step.key)
  if (stage.status === 'unknown') return '未知'
  if (stage.status === 'done') return stage.ms ? `${stage.ms} ms` : '完成'
  if (stage.status === 'running') return '处理中'
  if (stage.status === 'skipped') return '已跳过'
  if (stage.status === 'stopped') return '已停止'
  return '等待'
}

const totals = computed(() => {
  let ms = 0
  let cost = 0
  let started = false
  for (const step of PIPELINE_STEPS) {
    const stage = props.stages[step.key]
    if (!stage || stage.status === 'idle') continue
    started = true
    ms += Number(stage.ms) || 0
    cost += Number(stage.cost) || 0
  }
  return { ms, cost, started }
})

const highlights = computed(() => props.hits.map((hit) => ({
  ...hit,
  html: highlightTerms(hit.chunk?.text || '', props.query)
})))

const inlineLimit = computed(() => (autoExpandAll.value ? 12 : 3))

function preview(items) {
  return (items || []).slice(0, inlineLimit.value)
}

function retrieveDenseOriginal(detail = {}) {
  return detail.dense_original || detail.denseOriginal || detail.dense || { metric: '余弦相似度', items: [] }
}

function retrieveDenseRewritten(detail = {}) {
  return detail.dense_rewritten || detail.denseRewritten || { metric: '余弦相似度', items: [] }
}

function embedQueries(detail = {}) {
  if (Array.isArray(detail.queries) && detail.queries.length) return detail.queries
  if (detail.input) return [detail.input]
  return []
}

function openDialog(kind, title, detail) {
  dialogKind.value = kind
  dialogTitle.value = title
  dialogDetail.value = detail
  dialogVisible.value = true
}

function rankPair(row) {
  const dense = row.denseRank ? `稠密 ${row.denseRank}` : '稠密 —'
  const sparse = row.sparseRank ? `稀疏 ${row.sparseRank}` : '稀疏 —'
  const qa = row.qaRank ? `问答 ${row.qaRank}` : (row.qa_pair_hit || row.qaPairHit ? '问答命中' : '问答 —')
  return `${dense} / ${sparse} / ${qa}`
}

const FUSION_CHANNEL_LABELS = ['稠密原问', '稠密改写', '稀疏', '问答映射']

function fusionChannelRanks(row) {
  if (row.denseRank || row.sparseRank || row.qaRank) return rankPair(row)
  const parts = (row.rrf_ranks || []).map(([idx, rank]) => `${FUSION_CHANNEL_LABELS[idx] || `路${Number(idx) + 1}`} #${rank}`)
  return parts.length ? parts.join(' · ') : '未命中各路名次'
}

function focusQaRow(row) {
  const target = row.mapped_chunk_ids?.[0] || row.mappedChunkIds?.[0] || row.id
  emit('focus-hit', target)
}

function rewriteChanged(detail = {}) {
  if (detail.changed === true) return true
  const a = String(detail.original || '').trim()
  const b = String(detail.rewritten || '').trim()
  return Boolean(a && b && a !== b)
}
</script>

<template>
  <aside class="panel inspect" :class="{ embedded }">
    <div v-if="!embedded" class="panel-head">
      <div class="panel-title">检索溯源</div>
      <span class="panel-sub">RAG Pipeline</span>
    </div>

    <div class="inspect-body">
      <div v-if="totals.started" class="run-summary">
        <div>
          <span>总耗时</span>
          <b>{{ totals.ms }} ms</b>
        </div>
        <div>
          <span>总费用</span>
          <b>{{ formatCost(totals.cost) }}</b>
        </div>
      </div>
      <div v-if="totals.started" class="price-note">按后端返回的 token 用量估算；未知项会显示“无法估算”。</div>

      <div class="side-section-title" style="margin-top: 2px">执行链路</div>
      <div class="trace">
        <div v-for="step in PIPELINE_STEPS" :key="step.key" class="trace-step" :class="stageOf(step.key).status || 'idle'">
          <div class="trace-dot">
            <el-icon v-if="stageOf(step.key).status === 'done'"><Check /></el-icon>
            <span v-else-if="stageOf(step.key).status === 'skipped'">–</span>
          </div>
          <div class="trace-content">
            <button type="button" class="trace-toggle" @click="toggle(step.key)">
              <span class="trace-name">{{ step.name }}</span>
              <span class="trace-meta">
                <span v-if="stageOf(step.key).status === 'done' || stageOf(step.key).status === 'skipped'" class="trace-cost">
                  {{ formatCost(stageOf(step.key).cost) }}
                </span>
                <span class="trace-time">{{ statusText(step) }}</span>
                <el-icon class="trace-chevron" :class="{ open: isStepOpen(step.key) }"><ArrowDown /></el-icon>
              </span>
            </button>

            <div v-if="isStepOpen(step.key) && stageOf(step.key).detail" class="trace-panel">
              <template v-if="step.key === 'rewrite'">
                <div class="rewrite-head">
                  <el-tag v-if="rewriteChanged(stageOf(step.key).detail)" size="small" type="success" effect="plain">已改写</el-tag>
                  <el-tag v-else size="small" type="info" effect="plain">语义未变</el-tag>
                  <span class="rewrite-cost">{{ formatCost(stageOf(step.key).cost) }}</span>
                </div>
                <div class="rewrite-compare">
                  <div class="rewrite-col">
                    <span class="rewrite-label">原问题</span>
                    <p class="rewrite-text">{{ stageOf(step.key).detail.original }}</p>
                  </div>
                  <div class="rewrite-arrow" aria-hidden="true">→</div>
                  <div class="rewrite-col" :class="{ 'rewrite-col--changed': rewriteChanged(stageOf(step.key).detail) }">
                    <span class="rewrite-label">改写后</span>
                    <p class="rewrite-text">{{ stageOf(step.key).detail.rewritten }}</p>
                  </div>
                </div>
                <div class="kv-block"><span class="kv-label">理由</span><p>{{ stageOf(step.key).detail.reason }}</p></div>
                <div class="kv-block"><span class="kv-label">方式</span><p>{{ stageOf(step.key).detail.method }}</p></div>
                <div v-if="(stageOf(step.key).detail.keywords || []).length" class="kv-block">
                  <span class="kv-label">检索关键词</span>
                  <div class="term-chips">
                    <span v-for="kw in stageOf(step.key).detail.keywords" :key="kw" class="term-chip">{{ kw }}</span>
                  </div>
                </div>
              </template>

              <template v-else-if="step.key === 'embed'">
                <div class="kv"><span>模型</span><p>{{ stageOf(step.key).detail.model }} · {{ stageOf(step.key).detail.dim }} 维</p></div>
                <div class="kv"><span>输入</span>
                  <p v-if="embedQueries(stageOf(step.key).detail).length === 1">{{ embedQueries(stageOf(step.key).detail)[0] }}</p>
                  <ul v-else class="embed-query-list">
                    <li v-for="(q, idx) in embedQueries(stageOf(step.key).detail)" :key="idx"><b>{{ idx === 0 ? '原问' : '改写' }}</b> {{ q }}</li>
                  </ul>
                </div>
                <div class="kv"><span>向量</span><p>前 8 维</p></div>
                <div v-if="(stageOf(step.key).detail.preview || []).length" class="vec-chips">
                  <i v-for="(value, index) in stageOf(step.key).detail.preview" :key="index">{{ value }}</i>
                </div>
                <div v-else class="trace-desc">改写向量预览未返回</div>
                <div class="kv" style="margin-top: 6px"><span>用量</span><p>{{ stageOf(step.key).detail.tokens }} tokens · {{ stageOf(step.key).detail.price }}</p></div>
              </template>

              <template v-else-if="step.key === 'retrieve'">
                <div class="kv"><span>索引</span><p>{{ (stageOf(step.key).detail.indexSize || 0).toLocaleString('zh-CN') }} 个分块 · 稠密/稀疏/问答对 三路召回</p></div>
                <div v-if="(stageOf(step.key).detail.sparse_queries || []).length" class="kv">
                  <span>稀疏查询</span><p>{{ stageOf(step.key).detail.sparse_queries.join(' / ') }}</p>
                </div>
                <div class="lane-title">稠密 · 原问 · {{ retrieveDenseOriginal(stageOf(step.key).detail).metric || '余弦相似度' }}</div>
                <div class="mini-list">
                  <button v-for="row in preview(retrieveDenseOriginal(stageOf(step.key).detail).items)" :key="`d0-${row.id}`" type="button" class="mini-row" @click="emit('focus-hit', row.id)">
                    <b>{{ row.rank }}</b>
                    <span>{{ row.id }}</span>
                    <span class="grow">{{ row.chapterLabel }}</span>
                    <em>{{ row.scoreText }}</em>
                  </button>
                </div>
                <div class="lane-title">稠密 · 改写 · {{ retrieveDenseRewritten(stageOf(step.key).detail).metric || '余弦相似度' }}</div>
                <div class="mini-list">
                  <button v-for="row in preview(retrieveDenseRewritten(stageOf(step.key).detail).items)" :key="`d1-${row.id}`" type="button" class="mini-row" @click="emit('focus-hit', row.id)">
                    <b>{{ row.rank }}</b>
                    <span>{{ row.id }}</span>
                    <span class="grow">{{ row.chapterLabel }}</span>
                    <em>{{ row.scoreText }}</em>
                  </button>
                </div>
                <div class="lane-title">稀疏 · {{ stageOf(step.key).detail.sparse?.metric || 'BM25' }}</div>
                <div class="mini-list">
                  <button v-for="row in preview(stageOf(step.key).detail.sparse?.items)" :key="`s-${row.id}`" type="button" class="mini-row" @click="emit('focus-hit', row.id)">
                    <b>{{ row.rank }}</b>
                    <span>{{ row.id }}</span>
                    <span class="grow">{{ row.chapterLabel }}</span>
                    <em>{{ row.scoreText }}</em>
                  </button>
                </div>
                <div class="lane-title">问答对 · 关键词命中</div>
                <div v-if="(stageOf(step.key).detail.qa_pairs || []).length" class="mini-list">
                  <button v-for="row in preview(stageOf(step.key).detail.qa_pairs)" :key="`q-${row.id}`" type="button" class="mini-row" @click="focusQaRow(row)">
                    <b>{{ row.rank }}</b>
                    <span>{{ row.id }}</span>
                    <span class="grow">{{ row.question }}</span>
                    <em>{{ row.scoreText }}</em>
                  </button>
                </div>
                <div v-else class="trace-desc">本步未返回问答对命中</div>
                <button type="button" class="linkish" @click="openDialog('retrieve', '稠密 + 稀疏 + 问答对召回', stageOf(step.key).detail)">查看完整表</button>
              </template>

              <template v-else-if="step.key === 'fusion'">
                <div class="kv"><span>方法</span><p>{{ stageOf(step.key).detail.method }} · k = {{ stageOf(step.key).detail.k }}</p></div>
                <div v-if="(stageOf(step.key).detail.channels || []).length" class="kv">
                  <span>参与路</span><p>{{ (stageOf(step.key).detail.channels || []).join(' · ') }}</p>
                </div>
                <div class="mini-list">
                  <button v-for="row in preview(stageOf(step.key).detail.items)" :key="row.id" type="button" class="mini-row" @click="emit('focus-hit', row.id)">
                    <b>{{ row.rank }}</b>
                    <span>{{ row.id }}</span>
                    <span class="grow">{{ fusionChannelRanks(row) }}</span>
                    <em>{{ row.scoreText }}</em>
                  </button>
                </div>
                <button type="button" class="linkish" @click="openDialog('fusion', '融合结果', stageOf(step.key).detail)">查看完整表</button>
              </template>

              <template v-else-if="step.key === 'rerank'">
                <div class="kv"><span>模型</span><p>{{ stageOf(step.key).detail.model || 'rerank 模型' }}</p></div>
                <div class="kv"><span>策略</span><p>重排始终启用，按 rerank 分数选取 Top-K。</p></div>
                <div v-if="stageOf(step.key).detail.dropped != null" class="kv"><span>过滤</span><p>低于阈值丢弃 {{ stageOf(step.key).detail.dropped }} 条</p></div>
                <div class="kv"><span>单价</span><p>{{ stageOf(step.key).detail.tokens ?? '未知' }} tokens · {{ stageOf(step.key).detail.price || '无法估算' }}</p></div>
                <div class="mini-list">
                  <button v-for="row in preview(stageOf(step.key).detail.items)" :key="row.id" type="button" class="mini-row" @click="emit('focus-hit', row.id)">
                    <b>{{ row.rerankRank || row.rank }}</b>
                    <span>{{ row.id }}</span>
                    <span class="grow">融合 {{ row.rank }}</span>
                    <em>{{ row.rerankText || row.scoreText }}</em>
                  </button>
                </div>
                <button type="button" class="linkish" @click="openDialog('rerank', '重排对照', stageOf(step.key).detail)">查看完整表</button>
              </template>

              <template v-else-if="step.key === 'assemble'">
                <div class="kv"><span>入选</span><p>{{ stageOf(step.key).detail.ids.length ? stageOf(step.key).detail.ids.join('、') : '无' }}</p></div>
                <div class="kv"><span>用量</span><p>{{ stageOf(step.key).detail.tokens }} / {{ stageOf(step.key).detail.budget }} tokens</p></div>
                <pre class="prompt-preview">{{ stageOf(step.key).detail.prompt }}</pre>
                <button type="button" class="linkish" @click="openDialog('prompt', '组装后的提示词', stageOf(step.key).detail)">查看全文</button>
              </template>

              <template v-else-if="step.key === 'generate'">
                <div class="kv"><span>模型</span><p>{{ stageOf(step.key).detail.model }} · temperature {{ Number(stageOf(step.key).detail.temperature).toFixed(1) }}</p></div>
                <div class="kv"><span>输出</span><p>{{ stageOf(step.key).detail.streaming ? '流式' : '一次返回' }}</p></div>
                <div class="kv"><span>输入</span><p>{{ stageOf(step.key).detail.inputTokens }} tokens · {{ stageOf(step.key).detail.priceIn }}</p></div>
                <div class="kv"><span>输出</span><p>{{ stageOf(step.key).detail.outputTokens }} tokens · {{ stageOf(step.key).detail.priceOut }}</p></div>
              </template>
            </div>
            <div v-else-if="isStepOpen(step.key)" class="trace-desc">{{ stageOf(step.key).summary || '该步骤详情暂未返回' }}</div>
            <div v-else class="trace-desc">{{ stageOf(step.key).summary || '等待查询' }}</div>
          </div>
        </div>
      </div>

      <div class="retrieval-meta">
        <span>送入模型 <b>{{ hits.length }}</b> 个片段</span>
        <span>Rerank 已启用</span>
      </div>

      <template v-if="highlights.length">
        <div
          v-for="hit in highlights"
          :key="hit.id"
          class="chunk-card"
          @click="emit('focus-hit', hit.id)"
        >
          <div class="chunk-top">
            <span class="chunk-rank">{{ hit.rank }}</span>
            <span class="chunk-chapter">{{ hit.chunk?.chapterTitle }}</span>
            <el-tag v-if="hit.qaPairHit || hit.channel === 'qa_pair'" size="small" type="warning" style="margin-left: 4px">问答映射</el-tag>
            <span class="chunk-score">{{ hit.scoreText }}</span>
          </div>
          <div class="chunk-score-bar"><i :style="{ width: Math.min(100, hit.score * 100) + '%' }"></i></div>
          <div class="chunk-text" v-html="hit.html"></div>
          <div class="chunk-foot">
            <span>{{ hit.id }} · {{ hit.chunk?.tokens }} tokens</span>
            <span>查看原文 <el-icon><ArrowRight /></el-icon></span>
          </div>
        </div>
      </template>

      <div v-else class="empty-inspect">
        <el-icon><Files /></el-icon>
        <p v-if="busy">正在从《西游记》全文中检索相关片段…</p>
        <p v-else>发送一个问题后，这里会逐步展开改写、双路召回、融合、重排和生成的耗时与费用。</p>
      </div>
    </div>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="720px" align-center append-to-body>
      <template v-if="dialogKind === 'retrieve' && dialogDetail">
        <div class="lane-title">稠密 · 原问 · {{ retrieveDenseOriginal(dialogDetail).metric }}</div>
        <el-table :data="retrieveDenseOriginal(dialogDetail).items" size="small" @row-click="(row) => emit('focus-hit', row.id)">
          <el-table-column prop="rank" label="名次" width="64" />
          <el-table-column prop="id" label="片段" width="90" />
          <el-table-column prop="chapterLabel" label="回目" width="90" />
          <el-table-column prop="scoreText" label="余弦" width="80" />
          <el-table-column prop="snippet" label="摘要" />
        </el-table>
        <div class="lane-title" style="margin-top: 14px">稠密 · 改写 · {{ retrieveDenseRewritten(dialogDetail).metric }}</div>
        <el-table :data="retrieveDenseRewritten(dialogDetail).items" size="small" @row-click="(row) => emit('focus-hit', row.id)">
          <el-table-column prop="rank" label="名次" width="64" />
          <el-table-column prop="id" label="片段" width="90" />
          <el-table-column prop="chapterLabel" label="回目" width="90" />
          <el-table-column prop="scoreText" label="余弦" width="80" />
          <el-table-column prop="snippet" label="摘要" />
        </el-table>
        <div class="lane-title" style="margin-top: 14px">稀疏 · {{ dialogDetail.sparse.metric }}</div>
        <el-table :data="dialogDetail.sparse.items" size="small" @row-click="(row) => emit('focus-hit', row.id)">
          <el-table-column prop="rank" label="名次" width="64" />
          <el-table-column prop="id" label="片段" width="90" />
          <el-table-column prop="chapterLabel" label="回目" width="90" />
          <el-table-column prop="scoreText" label="BM25" width="80" />
          <el-table-column prop="snippet" label="摘要" />
        </el-table>
        <div class="lane-title" style="margin-top: 14px">问答对 · 关键词命中</div>
        <el-table v-if="dialogDetail.qa_pairs?.length" :data="dialogDetail.qa_pairs" size="small" @row-click="(row) => focusQaRow(row)">
          <el-table-column prop="rank" label="名次" width="64" />
          <el-table-column prop="id" label="问答对" width="90" />
          <el-table-column prop="question" label="问题" />
          <el-table-column prop="scoreText" label="命中分" width="90" />
        </el-table>
        <div v-else class="trace-desc">暂无问答对召回结果</div>
      </template>
      <el-table v-else-if="dialogKind === 'fusion' && dialogDetail" :data="dialogDetail.items" size="small" @row-click="(row) => emit('focus-hit', row.id)">
        <el-table-column prop="rank" label="融合名次" width="90" />
        <el-table-column prop="id" label="片段" width="90" />
        <el-table-column prop="chapterLabel" label="回目" width="90" />
        <el-table-column prop="denseRank" label="稠密名次" width="90" />
        <el-table-column prop="sparseRank" label="稀疏名次" width="90" />
        <el-table-column prop="scoreText" label="RRF" width="90" />
        <el-table-column prop="snippet" label="摘要" />
      </el-table>
      <el-table v-else-if="dialogKind === 'rerank' && dialogDetail" :data="dialogDetail.items" size="small" @row-click="(row) => emit('focus-hit', row.id)">
        <el-table-column prop="rerankRank" label="重排名次" width="90" />
        <el-table-column prop="rank" label="融合名次" width="90" />
        <el-table-column prop="id" label="片段" width="90" />
        <el-table-column prop="chapterLabel" label="回目" width="90" />
        <el-table-column prop="rerankText" label="重排分" width="90" />
        <el-table-column prop="snippet" label="摘要" />
      </el-table>
      <pre v-else-if="dialogKind === 'prompt' && dialogDetail" class="prompt-full">{{ dialogDetail.prompt }}</pre>
    </el-dialog>
  </aside>
</template>

<style scoped>
.embed-query-list {
  margin: 0;
  padding-left: 18px;
  color: var(--ink);
  font-size: 13px;
  line-height: 1.55;
}
.embed-query-list li { margin: 4px 0; }
.embed-query-list b { color: var(--muted); font-weight: 600; margin-right: 6px; }
</style>
