import { expect, test, type Page } from '@playwright/test';

import { enterWorkspace, newPerson, registered, signedIn, withAgency } from './support/people.ts';
import { attributionPass, withAnalyzeData, withClient, withCreditedLead } from './support/tenants.ts';

// Attribution (018-E) on the real API of the disposable stack: a visitor who came through a campaign
// link, was identified and became a lead; one attribution pass; and a stand-in ad account. Credit,
// the funnel and the return on ad spend each show the lead, under the model kept in the address.

const card = (page: Page, title: string) => page.locator('article').filter({ has: page.getByRole('heading', { name: title, exact: true }) });

test('an owner reads the credit, the funnel and the return on ad spend of a lead that came through a campaign', async ({ page }, testInfo) => {
  const owner = await registered(newPerson(testInfo));
  const agencyId = await withAgency(owner, 'Lumen Studio');
  // The API limits sign-ins per account and minute: the preparation signs in once.
  const session = await signedIn(owner);
  const clientId = await withClient(session, agencyId, 'Olive & Thyme');
  await withAnalyzeData(session, agencyId, clientId);
  await withCreditedLead(session, agencyId, clientId);
  attributionPass();
  await enterWorkspace(page, owner);

  await test.step('credit names the campaign the lead came through, under the client default model', async () => {
    await page.goto(`/agencies/${agencyId}/clients/${clientId}/attribution`);
    await expect(page.getByRole('heading', { name: 'Attribution', level: 1 })).toBeVisible();
    // The lead is today's: the range is asked for up to today, which is said to be provisional.
    await page.locator('main .a-range .c-select').click();
    await page.getByRole('option', { name: 'Last 30 days, up to today' }).click();
    await expect(page).toHaveURL(new RegExp(`to=${new Date().toISOString().slice(0, 10)}`));
    await expect(page.getByText(/Today is not over/)).toBeVisible();
    await expect(page.getByText('30-day window. Linear is the default for this client.')).toBeVisible();
    const credit = page.getByRole('region', { name: 'Credit by campaign' });
    const row = credit.getByRole('row').filter({ hasText: 'ramadan-2026' });
    await expect(row).toContainText('A Connect campaign');
    await expect(row.locator('td').first()).toHaveText('1');
    await expect(card(page, 'The models side by side').getByRole('rowheader')).toHaveCount(3);
  });

  await test.step('another model is kept in the address', async () => {
    await page.getByRole('button', { name: /^Linear/ }).click();
    await page.getByRole('option', { name: /First click/ }).click();
    await expect(page).toHaveURL(/model=/);
    await expect(page.getByRole('region', { name: 'Credit by campaign' }).getByRole('row').filter({ hasText: 'ramadan-2026' })).toBeVisible();
  });

  await test.step('the funnel counts the visit through the link and the lead, each on its own basis', async () => {
    await page.getByRole('tab', { name: 'Funnel' }).click();
    await expect(page).toHaveURL(/tab=funnel/);
    const row = page.getByRole('region', { name: 'Steps by campaign' }).getByRole('row').filter({ hasText: 'ramadan-2026' });
    await expect(row.locator('td').nth(0)).toHaveText('1');
    await expect(row.locator('td').nth(1)).toHaveText('1');
    await expect(card(page, 'How the steps are counted')).toContainText('By the day the page view was received, in UTC');
  });

  await test.step('the return on ad spend names the campaigns of the account, and the lead it did not match', async () => {
    await page.getByRole('tab', { name: 'Return on ad spend' }).click();
    await expect(page).toHaveURL(/tab=roas/);
    await expect(page.getByRole('rowheader').filter({ hasText: 'Ramadan offers' })).toContainText('1201');
    const unmatched = card(page, 'Not matched to this account');
    await expect(unmatched.locator('.a-figures__item').filter({ hasText: 'Leads' }).locator('dd')).toHaveText('1');
  });
});
