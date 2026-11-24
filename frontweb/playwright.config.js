import { defineConfig } from '@playwright/test'

export default defineConfig({
  timeout: 60000,
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:5180',
    headless: true
  }
})
