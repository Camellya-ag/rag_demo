import { expect, test } from '@playwright/test'

async function mockBootstrap(page) {
  await page.route('**/api/chat/stop', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) })
  )
  await page.route('**/api/health', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, status: 'ok', qa_pairs: { loaded: 1, enabled: true } })
    })
  )
  await page.route('**/api/settings/defaults', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        settings: { model: 'qwen-flash', streaming: true, top_k: 4, temperature: 0.3, system_prompt: 'test' }
      })
    })
  )
  await page.route('**/api/knowledge/**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        source: { chunkCount: 1, status: 'ready', chapters: 1, chunkSize: 512, chunkOverlap: 64, qaPairCount: 0 },
        items: []
      })
    })
  )
}

async function installChatMock(page, mode = 'stop') {
  await page.addInitScript((mockMode) => {
    const originalFetch = window.fetch.bind(window)
    window.__streamProbe = { started: 0, aborted: 0 }
    window.fetch = async (input, init = {}) => {
      const url = typeof input === 'string' ? input : input.url
      if (!url.includes('/api/chat/query')) {
        return originalFetch(input, init)
      }
      const encoder = new TextEncoder()
      window.__streamProbe.started += 1
      let aborted = false
      let finished = false
      let controllerRef = null
      const timers = []
      const abort = () => {
        if (aborted || finished) return
        aborted = true
        window.__streamProbe.aborted += 1
        timers.forEach(clearTimeout)
        controllerRef?.error(new DOMException('Aborted', 'AbortError'))
      }
      init?.signal?.addEventListener('abort', abort, { once: true })

      const stream = new ReadableStream({
        start(controller) {
          controllerRef = controller
          const push = (text) => controller.enqueue(encoder.encode(text))
          push('event: stage\ndata: {"type":"stage","key":"retrieve","status":"running","summary":"检索中"}\n\n')
          push('event: token\ndata: {"type":"token","text":"分段一"}\n\n')

          if (mockMode === 'full') {
            timers.push(setTimeout(() => {
              if (aborted) return
              push('event: stage\ndata: {"type":"stage","key":"retrieve","status":"done","summary":"检索完成"}\n\n')
              push('event: token\ndata: {"type":"token","text":"分段二"}\n\n')
              push('event: answer\ndata: {"type":"answer","text":"分段一分段二","hits":[],"meta":{"latency":12,"tokens":4}}\n\n')
              push('event: done\ndata: {"type":"done","ok":true}\n\n')
              finished = true
              controller.close()
            }, 1500))
          } else {
            timers.push(setTimeout(() => {
              if (aborted) return
              push('event: token\ndata: {"type":"token","text":"分段二"}\n\n')
            }, 1200))
            timers.push(setTimeout(() => {
              if (aborted) return
              push('event: done\ndata: {"type":"done","ok":true}\n\n')
              finished = true
              controller.close()
            }, 2200))
          }
        },
        cancel() {
          abort()
        }
      })
      return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
    }
  }, mode)
}

test('分时 SSE：停止后不再追加，且可继续下一轮', async ({ page }) => {
  await mockBootstrap(page)
  await installChatMock(page, 'stop')
  await page.goto('/')
  await page.getByPlaceholder('就《西游记》提一个问题').fill('孙悟空怎么出生')
  await page.getByTitle('发送').click()
  await expect(page.locator('.answer-body')).toContainText('分段一', { timeout: 5000 })
  await expect(page.locator('.answer-body')).not.toContainText('分段二', { timeout: 800 })
  await page.getByTitle('停止生成').click()
  await expect(page.locator('.answer-body').last()).toContainText('已停止生成', { timeout: 5000 })
  await expect.poll(() => page.evaluate(() => window.__streamProbe.aborted)).toBe(1)
  await page.waitForTimeout(1500)
  await expect(page.locator('.answer-body')).not.toContainText('分段二')
  await page.getByPlaceholder('就《西游记》提一个问题').fill('第二问')
  await page.getByTitle('发送').click()
  await expect(page.getByText('第二问')).toBeVisible()
  await expect.poll(() => page.evaluate(() => window.__streamProbe.started)).toBe(2)
  await expect(page.locator('.answer-body').last()).toContainText('分段一')
})

test('分时 SSE：stage 进度与 token 自然完成', async ({ page }) => {
  await mockBootstrap(page)
  await installChatMock(page, 'full')
  await page.goto('/')
  await page.getByPlaceholder('就《西游记》提一个问题').fill('水帘洞洞门刻着什么字？')
  await page.getByTitle('发送').click()
  await expect(page.locator('.answer-body')).toContainText('分段一', { timeout: 5000 })
  await expect(page.locator('.answer-body')).not.toContainText('分段二')
  await page.locator('.message-row.assistant .trace-btn', { hasText: '查看 RAG 全链路' }).last().click()
  const dialog = page.locator('.rag-trace-dialog')
  await expect(dialog.getByText('本次回答 · RAG 全链路')).toBeVisible()
  await page.getByRole('tab', { name: '步骤详情' }).click()
  await expect(dialog.getByText('检索中', { exact: true }).first()).toBeVisible()
  await expect(dialog.getByText('检索完成', { exact: false })).toBeVisible({ timeout: 5000 })
  await page.locator('.el-dialog__headerbtn').click()
  await expect(page.locator('.answer-body')).toContainText('分段一分段二')
  await expect(page.getByTitle('发送', { exact: true })).toBeVisible()
})
