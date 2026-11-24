<script setup>
import { computed } from 'vue'
import { formatCost } from '../lib/format'
import CostBreakdown from './CostBreakdown.vue'

const props = defineProps({
  source: { type: Object, required: true },
  distribution: { type: Array, default: () => [] },
  presets: { type: Array, default: () => [] },
  indexJob: { type: Object, default: null },
  backendOnline: { type: Boolean, default: false }
})
const emit = defineEmits(['ask', 'open-settings', 'request-index'])

const maxDist = computed(() => Math.max(...props.distribution.map((d) => d.value), 1))

const indexing = computed(() => {
  const status = props.indexJob?.status || props.source.status
  return ['queued', 'running', 'building', 'indexing'].includes(status)
})

const indexProgress = computed(() => {
  if (indexing.value) return Math.round(props.indexJob?.progress ?? 0)
  if (props.source.status === 'ready') return 100
  return 0
})

const statusText = computed(() => {
  if (!props.backendOnline) return '后端未连接'
  if (indexing.value) return props.indexJob?.message || '索引构建中'
  if (props.source.status === 'ready') return '向量化完成'
  if (props.source.status === 'empty') return '待首次正式入库'
  if (props.source.status === 'failed') return '索引失败，仍保留旧版本'
  return '等待索引状态'
})

const indexButtonText = computed(() => {
  if (indexing.value) return '正在索引…'
  if (props.source.status === 'empty') return '首次正式入库'
  return '重新索引文档'
})

function requestIndex() {
  emit('request-index', props.source.status === 'empty' ? 'initial' : 'rebuild')
}
</script>

<template>
  <aside class="panel sidebar">
    <div class="panel-head">
      <div class="panel-title">知识库</div>
      <span class="panel-sub">1 个文档</span>
    </div>

    <div class="sidebar-body">
      <!-- 文档卡片 -->
      <div class="kb-doc">
        <div class="kb-doc-top">
          <div class="kb-book-icon">游</div>
          <div style="min-width: 0">
            <div class="kb-doc-name">西游记.txt</div>
            <div class="kb-doc-meta">{{ source.author }} · {{ source.size }}</div>
            <div class="kb-ready"><i></i>{{ statusText }}</div>
          </div>
        </div>
        <div class="kb-index">
          <div class="kb-index-row">
            <span>索引进度</span>
            <b>{{ indexProgress }}%</b>
          </div>
          <div class="kb-progress"><i :style="{ width: indexProgress + '%' }"></i></div>
          <div v-if="indexJob?.costSoFar !== undefined && indexJob?.costSoFar !== null" class="kb-index-row" style="margin-top: 8px">
            <span>本次已花费</span>
            <b>{{ formatCost(indexJob.costSoFar) }}</b>
          </div>
          <div v-if="indexJob?.currentStage" class="kb-index-row" style="margin-top: 6px">
            <span>当前阶段</span>
            <b>{{ indexJob.currentStage }}</b>
          </div>
          <CostBreakdown
            v-if="indexJob?.stages?.length"
            title="入库费用分项"
            :stages="indexJob.stages"
            :total-cost="indexJob.costSoFar"
            compact
          />
        </div>
      </div>

      <!-- 统计 -->
      <div class="side-section">
        <div class="side-section-title">知识库概览</div>
        <div class="stat-grid">
          <div class="stat-cell">
            <div class="stat-value">{{ source.chapters }}<em>回</em></div>
            <div class="stat-label">全文回目</div>
          </div>
          <div class="stat-cell">
            <div class="stat-value">{{ source.chunkCount.toLocaleString() }}<em>块</em></div>
            <div class="stat-label">文本分块</div>
          </div>
          <div class="stat-cell">
            <div class="stat-value">1024<em>维</em></div>
            <div class="stat-label">向量维度</div>
          </div>
          <div class="stat-cell">
            <div class="stat-value">{{ source.qaPairCount || 0 }}<em>对</em></div>
            <div class="stat-label">问答对召回库</div>
          </div>
        </div>
      </div>

      <!-- 分块分布 -->
      <div class="side-section">
        <div class="side-section-title">章节分块分布</div>
        <div class="dist-list">
          <div v-for="d in distribution" :key="d.label" class="dist-item">
            <span class="dist-name">{{ d.label }}</span>
            <span class="dist-bar"><i :style="{ width: (d.value / maxDist * 100) + '%' }"></i></span>
            <span class="dist-num">{{ d.value }}</span>
          </div>
        </div>
      </div>

      <!-- 试试这样问 -->
      <div class="side-section">
        <div class="side-section-title">试试这样问</div>
        <div class="preset-list">
          <div v-for="(q, i) in presets.slice(0, 5)" :key="i" class="preset-item" @click="emit('ask', q)">
            <el-icon><Search /></el-icon>
            <span>{{ q }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="side-footer">
      <el-button plain style="width: 100%" :loading="indexing" :disabled="!backendOnline" @click="requestIndex">
        <el-icon style="margin-right: 5px"><RefreshRight /></el-icon>
        {{ indexButtonText }}
      </el-button>
      <div style="text-align: center; font-size: 10px; color: var(--muted); margin-top: 9px">
        向量库更新于 {{ source.indexedAt }}<span v-if="source.activeVersion"> · 版本 {{ source.activeVersion }}</span>
        <div v-if="source.qaPairsEnabled !== false" style="margin-top: 4px">问答对已纳入正式入库与召回</div>
      </div>
    </div>
  </aside>
</template>
