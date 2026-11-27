import { expect, test } from '@playwright/test';

import { agreement, newPerson, registered } from './support/people.ts';

test('too many wrong passwords are answered with a sentence to wait', async ({ page }, testInfo) => {
  const person = await registered(newPerson(testInfo));

  await page.goto('/sign-in');
  await page.getByLabel('Email').fill(person.email);
  await page.getByLabel('Password', { exact: true }).fill('not the password at all');
  await agreement(page).check();

  // The API allows five attempts per account in a minute. The count starts again when the minute
  // turns, so the journey goes on until the limit answers, at most for two minutes' worth of tries.
  let attempts = 0;
  let limited = false;
  while (!limited && attempts < 12) {
    attempts += 1;
    const answer = page.waitForResponse((response) => response.url().endsWith('/auth/login') && response.request().method() === 'POST');
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    limited = (await answer).status() === 429;
    if (!limited) await expect(page.getByRole('alert')).toContainText('The email or password is not correct.');
  }

  expect(limited).toBe(true);
  expect(attempts).toBeGreaterThan(5);
  // Since 017-A the API lets the application's origin read Retry-After, so the wait is named.
  await expect(page.getByRole('alert')).toHaveText(/^Too many attempts\. Try again in \d+ seconds?\.$/);
  await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();
});
