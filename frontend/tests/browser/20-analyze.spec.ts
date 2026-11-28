import { readFileSync } from 'node:fs';

import { expect, test, type Page } from '@playwright/test';

import { enterWorkspace, newPerson, registered, signedIn, withAgency } from './support/people.ts';
import { analyzeDays, withAnalyzeData, withClient } from './support/tenants.ts';

// Analyze (018-C) on the real API of the disposable stack, over synthetic Instagram, Meta ads and
// declared revenue. The pages name every state the reports give for these facts: partial totals,
// days outside the synchronized ones, metrics that cannot be added up, content of another kind,
// a content list that may be incomplete, and declarations kept apart from verified payments.

const days = `from=${analyzeDays.from}&to=${analyzeDays.to}`;
const card = (page: Page, title: string) => page.locator('article').filter({ has: page.getByRole('heading', { name: title, exact: true }) });
const figure = (page: Page, label: string) => page.getByRole('region', { name: 'Key figures' }).locator('article').filter({ has: page.getByText(label, { exact: true }) });

test('an owner reads the overview, content, revenue and ad spend of a client, with every state named', async ({ page }, testInfo) => {
  const owner = await registered(newPerson(testInfo));
  const agencyId = await withAgency(owner, 'Lumen Studio');
  // The API limits sign-ins per account and minute: the preparation signs in once.
  const session = await signedIn(owner);
  const clientId = await withClient(session, agencyId, 'Olive & Thyme');
  await withAnalyzeData(session, agencyId, clientId);
  const base = `/agencies/${agencyId}/clients/${clientId}`;
  await enterWorkspace(page, owner);

  await test.step('the overview names a partial total, its source, and what has no value', async () => {
    await page.goto(`${base}?${days}`);
    await expect(page.getByRole('heading', { name: 'Overview', level: 1 })).toBeVisible();
    const views = figure(page, 'Views');
    await expect(views.locator('.c-stat__value')).toHaveText(/^\d[\d,]*$/);
    await expect(views.getByText('Partial')).toBeVisible();
    await expect(views.getByText('Some days have no value.')).toBeVisible();
    await expect(views.getByText(/@olive\.thyme/)).toBeVisible();
    await expect(views.getByText('Days in UTC')).toBeVisible();
    await expect(figure(page, 'Net revenue').getByText('No verified revenue')).toBeVisible();
    await expect(figure(page, 'Ad spend').locator('.c-stat__value')).toContainText('EGP');
    await expect(card(page, 'Sources').getByText('Fresh').first()).toBeVisible();
  });

  await test.step('the comparison is kept in the address, and partial periods are not compared', async () => {
    await page.getByRole('checkbox', { name: 'Compare with the previous period' }).check();
    await expect(page).toHaveURL(/compare=true/);
    await expect(figure(page, 'Views').getByText(/^Not compared: /)).toBeVisible();
  });

  await test.step('content names each day outside the synchronized ones, and each metric that cannot be added up', async () => {
    await page.goto(`${base}/content?${days}`);
    await expect(page.getByRole('heading', { name: 'Content', level: 1 })).toBeVisible();
    await card(page, 'By day').getByRole('button', { name: 'Table' }).click();
    await expect(page.getByRole('table', { name: 'Views by day' }).getByText('Not synced: outside the synced days').first()).toBeVisible();
    const totals = card(page, 'Totals of the range');
    const reach = totals.getByRole('row').filter({ has: page.getByRole('rowheader', { name: 'Reach' }) });
    await expect(reach).toContainText('Not available');
    await expect(reach).toContainText('This metric cannot be added up over days.');
    const cohort = card(page, 'Published in this range');
    await expect(cohort.getByText(/^Not supported: not reported for this kind of content$/).first()).toBeVisible();
    await expect(cohort.getByText('The list of published content may be incomplete.')).toBeVisible();
  });

  await test.step('revenue keeps the declared sale apart from verified payments', async () => {
    await page.goto(`${base}/revenue?${days}`);
    await expect(page.getByRole('heading', { name: 'Revenue', level: 1 })).toBeVisible();
    await expect(card(page, 'Declared')).toContainText('1,500.00');
    await expect(card(page, 'Verified payments').getByText('No verified revenue')).toBeVisible();
    await expect(card(page, 'Verified payments')).not.toContainText('1,500.00');
  });

  await test.step('ad spend names each campaign and ad beside its ID, and downloads its CSV', async () => {
    await page.goto(`${base}/ad-spend?${days}`);
    await expect(page.getByRole('heading', { name: 'Ad spend', level: 1 })).toBeVisible();
    const campaign = page.getByRole('rowheader').filter({ hasText: 'Ramadan offers' });
    await expect(campaign).toContainText('1201');
    await expect(card(page, 'Ad account')).toContainText('Africa/Cairo');

    await page.getByRole('button', { name: /Campaigns/ }).click();
    await page.getByRole('option', { name: 'Ads' }).click();
    await expect(page).toHaveURL(/level=ad/);
    await expect(page.getByRole('rowheader').filter({ hasText: 'Reel: new menu' })).toContainText('1203');

    const download = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Download CSV' }).click();
    const file = await download;
    expect(file.suggestedFilename()).toBe(`ad-spend-ad-${analyzeDays.from}-${analyzeDays.to}.csv`);
    const text = readFileSync(await file.path(), 'utf8');
    expect(text.split('\n').length).toBeGreaterThan(1);
    expect(text).toContain('1203');
  });

  await test.step('the range is checked before it is asked for', async () => {
    await page.getByRole('button', { name: /Custom range|Last 30 days|Last 7 days|Last 28 days|This month/ }).first().click();
    await page.getByRole('option', { name: 'Custom range' }).click();
    await page.getByLabel('First day').fill('2026-09-01');
    await expect(page.getByText(/A range has at most 31 days; this one has \d+\./)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Apply' })).toBeDisabled();
  });
});
