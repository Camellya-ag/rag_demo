import { expect, test } from '@playwright/test'

test('双栏页面与后端状态展示', async ({ page }) => {
  const errors = []
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(msg.text())
  })

  await page.goto('/')
  await expect(page.getByText('西游问典').first()).toBeVisible()
  await expect(page.locator('.panel-title', { hasText: '知识库' })).toBeVisible()
  await expect(page.locator('.panel-title', { hasText: '问答对话' })).toBeVisible()
  await expect(page.locator('main.workspace .panel')).toHaveCount(2)
  await expect(page.locator('main.workspace .panel.inspect')).toHaveCount(0)
  await expect(page.locator('.header-right .header-status').first()).toContainText(
    /等待后端|后端未连接|后端联调|请求失败|知识库待首次|向量库就绪|索引构建/
  )

  await page.locator('.header-btn', { hasText: '参数配置' }).click()
  await expect(page.getByText('RAG 参数配置')).toBeVisible()
  await expect(page.getByText('重排序（Rerank）')).toBeVisible()
  await expect(page.getByText('始终启用')).toBeVisible()

  const noisy = errors.filter((line) => !line.includes('favicon') && !line.includes('/api/') && !line.includes('500'))
  expect(noisy).toEqual([])
})

test('小屏隐藏知识库侧栏，对话区仍可见', async ({ page }) => {
  await page.setViewportSize({ width: 860, height: 800 })
  await page.goto('/')
  await expect(page.locator('.panel-title', { hasText: '问答对话' })).toBeVisible()
  await expect(page.locator('aside.sidebar')).toBeHidden()
})
