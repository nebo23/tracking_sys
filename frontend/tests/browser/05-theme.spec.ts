import { expect, test, type Page } from '@playwright/test';

import { accountMenu, enterWorkspace, newPerson, registered, withAgency } from './support/people.ts';

/** How light the page background is, from 0 (black) to 1 (white). */
async function lightness(page: Page): Promise<number> {
  const color = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const [red = 0, green = 0, blue = 0] = (color.match(/[\d.]+/g) ?? []).map(Number);
  return (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255;
}

const theme = (page: Page) => page.locator('html').getAttribute('data-theme');

test('the dark theme is chosen from the account menu and remembered', async ({ page }, testInfo) => {
  const person = await registered(newPerson(testInfo));
  await withAgency(person, 'Lumen Studio');
  await enterWorkspace(page, person);
  expect(await theme(page)).toBeNull();
  expect(await lightness(page)).toBeGreaterThan(0.8);
  const logo = page.getByRole('complementary').getByRole('img', { name: 'Connect' });
  const darkInk = await logo.getAttribute('src');

  await accountMenu(page, person).click();
  await page.getByRole('menuitemradio', { name: 'Dark' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  expect(await lightness(page)).toBeLessThan(0.2);
  // The logo changes to its light version on the dark surface.
  await expect(logo).not.toHaveAttribute('src', darkInk ?? '');
  await expect(logo).toHaveAttribute('src', /f5f8f9/i);

  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  expect(await lightness(page)).toBeLessThan(0.2);

  await page.getByRole('link', { name: 'Account' }).first().click();
  await page.getByRole('radio', { name: 'Match the device' }).click();
  expect(await theme(page)).toBeNull();
  expect(await lightness(page)).toBeGreaterThan(0.8);
});

test.describe('a device set to dark', () => {
  test.use({ colorScheme: 'dark' });

  test('gets the dark theme without choosing it, and can choose light', async ({ page }, testInfo) => {
    const person = await registered(newPerson(testInfo));
    await withAgency(person, 'Lumen Studio');
    await enterWorkspace(page, person);
    expect(await theme(page)).toBeNull();
    expect(await lightness(page)).toBeLessThan(0.2);

    await accountMenu(page, person).click();
    await page.getByRole('menuitemradio', { name: 'Light' }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    expect(await lightness(page)).toBeGreaterThan(0.8);
  });
});
