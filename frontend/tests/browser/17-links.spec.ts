import { expect, test, type Page } from '@playwright/test';

import { newPerson, registered, signedInBrowser, withAgency } from './support/people.ts';
import { stack } from './support/stack.ts';
import { withClient } from './support/tenants.ts';

// Links are made of a destination site, a campaign and a UTM template, and are followed through
// the API's own short address on the disposable stack. Domain checks are off there.

const rowWith = (page: Page, text: string) => page.getByRole('row').filter({ hasText: text });

async function openRowMenu(page: Page, text: string, label = `Actions for ${text}`): Promise<void> {
  await rowWith(page, text).getByRole('button', { name: label }).click();
}

test('an owner adds a site, a campaign and a template, issues a link and follows it', async ({ page, context }, testInfo) => {
  const owner = await registered(newPerson(testInfo));
  const agencyId = await withAgency(owner, 'Lumen Studio');
  const clientId = await withClient(owner, agencyId, 'Olive & Thyme');
  await signedInBrowser(context, owner);
  const links = `/agencies/${agencyId}/clients/${clientId}/links`;
  const slug = `ramadan-${Date.now().toString(36)}`;
  const short = `${stack.apiOrigin}/r/${slug}`;

  await page.goto(links);
  await expect(page.getByRole('heading', { name: 'No links yet' })).toBeVisible();

  await test.step('a link needs a destination site first, and the panel leads there', async () => {
    await page.getByRole('button', { name: 'Create link' }).click();
    await expect(page.getByText('No destination site yet')).toBeVisible();
    await page.getByRole('button', { name: 'Go to destination sites' }).click();
    await expect(page).toHaveURL(/\?tab=sites$/);
    await expect(page.getByRole('tab', { name: 'Destination sites', selected: true })).toBeVisible();
  });

  await test.step('the site is written the way the API stores it', async () => {
    await page.getByRole('button', { name: 'New site' }).click();
    const dialog = page.getByRole('dialog', { name: 'New site' });
    await dialog.getByLabel('Site').fill('https://Shop.Olive.example/');
    await dialog.getByLabel('Query names to keep').fill('lang');
    await dialog.getByRole('button', { name: 'Add site' }).click();
    await expect(dialog).toBeHidden();
    await expect(rowWith(page, 'shop.olive.example').getByText('lang', { exact: true })).toBeVisible();
  });

  await test.step('a campaign and a template', async () => {
    await page.getByRole('tab', { name: 'Campaigns' }).click();
    await page.getByRole('button', { name: 'New campaign' }).click();
    const campaign = page.getByRole('dialog', { name: 'New campaign' });
    await campaign.getByLabel('Code').fill('ramadan-2026');
    await campaign.getByLabel('Name').fill('Ramadan 2026');
    await campaign.getByRole('button', { name: 'Create campaign' }).click();
    await expect(rowWith(page, 'Ramadan 2026').getByText('ramadan-2026')).toBeVisible();

    await page.getByRole('tab', { name: 'UTM templates' }).click();
    await page.getByRole('button', { name: 'New template' }).click();
    const template = page.getByRole('dialog', { name: 'New template' });
    await template.getByLabel('Name').fill('Instagram, unpaid');
    await template.getByLabel('utm_source').fill('instagram');
    await template.getByLabel('utm_medium').fill('social');
    await template.getByRole('button', { name: 'Create template' }).click();
    await expect(rowWith(page, 'Instagram, unpaid').getByText('utm_source=instagram')).toBeVisible();
  });

  let target = '';
  await test.step('the link is checked before it is sent, then shows the address the API issued', async () => {
    await page.getByRole('tab', { name: 'Links' }).click();
    await page.getByRole('button', { name: 'Create link' }).click();
    const panel = page.getByRole('form', { name: 'New link' });
    await panel.getByLabel('Destination').fill('https://elsewhere.example/page');
    await panel.getByLabel('Short path').fill('api');
    await panel.getByRole('button', { name: 'Create link' }).click();
    await expect(panel.getByText("The address must be on one of this client's destination sites.")).toBeVisible();
    await expect(panel.getByText('This word is kept for Connect itself. Choose another path.')).toBeVisible();

    await panel.getByLabel('Destination').fill('https://shop.olive.example/ramadan-box?lang=ar');
    await panel.getByLabel('Short path').fill(slug);
    await expect(panel.getByText(`The short address: ${short.replace('http://', '')}`)).toBeVisible();
    await panel.getByRole('button', { name: /Campaign/ }).click();
    await page.getByRole('option', { name: /Ramadan 2026/ }).click();
    await panel.getByRole('button', { name: /UTM template/ }).click();
    await page.getByRole('option', { name: /Instagram, unpaid/ }).click();
    await panel.getByRole('button', { name: 'Create link' }).click();

    const done = page.getByRole('region', { name: 'Link created' });
    await expect(done.getByRole('textbox', { name: 'Short address' })).toHaveValue(short);
    target = await done.getByRole('textbox', { name: 'Address visitors arrive at' }).inputValue();
    expect(target).toMatch(/^https:\/\/shop\.olive\.example\/ramadan-box\?lang=ar&utm_id=ramadan-2026&utm_medium=social&utm_source=instagram&ts_link=[0-9a-f-]{36}$/);
    await done.getByRole('button', { name: 'Done' }).click();
    const row = rowWith(page, short.replace('http://', ''));
    await expect(row.getByText('Ramadan 2026')).toBeVisible();
    await expect(row.getByText('Never')).toBeVisible();
  });

  await test.step('the short address leads to that address', async () => {
    const answer = await fetch(short, { redirect: 'manual' });
    expect(answer.status).toBe(302);
    expect(answer.headers.get('location')).toBe(target);
  });

  await test.step('paused, the short address is refused, and resumed it works again', async () => {
    await openRowMenu(page, short.replace('http://', ''));
    await page.getByRole('menuitem', { name: 'Pause link' }).click();
    await page.getByRole('alertdialog', { name: 'Pause this link?' }).getByRole('button', { name: 'Pause link' }).click();
    await expect(page.getByText('No active links.')).toBeVisible();
    expect((await fetch(short, { redirect: 'manual' })).status).toBe(404);

    await page.getByRole('group', { name: 'State' }).getByRole('button', { name: 'Paused' }).click();
    await openRowMenu(page, short.replace('http://', ''));
    await page.getByRole('menuitem', { name: 'Resume' }).click();
    await expect(page.getByText('No paused links.')).toBeVisible();
    expect((await fetch(short, { redirect: 'manual' })).status).toBe(302);
  });

  await test.step('a custom domain shows its DNS record once, and cannot be checked on this server', async () => {
    const host = `go-${Date.now().toString(36)}.olive.example`;
    await page.getByRole('tab', { name: 'Domains' }).click();
    await page.getByRole('button', { name: 'New domain' }).click();
    const claim = page.getByRole('dialog', { name: 'New domain' });
    await claim.getByLabel('Domain').fill(host);
    await claim.getByRole('button', { name: 'Add domain' }).click();
    await expect(rowWith(page, host).getByText('Not verified')).toBeVisible();

    await openRowMenu(page, host);
    await page.getByRole('menuitem', { name: 'Get the DNS record' }).click();
    const record = page.getByRole('dialog', { name: `DNS record for ${host}` });
    await expect(record.getByRole('textbox', { name: 'TXT record name' })).toHaveValue(`_tracking-verification.${host}`);
    const value = await record.getByRole('textbox', { name: 'Record value' }).inputValue();
    expect(value).toMatch(/^tracking-verification=[A-Za-z0-9_-]{43}$/);
    await record.getByRole('button', { name: 'I have copied it' }).click();
    await expect(record).toBeHidden();
    expect(await page.content()).not.toContain(value);
    await expect(rowWith(page, host).getByText('Waiting for DNS')).toBeVisible();

    await openRowMenu(page, host);
    await page.getByRole('menuitem', { name: 'Check now' }).click();
    await expect(page.getByText('Domain checks are not available on this server, so the domain cannot be verified here.')).toBeVisible();
  });

  await test.step('a reload keeps the tab', async () => {
    await page.reload();
    await expect(page.getByRole('tab', { name: 'Domains', selected: true })).toBeVisible();
  });
});
