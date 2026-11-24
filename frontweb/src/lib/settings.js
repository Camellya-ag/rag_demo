import { normalizeSettings } from './normalize'
import { request } from '../api/http'
import { API_CONTRACT } from '../api/config'

export const fallbackSettings = {
  topK: 4,
  temperature: 0.3,
  model: 'qwen-plus',
  chunkSize: 512,
  chunkOverlap: 64,
  streaming: true,
  systemPrompt: '你是《西游记》阅读助手。请严格依据检索到的原文片段回答问题，回答末尾用 [n] 标注引用来源。若片段不足以回答，请如实说明。'
}

export async function loadDefaultSettings() {
  try {
    const payload = await request(API_CONTRACT.settingsDefaults)
    return normalizeSettings(payload?.settings || payload, fallbackSettings)
  } catch {
    return { ...fallbackSettings }
  }
}
