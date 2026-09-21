import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  retries: process.env.CI ? 1 : 0,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:3000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        launchOptions: {
          ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
            ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
            : {}),
          args: [
            '--enable-unsafe-swiftshader',
            '--renderer-process-limit=1',
            '--js-flags=--max-old-space-size=128',
            '--in-process-gpu',
            '--no-zygote',
          ],
        },
      },
    },
    {
      name: 'webkit-mobile',
      testMatch: ['mobile-presentation.spec.ts', 'mobile-model.spec.ts'],
      use: { ...devices['iPhone 13'] },
    },
  ],
  webServer: {
    command: 'npm start',
    url: 'http://127.0.0.1:3000/api/menus/demo',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
    env: {
      ALLOW_LOCAL_DATABASE: 'true',
      ALLOW_SIGNUP: 'true',
      PGLITE_DATA_DIR: `.data/e2e-${Date.now()}`,
      NEXT_PUBLIC_APP_URL: 'http://127.0.0.1:3000',
      MEDIA_PUBLIC_ORIGIN: 'https://assets.example.test',
    },
  },
});
