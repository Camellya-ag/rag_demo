<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import RetrievalPanel from './RetrievalPanel.vue'
import { buildRawTraceLog, copyTraceLog } from '../lib/traceLog'

const props = defineProps({
  visible: { type: Boolean, default: false },
  trace: { type: Object, default: null },
  context: { type: Object, default: () => ({}) }
})
const emit = defineEmits(['update:visible', 'focus-hit'])

const manualVisible = ref(false)
const manualText = ref('')
const copying = ref(false)
const activeTab = ref('raw')

const logContext = computed(() => ({
  trace: props.trace,
  meta: props.context?.meta,
  status: props.context?.status || props.trace?.status,
  error: props.context?.error,
  answerText: props.context?.answerText
}))

const rawLogText = computed(() => buildRawTraceLog(logContext.value))

watch(() => props.visible, (v) => {
  if (!v) manualVisible.value = false
})

async function copyLog() {
  if (!props.trace) return
  copying.value = true
  const result = await copyTraceLog(logContext.value)
  copying.value = false
  if (result.ok) {
    ElMessage.success('原始日志已复制')
    return
  }
  manualText.value = result.text || rawLogText.value
  manualVisible.value = true
  ElMessage.warning('自动复制失败，请手动全选复制下方文本')
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    width="1120px"
    top="4vh"
    align-center
    append-to-body
    class="rag-trace-dialog"
    @update:model-value="emit('update:visible', $event)"
  >
    <template #header>
      <div class="dlg-head">
        <span>本次回答 · RAG 全链路</span>
        <el-tag v-if="trace?.query" size="small" type="info">{{ trace.query }}</el-tag>
        <el-button size="small" type="primary" plain :loading="copying" style="margin-left: auto" @click="copyLog">
          复制原始日志
        </el-button>
      </div>
    </template>
    <div v-if="trace" class="dlg-body">
      <el-tabs v-model="activeTab" class="trace-tabs">
        <el-tab-pane label="原始日志" name="raw">
          <p class="raw-hint">完整 trace JSON（各阶段 detail 原样保留；仅脱敏密钥类字段）。可复制给排错或存档。</p>
          <textarea
            class="raw-log-view"
            readonly
            :value="rawLogText"
            spellcheck="false"
            @focus="($event.target.select())"
          />
        </el-tab-pane>
        <el-tab-pane label="步骤详情" name="visual">
          <RetrievalPanel
            embedded
            expand-all
            :hits="trace.hits || []"
            :stages="trace.stages || {}"
            :query="trace.query || ''"
            :busy="trace.status === 'running'"
            @focus-hit="(id) => emit('focus-hit', id)"
          />
        </el-tab-pane>
      </el-tabs>
    </div>
    <el-dialog v-model="manualVisible" title="手动复制原始日志" width="900px" append-to-body class="rag-trace-manual">
      <p style="font-size: 12px; color: var(--muted); margin: 0 0 8px">请全选下方 JSON 后 Ctrl+C 复制（已脱敏）。</p>
      <textarea class="manual-log" readonly :value="manualText" @focus="($event.target.select())" />
    </el-dialog>
  </el-dialog>
</template>

<style scoped>
.dlg-head { display: flex; align-items: center; gap: 10px; width: 100%; font-weight: 700; font-family: var(--serif); }
.dlg-body { width: 100%; }
.trace-tabs :deep(.el-tabs__content) { width: 100%; }
.raw-hint { margin: 0 0 8px; font-size: 12px; color: var(--muted); line-height: 1.5; }
.raw-log-view {
  display: block;
  width: 100%;
  box-sizing: border-box;
  min-height: min(68vh, 640px);
  max-height: min(72vh, 680px);
  border-radius: 10px;
  border: 1px solid var(--line);
  padding: 12px 14px;
  font-size: 12px;
  line-height: 1.55;
  font-family: ui-monospace, Consolas, 'Cascadia Code', monospace;
  background: #f8f6f1;
  color: var(--ink);
  resize: vertical;
}
.dlg-body :deep(.panel.inspect.embedded) {
  width: 100%;
  flex: 1 1 auto;
  max-width: 100%;
  border: none;
  box-shadow: none;
  min-height: 60vh;
}
.dlg-body :deep(.panel-head) { display: none; }
.dlg-body :deep(.inspect-body) { max-height: min(68vh, 640px); width: 100%; }
.manual-log {
  width: 100%; min-height: 360px; border-radius: 8px; border: 1px solid var(--line);
  padding: 10px; font-size: 12px; line-height: 1.6; font-family: ui-monospace, Consolas, monospace;
}
@media (max-width: 900px) {
  :global(.rag-trace-dialog) { width: calc(100vw - 16px) !important; max-width: 100%; }
  .dlg-body :deep(.inspect-body) { max-height: min(68vh, calc(100vh - 180px)); }
  .raw-log-view { min-height: 55vh; }
}
</style>
