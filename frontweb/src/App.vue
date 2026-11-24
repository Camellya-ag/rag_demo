<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import KnowledgeSidebar from './components/KnowledgeSidebar.vue'
import ChatPanel from './components/ChatPanel.vue'
import SettingsDrawer from './components/SettingsDrawer.vue'
import RagTraceDialog from './components/RagTraceDialog.vue'
import { defaultQuestions } from './data/qa'
import { fetchChunkDetail, estimateIndex, fetchHealth, fetchIndexJob, fetchKnowledgeDistribution, fetchKnowledgeSource, startIndex } from './api/knowledge'
import { fallbackSettings, loadDefaultSettings } from './lib/settings'
import { formatCost, formatStageUsage } from './lib/format'
import {
  createMessageTrace,
  finalizeTrace,
  mergeBackendTrace,
  snapshotTrace
} from './lib/trace'
import { cancelRagQuery, runRagQuery } from './services/ragService'
import {
  buildIndexEstimateIntro,
  filterIndexWarning,
  indexConfirmTitle
} from './lib/indexing'

const settings = reactive({ ...fallbackSettings })
const drawerVisible = ref(false)
const detailVisible = ref(false)
const detailChunk = ref(null)
const traceDialogVisible = ref(false)
const activeTrace = ref(null)
const activeTraceContext = ref(null)

const messages = ref([])
const busy = ref(false)
const backendOnline = ref(false)
const backendError = ref('')
const source = ref({
  name: '西游记.txt',
  author: '吴承恩（明）',
  size: '—',
  chapters: 0,
  chunkCount: 0,
  embeddingModel: 'text-embedding-v4',
  dimension: 1024,
  indexedAt: '—',
  chunkSize: 512,
  chunkOverlap: 64,
  status: 'unknown',
  activeVersion: null,
  buildingVersion: null,
  qaPairCount: 0,
  qaPairsEnabled: true
})
const distribution = ref([])
const indexJob = ref(null)
let indexTimer = null
let activeRequestId = ''
let askController = null

function applyStagePatch(key, patch, traceHolder = null) {
  if (traceHolder?.stages?.[key]) Object.assign(traceHolder.stages[key], patch)
}

let seq = 0
const nextId = () => `m-${++seq}`
const createRequestId = () => (globalThis.crypto?.randomUUID?.() || `req-${Date.now()}-${Math.random().toString(16).slice(2)}`)

const headerStatus = computed(() => {
  if (!backendOnline.value) return backendError.value || '后端未连接'
  if (source.value.status === 'ready') return `向量库就绪 · ${source.value.chunkCount.toLocaleString('zh-CN')} chunks`
  if (source.value.status === 'empty') return '知识库待首次正式入库（需估算确认）'
  return '索引状态同步中'
})

async function refreshKnowledge() {
  const [nextSource, nextDistribution, health] = await Promise.all([
    fetchKnowledgeSource(),
    fetchKnowledgeDistribution(),
    fetchHealth().catch(() => null)
  ])
  if (health?.qa_pairs) {
    source.value = {
      ...nextSource,
      qaPairCount: Number(health.qa_pairs.loaded ?? nextSource.qaPairCount ?? 0),
      qaPairsEnabled: health.qa_pairs.enabled !== false
    }
  } else {
    source.value = nextSource
  }
  distribution.value = nextDistribution
  settings.chunkSize = nextSource.chunkSize || settings.chunkSize
  settings.chunkOverlap = nextSource.chunkOverlap || settings.chunkOverlap
}

async function bootstrap() {
  backendError.value = ''
  try {
    await fetchHealth()
    backendOnline.value = true
    await Promise.all([refreshKnowledge(), loadDefaultSettings().then((next) => Object.assign(settings, next))])
  } catch (error) {
    backendOnline.value = false
    backendError.value = error?.message || '后端未连接'
  }
}

function buildEstimateMessage(estimate) {
  const mode = estimate.mode || 'rebuild'
  const lines = [
    buildIndexEstimateIntro(mode),
    `预计原文分块：${estimate.chunkCount || '未知'}`,
    estimate.qaPairCount ? `预计问答对：${estimate.qaPairCount}` : '问答对数量：待后端返回',
    `总费用估算：${formatCost(estimate.totalCost)}`,
    estimate.note || '',
    filterIndexWarning(estimate.warning)
  ].filter(Boolean)
  if (estimate.stages?.length) {
    lines.push('', '分项估算：')
    estimate.stages.forEach((stage) => {
      lines.push(`- ${stage.label || stage.key}：${formatCost(stage.cost)} · ${formatStageUsage(stage)}`)
    })
  }
  return lines.join('\n')
}

async function pollIndexJob(jobId) {
  clearInterval(indexTimer)
  indexTimer = setInterval(async () => {
    try {
      const job = await fetchIndexJob(jobId)
      indexJob.value = job
      if (['completed', 'failed', 'cancelled'].includes(job.status)) {
        clearInterval(indexTimer)
        indexTimer = null
        await refreshKnowledge()
        if (job.status === 'completed') {
          const mode = indexJob.value?.mode
          if (job.switched) ElMessage.success('新索引已切换')
          else if (mode === 'initial') ElMessage.success('首次正式入库完成')
          else ElMessage.success('索引任务完成')
        } else if (job.status === 'failed') {
          ElMessage.error(job.error || '索引失败，已保留旧版本')
        }
      }
    } catch (error) {
      clearInterval(indexTimer)
      indexTimer = null
      ElMessage.error(error?.message || '索引进度查询失败')
    }
  }, 1200)
}

async function requestIndex(mode) {
  if (!backendOnline.value) {
    ElMessage.warning('后端未连接，无法发起入库/重建')
    return
  }
  try {
    const estimate = await estimateIndex({ mode })
    await ElMessageBox.confirm(buildEstimateMessage(estimate), indexConfirmTitle(mode), {
      confirmButtonText: '确认执行',
      cancelButtonText: '取消',
      type: 'warning'
    })
    const job = await startIndex({ mode, confirmed: true })
    if (estimate.estimateId) {
      job.estimateId = estimate.estimateId
    }
    indexJob.value = { ...job, mode }
    if (job.id) await pollIndexJob(job.id)
    else await refreshKnowledge()
  } catch (error) {
    if (error === 'cancel') return
    ElMessage.error(error?.message || '索引任务启动失败')
  }
}

async function ask(question, reuse = false) {
  const q = String(question || '').trim()
  if (!q || busy.value) return
  if (!backendOnline.value) {
    ElMessage.error('后端未连接，无法发起真实问答')
    return
  }

  if (reuse) {
    while (messages.value.length && messages.value[messages.value.length - 1].role === 'assistant') {
      messages.value.pop()
    }
  } else {
    messages.value.push({ id: nextId(), role: 'user', text: q })
  }
  const answerMsg = { id: nextId(), role: 'assistant', status: 'thinking', text: '', hits: [], meta: null }
  answerMsg.trace = createMessageTrace(q)
  messages.value.push(answerMsg)

  busy.value = true
  activeRequestId = createRequestId()
  askController = new AbortController()

  try {
    await runRagQuery({
      question: q,
      settings,
      messages: messages.value,
      requestId: activeRequestId,
      signal: askController.signal,
      callbacks: {
        onStage: (key, patch) => applyStagePatch(key, patch, answerMsg.trace),
        onHits: (data) => {
          answerMsg.hits = data
          if (answerMsg.trace) answerMsg.trace.hits = data
        },
        onToken: (token) => {
          if (answerMsg.status === 'thinking') answerMsg.status = 'streaming'
          answerMsg.text += token
        },
        onAnswer: (data) => {
          answerMsg.text = data.text || answerMsg.text
          answerMsg.status = 'done'
          answerMsg.hits = data.hits || answerMsg.hits
          if (answerMsg.trace) {
            answerMsg.trace.hits = answerMsg.hits
            mergeBackendTrace(answerMsg.trace, data.trace)
          }
          answerMsg.meta = {
            latency: data.latency ?? data.meta?.latency,
            tokens: data.tokens ?? data.meta?.tokens,
            cost: data.cost ?? data.meta?.cost,
            followUps: data.followUps || data.meta?.followUps || []
          }
        },
        onError: (error) => {
          answerMsg.status = 'error'
          answerMsg.error = error?.message || '问答失败'
        }
      }
    })
  } catch (error) {
    if (error?.code === 'aborted' || askController.signal.aborted) {
      answerMsg.status = 'stopped'
      answerMsg.text = (answerMsg.text || '') + (answerMsg.text ? '\n\n' : '') + '（已停止生成）'
    } else {
      answerMsg.status = 'error'
      answerMsg.error = error?.message || '问答失败'
    }
  } finally {
    if (answerMsg.trace) {
      finalizeTrace(answerMsg.trace, answerMsg.status)
      answerMsg.trace = snapshotTrace(answerMsg.trace)
    }
    busy.value = false
    askController = null
    activeRequestId = ''
  }
}

async function stop() {
  if (!busy.value) return
  askController?.abort()
  if (activeRequestId) await cancelRagQuery(activeRequestId)
  ElMessage({ message: '已停止生成', type: 'info', duration: 1200 })
}

function regenerate() {
  const lastUser = [...messages.value].reverse().find((m) => m.role === 'user')
  if (lastUser) ask(lastUser.text, true)
}

function newChat() {
  if (busy.value) askController?.abort()
  messages.value = []
  activeTrace.value = null
  activeTraceContext.value = null
  traceDialogVisible.value = false
}

function viewTrace(message) {
  if (!message?.trace) return
  activeTrace.value = message.trace
  activeTraceContext.value = {
    status: message.status,
    error: message.error,
    meta: message.meta,
    answerText: message.text,
    messageId: message.id
  }
  traceDialogVisible.value = true
}

async function focusHit(id, hitPool = null) {
  let pool = hitPool
  if (!pool?.length) {
    for (const message of messages.value) {
      const fromMessage = message.hits?.find((h) => h.id === id)
      if (fromMessage) {
        pool = message.hits
        break
      }
    }
  }
  const hit = pool?.find((h) => h.id === id)
  let chunk = hit?.chunk
  if (!chunk?.text && backendOnline.value) {
    try {
      chunk = await fetchChunkDetail(id)
    } catch {
      ElMessage.warning('无法获取片段详情')
      return
    }
  }
  if (!chunk) {
    ElMessage.warning('未找到对应片段')
    return
  }
  detailChunk.value = {
    ...chunk,
    chapterTitle: chunk.chapterTitle || `第 ${chunk.chapter} 回`,
    score: hit?.scoreText || chunk.scoreText
  }
  detailVisible.value = true
}

function resetSettings() {
  Object.assign(settings, fallbackSettings)
  ElMessage({ message: '已恢复默认参数', type: 'success', duration: 1200 })
}

onMounted(() => {
  bootstrap()
})

onBeforeUnmount(() => {
  if (indexTimer) clearInterval(indexTimer)
  askController?.abort()
})
</script>

<template>
  <div class="app-shell">
    <!-- 顶部栏 -->
    <header class="app-header">
      <div class="brand">
        <div class="brand-seal">典</div>
        <div>
          <div class="brand-title">西游问典</div>
          <div class="brand-sub">XIYOU RAG · 检索增强问答演示系统</div>
        </div>
      </div>
      <div class="header-right">
        <div class="header-status" :class="{ offline: !backendOnline }"><i class="status-dot"></i> {{ headerStatus }}</div>
        <span class="header-divider"></span>
        <div class="header-status" style="font-size: 11px">{{ backendOnline ? '后端联调' : '等待后端' }}</div>
        <div class="header-btn" @click="newChat">
          <el-icon><EditPen /></el-icon> 新建对话
        </div>
        <div class="header-btn" @click="drawerVisible = true">
          <el-icon><Setting /></el-icon> 参数配置
        </div>
      </div>
    </header>

    <!-- 双栏工作区：知识库侧栏 + 对话区；检索溯源在每条回答弹窗中 -->
    <main class="workspace">
      <KnowledgeSidebar
        :source="source"
        :distribution="distribution"
        :presets="defaultQuestions"
        :index-job="indexJob"
        :backend-online="backendOnline"
        @ask="ask"
        @open-settings="drawerVisible = true"
        @request-index="requestIndex"
      />

      <ChatPanel
        :messages="messages"
        :presets="defaultQuestions"
        :busy="busy"
        :settings="settings"
        @submit="ask"
        @ask="ask"
        @focus-hit="focusHit"
        @regenerate="regenerate"
        @stop="stop"
        @view-trace="viewTrace"
      />
    </main>

    <!-- 设置抽屉 -->
    <SettingsDrawer
      v-model:visible="drawerVisible"
      :settings="settings"
      @reset="resetSettings"
    />

    <!-- 原文片段详情 -->
    <el-dialog v-model="detailVisible" width="620px" align-center>
      <template #header>
        <div style="display: flex; align-items: center; gap: 10px">
          <span style="font-family: var(--serif); font-size: 16px; font-weight: 700">原文片段详情</span>
          <el-tag size="small" type="danger">{{ detailChunk?.id }}</el-tag>
          <el-tag v-if="detailChunk?.score" size="small" type="warning">相似度 {{ detailChunk.score }}</el-tag>
        </div>
      </template>
      <div v-if="detailChunk">
        <div style="font-weight: 700; margin-bottom: 6px; color: var(--ink)">{{ detailChunk.chapterTitle }}</div>
        <div style="font-size: 11px; color: var(--muted); margin-bottom: 14px">
          第 {{ detailChunk.chapter }} 回 · {{ detailChunk.tokens }} tokens · 来源 西游记.txt
        </div>
        <div class="chunk-full">{{ detailChunk.text }}</div>
        <div style="margin-top: 14px; font-size: 11px; color: var(--muted)">
          <el-icon style="vertical-align: -2px"><InfoFilled /></el-icon>
          该片段来自混合检索的候选，文本摘自《西游记》原文。
        </div>
      </div>
    </el-dialog>

    <RagTraceDialog
      v-model:visible="traceDialogVisible"
      :trace="activeTrace"
      :context="activeTraceContext"
      @focus-hit="(id) => focusHit(id, activeTrace?.hits || [])"
    />
  </div>
</template>

<style scoped>
.chunk-full {
  padding: 15px 17px; border-radius: 10px;
  background: var(--paper-soft); border: 1px solid var(--line);
  font-family: var(--serif); font-size: 14px; line-height: 2.1; color: #39434f;
}
.header-status.offline .status-dot { background: #b8907b; box-shadow: 0 0 0 3px rgba(184, 144, 123, .22); }
</style>
