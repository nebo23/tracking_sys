import { expect, test } from '@playwright/test';

import { linkIn } from './support/mail.ts';
import { newPerson, registered, signedInBrowser, withAgency } from './support/people.ts';
import { acceptInvitation, inviteAs, withClient } from './support/tenants.ts';

test('an owner adds, opens, renames and finds clients', async ({ page, context }, testInfo) => {
  const owner = await registered(newPerson(testInfo));
  const agencyId = await withAgency(owner, 'Lumen Studio');
  await signedInBrowser(context, owner);
  const clients = `/agencies/${agencyId}/clients`;
  const row = (name: string) => page.getByRole('row', { name: new RegExp(name) });

  await test.step('an agency without clients says so and offers the first one', async () => {
    await page.goto('/');
    await expect(page).toHaveURL(new RegExp(`${clients}$`));
    await expect(page.getByRole('heading', { name: 'No clients yet' })).toBeVisible();
  });

  await test.step('a client needs a name, and the new client opens ready for its first connection', async () => {
    await page.getByRole('button', { name: 'Add client' }).click();
    const dialog = page.getByRole('dialog', { name: 'Add a client' });
    await expect(dialog.getByLabel('Client name')).toBeFocused();
    await dialog.getByRole('button', { name: 'Add client' }).click();
    await expect(dialog.getByText('This field is needed.')).toBeVisible();

    await dialog.getByLabel('Client name').fill('Olive & Thyme');
    await dialog.getByRole('button', { name: 'Add client' }).click();
    await expect(page.getByRole('heading', { name: 'Connections', level: 1 })).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`${clients}/[0-9a-f-]{36}/connections$`));
    await expect(page.getByRole('heading', { name: 'Connect the first account' })).toBeVisible();
    await expect(page).toHaveTitle('Connections · Connect');
  });

  const oliveAddress = page.url();

  await test.step('the breadcrumb leads back to the agency, where the client is listed', async () => {
    const crumbs = page.getByRole('navigation', { name: 'Breadcrumb' });
    await expect(crumbs.getByText('Olive & Thyme')).toBeVisible();
    await crumbs.getByRole('link', { name: 'Lumen Studio' }).click();
    await expect(page.getByRole('heading', { name: 'Clients', level: 1 })).toBeFocused();
    await expect(row('Olive & Thyme').getByText('Connect the first account')).toBeVisible();
    await expect(row('Olive & Thyme').getByText('None yet')).toBeVisible();
    await expect(page.getByText('1 client', { exact: true })).toBeVisible();
  });

  await test.step('a second client, and the switcher moves between them', async () => {
    await page.getByRole('button', { name: 'Add client' }).click();
    await page.getByRole('dialog').getByLabel('Client name').fill('Cedar Fitness');
    await page.getByRole('dialog').getByRole('button', { name: 'Add client' }).click();
    await expect(page.getByRole('heading', { name: 'Connections', level: 1 })).toBeVisible();

    const switcher = page.getByRole('complementary').getByRole('button', { name: /Switch client or agency/ });
    await expect(switcher).toContainText('Cedar Fitness');
    await switcher.click();
    const menu = page.getByRole('menu');
    await expect(menu.getByRole('menuitemradio', { name: 'Cedar Fitness' })).toHaveAttribute('aria-checked', 'true');
    await menu.getByRole('menuitemradio', { name: 'Olive & Thyme' }).click();
    // A client opens on its overview (018-C).
    await expect(page).toHaveURL(oliveAddress.replace(/\/connections$/, ''));
    await expect(page.getByRole('heading', { name: 'Overview', level: 1 })).toBeVisible();
    await expect(switcher).toContainText('Olive & Thyme');

    await switcher.click();
    await page.getByRole('menuitemradio', { name: 'All clients' }).click();
    await expect(page.getByRole('heading', { name: 'Clients', level: 1 })).toBeVisible();
    await expect(page.getByText('2 clients', { exact: true })).toBeVisible();
  });

  await test.step('a client is renamed, and the list is searched', async () => {
    await page.getByRole('button', { name: 'Actions for Cedar Fitness' }).click();
    await page.getByRole('menuitem', { name: 'Rename' }).click();
    const dialog = page.getByRole('dialog', { name: 'Rename Cedar Fitness' });
    await expect(dialog.getByLabel('Client name')).toHaveValue('Cedar Fitness');
    await dialog.getByLabel('Client name').fill('Cedar Gyms');
    await dialog.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText('The client is now called Cedar Gyms.')).toBeVisible();
    await expect(row('Cedar Gyms')).toBeVisible();

    await page.getByRole('searchbox', { name: 'Search clients' }).fill('olive');
    await expect(page.getByText('1 of 2 clients')).toBeVisible();
    await expect(row('Cedar Gyms')).toBeHidden();
  });

  await test.step('a reload stays on the page the address names', async () => {
    await page.goto(oliveAddress);
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Connections', level: 1 })).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Breadcrumb' }).getByText('Olive & Thyme')).toBeVisible();
  });
});

test('an address is not permission', async ({ page, context }, testInfo) => {
  const owner = await registered(newPerson(testInfo));
  const agencyId = await withAgency(owner, 'Lumen Studio');
  const other = await registered(newPerson(testInfo, 'Karim Adel'));
  const otherAgency = await withAgency(other, 'Northlight Media');
  const foreignClient = await withClient(other, otherAgency, 'Sahara Books');
  await signedInBrowser(context, owner);

  for (const address of [
    `/agencies/${otherAgency}/clients`,
    `/agencies/${otherAgency}/clients/${foreignClient}/connections`,
    `/agencies/${agencyId}/clients/${foreignClient}/connections`,
    `/agencies/${otherAgency}/team`,
  ]) {
    await page.goto(address);
    await expect(page.getByRole('heading', { name: 'Page not found', level: 1 }), address).toBeVisible();
    await expect(page.getByText('Sahara Books')).toHaveCount(0);
    await expect(page.getByText('Northlight Media')).toHaveCount(0);
  }
  // The person's own agency is still the one they work in.
  await page.getByRole('link', { name: 'Go to your clients' }).click();
  await expect(page).toHaveURL(new RegExp(`/agencies/${agencyId}/clients$`));
});

test('an analyst sees only the client they were given, and manages nothing', async ({ page, context }, testInfo) => {
  const owner = await registered(newPerson(testInfo));
  const agencyId = await withAgency(owner, 'Lumen Studio');
  const granted = await withClient(owner, agencyId, 'Olive & Thyme');
  const withheld = await withClient(owner, agencyId, 'Cedar Fitness');
  const analyst = await registered(newPerson(testInfo, 'Youssef Salah'));
  await inviteAs(owner, agencyId, analyst.email, 'analyst', [{ client_id: granted }]);
  await acceptInvitation(analyst, linkIn(analyst.email, 'Agency invitation').split('#token=')[1] ?? '');
  await signedInBrowser(context, analyst);

  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Clients', level: 1 })).toBeVisible();
  await expect(page.getByRole('row', { name: /Olive & Thyme/ })).toBeVisible();
  await expect(page.getByText('Cedar Fitness')).toHaveCount(0);
  await expect(page.getByText('Clients you can open')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Add client' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /Rename/ })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Team and access' })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'API keys' })).toHaveCount(0);

  // The granted client opens, read only.
  await page.getByRole('link', { name: 'Open: Olive & Thyme' }).click();
  await expect(page.getByRole('heading', { name: 'Overview', level: 1 })).toBeVisible();
  await page.getByRole('complementary').getByRole('link', { name: 'Connections' }).click();
  await expect(page.getByRole('heading', { name: 'Connections', level: 1 })).toBeVisible();
  await expect(page.getByText('No account is connected for Olive & Thyme yet.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Connect account' })).toHaveCount(0);

  // What was not given does not exist for them, whatever the address says.
  for (const address of [`/agencies/${agencyId}/clients/${withheld}/connections`, `/agencies/${agencyId}/team`, `/agencies/${agencyId}/keys`]) {
    await page.goto(address);
    await expect(page.getByRole('heading', { name: 'Page not found', level: 1 }), address).toBeVisible();
  }
});
