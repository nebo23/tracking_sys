import { expect, test } from '@playwright/test';

import { linkIn } from './support/mail.ts';
import { invite, newPerson, recordRequests, registered, signInOnScreen, withAgency } from './support/people.ts';

test('an invited person signs in and joins the agency through the mailed link', async ({ page }, testInfo) => {
  const owner = await registered(newPerson(testInfo, 'Omar Farouk'));
  const agencyId = await withAgency(owner, 'Northlight Media');
  const guest = await registered(newPerson(testInfo, 'Mona Hassan'));
  await invite(owner, agencyId, guest.email);
  const link = linkIn(guest.email, 'Agency invitation');
  const token = link.split('#token=')[1] ?? '';
  const requests = recordRequests(page);

  await test.step('the link asks a visitor to sign in first, and keeps its token out of every address', async () => {
    await page.goto(link);
    await expect(page.getByRole('heading', { name: 'Join the agency', level: 1 })).toBeVisible();
    expect(page.url()).toMatch(/\/auth\/accept-invitation$/);
    const signIn = page.getByRole('link', { name: 'Sign in to continue' });
    await expect(signIn).toHaveAttribute('href', '/sign-in?next=%2Fauth%2Faccept-invitation');
    expect(await page.content()).not.toContain(token);
    await signIn.click();
  });

  await test.step('after signing in the invitation is still there to accept', async () => {
    await signInOnScreen(page, guest);
    await expect(page.getByRole('heading', { name: 'Join the agency', level: 1 })).toBeVisible();
    await page.getByRole('button', { name: 'Accept the invitation' }).click();
  });

  await test.step('the agency opens with the role of the invitation', async () => {
    await expect(page.getByRole('heading', { name: 'Clients', level: 1 })).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Breadcrumb' }).getByText('Northlight Media')).toBeVisible();
    // An admin manages the agency: its team and its keys are offered.
    await expect(page.getByRole('link', { name: 'Team and access' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'API keys' })).toBeVisible();
  });

  await test.step('the link cannot be used again', async () => {
    await page.goto(link);
    await page.getByRole('button', { name: 'Accept the invitation' }).click();
    await expect(page.getByRole('alert')).toContainText('This invitation has expired, was withdrawn or belongs to another email.');
  });

  for (const request of requests) expect(request).not.toContain(token);
});

test('an invitation for another address is refused', async ({ page }, testInfo) => {
  const owner = await registered(newPerson(testInfo, 'Omar Farouk'));
  const agencyId = await withAgency(owner, 'Northlight Media');
  const guest = await registered(newPerson(testInfo, 'Mona Hassan'));
  const stranger = await registered(newPerson(testInfo, 'Sara Adel'));
  await invite(owner, agencyId, guest.email);
  const link = linkIn(guest.email, 'Agency invitation');

  await page.goto(link);
  await page.getByRole('link', { name: 'Sign in to continue' }).click();
  await signInOnScreen(page, stranger);
  await page.getByRole('button', { name: 'Accept the invitation' }).click();

  await expect(page.getByRole('alert')).toContainText('This invitation has expired, was withdrawn or belongs to another email.');
  await expect(page.getByRole('heading', { name: 'This invitation link cannot be used', level: 1 })).toBeVisible();
});
