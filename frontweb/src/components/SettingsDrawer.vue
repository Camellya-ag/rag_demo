<script setup>
defineProps({
  visible: { type: Boolean, default: false },
  settings: { type: Object, required: true }
})
const emit = defineEmits(['update:visible', 'reset'])

const models = [
  { value: 'qwen-plus', label: 'qwen-plus（平衡）' },
  { value: 'qwen-turbo', label: 'qwen-turbo（快速）' },
  { value: 'qwen-max', label: 'qwen-max（高质量）' }
]
</script>

<template>
  <el-drawer
    :model-value="visible"
    title="RAG 参数配置"
    direction="rtl"
    size="470px"
    @update:model-value="emit('update:visible', $event)"
  >
    <div class="setting-block">
      <div class="setting-block-title">检索策略</div>
      <div class="setting-row">
        <div class="setting-row-label"><span>召回数量 Top-K</span><b>{{ settings.topK }}</b></div>
        <el-slider v-model="settings.topK" :min="1" :max="8" :step="1" />
        <div class="setting-tip">最终送入大模型的原文片段数量，越多上下文越丰富，但噪声也可能增加。</div>
      </div>
      <div class="setting-row">
        <div class="setting-row-label"><span>重排序（Rerank）</span><b>始终启用</b></div>
        <div class="setting-tip">后端始终调用 rerank 模型精排，前端不再提供关闭开关。</div>
      </div>
      <div class="setting-row">
        <div class="setting-row-label"><span>分块大小</span><b>{{ settings.chunkSize }} tokens</b></div>
        <el-slider v-model="settings.chunkSize" :min="256" :max="1024" :step="128" :disabled="true" />
        <div class="setting-tip">知识库已按 {{ settings.chunkSize }} tokens 完成切分， overlap {{ settings.chunkOverlap }}。修改需重新索引。</div>
      </div>
    </div>

    <div class="setting-block">
      <div class="setting-block-title">生成策略</div>
      <div class="setting-row">
        <div class="setting-row-label"><span>生成模型</span></div>
        <el-select v-model="settings.model" style="width: 100%">
          <el-option v-for="m in models" :key="m.value" :label="m.label" :value="m.value" />
        </el-select>
      </div>
      <div class="setting-row">
        <div class="setting-row-label"><span>Temperature</span><b>{{ settings.temperature.toFixed(1) }}</b></div>
        <el-slider v-model="settings.temperature" :min="0" :max="1" :step="0.1" />
        <div class="setting-tip">值越低回答越稳定、越贴近原文；值越高越有创造性。</div>
      </div>
      <div class="setting-row">
        <div class="setting-row-label"><span>流式输出</span></div>
        <el-switch v-model="settings.streaming" active-text="开启" inactive-text="关闭" />
      </div>
    </div>

    <div class="setting-block">
      <div class="setting-block-title">System Prompt</div>
      <textarea v-model="settings.systemPrompt" class="prompt-box"></textarea>
      <div class="setting-tip">提示词会与检索片段一起送入模型，用于约束回答风格与引用格式。</div>
    </div>

    <el-button plain style="width: 100%" @click="emit('reset')">
      <el-icon style="margin-right: 5px"><RefreshLeft /></el-icon>
      恢复默认配置
    </el-button>
  </el-drawer>
</template>
