import { expect, test, type Locator, type Page } from '@playwright/test';

import { accountMenu, agreement, newPerson, registered, signedInBrowser, withAgency } from './support/people.ts';

/** Presses Tab until a control has focus, as a person without a mouse does. */
async function tabTo(page: Page, control: Locator, limit = 25): Promise<void> {
  for (let presses = 0; presses < limit; presses += 1) {
    await page.keyboard.press('Tab');
    if (await control.evaluate((element) => element === document.activeElement)) return;
  }
  throw new Error('Tab never reached the control.');
}

/** True when the focused control shows it: an outline of at least two pixels. */
const showsFocus = (control: Locator) =>
  control.evaluate((element) => {
    const style = getComputedStyle(element);
    return style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) >= 2;
  });

test('a person signs in with the keyboard alone', async ({ page }, testInfo) => {
  const person = await registered(newPerson(testInfo));
  await withAgency(person, 'Lumen Studio');
  await page.goto('/sign-in');
  await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();

  const email = page.getByLabel('Email');
  await tabTo(page, email);
  expect(await showsFocus(email)).toBe(true);
  await page.keyboard.type(person.email);

  await page.keyboard.press('Tab');
  await expect(page.getByLabel('Password', { exact: true })).toBeFocused();
  await page.keyboard.type(person.password);

  // Enter without the tick: focus lands on the box that is missing.
  await page.keyboard.press('Enter');
  await expect(agreement(page)).toBeFocused();
  expect(await showsFocus(agreement(page))).toBe(true);
  await page.keyboard.press('Space');
  await expect(agreement(page)).toBeChecked();

  const submit = page.getByRole('button', { name: 'Sign in', exact: true });
  await tabTo(page, submit);
  expect(await showsFocus(submit)).toBe(true);
  await page.keyboard.press('Enter');

  await expect(page.getByRole('heading', { name: 'Overview', level: 1 })).toBeFocused();
});

test('the workspace is used with the keyboard alone', async ({ page, context }, testInfo) => {
  const person = await registered(newPerson(testInfo));
  await withAgency(person, 'Lumen Studio');
  await signedInBrowser(context, person);
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Overview', level: 1 })).toBeVisible();

  await test.step('the first Tab offers to skip to the content', async () => {
    await page.keyboard.press('Tab');
    const skip = page.getByRole('link', { name: 'Skip to content' });
    await expect(skip).toBeFocused();
    await expect(skip).toBeInViewport();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('main')).toBeFocused();
  });

  await test.step('the account menu opens, moves and closes with keys', async () => {
    const trigger = accountMenu(page, person);
    await tabTo(page, trigger);
    expect(await showsFocus(trigger)).toBe(true);
    await page.keyboard.press('Enter');
    const menu = page.getByRole('menu');
    await expect(menu).toBeVisible();
    await expect(menu.getByRole('menuitemradio', { name: 'English' })).toBeFocused();
    await page.keyboard.press('ArrowDown');
    await expect(menu.getByRole('menuitemradio', { name: 'العربية' })).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(menu).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  await test.step('the account page is reached and its dialog keeps focus inside', async () => {
    await accountMenu(page, person).press('Enter');
    await page.keyboard.press('End');
    await page.keyboard.press('ArrowUp');
    await expect(page.getByRole('menuitem', { name: 'Account' })).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('heading', { name: 'Account', level: 1 })).toBeFocused();

    const open = page.getByRole('button', { name: 'Close my account' });
    await tabTo(page, open, 40);
    await page.keyboard.press('Enter');
    const dialog = page.getByRole('alertdialog', { name: 'Close your account?' });
    await expect(dialog).toBeVisible();
    for (let presses = 0; presses < 8; presses += 1) {
      await page.keyboard.press('Tab');
      expect(await dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
    }
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(open).toBeFocused();
  });

  await test.step('signing out is the last row of the menu', async () => {
    await accountMenu(page, person).press('Enter');
    await page.keyboard.press('End');
    await expect(page.getByRole('menuitem', { name: 'Sign out' })).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.getByText('You are signed out.')).toBeVisible();
  });
});
