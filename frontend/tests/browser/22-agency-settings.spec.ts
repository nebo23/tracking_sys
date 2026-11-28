import { crc32, deflateSync } from 'node:zlib';

import { expect, test } from '@playwright/test';

import { linkIn } from './support/mail.ts';
import { newPerson, recordRequests, registered, send, signedIn, signedInBrowser, withAgency } from './support/people.ts';
import { stack } from './support/stack.ts';
import { acceptInvitation, inviteAs, withClient } from './support/tenants.ts';

// Agency settings (018-F; D7 and D8 of the completion entry review) on the real API: the plan and
// its use, the branding profile with a PNG logo, and closing the agency, then keeping it.

/** A small PNG that the API accepts: the signature, IHDR, one IDAT of plain rows, and IEND. */
function png(width: number, height: number): Buffer {
  const chunk = (type: string, data: Buffer) => {
    const length = Buffer.alloc(4);
    length.writeUInt32BE(data.length);
    const body = Buffer.concat([Buffer.from(type, 'ascii'), data]);
    const check = Buffer.alloc(4);
    check.writeUInt32BE(crc32(body));
    return Buffer.concat([length, body, check]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8; // bits per sample
  header[9] = 2; // truecolor; compression, filter and interlace stay 0
  const row = Buffer.concat([Buffer.from([0]), Buffer.alloc(width * 3, 0x7b)]);
  const pixels = deflateSync(Buffer.concat(Array.from({ length: height }, () => row)));
  const signature = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  return Buffer.concat([signature, chunk('IHDR', header), chunk('IDAT', pixels), chunk('IEND', Buffer.alloc(0))]);
}

test('an owner reads the plan, brands the agency, and closes it, then keeps it', async ({ page, context, browser }, testInfo) => {
  const owner = await registered(newPerson(testInfo));
  const admin = await registered(newPerson(testInfo, 'Nour Adel'));
  const agencyId = await withAgency(owner, 'Lumen Studio');
  // One sign-in for the whole preparation: the API limits how often an account signs in.
  const session = await signedIn(owner);
  await withClient(session, agencyId, 'Olive & Thyme');
  await inviteAs(session, agencyId, admin.email, 'admin');
  await send('POST /auth/logout', undefined, session);
  await acceptInvitation(admin, linkIn(admin.email, 'Agency invitation').split('#token=')[1] ?? '');

  await signedInBrowser(context, owner);
  const theirs = await browser.newContext({ baseURL: stack.webOrigin });
  await signedInBrowser(theirs, admin);
  const visit = await theirs.newPage();
  const requests = recordRequests(page);
  const logoUploads = () => requests.filter((request) => request.startsWith('PUT ') && request.endsWith('/branding/logo'));

  await page.goto('/');
  await page.getByRole('link', { name: 'Agency settings' }).click();
  await expect(page.getByRole('heading', { name: 'Agency settings', level: 1 })).toBeFocused();

  await test.step('the plan shows each limit with its use, and the tracked events of the month', async () => {
    await expect(page.getByRole('tab', { name: 'Plan and usage' })).toHaveAttribute('aria-selected', 'true');
    const limit = (name: string) => page.getByRole('row', { name: new RegExp(`^${name}`) });
    await expect(limit('Clients')).toContainText('1 of 5');
    // The owner and the admin who accepted.
    await expect(limit('Seats')).toContainText('2 of 10');
    await expect(limit('Connections')).toContainText('0 of 10');
    await expect(limit('Managed links')).toContainText('0 of 500');
    for (const name of ['Clients', 'Seats', 'Connections', 'Managed links']) await expect(limit(name)).toContainText('Within the plan');
    await expect(page.getByText(/^Tracked events in /)).toContainText('Within the plan');
    await expect(page.getByText('of 100,000')).toBeVisible();
  });

  await test.step('the branding profile is saved, then a PNG logo; an SVG is refused before it is sent', async () => {
    await page.getByRole('tab', { name: 'Branding' }).click();
    await expect(page).toHaveURL(/tab=branding/);
    // The API keeps a logo only with a saved profile.
    await expect(page.getByText('Save the display name and the color first; then you can add a logo.')).toBeVisible();
    await page.getByLabel('Display name').fill('  Lumen  ');
    await page.getByLabel('Accent color as #RRGGBB').fill('#1f6feb');
    await page.getByRole('button', { name: 'Save the profile' }).click();
    await expect(page.getByText('The branding profile is saved.')).toBeVisible();
    // What the API kept: the trimmed name and the color in upper case.
    await expect(page.getByLabel('Display name')).toHaveValue('Lumen');
    await expect(page.getByLabel('Accent color as #RRGGBB')).toHaveValue('#1F6FEB');

    await expect(page.getByText('No logo yet.')).toBeVisible();
    const picker = page.getByLabel('Upload a PNG logo');
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>';
    await picker.setInputFiles({ name: 'logo.svg', mimeType: 'image/svg+xml', buffer: Buffer.from(svg) });
    await expect(page.getByText('Choose a PNG file. SVG and other kinds of file are refused.')).toBeVisible();
    expect(logoUploads()).toHaveLength(0);

    await picker.setInputFiles({ name: 'logo.png', mimeType: 'image/png', buffer: png(48, 32) });
    await expect(page.getByText('A PNG of 48 by 32 pixels, 1 KiB.')).toBeVisible();
    expect(logoUploads()).toHaveLength(1);
    // The preview draws the profile and the logo the API keeps, on this page only (D8).
    const preview = page.locator('.a-brand-preview');
    await expect(preview).toContainText('Lumen');
    await expect.poll(() => preview.locator('img').evaluate((image: HTMLImageElement) => image.naturalWidth)).toBe(48);

    await page.getByRole('button', { name: 'Remove the logo' }).click();
    await expect(page.getByText('No logo yet.')).toBeVisible();
    await expect(preview.locator('img')).toHaveCount(0);
  });

  await test.step('an admin edits the branding but has no way to close the agency', async () => {
    await visit.goto(`/agencies/${agencyId}/settings?tab=closure`);
    await expect(visit.getByRole('heading', { name: 'Agency settings', level: 1 })).toBeVisible();
    await expect(visit.getByRole('tab')).toHaveText(['Plan and usage', 'Branding']);
    await expect(visit.getByRole('tab', { name: 'Plan and usage' })).toHaveAttribute('aria-selected', 'true');
    await visit.getByRole('tab', { name: 'Branding' }).click();
    await expect(visit.getByLabel('Display name')).toHaveValue('Lumen');
    await expect(visit.getByRole('button', { name: 'Save the profile' })).toBeVisible();
  });

  await test.step('closing needs the exact name and the password', async () => {
    await page.getByRole('tab', { name: 'Close the agency' }).click();
    await page.getByRole('button', { name: 'Close Lumen Studio' }).click();
    const dialog = page.getByRole('alertdialog', { name: 'Close Lumen Studio?' });
    await dialog.getByLabel("Type the agency's name").fill('lumen studio');
    await dialog.getByRole('button', { name: 'Close the agency' }).click();
    await expect(dialog.getByText("Type the agency's name exactly as it is written.")).toBeVisible();

    await dialog.getByLabel("Type the agency's name").fill('Lumen Studio');
    await dialog.getByLabel('Your password', { exact: true }).fill('not the password');
    await dialog.getByRole('button', { name: 'Close the agency' }).click();
    await expect(dialog.getByRole('alert')).toContainText('The password is not correct.');

    await dialog.getByLabel('Your password', { exact: true }).fill(owner.password);
    await dialog.getByRole('button', { name: 'Close the agency' }).click();
    await expect(page).toHaveURL(new RegExp(`/agencies/${agencyId}/closing$`));
    await expect(page.getByRole('heading', { name: 'Lumen Studio is closing', level: 1 })).toBeVisible();
    await expect(page.getByText(/The agency closes for good on/)).toBeVisible();
  });

  await test.step('while it closes, only its owner sees the agency, and its pages lead to the closing page', async () => {
    // The admin's list of agencies no longer has it, so they are asked to create one.
    await visit.goto('/');
    await expect(visit.getByRole('heading', { name: 'Create your agency', level: 1 })).toBeVisible();
    await page.goto(`/agencies/${agencyId}/clients`);
    await expect(page).toHaveURL(new RegExp(`/agencies/${agencyId}/closing$`));
    // A fresh page has no name to show: the API no longer answers for the agency itself.
    await expect(page.getByRole('heading', { name: 'This agency is closing', level: 1 })).toBeVisible();
  });

  await test.step('the owner keeps the agency, and the admin sees it again', async () => {
    await page.getByRole('button', { name: 'Keep the agency' }).click();
    await expect(page.getByRole('heading', { name: 'Clients', level: 1 })).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`/agencies/${agencyId}/clients$`));
    await visit.goto('/');
    await expect(visit.getByRole('heading', { name: 'Clients', level: 1 })).toBeVisible();
    await expect(visit.getByRole('row', { name: /Olive & Thyme/ })).toBeVisible();
  });

  await theirs.close();
});
