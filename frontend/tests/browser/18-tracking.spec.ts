import { createHash } from 'node:crypto';

import { expect, test, type Page } from '@playwright/test';

import { grantConsent, sendPageView, signedPost } from './support/collect.ts';
import { newPerson, registered, signedInBrowser, withAgency } from './support/people.ts';
import { stack } from './support/stack.ts';
import { withClient } from './support/tenants.ts';

// A synthetic website and a synthetic server send to the disposable collector. Nothing here is a
// real visitor: the consent and the events are made up by the journey.

const site = 'https://shop.olive.example';
const notice = 'We count visits to this shop with your consent. You can change your choice at any time.';
const rowWith = (page: Page, text: string) => page.getByRole('row').filter({ hasText: text });

test('an owner sets up website tracking, sees what arrived and erases a visitor', async ({ page, context }, testInfo) => {
  const owner = await registered(newPerson(testInfo));
  const agencyId = await withAgency(owner, 'Lumen Studio');
  const clientId = await withClient(owner, agencyId, 'Olive & Thyme');
  await signedInBrowser(context, owner);
  await page.goto(`/agencies/${agencyId}/clients/${clientId}/tracking`);
  await expect(page.getByRole('heading', { name: 'Nothing sends events yet' })).toBeVisible();

  let publicKey = '';
  await test.step('a website source for its exact site, with the fingerprint of its notice', async () => {
    await page.getByRole('button', { name: 'New source' }).click();
    const dialog = page.getByRole('dialog', { name: 'New source' });
    await dialog.getByLabel('Name').fill('Main website');
    await dialog.getByLabel('Sites').fill('https://SHOP.olive.example/');
    await dialog.getByLabel('Consent notice').fill(notice);
    await expect(dialog.getByText(createHash('sha256').update(notice, 'utf8').digest('hex'))).toBeVisible();
    await dialog.getByRole('button', { name: 'Create source' }).click();

    const install = page.getByRole('dialog', { name: 'Install the tracker for Main website' });
    publicKey = await install.getByRole('textbox', { name: 'Public key' }).inputValue();
    expect(publicKey).toMatch(/^pk_[A-Za-z0-9_-]{43}$/);
    const code = await install.getByRole('textbox', { name: 'Code for the page' }).inputValue();
    expect(code).toContain(`collector: "${stack.apiOrigin}"`);
    expect(code).toContain(`publicKey: "${publicKey}"`);
    await install.getByRole('button', { name: 'Done' }).click();
    await expect(rowWith(page, 'Main website').getByText('shop.olive.example')).toBeVisible();
  });

  let secret = '';
  let webhookAddress = '';
  await test.step('a webhook source shows its signing secret once', async () => {
    await page.getByRole('button', { name: 'New source' }).click();
    const dialog = page.getByRole('dialog', { name: 'New source' });
    await dialog.getByRole('radio', { name: /Server webhook/ }).check();
    await dialog.getByLabel('Name').fill('Order server');
    await dialog.getByRole('button', { name: 'Create source' }).click();
    const shown = page.getByRole('dialog', { name: 'Signing secret of Order server' });
    secret = await shown.getByRole('textbox', { name: 'Signing secret' }).inputValue();
    webhookAddress = await shown.getByRole('textbox', { name: 'Webhook address' }).inputValue();
    expect(secret).toMatch(/^whsec_/);
    expect(webhookAddress).toMatch(new RegExp(`^${stack.apiOrigin}/webhooks/v1/[0-9a-f-]{36}/events$`));
    await shown.getByRole('button', { name: 'I have copied it' }).click();
    await expect(shown).toBeHidden();
    expect(await page.content()).not.toContain(secret);
  });

  await test.step('a form is registered field by field', async () => {
    await page.getByRole('button', { name: 'Register form' }).click();
    const dialog = page.getByRole('dialog', { name: 'Register form' });
    await dialog.getByLabel('Form').fill('lead');
    await dialog.getByLabel('Name in the page').fill('plan');
    await dialog.getByLabel('Choices').fill('basic\npro');
    await dialog.getByRole('button', { name: 'Register' }).click();
    await expect(dialog).toBeHidden();
    await expect(rowWith(page, 'lead').getByText('plan', { exact: true })).toBeVisible();
  });

  let token = '';
  await test.step('a visit with consent is kept, and a forged webhook is refused', async () => {
    token = await grantConsent(publicKey, site);
    await sendPageView(publicKey, site, token);
    const forged = await signedPost(webhookAddress, `${secret}-not-it`, { schema_version: 1 });
    expect(forged.status).toBe(401);
    await page.reload();
    const arrived = page.getByRole('region', { name: 'What arrived' });
    // The page view is counted on today's UTC row as a new event the collector kept.
    const viewed = arrived.getByRole('row').filter({ hasText: 'Website' }).filter({ hasText: 'New' });
    await expect(viewed).toBeVisible();
    await expect(viewed.getByRole('cell').last()).toHaveText('1');
    await expect(arrived.locator('.a-figures__item').filter({ hasText: 'Kept' }).locator('dd')).not.toHaveText('0');
  });

  await test.step('the visitor is erased by token, after an alert', async () => {
    await page.getByRole('button', { name: 'Erase a visitor' }).click();
    const dialog = page.getByRole('alertdialog', { name: 'Erase a visitor?' });
    await expect(dialog.getByText(/It cannot be undone/)).toBeVisible();
    await dialog.getByRole('textbox', { name: 'Visitor token' }).fill(token);
    await dialog.getByRole('button', { name: 'Erase visitor' }).click();
    await expect(page.getByText('The visitor was erased. Their token and events are refused from now on.')).toBeVisible();
    const erased = rowWith(page, 'An owner or admin of the agency');
    await expect(erased.getByText('Done', { exact: true })).toBeVisible();
    await expect(erased.getByText(/events/)).toBeVisible();
    // The erased token is refused from now on.
    const again = await fetch(`${stack.apiOrigin}/collect/v1/${publicKey}/consent-state`, {
      method: 'POST',
      headers: { Origin: site, 'Content-Type': 'text/plain' },
      body: JSON.stringify({ subject_token: token }),
    });
    expect(((await again.json()) as { status: string }).status).toBe('unknown');
  });
});
