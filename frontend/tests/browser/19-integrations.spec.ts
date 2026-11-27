import { randomBytes } from 'node:crypto';

import { expect, test, type Page } from '@playwright/test';

import { bookingCreated, dealStage, signedPost } from './support/collect.ts';
import { newPerson, registered, signedInBrowser, withAgency } from './support/people.ts';
import { stack } from './support/stack.ts';
import { answerAtProvider, standInDataset, withClient } from './support/tenants.ts';

// The integrations are switched on in the disposable stack. Nothing calls Paymob, Cal.com or Meta:
// the journey signs its own synthetic callbacks with the secrets this run issues, and the Meta
// dataset belongs to the stand-in provider, which contacts nobody.

const rowWith = (page: Page, text: string) => page.getByRole('row').filter({ hasText: text });
const figure = (page: Page, region: string, label: string) =>
  page.getByRole('region', { name: region }).locator('.a-figures__item').filter({ has: page.getByText(label, { exact: true }) }).locator('dd');

test('an owner sets up payments, bookings, a CRM, WhatsApp and a Meta dataset', async ({ page, context }, testInfo) => {
  const owner = await registered(newPerson(testInfo));
  const agencyId = await withAgency(owner, 'Lumen Studio');
  const clientId = await withClient(owner, agencyId, 'Olive & Thyme');
  await signedInBrowser(context, owner);
  const integrations = `/agencies/${agencyId}/clients/${clientId}/integrations`;
  await page.goto(integrations);
  await expect(page.getByRole('heading', { name: 'No Paymob source yet' })).toBeVisible();

  await test.step('a Paymob source with its live integrations and a write-only secret', async () => {
    const hmac = randomBytes(24).toString('hex');
    await page.getByRole('button', { name: 'Add Paymob source' }).click();
    const dialog = page.getByRole('dialog', { name: 'Add Paymob source' });
    await dialog.getByLabel('Name').fill('Online shop');
    await dialog.getByLabel('HMAC secret').fill(hmac);
    await dialog.getByLabel('Live integration IDs').fill('4567890, 4567891');
    await dialog.getByRole('button', { name: 'Add source' }).click();
    const card = page.getByRole('article', { name: 'Online shop' });
    await expect(card.getByText('Egypt · 2 live integrations')).toBeVisible();
    await expect(card.getByRole('textbox', { name: 'Callback address' })).toHaveValue(new RegExp(`^${stack.apiOrigin}/payments/paymob/callback/ppk_`));
    expect(await page.content()).not.toContain(hmac);
  });

  let secret = '';
  let callback = '';
  await test.step('a signed webhook source shows its secret once, and a booking it delivers is counted', async () => {
    await page.getByRole('tab', { name: 'Bookings and CRM' }).click();
    await page.getByRole('button', { name: 'Add source' }).click();
    const dialog = page.getByRole('dialog', { name: 'Add source' });
    await dialog.getByRole('radio', { name: /Signed webhook/ }).check();
    await dialog.getByLabel('Name').fill('Booking tool');
    await dialog.getByRole('button', { name: 'Add source' }).click();
    const shown = page.getByRole('dialog', { name: 'Signing secret of Booking tool' });
    secret = await shown.getByRole('textbox', { name: 'Signing secret' }).inputValue();
    callback = await shown.getByRole('textbox', { name: 'Callback address' }).inputValue();
    expect(callback).toMatch(new RegExp(`^${stack.apiOrigin}/integrations/webhook/isk_`));
    await shown.getByRole('button', { name: 'I have copied it' }).click();
    await expect(shown).toBeHidden();

    const delivered = await signedPost(callback, secret, bookingCreated(`booking-${Date.now()}`));
    expect(delivered.status).toBe(200);
    expect((await signedPost(callback, `${secret}x`, bookingCreated('booking-forged'))).status).toBe(401);
    await page.reload();
    await expect(figure(page, 'Bookings', 'Scheduled')).toHaveText('1');
    await expect(figure(page, 'Bookings', 'Linked to a visitor')).toHaveText('0');
  });

  await test.step('a CRM stage makes a deal won, still without a matching payment', async () => {
    await page.getByRole('button', { name: 'Add stage rule' }).click();
    const dialog = page.getByRole('dialog', { name: 'Add stage rule' });
    await dialog.getByLabel('Pipeline', { exact: true }).fill('Sales');
    await dialog.getByLabel('Stage', { exact: true }).fill('Closed won');
    await dialog.getByRole('button', { name: 'Add rule' }).click();
    await expect(rowWith(page, 'Closed won').getByText('Won', { exact: true })).toBeVisible();

    expect((await signedPost(callback, secret, dealStage(`deal-${Date.now()}`, 'Sales', 'Closed won'))).status).toBe(200);
    await page.reload();
    await expect(figure(page, 'CRM stages', 'Won, payment not matched')).toHaveText('1');
    await expect(figure(page, 'CRM stages', 'Won and paid')).toHaveText('0');
  });

  await test.step('a WhatsApp number waits for the Connect operator', async () => {
    await page.getByRole('tab', { name: 'WhatsApp' }).click();
    await page.getByRole('button', { name: 'Register number' }).click();
    const dialog = page.getByRole('dialog', { name: 'Register number' });
    await dialog.getByLabel('Phone number ID').fill(`1065${String(Date.now()).slice(-10)}`);
    await dialog.getByLabel('Name').fill('Orders line');
    await dialog.getByRole('button', { name: 'Register' }).click();
    await expect(rowWith(page, 'Orders line').getByText('Waiting for verification')).toBeVisible();
    await rowWith(page, 'Orders line').getByRole('button', { name: 'Actions for Orders line' }).click();
    await expect(page.getByRole('menuitem')).toHaveText(['Rename']);
    await page.keyboard.press('Escape');
  });

  await test.step('a Meta dataset is connected, and its destination starts off', async () => {
    const dataset = standInDataset('Olive pixel');
    await page.getByRole('tab', { name: 'Meta conversions' }).click();
    await expect(page.getByRole('heading', { name: 'No destination yet' })).toBeVisible();
    await answerAtProvider(page, dataset);
    await page.getByRole('button', { name: 'Connect a dataset' }).click();
    const dialog = page.getByRole('dialog', { name: 'Connect an account' });
    await dialog.getByRole('radio', { name: /Sample Meta conversions/ }).check();
    await dialog.getByLabel('Dataset ID').fill(dataset.account);
    await dialog.getByRole('button', { name: 'Continue to the provider' }).click();

    // The page left for the provider and came back here. The stand-in provider's approval runs a
    // Python process of its own, which can take a while on a busy machine.
    await expect(page.getByText('Add a destination for the dataset to start sending its conversions.')).toBeVisible({ timeout: 45_000 });
    await expect(page).toHaveURL(new RegExp(`${integrations}\\?tab=conversions$`));
    await page.getByRole('button', { name: 'Add destination' }).click();
    const add = page.getByRole('dialog', { name: 'Add destination' });
    await expect(add.getByRole('textbox', { name: 'Event name' })).toHaveValue('Purchase');
    await add.getByRole('button', { name: 'Add destination' }).click();
    const row = rowWith(page, 'Olive pixel');
    await expect(row.getByText('Off', { exact: true })).toBeVisible();
    await row.getByRole('button', { name: 'Actions for Olive pixel' }).click();
    await page.getByRole('menuitem', { name: 'Turn on' }).click();
    await expect(row.getByText('Sending', { exact: true })).toBeVisible();
    await expect(page.getByText('Nothing was sent yet.')).toBeVisible();
  });
});
