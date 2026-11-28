import { expect, test } from '@playwright/test';

import { newPerson, registered, signedInBrowser, withAgency } from './support/people.ts';
import { stack } from './support/stack.ts';

const api = `${stack.apiOrigin}/**`;

test('a page that cannot reach the API says so and recovers on request', async ({ page }) => {
  await page.route(api, (route) => route.abort());
  await page.goto('/sign-in');

  await expect(page.getByRole('heading', { name: 'This page could not be shown', level: 1 })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveText('Connect could not reach the server. Check your connection and try again.');
  await expect(page.getByRole('main')).toHaveCount(1);
  // The frame stays: the person can still change the language while the API is away.
  await page.getByRole('radio', { name: 'العربية' }).click();
  await expect(page.getByRole('alert')).toHaveText('تعذَّر على كونكت الوصول إلى الخادم. تحقق من اتصالك وحاول مرة أخرى.');
  await page.getByRole('radio', { name: 'English' }).click();

  await page.unroute(api);
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();
});

test('a request that fails in the middle of work is reported where it was made', async ({ page, context }, testInfo) => {
  const person = await registered(newPerson(testInfo));
  await withAgency(person, 'Lumen Studio');
  await signedInBrowser(context, person);
  await page.goto('/account');
  await expect(page.getByRole('heading', { name: 'Account', level: 1 })).toBeVisible();

  await page.route(api, (route) => route.abort());
  await page.getByLabel('Current password').fill(person.password);
  await page.getByLabel('New password').fill(`${person.password} and more`);
  await page.getByRole('button', { name: 'Change password' }).click();

  await expect(page.getByRole('alert')).toHaveText('Connect could not reach the server. Check your connection and try again.');
  // Nothing was lost: the page and what was typed are still there.
  await expect(page.getByRole('heading', { name: 'Account', level: 1 })).toBeVisible();
  await expect(page.getByLabel('Current password')).toHaveValue(person.password);
});
