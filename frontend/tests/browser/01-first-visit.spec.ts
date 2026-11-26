import { expect, test } from '@playwright/test';

import { verificationCode } from './support/mail.ts';
import { accountMenu, agreement, newPerson, recordRequests } from './support/people.ts';
import { stack } from './support/stack.ts';

test('a new person creates an account and an agency, then signs out', async ({ page, context }, testInfo) => {
  const person = newPerson(testInfo);
  const requests = recordRequests(page);
  const signIns = () => requests.filter((request) => request.startsWith('POST') && request.endsWith('/auth/login'));

  await test.step('the start page asks a visitor to sign in', async () => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/sign-in$/);
    await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();
  });

  await test.step('registering asks for the agreement and then for the mailed code', async () => {
    await page.getByRole('link', { name: 'Create an agency account' }).click();
    // After a move to another page, focus is on its heading.
    await expect(page.getByRole('heading', { name: 'Create your account', level: 1 })).toBeFocused();
    await page.getByLabel('Your name').fill(person.name);
    await page.getByLabel('Email').fill(person.email);
    await page.getByLabel('Password', { exact: true }).fill(person.password);
    await page.getByRole('button', { name: 'Create account' }).click();
    await expect(page.getByText('Tick the box to agree before you continue.')).toBeVisible();
    await expect(agreement(page)).toBeFocused();
    expect(requests.filter((request) => request.includes('/auth/register'))).toEqual([]);

    await agreement(page).check();
    await page.getByRole('button', { name: 'Create account' }).click();
    await expect(page.getByRole('heading', { name: 'Confirm your email', level: 1 })).toBeVisible();
    await expect(page.getByText(person.email)).toBeVisible();
    expect(page.url()).not.toContain(encodeURIComponent(person.email));
  });

  await test.step('a wrong code is refused', async () => {
    await page.getByLabel('Digit 1 of 6').click();
    await page.keyboard.type('000000');
    await page.getByRole('button', { name: 'Confirm' }).click();
    await expect(page.getByRole('alert')).toContainText('That code is not correct or has expired.');
    await expect(page.getByLabel('Digit 1 of 6')).toHaveValue('');
    await expect(page.getByLabel('Digit 1 of 6')).toBeFocused();
  });

  const code = verificationCode(person.email);
  await test.step('the mailed code confirms the address', async () => {
    await page.keyboard.type(code);
    await expect(page.getByLabel('Digit 6 of 6')).toHaveValue(code.slice(-1));
    await page.getByRole('button', { name: 'Confirm' }).click();
    await expect(page.getByText('Your email is confirmed. You can sign in now.')).toBeVisible();
    await expect(page.getByLabel('Email')).toHaveValue(person.email);
  });

  let token = '';
  await test.step('signing in needs the agreement, then opens the first-agency screen', async () => {
    await page.getByLabel('Password', { exact: true }).fill(person.password);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await expect(page.getByText('Tick the box to agree before you continue.')).toBeVisible();
    expect(signIns()).toEqual([]);

    await agreement(page).check();
    const answer = page.waitForResponse((response) => response.url().endsWith('/auth/login') && response.request().method() === 'POST');
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    token = ((await (await answer).json()) as { csrf_token: string }).csrf_token;
    await expect(page.getByRole('heading', { name: 'Create your agency', level: 1 })).toBeVisible();
  });

  await test.step('the new agency opens the workspace', async () => {
    await page.getByLabel('Agency name').fill('Lumen Studio');
    await page.getByRole('button', { name: 'Create agency' }).click();
    await expect(page.getByRole('heading', { name: 'Overview', level: 1 })).toBeFocused();
    const main = page.getByRole('main');
    await expect(main.getByText('Lumen Studio')).toBeVisible();
    await expect(main.getByText('Owner')).toBeVisible();
    await expect(main.getByText(person.email)).toBeVisible();
    await expect(page).toHaveTitle('Overview · Connect');
  });

  await test.step('the session is a cookie scripts cannot read, and nothing secret is stored', async () => {
    const cookie = (await context.cookies(stack.apiOrigin)).find((item) => item.name === 'tracking_session');
    expect(cookie).toMatchObject({ httpOnly: true, sameSite: 'Lax' });
    const stored = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }) + document.cookie);
    expect(token.length).toBeGreaterThan(20);
    expect(stored).not.toContain(token);
    expect(stored).not.toContain(cookie?.value ?? 'no cookie');
    expect(stored).not.toContain(person.password);
  });

  await test.step('a reload keeps the person signed in', async () => {
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Overview', level: 1 })).toBeVisible();
    await expect(page.getByRole('main').getByText('Lumen Studio')).toBeVisible();
  });

  await test.step('signing out closes the workspace, also for the Back button', async () => {
    await accountMenu(page, person).click();
    await page.getByRole('menuitem', { name: 'Sign out' }).click();
    await expect(page.getByText('You are signed out.')).toBeVisible();
    await page.goBack();
    await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();
    await page.goto('/account');
    await expect(page).toHaveURL(/\/sign-in\?next=%2Faccount$/);
    expect((await context.cookies(stack.apiOrigin)).find((item) => item.name === 'tracking_session')).toBeUndefined();
  });

  // The password, the code and the token travelled in request bodies and headers, never in an address.
  for (const request of requests) {
    expect(request).not.toContain(code);
    expect(request).not.toContain(token);
    expect(request).not.toContain(encodeURIComponent(person.password));
  }
});
