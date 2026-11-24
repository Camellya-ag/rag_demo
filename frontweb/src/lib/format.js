export function formatCost(value) {
  if (value === null || value === undefined || value === '') return '无法估算'
  const n = Number(value)
  if (Number.isNaN(n)) return '无法估算'
  if (n === 0) return '¥0'
  return `¥${n.toFixed(6)}`
}

export function formatUnknownNumber(value, suffix = '') {
  if (value === null || value === undefined || value === '') return '未知'
  const n = Number(value)
  if (Number.isNaN(n)) return '未知'
  return `${n.toLocaleString('zh-CN')}${suffix}`
}

export function formatUsageKnown(usageKnown) {
  if (usageKnown === false) return '用量未知'
  if (usageKnown === true) return ''
  return ''
}

export function formatStageUsage(stage = {}) {
  const usage = stage.usage || stage.summary || ''
  if (stage.usage_known === false || stage.usageKnown === false) {
    return usage ? `${usage}（用量未知）` : '用量未知'
  }
  return usage || '—'
}
