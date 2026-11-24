<script setup>
import { ref, nextTick, watch, computed } from 'vue'
import { ElMessage } from 'element-plus'
import AnswerContent from './AnswerContent.vue'
import { hasTraceContent } from '../lib/trace'
import { copyTraceLog } from '../lib/traceLog'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  presets: { type: Array, default: () => [] },
  busy: { type: Boolean, default: false },
  settings: { type: Object, required: true }
})
const emit = defineEmits(['submit', 'ask', 'cite', 'focus-hit', 'regenerate', 'stop', 'view-trace'])

const input = ref('')
const scrollRef = ref(null)

const introQuestions = computed(() => props.presets.slice(0, 4))

function scrollToBottom() {
  nextTick(() => {
    if (scrollRef.value) scrollRef.value.scrollTop = scrollRef.value.scrollHeight
  })
}
watch(
  () => [props.messages.length, props.messages[props.messages.length - 1]?.text?.length],
  scrollToBottom
)

function submit() {
  const q = input.value.trim()
  if (!q || props.busy) return
  emit('submit', q)
  input.value = ''
}

function onCite({ message, n }) {
  const hit = message.hits?.[n - 1]
  if (hit) {
    emit('focus-hit', hit.id)
    ElMessage({ message: `已定位引用 [${n}]：${hit.chunk?.chapterTitle || hit.id}`, type: 'info', duration: 1800 })
  } else {
    emit('cite', n)
  }
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage({ message: '答案已复制', type: 'success', duration: 1500 })
  } catch {
    ElMessage({ message: '复制失败，请手动选择文本', type: 'warning', duration: 1800 })
  }
}

async function copyTrace(message) {
  const result = await copyTraceLog({
    trace: message.trace,
    meta: message.meta,
    status: message.status,
    error: message.error,
    answerText: message.text
  })
  if (result.ok) ElMessage({ message: '全链路日志已复制', type: 'success', duration: 1500 })
  else {
    emit('view-trace', message)
    ElMessage({ message: '自动复制失败，请在弹窗中使用手动复制', type: 'warning', duration: 2200 })
  }
}
</script>

<template>
  <section class="panel chat-panel">
    <div class="panel-head">
      <div class="panel-title">问答对话</div>
      <div class="chat-head-extra">
        <span class="model-chip">{{ settings.model }}</span>
        <span class="panel-sub">RAG 模式</span>
      </div>
    </div>

    <div ref="scrollRef" class="chat-scroll">
      <!-- 欢迎页 -->
      <div v-if="messages.length === 0" class="hero">
        <div class="hero-mark">典</div>
        <div class="hero-title">西游问典</div>
        <div class="hero-desc">
          基于《西游记》全书构建的检索增强问答演示。提问后先检索再生成；每条回答可通过「查看 RAG 全链路」查看召回、融合、重排与阶段费用（生成中也可打开），并支持复制全链路日志。
        </div>
        <div class="hero-features">
          <span class="feature-pill"><el-icon><Connection /></el-icon> 向量语义检索</span>
          <span class="feature-pill"><el-icon><Document /></el-icon> 原文片段溯源</span>
          <span class="feature-pill"><el-icon><MagicStick /></el-icon> 可解释生成</span>
        </div>
        <div class="hero-questions">
          <div class="hero-questions-label">选择一个问题开始体验</div>
          <div class="hero-q-grid">
            <div v-for="(q, i) in introQuestions" :key="q" class="hero-q" @click="emit('ask', q)">
              <span class="hero-q-num">0{{ i + 1 }}</span>
              <span>{{ q }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 消息列表 -->
      <div v-for="msg in messages" :key="msg.id" class="message-row" :class="msg.role">
        <div class="avatar" :class="{ 'user-avatar': msg.role === 'user' }">
          {{ msg.role === 'user' ? '我' : '典' }}
        </div>
        <div class="msg-main">
          <div class="msg-name">
            <span>{{ msg.role === 'user' ? '你' : '西游问典' }}</span>
            <span v-if="msg.role === 'assistant' && msg.meta">{{ msg.meta.latency }} ms · {{ msg.meta.tokens }} tokens</span>
          </div>

          <div v-if="msg.role === 'user'" class="msg-bubble">{{ msg.text }}</div>

          <div v-else-if="msg.status === 'thinking'" class="thinking">
            <span class="dots"><i></i><i></i><i></i></span>
            <span>正在检索《西游记》知识库…</span>
          </div>

          <div v-else class="answer-card">
            <div class="answer-body">
              <AnswerContent :text="msg.text" :streaming="msg.status === 'streaming'" @cite="(n) => onCite({ message: msg, n })" />
            </div>
            <div v-if="msg.status === 'error'" class="answer-error">{{ msg.error || '请求失败' }}</div>
            <div v-if="['done', 'stopped', 'error'].includes(msg.status)" class="answer-foot">
              <div class="answer-refs">
                <el-icon><Link /></el-icon>
                <span>{{ msg.status === 'stopped' ? '已停止生成' : `参考 ${msg.hits?.length || 0} 处原文` }}</span>
                <span
                  v-for="hit in msg.hits || []"
                  :key="hit.id"
                  class="ref-chip"
                  @click="emit('focus-hit', hit.id)"
                >
                  [{{ hit.rank }}] {{ hit.qaPairHit || hit.channel === 'qa_pair' ? '问答对' : `第${hit.chapter || hit.chunk?.chapter}回` }}
                </span>
              </div>
              <div class="answer-actions">
                <span
                  v-if="hasTraceContent(msg.trace)"
                  class="trace-btn"
                  title="查看本条回答的 RAG 全链路"
                  @click="emit('view-trace', msg)"
                >
                  查看 RAG 全链路
                </span>
                <span
                  v-if="hasTraceContent(msg.trace)"
                  class="trace-btn"
                  title="复制本次回答的全链路日志"
                  @click="copyTrace(msg)"
                >
                  复制全链路日志
                </span>
                <span class="icon-act" title="复制答案" @click="copy(msg.text)"><el-icon><CopyDocument /></el-icon></span>
                <span v-if="msg.status === 'done'" class="icon-act" title="重新生成" @click="emit('regenerate')"><el-icon><RefreshRight /></el-icon></span>
              </div>
            </div>
            <div v-else-if="msg.status === 'streaming' && hasTraceContent(msg.trace)" class="answer-foot answer-foot-live">
              <span class="trace-btn" @click="emit('view-trace', msg)">查看 RAG 全链路（进行中）</span>
            </div>
          </div>

          <!-- 追问建议 -->
          <div v-if="msg.role === 'assistant' && msg.status === 'done' && msg.meta?.followUps?.length" class="follow-ups">
            <span class="follow-label">继续追问</span>
            <span v-for="q in msg.meta.followUps" :key="q" class="follow-chip" @click="emit('ask', q)">{{ q }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="composer-wrap">
      <div class="composer-hint">
        <el-icon><InfoFilled /></el-icon>
        Enter 发送 · Shift + Enter 换行 · 全链路溯源见回答下方按钮 · 回答依据知识库原文生成
      </div>
      <div class="composer">
        <textarea
          v-model="input"
          rows="1"
          placeholder="就《西游记》提一个问题，例如：孙悟空是怎么诞生的？"
          :disabled="busy"
          @keydown.enter.exact.prevent="submit"
        ></textarea>
        <button v-if="busy" class="send-btn" title="停止生成" @click="emit('stop')">
          <el-icon><VideoPause /></el-icon>
        </button>
        <button v-else class="send-btn" :disabled="!input.trim()" title="发送" @click="submit">
          <el-icon><Promotion /></el-icon>
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.follow-ups { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; margin-top: 9px; }
.follow-label { font-size: 10px; color: var(--muted); }
.follow-chip {
  padding: 4px 9px; border-radius: 20px; cursor: pointer; font-size: 11px;
  background: var(--paper-soft); border: 1px solid var(--line); color: var(--ink-2);
  transition: all .15s ease;
}
.follow-chip:hover { background: var(--cinnabar-soft); border-color: #efc9bf; color: var(--cinnabar-deep); }
.answer-error {
  margin-top: 8px; padding: 8px 10px; border-radius: 8px;
  background: #fff4f2; border: 1px solid #f0c9c2; color: #9b2f23; font-size: 12px;
}
.answer-foot-live { justify-content: flex-end; margin-top: 8px; }
.trace-btn {
  margin-right: auto; padding: 4px 10px; border-radius: 999px; cursor: pointer; font-size: 11px;
  background: var(--cinnabar-soft); border: 1px solid #efc9bf; color: var(--cinnabar-deep);
}
.trace-btn:hover { filter: brightness(0.98); }
</style>
