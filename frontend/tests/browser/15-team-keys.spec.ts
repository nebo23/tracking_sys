import { expect, test } from '@playwright/test';

import { linkIn } from './support/mail.ts';
import { newPerson, registered, signedInBrowser, signInOnScreen, withAgency } from './support/people.ts';
import { stack } from './support/stack.ts';
import { withClient } from './support/tenants.ts';

test('an owner invites people with the clients they may open, and withdraws an invitation', async ({ page, context, browser }, testInfo) => {
  const owner = await registered(newPerson(testInfo));
  const agencyId = await withAgency(owner, 'Lumen Studio');
  await withClient(owner, agencyId, 'Olive & Thyme');
  await withClient(owner, agencyId, 'Cedar Fitness');
  const analyst = await registered(newPerson(testInfo, 'Youssef Salah'));
  const viewer = await registered(newPerson(testInfo, 'Sara Fouad'));
  await signedInBrowser(context, owner);
  const row = (email: string) => page.getByRole('row', { name: new RegExp(email.replace(/[.+]/g, '\\$&')) });

  await page.goto('/');
  await page.getByRole('link', { name: 'Team and access' }).click();
  await expect(page.getByRole('heading', { name: 'Team and access', level: 1 })).toBeFocused();
  // The members come first: so far the owner alone.
  await expect(page.getByRole('tab', { name: /Members/ })).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('main tbody tr')).toHaveCount(1);
  await page.getByRole('tab', { name: /Invitations/ }).click();
  await expect(page.getByRole('heading', { name: 'No invitations yet' })).toBeVisible();

  await test.step('an invitation needs an address and, for an analyst, a client', async () => {
    await page.getByRole('button', { name: 'Invite person' }).click();
    const dialog = page.getByRole('dialog', { name: 'Invite a person' });
    await dialog.getByRole('button', { name: 'Send invitation' }).click();
    await expect(dialog.getByText('This field is needed.')).toBeVisible();
    await expect(dialog.getByText('Choose at least one client.')).toBeVisible();

    await dialog.getByLabel('Email').fill(analyst.email);
    await dialog.getByRole('checkbox', { name: 'Olive & Thyme', exact: true }).check();
    await dialog.getByRole('checkbox', { name: 'Financial data of Olive & Thyme' }).check();
    await dialog.getByRole('button', { name: 'Send invitation' }).click();

    await expect(page.getByText(/An invitation is on its way to/)).toContainText(analyst.email);
    await expect(row(analyst.email).getByText('Analyst')).toBeVisible();
    await expect(row(analyst.email).getByText('Waiting')).toBeVisible();
  });

  await test.step('the same person is not invited twice', async () => {
    await page.getByRole('button', { name: 'Invite person' }).click();
    const dialog = page.getByRole('dialog', { name: 'Invite a person' });
    await dialog.getByLabel('Email').fill(analyst.email);
    await dialog.getByRole('checkbox', { name: 'Cedar Fitness', exact: true }).check();
    await dialog.getByRole('button', { name: 'Send invitation' }).click();
    await expect(dialog.getByRole('alert')).toContainText('This person is already a member, or an invitation is still waiting for them.');
    await dialog.getByRole('button', { name: 'Cancel' }).click();
  });

  await test.step('the invited analyst accepts and opens only the client they were given', async () => {
    const theirs = await browser.newContext({ baseURL: stack.webOrigin });
    const visit = await theirs.newPage();
    await visit.goto(linkIn(analyst.email, 'Agency invitation'));
    await visit.getByRole('link', { name: 'Sign in to continue' }).click();
    await signInOnScreen(visit, analyst);
    await visit.getByRole('button', { name: 'Accept the invitation' }).click();
    await expect(visit.getByRole('heading', { name: 'Clients', level: 1 })).toBeVisible();
    await expect(visit.getByRole('row', { name: /Olive & Thyme/ })).toBeVisible();
    await expect(visit.getByText('Cedar Fitness')).toHaveCount(0);
    await expect(visit.getByRole('link', { name: 'Team and access' })).toHaveCount(0);
    await theirs.close();

    await page.reload();
    // The analyst is now a member, named, with the one client and its financial data.
    const member = page.getByRole('row', { name: /Youssef Salah/ });
    await expect(member.getByText(analyst.email)).toBeVisible();
    await expect(member.getByText('Olive & Thyme')).toBeVisible();
    await expect(member.getByText('Active')).toBeVisible();
    await page.getByRole('tab', { name: /Invitations/ }).click();
    await expect(row(analyst.email).getByText('Accepted')).toBeVisible();
    await expect(row(analyst.email).getByRole('button')).toHaveCount(0);
  });

  await test.step('a client viewer is invited with another role from the list', async () => {
    await page.getByRole('button', { name: 'Invite person' }).click();
    const dialog = page.getByRole('dialog', { name: 'Invite a person' });
    await dialog.getByLabel('Email').fill(viewer.email);
    await dialog.getByRole('button', { name: /Role/ }).click();
    await page.getByRole('option', { name: /^Client viewer/ }).click();
    await dialog.getByRole('checkbox', { name: 'Cedar Fitness', exact: true }).check();
    await dialog.getByRole('button', { name: 'Send invitation' }).click();
    await expect(row(viewer.email).getByText('Client viewer')).toBeVisible();
  });

  await test.step('a withdrawn invitation no longer lets anyone in', async () => {
    const link = linkIn(viewer.email, 'Agency invitation');
    await row(viewer.email).getByRole('button', { name: `Withdraw the invitation to ${viewer.email}` }).click();
    const dialog = page.getByRole('alertdialog', { name: 'Withdraw this invitation?' });
    await expect(dialog).toContainText(viewer.email);
    await dialog.getByRole('button', { name: 'Withdraw' }).click();
    await expect(row(viewer.email).getByText('Withdrawn')).toBeVisible();

    const theirs = await browser.newContext({ baseURL: stack.webOrigin });
    const visit = await theirs.newPage();
    await visit.goto(link);
    await visit.getByRole('link', { name: 'Sign in to continue' }).click();
    await signInOnScreen(visit, viewer);
    await visit.getByRole('button', { name: 'Accept the invitation' }).click();
    await expect(visit.getByRole('alert')).toContainText('This invitation has expired, was withdrawn or belongs to another email.');
    await theirs.close();
  });
});

test('a key is shown once, works for the clients it was given, and stops when it is revoked', async ({ page, context }, testInfo) => {
  const owner = await registered(newPerson(testInfo));
  const agencyId = await withAgency(owner, 'Lumen Studio');
  const granted = await withClient(owner, agencyId, 'Olive & Thyme');
  await withClient(owner, agencyId, 'Cedar Fitness');
  await signedInBrowser(context, owner);
  // What the agency's own system would do with the key: read the clients it reaches.
  const readClients = (key: string) => fetch(`${stack.apiOrigin}/agencies/${agencyId}/clients`, { headers: { Authorization: `Bearer ${key}` } });
  let key = '';

  await page.goto(`/agencies/${agencyId}/keys`);
  await expect(page.getByRole('heading', { name: 'No keys yet' })).toBeVisible();

  await test.step('the key is created for one client and shown once', async () => {
    await page.getByRole('button', { name: 'Create key' }).click();
    const dialog = page.getByRole('dialog', { name: 'Create a key' });
    await dialog.getByLabel('Name').fill('Reporting sheet');
    await dialog.getByRole('checkbox', { name: 'Olive & Thyme', exact: true }).check();
    await dialog.getByRole('button', { name: 'Create key' }).click();

    const shown = page.getByRole('dialog', { name: 'Key “Reporting sheet” is ready' });
    await expect(shown.getByText('It is not shown again.')).toBeVisible();
    key = await shown.getByLabel('Key').inputValue();
    expect(key).toMatch(/^tsk_[\w-]{32,}$/);
    const kept = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }) + location.href);
    expect(kept).not.toContain(key);

    await shown.getByRole('button', { name: 'I have copied it' }).click();
    await expect(shown).toBeHidden();
    expect(await page.content()).not.toContain(key);
    const row = page.getByRole('row', { name: /Reporting sheet/ });
    await expect(row.getByText('Read')).toBeVisible();
    await expect(row.getByText('Active')).toBeVisible();
  });

  await test.step('the key reads the client it was given, and no other', async () => {
    const answer = await readClients(key);
    expect(answer.status).toBe(200);
    const clients = (await answer.json()) as Array<{ id: string; name: string }>;
    expect(clients.map((client) => client.id)).toEqual([granted]);
  });

  await test.step('a reload never shows the key again', async () => {
    await page.reload();
    await expect(page.getByRole('row', { name: /Reporting sheet/ })).toBeVisible();
    expect(await page.content()).not.toContain(key);
  });

  await test.step('a revoked key stops working at once', async () => {
    await page.getByRole('button', { name: 'Revoke the key Reporting sheet' }).click();
    const dialog = page.getByRole('alertdialog', { name: 'Revoke “Reporting sheet”?' });
    await dialog.getByRole('button', { name: 'Revoke' }).click();
    const row = page.getByRole('row', { name: /Reporting sheet/ });
    await expect(row.getByText('Revoked')).toBeVisible();
    await expect(row.getByRole('button')).toHaveCount(0);
    expect((await readClients(key)).status).toBe(401);
  });
});
