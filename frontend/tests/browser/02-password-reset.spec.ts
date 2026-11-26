import { expect, test } from '@playwright/test';

import { linkIn } from './support/mail.ts';
import { newPerson, recordRequests, registered, signInOnScreen } from './support/people.ts';

test('a forgotten password is replaced through the mailed link', async ({ page }, testInfo) => {
  const person = await registered(newPerson(testInfo));
  const next = `${person.password} and changed`;
  const requests = recordRequests(page);

  await test.step('asking for a link answers the same way for every address', async () => {
    await page.goto('/sign-in');
    await page.getByRole('link', { name: 'Forgot password?' }).click();
    await page.getByLabel('Email').fill(person.email);
    await page.getByRole('button', { name: 'Send the link' }).click();
    await expect(page.getByRole('heading', { name: 'Check your email', level: 1 })).toBeVisible();
    await expect(page.getByRole('status')).toContainText(`If an account uses ${person.email}, a reset link is on its way.`);
  });

  const link = linkIn(person.email, 'Reset your password');
  const token = link.split('#token=')[1] ?? '';
  expect(token.length).toBeGreaterThanOrEqual(32);

  await test.step('the link opens the form and its token leaves the address bar', async () => {
    await page.goto(link);
    await expect(page.getByLabel('New password')).toBeVisible();
    expect(page.url()).toMatch(/\/auth\/reset-password$/);
    expect(await page.evaluate(() => window.location.hash)).toBe('');
    const stored = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }));
    expect(stored).not.toContain(token);
  });

  await test.step('the new password is saved and the person is asked to sign in with it', async () => {
    await page.getByLabel('New password').fill('too short');
    await page.getByRole('button', { name: 'Save the password' }).click();
    await expect(page.getByText('Use at least 15 characters.')).toBeVisible();

    await page.getByLabel('New password').fill(next);
    await page.getByRole('button', { name: 'Save the password' }).click();
    await expect(page.getByText('Your new password is saved. Sign in with it.')).toBeVisible();
  });

  await test.step('the old password no longer works and the new one does', async () => {
    await signInOnScreen(page, person);
    await expect(page.getByRole('alert')).toContainText('The email or password is not correct.');

    await page.getByLabel('Password', { exact: true }).fill(next);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Create your agency', level: 1 })).toBeVisible();
    await page.getByRole('button', { name: 'Sign out' }).click();
    await expect(page.getByText('You are signed out.')).toBeVisible();
  });

  await test.step('the link cannot be used a second time', async () => {
    await page.goto(link);
    await page.getByLabel('New password').fill(`${next} again`);
    await page.getByRole('button', { name: 'Save the password' }).click();
    await expect(page.getByRole('alert')).toContainText('This link has expired or was already used. Ask for a new one.');
    await expect(page.getByRole('link', { name: 'Ask for a new link' })).toBeVisible();
  });

  // The token travelled once in a request body. No request carried it in its address.
  for (const request of requests) expect(request).not.toContain(token);
});

test('a reset link without its token says it cannot be used', async ({ page }) => {
  await page.goto('/auth/reset-password');
  await expect(page.getByRole('heading', { name: 'This link cannot be used', level: 1 })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Ask for a new link' })).toHaveAttribute('href', '/forgot-password');

  // A link pasted into the same tab is taken, and its token leaves the address bar as well.
  await page.goto('/auth/reset-password#token=Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC10b2tlbi0x');
  await expect(page.getByLabel('New password')).toBeVisible();
  expect(await page.evaluate(() => window.location.hash)).toBe('');
});
