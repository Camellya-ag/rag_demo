<script setup>
import { computed } from 'vue'

const props = defineProps({
  text: { type: String, default: '' },
  streaming: { type: Boolean, default: false }
})
const emit = defineEmits(['cite'])

function inlineParts(text) {
  const parts = []
  const re = /(\*\*[^*]+\*\*|\[\d+\])/g
  let last = 0
  let m
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push({ type: 'text', value: text.slice(last, m.index) })
    if (m[0].startsWith('**')) {
      parts.push({ type: 'bold', value: m[0].slice(2, -2) })
    } else {
      parts.push({ type: 'cite', value: Number(m[0].slice(1, -1)) })
    }
    last = re.lastIndex
  }
  if (last < text.length) parts.push({ type: 'text', value: text.slice(last) })
  return parts
}

const blocks = computed(() => {
  const lines = props.text.split('\n')
  const out = []
  let list = []
  for (const line of lines) {
    if (line.trim().startsWith('- ')) {
      list.push(inlineParts(line.trim().slice(2)))
      continue
    }
    if (list.length) {
      out.push({ type: 'list', items: list })
      list = []
    }
    if (!line.trim()) continue
    if (line.trim().startsWith('> ')) {
      out.push({ type: 'quote', parts: inlineParts(line.trim().slice(2)) })
    } else {
      out.push({ type: 'p', parts: inlineParts(line) })
    }
  }
  if (list.length) out.push({ type: 'list', items: list })
  return out
})
</script>

<template>
  <div class="answer-content">
    <template v-for="(block, bi) in blocks" :key="bi">
      <p v-if="block.type === 'p'">
        <template v-for="(part, pi) in block.parts" :key="pi">
          <strong v-if="part.type === 'bold'">{{ part.value }}</strong>
          <span v-else-if="part.type === 'cite'" class="cite" @click="emit('cite', part.value)">{{ part.value }}</span>
          <template v-else>{{ part.value }}</template>
        </template>
      </p>
      <blockquote v-else-if="block.type === 'quote'">
        <template v-for="(part, pi) in block.parts" :key="pi">
          <strong v-if="part.type === 'bold'">{{ part.value }}</strong>
          <span v-else-if="part.type === 'cite'" class="cite" @click="emit('cite', part.value)">{{ part.value }}</span>
          <template v-else>{{ part.value }}</template>
        </template>
      </blockquote>
      <ul v-else-if="block.type === 'list'">
        <li v-for="(item, ii) in block.items" :key="ii">
          <template v-for="(part, pi) in item" :key="pi">
            <strong v-if="part.type === 'bold'">{{ part.value }}</strong>
            <span v-else-if="part.type === 'cite'" class="cite" @click="emit('cite', part.value)">{{ part.value }}</span>
            <template v-else>{{ part.value }}</template>
          </template>
        </li>
      </ul>
    </template>
    <span v-if="streaming" class="cursor-blink"></span>
  </div>
</template>

<style scoped>
.answer-content { min-height: 18px; }
.answer-content p { margin: 0 0 10px; }
.answer-content p:last-child { margin-bottom: 2px; }
.answer-content blockquote {
  margin: 8px 0 12px; padding: 8px 12px;
  border-left: 3px solid var(--gold);
  background: var(--gold-soft); border-radius: 0 7px 7px 0;
  color: #6d5a3c; font-family: var(--serif); font-size: 12.5px;
}
.answer-content ul { margin: 6px 0 10px; padding-left: 20px; }
.answer-content li { margin-bottom: 3px; }
</style>
