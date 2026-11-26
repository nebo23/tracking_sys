import { expect, test } from '@playwright/test';

import { newPerson, recordRequests, registered, signedInBrowser, withAgency } from './support/people.ts';
import { stack } from './support/stack.ts';
import { answerAtProvider, standInAccount, withClient, workerPass } from './support/tenants.ts';

// The stand-in provider keeps made-up accounts in a file and contacts nobody. The journey stands
// in for its consent page, which no browser can open, and for the worker that reads and removes.

test('an owner connects an account, watches it synchronize and disconnects it', async ({ page, context }, testInfo) => {
  const owner = await registered(newPerson(testInfo));
  const agencyId = await withAgency(owner, 'Lumen Studio');
  const clientId = await withClient(owner, agencyId, 'Olive & Thyme');
  await signedInBrowser(context, owner);
  const connections = `/agencies/${agencyId}/clients/${clientId}/connections`;
  const account = standInAccount('@olive.thyme');
  const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Sample provider' }) });
  const requests = recordRequests(page);

  await page.goto(connections);
  await expect(page.getByRole('heading', { name: 'Connect the first account' })).toBeVisible();

  await test.step('the provider is chosen, and the browser leaves for it and comes back connected', async () => {
    await answerAtProvider(page, account);
    await page.getByRole('button', { name: 'Connect account' }).click();
    const dialog = page.getByRole('dialog', { name: 'Connect an account' });
    await expect(dialog.getByText('never receives the password')).toBeVisible();
    await dialog.getByRole('radio', { name: /^Sample provider/ }).check();
    await dialog.getByRole('button', { name: 'Continue to the provider' }).click();

    await expect(page.getByText('The account is connected.')).toBeVisible();
    await expect(card.getByText('@olive.thyme')).toBeVisible();
    await expect(card.getByText('Connected', { exact: true })).toBeVisible();
    // The outcome leaves the address at once, and the record of the start is gone.
    await expect(page).toHaveURL(new RegExp(`${connections}$`));
    expect(await page.evaluate(() => window.sessionStorage.getItem('connect.pendingConnection'))).toBeNull();
  });

  await test.step('nothing of the authorization travelled through the application', async () => {
    // The code and the state go from the provider to the API. The application sees the outcome only.
    const through = requests.filter((request) => request.includes(stack.webOrigin) && /[?&](code|state)=/.test(request));
    expect(through).toEqual([]);
    const stored = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }));
    expect(stored).not.toMatch(/syn_code_|code_challenge/);
  });

  await test.step('before the first read, nothing is called fresh and no figure is invented', async () => {
    await expect(card.getByText('Not synced').first()).toBeVisible();
    await expect(card.getByText('Waiting to start')).toBeVisible();
    await expect(card.getByText('Fresh')).toHaveCount(0);
    await expect(card.getByRole('button', { name: 'Sync now' })).toBeDisabled();
  });

  await test.step('a reload does not repeat the news', async () => {
    await page.reload();
    await expect(card.getByText('@olive.thyme')).toBeVisible();
    await expect(page.getByText('The account is connected.')).toHaveCount(0);
  });

  await test.step('the worker reads, and the card follows without a reload', async () => {
    expect(workerPass().sync).toMatchObject({ succeeded: 1 });
    await expect(card.getByText('Fresh')).toBeVisible({ timeout: 20_000 });
    await expect(card.getByText('Complete')).toBeVisible();
    await expect(card.getByRole('img', { name: /used today$/ })).toBeVisible();
    await expect(card.getByText('Waiting to start')).toHaveCount(0);
  });

  await test.step('a sync is requested once, and a second one waits for the first', async () => {
    await card.getByRole('button', { name: 'Sync now' }).click();
    await expect(card.getByText('A sync was requested. New data appears here when it finishes.')).toBeVisible();
    await expect(card.getByText('Waiting to start')).toBeVisible();
    await expect(card.getByRole('button', { name: 'Sync now' })).toBeDisabled();
    expect(workerPass().sync).toMatchObject({ succeeded: 1 });
    await expect(card.getByText('Waiting to start')).toHaveCount(0, { timeout: 20_000 });
    await expect(card.getByRole('button', { name: 'Sync now' })).toBeEnabled();
  });

  await test.step('the list of clients shows the client as connected', async () => {
    await page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link', { name: 'Lumen Studio' }).click();
    const row = page.getByRole('row', { name: /Olive & Thyme/ });
    await expect(row.getByText('Connected')).toBeVisible();
    await expect(row.getByRole('img', { name: 'Sample provider' })).toBeVisible();
    await page.goBack();
    await expect(card.getByText('@olive.thyme')).toBeVisible();
  });

  await test.step('a person who says no at the provider is told so, and nothing changes', async () => {
    await answerAtProvider(page, standInAccount('@another'), { refuse: true });
    await page.getByRole('button', { name: 'Connect account' }).click();
    await page.getByRole('dialog').getByRole('radio', { name: /^Sample provider/ }).check();
    await page.getByRole('dialog').getByRole('button', { name: 'Continue to the provider' }).click();
    await expect(page.getByRole('alert')).toContainText('The connection was cancelled at the provider.');
    await expect(page.getByRole('article')).toHaveCount(1);
  });

  await test.step('the same account is not connected twice', async () => {
    await answerAtProvider(page, account);
    await page.getByRole('button', { name: 'Connect account' }).click();
    await page.getByRole('dialog').getByRole('radio', { name: /^Sample provider/ }).check();
    await page.getByRole('dialog').getByRole('button', { name: 'Continue to the provider' }).click();
    await expect(page.getByRole('alert')).toContainText('This account is already connected to this client.');
    await expect(page.getByRole('article')).toHaveCount(1);
  });

  await test.step('disconnecting is asked twice and removes what was stored', async () => {
    await card.getByRole('button', { name: 'Disconnect' }).click();
    const dialog = page.getByRole('alertdialog', { name: 'Disconnect Sample provider (@olive.thyme)?' });
    await dialog.getByRole('button', { name: 'Disconnect' }).click();
    await expect(dialog.getByText('Tick the box to confirm.')).toBeVisible();
    await expect(dialog.getByRole('checkbox')).toBeFocused();
    await dialog.getByRole('checkbox', { name: 'I understand that this cannot be undone' }).check();
    await dialog.getByRole('button', { name: 'Disconnect' }).click();

    await expect(card.getByText('Disconnecting', { exact: true })).toBeVisible();
    await expect(card.getByText(/Its stored data is removed by/)).toBeVisible();
    await expect(card.getByRole('button')).toHaveCount(0);

    expect(workerPass().teardown).toMatchObject({ disconnected: 1 });
    const past = page.getByRole('region', { name: 'Past connections' });
    await expect(past.getByText('Data removed')).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole('heading', { name: 'Connect the first account' })).toBeVisible();
  });
});

test('the approval of the account holder is asked for where the provider needs it', async ({ page, context }, testInfo) => {
  const owner = await registered(newPerson(testInfo));
  const agencyId = await withAgency(owner, 'Lumen Studio');
  const clientId = await withClient(owner, agencyId, 'Olive & Thyme');
  await signedInBrowser(context, owner);
  await page.goto(`/agencies/${agencyId}/clients/${clientId}/connections`);

  await answerAtProvider(page, standInAccount('Olive & Thyme Kitchen', 'synthetic_youtube'));
  await page.getByRole('button', { name: 'Connect account' }).click();
  const dialog = page.getByRole('dialog', { name: 'Connect an account' });
  await dialog.getByRole('radio', { name: /^Sample YouTube/ }).check();
  const approval = dialog.getByRole('checkbox', { name: /approve the agency and the people it gives access to Olive & Thyme/ });
  await expect(approval).not.toBeChecked();

  await dialog.getByRole('button', { name: 'Continue to the provider' }).click();
  await expect(dialog.getByText('Tick the box to give this approval before you continue.')).toBeVisible();
  await expect(approval).toBeFocused();

  await approval.check();
  await dialog.getByRole('button', { name: 'Continue to the provider' }).click();
  await expect(page.getByText('The account is connected.')).toBeVisible();
  const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Sample YouTube' }) });
  await expect(card.getByText('Olive & Thyme Kitchen')).toBeVisible();

  // The stand-in channel has four streams and two limits of its own; each is shown by name.
  workerPass();
  await expect(card.getByText('Channel days')).toBeVisible({ timeout: 20_000 });
  await expect(card.getByText('Video totals')).toBeVisible();
  await expect(card.getByRole('img', { name: /used today$/ })).toHaveCount(2);
});
