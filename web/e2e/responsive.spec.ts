import { expect, test } from '@playwright/test'

const PAGES = ['/', '/lineups', '/lineups/281112', '/predict?season=2025-26&team=1610612750&lineup=281112', '/insights', '/model']

for (const path of PAGES) {
  test(`no horizontal page scroll on a phone: ${path}`, async ({ page }) => {
    await page.goto(path)
    await page.waitForLoadState('networkidle')
    await expect(page.locator('main')).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow).toBeLessThanOrEqual(0)
  })
}

test('mobile navigation menu', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Open menu' }).click()
  await page.locator('#mobile-nav').getByRole('link', { name: 'Model' }).click()
  await expect(page).toHaveURL(/\/model/)
  await expect(page.getByRole('heading', { level: 1, name: 'Model performance' })).toBeVisible()
})
