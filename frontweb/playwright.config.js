import { defineConfig } from '@playwright/test'

export default defineConfig({
  timeout: 120000,
  workers: 1,
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5180',
    headless: true
  }
})
