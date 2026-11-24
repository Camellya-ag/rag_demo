<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import RetrievalPanel from './RetrievalPanel.vue'
import { buildTraceLog, copyTraceLog } from '../lib/traceLog'

const props = defineProps({
  visible: { type: Boolean, default: false },
  trace: { type: Object, default: null },
  context: { type: Object, default: () => ({}) }
})
const emit = defineEmits(['update:visible', 'focus-hit'])

const manualVisible = ref(false)
const manualText = ref('')
const copying = ref(false)

const logContext = computed(() => ({
  trace: props.trace,
  meta: props.context?.meta,
  status: props.context?.status || props.trace?.status,
  error: props.context?.error,
  answerText: props.context?.answerText
}))

watch(() => props.visible, (v) => {
  if (!v) manualVisible.value = false
})

async function copyLog() {
  if (!props.trace) return
  copying.value = true
  const result = await copyTraceLog(logContext.value)
  copying.value = false
  if (result.ok) {
    ElMessage.success('全链路日志已复制')
    return
  }
  manualText.value = result.text || buildTraceLog(logContext.value)
  manualVisible.value = true
  ElMessage.warning('自动复制失败，请手动全选复制下方文本')
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    width="860px"
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
          复制全链路日志
        </el-button>
      </div>
    </template>
    <div v-if="trace" class="dlg-body">
      <RetrievalPanel
        embedded
        expand-all
        :hits="trace.hits || []"
        :stages="trace.stages || {}"
        :query="trace.query || ''"
        :busy="trace.status === 'running'"
        @focus-hit="(id) => emit('focus-hit', id)"
      />
    </div>
    <el-dialog v-model="manualVisible" title="手动复制全链路日志" width="720px" append-to-body>
      <p style="font-size: 12px; color: var(--muted); margin: 0 0 8px">若浏览器阻止剪贴板写入，请全选下方内容后 Ctrl+C 复制（已脱敏）。</p>
      <textarea class="manual-log" readonly :value="manualText" @focus="($event.target.select())" />
    </el-dialog>
  </el-dialog>
</template>

<style scoped>
.dlg-head { display: flex; align-items: center; gap: 10px; width: 100%; font-weight: 700; font-family: var(--serif); }
.dlg-body :deep(.panel.inspect) { border: none; box-shadow: none; min-height: 68vh; }
.dlg-body :deep(.panel-head) { display: none; }
.dlg-body :deep(.inspect-body) { max-height: 68vh; }
.manual-log {
  width: 100%; min-height: 360px; border-radius: 8px; border: 1px solid var(--line);
  padding: 10px; font-size: 12px; line-height: 1.6; font-family: ui-monospace, Consolas, monospace;
}
@media (max-width: 900px) {
  :global(.rag-trace-dialog) { width: calc(100vw - 24px) !important; max-width: 100%; }
  .dlg-body :deep(.inspect-body) { max-height: min(68vh, calc(100vh - 180px)); }
}
</style>
