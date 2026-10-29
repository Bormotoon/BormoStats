import { expect, test } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.clock.install({ time: new Date('2026-10-29T09:00:00+03:00') });
  await page.addInitScript(() => {
    sessionStorage.setItem('bormostats_api_key', 'bsk_calendar_test');
    localStorage.setItem('bormostats_ui_lang', 'ru');
  });
  await page.route('**/api/**', route => route.fulfill({ json: { items: [], pagination: { has_more: false } } }));
  await page.route('**/health/**', route => route.fulfill({ json: { status: 'ok' } }));
  await page.goto('#/finance?dateFrom=2026-09-30&dateTo=2026-10-29&accountId=main');
});
const open = page => page.getByRole('button', { name: '30.09.26 — 29.10.26' }).click();
const day = (page, iso) => page.locator(`button[data-day="${iso}"][data-outside="false"]`);

test('two-month picker applies presets atomically and preserves other filters', async ({ page }) => {
  await open(page);
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Месяц 1' })).toHaveValue('9');
  await expect(page.getByRole('combobox', { name: 'Месяц 2' })).toHaveValue('10');
  await expect(day(page, '2026-10-30')).toBeDisabled();
  await page.screenshot({ path: '../outputs/calendar-update/calendar.png' });
  await page.getByRole('button', { name: 'Предыдущая неделя', exact: true }).click();
  await expect(page).toHaveURL(/dateFrom=2026-10-19&dateTo=2026-10-25&accountId=main/);
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('drafts can be cancelled and a reversed range is ordered before applying', async ({ page }) => {
  await open(page);
  await day(page, '2026-10-20').click();
  await expect(page).toHaveURL(/dateFrom=2026-09-30&dateTo=2026-10-29/);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '30.09.26 — 29.10.26' })).toBeFocused();
  await open(page);
  await day(page, '2026-10-20').click();
  await day(page, '2026-10-10').click();
  await expect(page).toHaveURL(/dateFrom=2026-10-10&dateTo=2026-10-20/);
});

test('ranges cross months and can include a single day', async ({ page }) => {
  await open(page);
  await page.locator('.date-range-arrow[aria-label="Предыдущий месяц"]').click();
  await day(page, '2026-09-28').click();
  await day(page, '2026-10-05').click();
  await expect(page).toHaveURL(/dateFrom=2026-09-28&dateTo=2026-10-05/);
  await page.locator('.date-range-trigger').click();
  await day(page, '2026-10-15').click();
  await day(page, '2026-10-15').click();
  await expect(page).toHaveURL(/dateFrom=2026-10-15&dateTo=2026-10-15/);
});

test('custom day count and keyboard day navigation work', async ({ page }) => {
  await open(page);
  await day(page, '2026-10-20').focus();
  await page.keyboard.press('ArrowLeft');
  await expect(day(page, '2026-10-19')).toBeFocused();
  await page.getByRole('spinbutton', { name: 'Количество дней' }).fill('42');
  await page.getByRole('spinbutton', { name: 'Количество дней' }).press('Enter');
  await expect(page).toHaveURL(/dateFrom=2026-09-18&dateTo=2026-10-29/);
});

test('picker fits a phone viewport and dismisses on outside click', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  const box = await page.getByRole('dialog').boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(390);
  expect(box.y + box.height).toBeLessThanOrEqual(844);
  await page.getByRole('heading', { name: 'Финансы', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
});
