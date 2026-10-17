const {defineConfig} = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests/browser',
  timeout: 90_000,
  retries: 1,
  workers: 1,
  reporter: [['list']],
  use: {
    browserName: 'chromium',
    headless: true,
    actionTimeout: 20_000,
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: 'python3 -m http.server 8877 --bind 127.0.0.1 --directory docs',
      url: 'http://127.0.0.1:8877/',
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: 'python3 -m uvicorn movie_modify.server:app --host 127.0.0.1 --port 8878',
      url: 'http://127.0.0.1:8878/api/health',
      env: {MOVIE_MODIFY_DATA: '/tmp/movie_modify_playwright_data'},
      reuseExistingServer: false,
      timeout: 30_000,
    }
  ]
});
