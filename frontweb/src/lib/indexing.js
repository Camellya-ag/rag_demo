export const INDEX_MODES = {
  initial: 'initial',
  rebuild: 'rebuild'
}

export function indexModeLabel(mode) {
  return mode === INDEX_MODES.initial ? '首次正式入库' : '重新索引'
}

export function indexConfirmTitle(mode) {
  return mode === INDEX_MODES.initial ? '确认首次正式入库' : '确认重新索引'
}

export function indexScopeDescription() {
  return '原文全文分块向量化 + 问答对生成/向量化 + Milvus 入库'
}

export function buildIndexEstimateIntro(mode) {
  const scope = indexScopeDescription()
  if (mode === INDEX_MODES.initial) {
    return `将创建首版生产知识库：${scope}。必须先查看费用估算并由你确认后才会扣费执行。`
  }
  return `将重建生产知识库：${scope}。确认后执行；成功则切换新版本，失败保留旧索引。`
}

/** 后端在适配前可能仍返回“样本”类 warning，避免误导正式用户 */
export function filterIndexWarning(warning = '') {
  const text = String(warning || '').trim()
  if (!text) return ''
  if (/样本|少量验证|sample/i.test(text)) {
    if (import.meta.env.DEV) {
      return '（开发期）后端仍可能按样本限额估算，正式环境应返回全文 + 问答对分项。'
    }
    return ''
  }
  return text
}
