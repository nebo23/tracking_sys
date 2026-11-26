import { expect, test } from '@playwright/test';

import { accountMenu, enterWorkspace, newPerson, registered, signInOnScreen, signedInBrowser, withAgency } from './support/people.ts';

test('a visitor is asked to sign in and then lands on the page they wanted', async ({ page }, testInfo) => {
  const person = await registered(newPerson(testInfo));
  await withAgency(person, 'Lumen Studio');

  await page.goto('/account');
  await expect(page).toHaveURL(/\/sign-in\?next=%2Faccount$/);
  await signInOnScreen(page, person);
  await expect(page.getByRole('heading', { name: 'Account', level: 1 })).toBeVisible();
  await expect(page).toHaveURL(/\/account$/);
});

test('a session that ended sends the person to sign in, and back to their page afterwards', async ({ page, context }, testInfo) => {
  const person = await registered(newPerson(testInfo));
  await withAgency(person, 'Lumen Studio');
  await enterWorkspace(page, person);
  await page.getByRole('link', { name: 'Account' }).first().click();
  await expect(page.getByRole('heading', { name: 'Account', level: 1 })).toBeVisible();

  // The session ends on the server's side; the page does not know yet.
  await context.clearCookies();
  await page.getByLabel('Current password').fill(person.password);
  await page.getByLabel('New password').fill(`${person.password} and more`);
  await page.getByRole('button', { name: 'Change password' }).click();

  await expect(page.getByText('Your session ended. Sign in again.')).toBeVisible();
  await expect(page).toHaveURL(/\/sign-in\?notice=expired&next=%2Faccount$/);
  // The password did not change: the request was refused before anything happened.
  await signInOnScreen(page, person);
  await expect(page.getByRole('heading', { name: 'Account', level: 1 })).toBeVisible();
});

test('changing the password ends every session and only the new password works', async ({ page, context }, testInfo) => {
  const person = await registered(newPerson(testInfo));
  await withAgency(person, 'Lumen Studio');
  const next = `${person.password} and changed`;
  await signedInBrowser(context, person);
  await page.goto('/account');

  await page.getByLabel('Current password').fill('not the current password');
  await page.getByLabel('New password').fill(next);
  await page.getByRole('button', { name: 'Change password' }).click();
  await expect(page.getByRole('alert')).toContainText('The current password is not correct.');
  await expect(page.getByRole('heading', { name: 'Account', level: 1 })).toBeVisible();

  await page.getByLabel('Current password').fill(person.password);
  await page.getByRole('button', { name: 'Change password' }).click();
  await expect(page.getByText('Your password was changed. Sign in with the new password.')).toBeVisible();

  await signInOnScreen(page, person);
  await expect(page.getByRole('alert')).toContainText('The email or password is not correct.');
  await page.getByLabel('Password', { exact: true }).fill(next);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Overview', level: 1 })).toBeVisible();
});

test('signing out everywhere ends the session of another browser too', async ({ page, context, browser }, testInfo) => {
  const person = await registered(newPerson(testInfo));
  await withAgency(person, 'Lumen Studio');
  await signedInBrowser(context, person);
  const other = await browser.newContext();
  await signedInBrowser(other, person);
  const otherPage = await other.newPage();
  await otherPage.goto('/account');
  await expect(otherPage.getByRole('heading', { name: 'Account', level: 1 })).toBeVisible();

  await page.goto('/account');
  await page.getByRole('button', { name: 'Sign out everywhere' }).click();
  await expect(page.getByText('You are signed out.')).toBeVisible();

  await otherPage.reload();
  await expect(otherPage.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();
  await other.close();
});

test('an account is closed only after asking twice and checking the password', async ({ page }, testInfo) => {
  const person = await registered(newPerson(testInfo));

  await test.step('a person without an agency still reaches their account', async () => {
    await page.goto('/sign-in');
    await signInOnScreen(page, person);
    await expect(page.getByRole('heading', { name: 'Create your agency', level: 1 })).toBeVisible();
    await page.getByRole('link', { name: 'Account' }).click();
    await expect(page.getByRole('heading', { name: 'Account', level: 1 })).toBeVisible();
  });

  const dialog = page.getByRole('alertdialog', { name: 'Close your account?' });
  await test.step('the dialog explains, and a wrong password closes nothing', async () => {
    await page.getByRole('button', { name: 'Close my account' }).click();
    await expect(dialog).toContainText('This cannot be undone.');
    await dialog.getByLabel('Password', { exact: true }).fill('not the password at all');
    await dialog.getByRole('button', { name: 'Close account' }).click();
    await expect(dialog.getByRole('alert')).toContainText('The password is not correct.');
  });

  await test.step('the right password closes the account for good', async () => {
    await dialog.getByLabel('Password', { exact: true }).fill(person.password);
    await dialog.getByRole('button', { name: 'Close account' }).click();
    await expect(page.getByText('Your account is closed.')).toBeVisible();
    await signInOnScreen(page, person);
    await expect(page.getByRole('alert')).toContainText('The email or password is not correct.');
  });
});

test('the only owner of an agency is told why the account cannot be closed', async ({ page, context }, testInfo) => {
  const person = await registered(newPerson(testInfo));
  await withAgency(person, 'Lumen Studio');
  await signedInBrowser(context, person);
  await page.goto('/account');

  await page.getByRole('button', { name: 'Close my account' }).click();
  const dialog = page.getByRole('alertdialog', { name: 'Close your account?' });
  await dialog.getByLabel('Password', { exact: true }).fill(person.password);
  await dialog.getByRole('button', { name: 'Close account' }).click();
  await expect(dialog.getByRole('alert')).toContainText('An agency would be left without an owner.');

  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect(dialog).toBeHidden();
  await accountMenu(page, person).click();
  await expect(page.getByRole('menu')).toBeVisible();
});
