import { expect, test, type Page } from '@playwright/test';

import { linkIn } from './support/mail.ts';
import { newPerson, registered, send, signedIn, signedInBrowser, withAgency } from './support/people.ts';
import { stack } from './support/stack.ts';
import { acceptInvitation, inviteAs, withClient } from './support/tenants.ts';

// The members of an agency by name, their client access, paused access, archived clients and the
// audit log (018-B plan, B1 and B2; D-094), on the real API.

test('an owner changes, pauses and restores a member\'s access, archives a client and reads the audit log', async ({ page, context, browser }, testInfo) => {
  const owner = await registered(newPerson(testInfo));
  const analyst = await registered(newPerson(testInfo, 'Youssef Salah'));
  const agencyId = await withAgency(owner, 'Lumen Studio');
  // One sign-in for the whole preparation: the API limits how often an account signs in.
  const session = await signedIn(owner);
  const olive = await withClient(session, agencyId, 'Olive & Thyme');
  const cedar = await withClient(session, agencyId, 'Cedar Fitness');
  await inviteAs(session, agencyId, analyst.email, 'analyst', [{ client_id: olive }]);
  await send('POST /auth/logout', undefined, session);
  await acceptInvitation(analyst, linkIn(analyst.email, 'Agency invitation').split('#token=')[1] ?? '');

  await signedInBrowser(context, owner);
  const theirs = await browser.newContext({ baseURL: stack.webOrigin });
  await signedInBrowser(theirs, analyst);
  const visit = await theirs.newPage();
  const member = page.getByRole('row', { name: /Youssef Salah/ });
  const clientsOf = async (who: Page) => {
    await who.goto(`/agencies/${agencyId}/clients`);
    await expect(who.getByRole('heading', { level: 1 })).toBeVisible();
  };

  await test.step('the members are listed by name, with what each may open', async () => {
    await page.goto(`/agencies/${agencyId}/team`);
    await expect(page.getByRole('tab', { name: /Members/ })).toHaveAttribute('aria-selected', 'true');
    const you = page.getByRole('row', { name: /Mona Hassan/ });
    await expect(you.getByText('(you)')).toBeVisible();
    await expect(you.getByText('All clients')).toBeVisible();
    await expect(you.getByRole('button')).toHaveCount(0);
    await expect(member.getByText(analyst.email)).toBeVisible();
    await expect(member.getByText('Olive & Thyme')).toBeVisible();
    await expect(member.getByText('None')).toBeVisible();
  });

  await test.step('a second client and its financial data are given', async () => {
    await member.getByRole('button', { name: 'Actions for Youssef Salah' }).click();
    await page.getByRole('menuitem', { name: 'Change access' }).click();
    const dialog = page.getByRole('dialog', { name: 'Access of Youssef Salah' });
    await expect(dialog.getByRole('checkbox', { name: 'Olive & Thyme', exact: true })).toBeChecked();
    await dialog.getByRole('checkbox', { name: 'Cedar Fitness', exact: true }).check();
    await dialog.getByRole('checkbox', { name: 'Financial data of Cedar Fitness' }).check();
    await dialog.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText('The access of Youssef Salah is saved.')).toBeVisible();
    await expect(member.getByText('2 clients')).toBeVisible();
    await expect(member.getByText('1 of 2')).toBeVisible();

    await clientsOf(visit);
    await expect(visit.getByRole('row', { name: /Cedar Fitness/ })).toBeVisible();
    await expect(visit.getByRole('row', { name: /Olive & Thyme/ })).toBeVisible();
  });

  await test.step('paused access closes the agency to the member until it is restored', async () => {
    await member.getByRole('button', { name: 'Actions for Youssef Salah' }).click();
    await page.getByRole('menuitem', { name: 'Pause access' }).click();
    await page.getByRole('alertdialog', { name: 'Pause the access of Youssef Salah?' }).getByRole('button', { name: 'Pause access' }).click();
    await expect(member.getByText('Access paused')).toBeVisible();

    await clientsOf(visit);
    await expect(visit.getByRole('heading', { name: 'Page not found', level: 1 })).toBeVisible();
    await expect(visit.getByText('Cedar Fitness')).toHaveCount(0);

    await member.getByRole('button', { name: 'Actions for Youssef Salah' }).click();
    await page.getByRole('menuitem', { name: 'Restore access' }).click();
    await expect(page.getByText('The access of Youssef Salah is restored.')).toBeVisible();
    await expect(member.getByText('Active')).toBeVisible();

    await clientsOf(visit);
    await expect(visit.getByRole('row', { name: /Cedar Fitness/ })).toBeVisible();
  });

  await test.step('an archived client cannot be opened by anyone until it is restored', async () => {
    await page.getByRole('link', { name: 'Clients' }).click();
    const cedarRow = page.getByRole('row', { name: /Cedar Fitness/ });
    await cedarRow.getByRole('button', { name: 'Actions for Cedar Fitness' }).click();
    await page.getByRole('menuitem', { name: 'Archive' }).click();
    await page.getByRole('alertdialog', { name: 'Archive Cedar Fitness?' }).getByRole('button', { name: 'Archive' }).click();
    await expect(page.getByText(/Cedar Fitness is archived\./)).toBeVisible();
    await expect(cedarRow).toHaveCount(0);
    await expect(page.getByText('1 archived', { exact: true })).toBeVisible();

    // Neither the member nor the owner can open it, whatever the address says.
    for (const who of [visit, page]) {
      await who.goto(`/agencies/${agencyId}/clients/${cedar}/connections`);
      await expect(who.getByRole('heading', { name: 'Page not found', level: 1 })).toBeVisible();
    }
    await clientsOf(visit);
    await expect(visit.getByRole('row', { name: /Olive & Thyme/ })).toBeVisible();
    await expect(visit.getByText('Cedar Fitness')).toHaveCount(0);

    await clientsOf(page);
    await page.getByRole('group', { name: 'Show' }).getByRole('button', { name: 'Archived' }).click();
    await page.getByRole('button', { name: 'Restore Cedar Fitness' }).click();
    await expect(page.getByText('Cedar Fitness is active again.')).toBeVisible();
    await clientsOf(visit);
    await expect(visit.getByRole('row', { name: /Cedar Fitness/ })).toBeVisible();
  });

  await test.step('the audit log names who did what', async () => {
    await page.getByRole('link', { name: 'Audit log' }).click();
    await expect(page.getByRole('heading', { name: 'Audit log', level: 1 })).toBeFocused();
    const row = (sentence: string | RegExp) => page.getByRole('row').filter({ hasText: sentence });
    await expect(row('Added the client Olive & Thyme').getByText('Mona Hassan')).toBeVisible();
    await expect(row('Gave Youssef Salah access to a client').getByText('Cedar Fitness')).toBeVisible();
    await expect(row('Accepted an invitation').getByText('Youssef Salah')).toBeVisible();
    await expect(row('Changed the role or access of Youssef Salah')).toHaveCount(2);
    await expect(row('Changed the client Cedar Fitness')).toHaveCount(2);
    await expect(row(`Invited ${analyst.email}`)).toHaveCount(1);
    // Newest first: the restore of the client is at the top.
    await expect(page.getByRole('row').nth(1)).toContainText('Changed the client Cedar Fitness');
  });

  await theirs.close();
});
