import { expect, test } from '@playwright/test'

const PIPELINE_LABELS = [
  '查询改写',
  '向量化',
  '稠密 + 稀疏召回',
  '融合',
  '重排',
  '组装上下文',
  '生成'
]

test.describe('全量页面验收', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('.header-right .header-status').first()).toContainText(/向量库就绪|后端/, {
      timeout: 20000
    })
  })

  test('知识库侧栏展示真实统计与章节分布', async ({ page }) => {
    await expect(page.locator('.side-section-title', { hasText: '知识库概览' })).toBeVisible()
    const chunkStat = page.locator('.stat-cell').filter({ hasText: '文本分块' }).locator('.stat-value')
    await expect(chunkStat).toContainText(/\d+/)
    const chunkNum = parseInt((await chunkStat.innerText()).replace(/\D/g, ''), 10)
    expect(chunkNum).toBeGreaterThan(100)

    await expect(page.locator('.side-section-title', { hasText: '章节分块分布' })).toBeVisible()
    const distItems = page.locator('.dist-list .dist-item')
    await expect(distItems.first()).toBeVisible()
    expect(await distItems.count()).toBeGreaterThanOrEqual(5)

    await expect(page.locator('.side-footer')).toContainText(/版本 v/)
    await expect(page.locator('.kb-ready')).toContainText(/向量化完成|等待/)
  })

  test('参数配置抽屉可打开且关键项可见', async ({ page }) => {
    await page.locator('.header-btn', { hasText: '参数配置' }).click()
    await expect(page.getByText('RAG 参数配置')).toBeVisible()
    await expect(page.getByText('重排序（Rerank）')).toBeVisible()
    await expect(page.getByText('分块大小')).toBeVisible()
    await expect(page.getByText('始终启用')).toBeVisible()
    await page.keyboard.press('Escape')
  })

  test('重新索引仅展示费用估算，取消不执行扣费任务', async ({ page }) => {
    const indexBtn = page.getByRole('button', { name: /重新索引|首次正式入库/ })
    await expect(indexBtn).toBeEnabled()
    await indexBtn.click()

    const dialog = page.locator('.el-message-box')
    await expect(dialog).toBeVisible({ timeout: 30000 })
    await expect(dialog).toContainText(/总费用估算|预计原文分块/)
    await expect(dialog).toContainText(/确认重新索引|确认首次正式入库/)

    await page.getByRole('button', { name: '取消' }).click()
    await expect(dialog).toBeHidden({ timeout: 5000 })

    await expect(page.locator('.kb-index-row', { hasText: '索引进度' }).locator('b')).toContainText('100%')
  })

  test('示例问题可发起问答并打开引用片段', async ({ page }) => {
    test.setTimeout(120000)
    await page.locator('.preset-item').first().click()
    await expect(page.locator('.message-row.user').last()).toBeVisible({ timeout: 5000 })

    await expect(page.locator('.message-row.assistant .trace-btn', { hasText: '查看 RAG 全链路' }).last()).toBeVisible({
      timeout: 90000
    })

    const cite = page.locator('.message-row.assistant .answer-body .cite').first()
    if (await cite.isVisible()) {
      await cite.click()
      await expect(page.getByText('原文片段详情')).toBeVisible({
        timeout: 10000
      })
    }
  })

  test('全链路弹窗展示七个阶段详情', async ({ page }) => {
    test.setTimeout(120000)
    await page.locator('.hero-q').first().click()
    await expect(page.locator('.message-row.assistant .trace-btn', { hasText: '查看 RAG 全链路' }).last()).toBeVisible({
      timeout: 90000
    })

    await page.locator('.message-row.assistant .trace-btn', { hasText: '查看 RAG 全链路' }).last().click()
    const dialog = page.locator('.rag-trace-dialog')
    await expect(dialog.getByText('本次回答 · RAG 全链路')).toBeVisible()
    await page.getByRole('tab', { name: '步骤详情' }).click()

    for (const label of PIPELINE_LABELS) {
      await expect(dialog.locator('.trace-name', { hasText: label })).toBeVisible()
    }
    await expect(dialog.getByText('稠密 · 原问')).toBeVisible()
    await expect(dialog.getByText('总费用')).toBeVisible()
  })

  test('西游主题背景层存在且主工作区可交互', async ({ page }) => {
    const shell = page.locator('.app-shell')
    await expect(shell).toBeVisible()
    const bgMist = await page.evaluate(() =>
      getComputedStyle(document.querySelector('.app-shell')).getPropertyValue('--xiyou-bg-mist')
    )
    expect(bgMist).toMatch(/xiyou-mist/)
    await expect(page.locator('.composer textarea')).toBeEditable()
  })
})
