import { readFileSync } from 'node:fs';

import { expect, test } from '@playwright/test';

import { linkIn, reportLinkIn } from './support/mail.ts';
import { newPerson, registered, send, signedIn, signedInBrowser, withAgency } from './support/people.ts';
import { makeScheduleDue, runReportWorker, stack, type BackendEnvironment } from './support/stack.ts';
import { acceptInvitation, analyzeDays, declareSale, inviteAs, withClient } from './support/tenants.ts';

// Reports (018-G; E03 to E08 on the 016-C contract) on the real API: an export saved from a report
// page, downloaded and revoked; a schedule with a recipient, one pass of the report worker, the
// email it queues and the address it holds.

function runningStack(): { python: string; backend: BackendEnvironment } {
  const python = process.env.CONNECT_E2E_PYTHON;
  const backend = process.env.CONNECT_E2E_BACKEND;
  if (!python || !backend) throw new Error('The disposable stack is not running (see global-setup.ts).');
  return { python, backend: JSON.parse(backend) as BackendEnvironment };
}

test('a report is kept as an export, downloaded and revoked, and sent on a schedule', async ({ page, context, browser }, testInfo) => {
  const owner = await registered(newPerson(testInfo));
  const analyst = await registered(newPerson(testInfo, 'Youssef Salah'));
  const agencyId = await withAgency(owner, 'Lumen Studio');
  // One sign-in for the whole preparation: the API limits how often an account signs in.
  const session = await signedIn(owner);
  const clientId = await withClient(session, agencyId, 'Olive & Thyme');
  await declareSale(session, agencyId, clientId, `sale-${Date.now()}`, '1250.00', '2026-11-05T10:00:00Z');
  // The analyst may open the client, without its financial data.
  await inviteAs(session, agencyId, analyst.email, 'analyst', [{ client_id: clientId }]);
  await send('POST /auth/logout', undefined, session);
  await acceptInvitation(analyst, linkIn(analyst.email, 'Agency invitation').split('#token=')[1] ?? '');
  await signedInBrowser(context, owner);
  const base = `/agencies/${agencyId}/clients/${clientId}`;
  const { python, backend } = runningStack();

  await test.step('a report page saves its report as an export', async () => {
    await page.goto(`${base}/revenue?from=${analyzeDays.from}&to=${analyzeDays.to}`);
    await page.getByRole('button', { name: 'Save as export' }).click();
    const dialog = page.getByRole('dialog', { name: 'Save this report as an export?' });
    await expect(dialog.getByText('Revenue', { exact: true })).toBeVisible();
    await expect(dialog.getByText(/21 days$/)).toBeVisible();
    await dialog.getByRole('button', { name: 'Save export' }).click();
    await expect(page.getByText(/Saved as an export\./)).toBeVisible();
    await page.getByRole('link', { name: 'Open the export' }).click();
    await expect(page.getByRole('heading', { level: 1, name: /^Revenue/ })).toBeVisible();
    await expect(page.getByText('Each download is checked again: it needs access to this client and to its financial data.')).toBeVisible();
  });

  await test.step('the export downloads as the CSV of the report', async () => {
    const download = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Download CSV' }).click();
    const file = await download;
    expect(file.suggestedFilename()).toBe('report-revenue.csv');
    expect(readFileSync((await file.path()) ?? '', 'utf8').length).toBeGreaterThan(0);
  });

  await test.step('a revoked export is gone, and says why', async () => {
    await page.getByRole('link', { name: 'All exports' }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Reports' })).toBeVisible();
    const row = page.getByRole('row', { name: /^Revenue/ });
    await expect(row.getByText('Ready')).toBeVisible();
    await row.getByRole('button', { name: /^Actions for Revenue/ }).click();
    await page.getByRole('menuitem', { name: 'Revoke' }).click();
    await page.getByRole('alertdialog').getByRole('button', { name: 'Revoke the export' }).click();
    await expect(row.getByText('Revoked by a person')).toBeVisible();
    await row.getByRole('button', { name: /^Actions for Revenue/ }).click();
    await page.getByRole('menuitem', { name: 'Open' }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'This export is no longer available' })).toBeVisible();
    await expect(page.getByText(/It was revoked on/)).toBeVisible();
  });

  let scheduleId = '';
  await test.step('a schedule is made with a recipient who may read its report', async () => {
    await page.goto(`${base}/reports?tab=schedules`);
    await expect(page.getByRole('heading', { name: 'No schedules yet' })).toBeVisible();
    await page.getByRole('button', { name: 'New schedule' }).click();
    const dialog = page.getByRole('dialog', { name: 'New schedule' });
    await dialog.getByLabel('Name', { exact: true }).fill('Weekly revenue');
    // Revenue needs financial access, which the analyst does not have.
    await expect(dialog.getByRole('checkbox', { name: /Youssef Salah/ })).toBeDisabled();
    await dialog.getByRole('checkbox', { name: new RegExp(owner.name) }).check();
    const created = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith('/report-schedules'));
    await dialog.getByRole('button', { name: 'Create schedule' }).click();
    scheduleId = ((await (await created).json()) as { id: string }).id;
    const row = page.getByRole('row', { name: /^Weekly revenue/ });
    await expect(row.getByText('Active')).toBeVisible();
    await expect(row.getByText('Not run yet')).toBeVisible();
  });

  let address = '';
  await test.step('the report worker builds it, and the recipient is told by email with a link', async () => {
    makeScheduleDue(python, backend, scheduleId);
    const counts = JSON.parse(runReportWorker(python, backend)) as Record<string, number>;
    expect(counts).toMatchObject({ built: 1, notified: 1, failed: 0 });
    await page.reload();
    await expect(page.getByRole('row', { name: /^Weekly revenue/ }).getByText('Built; 1 recipient told')).toBeVisible();
    address = reportLinkIn(owner.email, 'Weekly revenue');
    expect(address).toMatch(new RegExp(`^/agencies/${agencyId}/clients/${clientId}/reports/exports/[0-9a-f-]{36}$`));
    await page.goto(address);
    await expect(page.getByText(/Made by the schedule .Weekly revenue. on/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Download CSV' })).toBeVisible();
  });

  await test.step('the address opens nothing for a member who may not see the export', async () => {
    const theirs = await browser.newContext({ baseURL: stack.webOrigin });
    await signedInBrowser(theirs, analyst);
    const visit = await theirs.newPage();
    await visit.goto(address);
    await expect(visit.getByRole('heading', { name: 'Page not found', level: 1 })).toBeVisible();
    await visit.goto(`${base}/reports`);
    await expect(visit.getByRole('heading', { name: 'No exports yet' })).toBeVisible();
    await theirs.close();
  });
});
