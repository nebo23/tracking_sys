import { expect, test } from '@playwright/test';

import { agreement, newPerson, registered, withAgency } from './support/people.ts';

test('the sign-in screen and the workspace read right to left in Arabic', async ({ page }, testInfo) => {
  const person = await registered(newPerson(testInfo, 'منى حسن'));
  await withAgency(person, 'استوديو لومن');
  const width = page.viewportSize()?.width ?? 0;

  await test.step('the switch turns the whole screen', async () => {
    await page.goto('/sign-in');
    const english = await page.locator('.l-auth__brand').boundingBox();
    expect(english?.x).toBe(0);

    await page.getByRole('radio', { name: 'العربية' }).click();
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    await expect(page.locator('html')).toHaveAttribute('lang', 'ar');
    await expect(page.getByRole('heading', { name: 'تسجيل الدخول', level: 1 })).toBeVisible();
    await expect(page).toHaveTitle('تسجيل الدخول · كونكت');
    await expect(page.getByRole('img', { name: 'كونكت' })).toBeVisible();

    // The brand side moves to the right half; the language switch to the top left corner.
    const brand = await page.locator('.l-auth__brand').boundingBox();
    expect(brand?.x).toBeGreaterThanOrEqual(width / 2 - 1);
    const languages = await page.getByRole('radiogroup', { name: 'اللغة' }).boundingBox();
    expect(languages?.x).toBeLessThan(width / 4);
    expect(languages?.y).toBeLessThan(60);
  });

  await test.step('the choice is remembered', async () => {
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    await expect(page.getByRole('heading', { name: 'تسجيل الدخول', level: 1 })).toBeVisible();
  });

  await test.step('signing in works in Arabic', async () => {
    const email = page.getByLabel('البريد الإلكتروني');
    await email.fill(person.email);
    // An address is typed left to right, also on a right-to-left page.
    expect(await email.evaluate((field) => getComputedStyle(field).direction)).toBe('ltr');
    await page.getByLabel('كلمة المرور', { exact: true }).fill(person.password);
    await page.getByRole('button', { name: 'تسجيل الدخول', exact: true }).click();
    await expect(page.getByText('ضع علامة الموافقة قبل المتابعة.')).toBeVisible();
    await agreement(page).check();
    await page.getByRole('button', { name: 'تسجيل الدخول', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'نظرة عامة', level: 1 })).toBeVisible();
  });

  await test.step('the workspace is mirrored, with Western digits and Gregorian dates', async () => {
    const sidebar = await page.getByRole('complementary').boundingBox();
    expect(sidebar?.x).toBeGreaterThan(width / 2);
    const main = page.getByRole('main');
    await expect(main.getByText('استوديو لومن')).toBeVisible();
    await expect(main.getByText('مالك')).toBeVisible();
    await expect(main.getByText('منى حسن')).toBeVisible();

    const created = main.locator('dl').first().locator('dd').nth(2);
    await expect(created).toHaveText(/^\d{1,2} \S+ 20\d\d$/);
    await expect(created).not.toHaveText(/[٠-٩]/);
    expect(await main.getByText(person.email).evaluate((element) => getComputedStyle(element).direction)).toBe('ltr');
    await expect(page).toHaveTitle('نظرة عامة · كونكت');
  });

  await test.step('nothing spills past the edge of the page', async () => {
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
});

test.describe('a browser set to Arabic', () => {
  test.use({ locale: 'ar-EG' });

  test('starts in Arabic without being asked', async ({ page }) => {
    await page.goto('/sign-in');
    await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
    await expect(page.getByRole('heading', { name: 'تسجيل الدخول', level: 1 })).toBeVisible();
    await expect(page.getByRole('radio', { name: 'العربية' })).toBeChecked();
  });
});
