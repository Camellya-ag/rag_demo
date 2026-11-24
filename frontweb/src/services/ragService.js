import { stopChatQuery, streamChatQuery } from '../api/chat'

function toApiSettings(settings = {}) {
  return {
    top_k: settings.topK,
    temperature: settings.temperature,
    model: settings.model,
    streaming: settings.streaming,
    system_prompt: settings.systemPrompt,
    chunk_size: settings.chunkSize,
    chunk_overlap: settings.chunkOverlap,
    rerank: true
  }
}

export function buildConversation(messages = []) {
  return messages
    .filter((item) => item.role === 'user' || (item.role === 'assistant' && item.status === 'done' && item.text))
    .slice(-12)
    .map((item) => ({ role: item.role, content: item.text }))
}

export async function runRagQuery({
  question,
  settings,
  messages,
  requestId,
  callbacks,
  signal
}) {
  await streamChatQuery(
    {
      request_id: requestId,
      question,
      settings: toApiSettings(settings),
      messages: buildConversation(messages)
    },
    {
      onStage: callbacks.onStage,
      onHits: callbacks.onHits,
      onToken: callbacks.onToken,
      onAnswer: callbacks.onAnswer,
      onTrace: callbacks.onTrace,
      onError: callbacks.onError
    },
    signal
  )
}

export async function cancelRagQuery(requestId) {
  try {
    await stopChatQuery(requestId)
  } catch {
    // 后端可能尚未实现 stop；前端仍会中断流式请求
  }
}
