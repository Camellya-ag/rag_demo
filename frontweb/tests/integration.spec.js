import { expect, test } from '@playwright/test'

test.describe.configure({ timeout: 120000 })

test('真实 RAG 问答与全链路弹窗', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('.header-right .header-status').first()).toContainText(/向量库就绪/, {
    timeout: 15000
  })

  const textarea = page.locator('.composer textarea')
  await textarea.fill('孙悟空是怎么出生的？')
  await page.locator('.send-btn[title="发送"]').click()

  await expect(page.locator('.message-row.assistant .trace-btn', { hasText: '查看 RAG 全链路' }).first()).toBeVisible({
    timeout: 90000
  })
  await expect(page.locator('.message-row.assistant .answer-body').last()).toContainText(/\[/)

  await page.locator('.message-row.assistant .trace-btn', { hasText: '查看 RAG 全链路' }).first().click()
  await expect(page.getByText('本次回答 · RAG 全链路')).toBeVisible()
  const dialog = page.locator('.rag-trace-dialog')
  await expect(dialog.locator('.raw-log-view')).toBeVisible()
  await page.getByRole('tab', { name: '步骤详情' }).click()
  await expect(dialog.getByText('查询改写')).toBeVisible()
  await expect(dialog.locator('.trace-name', { hasText: '生成' })).toBeVisible()
  await expect(dialog.getByText('稠密 · 原问')).toBeVisible()
  await expect(dialog.locator('.trace-panel').first()).toBeVisible()

  await page.getByRole('button', { name: '复制原始日志' }).click()
  await expect(page.getByText('原始日志已复制')).toBeVisible({ timeout: 8000 })
})
