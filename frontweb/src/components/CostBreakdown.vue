<script setup>
import { formatCost, formatStageUsage } from '../lib/format'

defineProps({
  title: { type: String, default: '费用分项' },
  stages: { type: Array, default: () => [] },
  totalCost: { type: [Number, String, null], default: null },
  compact: { type: Boolean, default: false }
})
</script>

<template>
  <div class="cost-breakdown" :class="{ compact }">
    <div v-if="title" class="cost-title">{{ title }}</div>
    <div v-for="stage in stages" :key="stage.key" class="cost-row">
      <span class="cost-label">{{ stage.label || stage.key }}</span>
      <span class="cost-value">{{ formatCost(stage.cost) }}</span>
      <span class="cost-usage">{{ formatStageUsage(stage) }}</span>
    </div>
    <div v-if="totalCost !== undefined && totalCost !== null" class="cost-total">
      <span>合计</span>
      <b>{{ formatCost(totalCost) }}</b>
    </div>
  </div>
</template>

<style scoped>
.cost-breakdown { margin-top: 8px; padding: 10px 11px; border-radius: 10px; background: var(--paper-soft); border: 1px solid var(--line); }
.cost-breakdown.compact { margin-top: 6px; padding: 8px 9px; }
.cost-title { font-size: 11px; font-weight: 700; margin-bottom: 8px; color: var(--ink); }
.cost-row { display: grid; grid-template-columns: 1.2fr .7fr 1fr; gap: 8px; font-size: 11px; padding: 4px 0; border-bottom: 1px dashed #eadfd4; }
.cost-row:last-child { border-bottom: none; }
.cost-label { color: var(--ink-2); }
.cost-value { color: var(--cinnabar-deep); font-weight: 700; text-align: right; }
.cost-usage { color: var(--muted); text-align: right; }
.cost-total { margin-top: 8px; display: flex; justify-content: space-between; font-size: 11px; }
</style>
