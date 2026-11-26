import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type TestInfo } from '@playwright/test';

import { newPerson, registered, send, signedIn, signedInBrowser, withAgency } from './support/people.ts';
import { stack } from './support/stack.ts';
import { inviteAs, standInAccount, withClient, withConnection, workerPass } from './support/tenants.ts';

// axe-core on every screen of the slice, in both languages and both themes (D12: WCAG 2.2 AA).
// It finds what a machine can find. Screen readers, real phones and people stay to be checked.

const rules = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

// A token of the right shape that no API ever issued, to draw the screens a mail link opens.
const syntheticToken = 'Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC10b2tlbi0x';

type AxePage = ConstructorParameters<typeof AxeBuilder>[0]['page'];

interface Found {
  screen: string;
  rule: string;
  impact: string;
  where: string;
}

async function findings(page: Page, screen: string): Promise<Found[]> {
  // The checker is typed against its own copy of playwright-core; the page object is the same at run time.
  const { violations } = await new AxeBuilder({ page: page as unknown as AxePage }).withTags(rules).analyze();
  return violations.map((violation) => ({
    screen,
    rule: violation.id,
    impact: violation.impact ?? 'unknown',
    where: violation.nodes.map((node) => node.target.join(' ')).join(' | '),
  }));
}

/** The first heading is drawn once the page has loaded what it needs. */
const ready = (page: Page) => expect(page.locator('h1')).toBeVisible();

// Locators by structure, so the same steps work in both languages.
const submit = (page: Page) => page.locator('main form button[type="submit"]');
const accountMenu = (page: Page) => page.locator('.l-topbar .c-btn--icon');
const switcher = (page: Page) => page.locator('.l-sidebar .c-switcher');
const pageAction = (page: Page) => page.locator('.c-pagehead .c-btn--primary');
const dialog = (page: Page) => page.locator('[role="dialog"], [role="alertdialog"]');
const dialogSubmit = (page: Page) => dialog(page).locator('button[type="submit"]');

/** An agency with two clients, one of them with a connected and synchronized stand-in account, and an invitation. */
async function agencyInUse(testInfo: TestInfo) {
  const owner = await registered(newPerson(testInfo));
  const agencyId = await withAgency(owner, 'Lumen Studio');
  // One sign-in for the whole preparation: the API limits how often an account signs in.
  const session = await signedIn(owner);
  const clientId = await withClient(session, agencyId, 'Olive & Thyme');
  await withClient(session, agencyId, 'Nile Home');
  await withConnection(session, agencyId, clientId, standInAccount('@olive.thyme'));
  workerPass();
  await inviteAs(session, agencyId, newPerson(testInfo, 'Youssef Salah').email, 'analyst', [{ client_id: clientId }]);
  await send('POST /auth/logout', undefined, session);
  return { owner, agencyId, clientId, connections: `/agencies/${agencyId}/clients/${clientId}/connections` };
}

const looks = [
  { language: 'en', theme: 'light' },
  { language: 'en', theme: 'dark' },
  { language: 'ar', theme: 'light' },
  { language: 'ar', theme: 'dark' },
] as const;

async function report(testInfo: TestInfo, found: Found[]): Promise<void> {
  await testInfo.attach('axe-findings.json', { body: JSON.stringify(found, null, 2), contentType: 'application/json' });
  const blocking = found.filter((finding) => finding.impact === 'serious' || finding.impact === 'critical');
  const other = found.length - blocking.length;
  console.log(`[axe] ${testInfo.title}: ${blocking.length} serious or critical, ${other} moderate or minor`);
  for (const finding of found) console.log(`[axe]   ${finding.impact} ${finding.rule} on ${finding.screen}: ${finding.where}`);
  expect(blocking).toEqual([]);
}

for (const look of looks) {
  test.describe(`${look.language}, ${look.theme}`, () => {
    test.beforeEach(async ({ context }) => {
      await context.addInitScript((chosen) => {
        window.localStorage.setItem('connect.language', chosen.language);
        window.localStorage.setItem('connect.theme', chosen.theme);
      }, look);
    });

    test('the screens before sign-in have no serious accessibility finding', async ({ page }, testInfo) => {
      const found: Found[] = [];

      await page.goto('/sign-in');
      await ready(page);
      found.push(...(await findings(page, 'sign-in')));
      await submit(page).click();
      await expect(page.locator('.c-field__error').first()).toBeVisible();
      found.push(...(await findings(page, 'sign-in with errors')));

      await page.goto('/register');
      await ready(page);
      await submit(page).click();
      await expect(page.locator('.c-field__error').first()).toBeVisible();
      found.push(...(await findings(page, 'register with errors')));

      // Each screen with the part that shows it reached the state that is meant.
      for (const [screen, address, shows] of [
        ['verify', '/verify-email', '.c-otp'],
        ['forgot password', '/forgot-password', '#forgot-email'],
        ['reset without token', '/auth/reset-password', '.c-banner'],
        ['reset form', '/auth/reset-password#token=' + syntheticToken, '#reset-password'],
        ['invitation without token', '/auth/accept-invitation', '.c-banner'],
        ['invitation signed out', '/auth/accept-invitation#token=' + syntheticToken, 'main a.c-btn--primary'],
        ['google failure', '/auth/google/complete?error=google_link_required', '.c-banner--danger'],
        ['terms', '/terms', '.c-banner'],
        ['not found', '/nowhere', '.c-empty'],
      ] as const) {
        await page.goto('about:blank');
        await page.goto(address);
        await ready(page);
        await expect(page.locator(shows).first()).toBeVisible();
        found.push(...(await findings(page, screen)));
      }

      // The API cannot be reached: the page says so inside the same frame.
      await page.goto('about:blank');
      await page.route(stack.apiOrigin + '/**', (route) => route.abort());
      await page.goto('/sign-in');
      await expect(page.locator('.c-empty')).toBeVisible();
      found.push(...(await findings(page, 'server unreachable')));
      await page.unroute(stack.apiOrigin + '/**');

      await report(testInfo, found);
    });

    test('the workspace has no serious accessibility finding', async ({ page, context }, testInfo) => {
      const found: Found[] = [];
      const { owner, agencyId, connections } = await agencyInUse(testInfo);
      await signedInBrowser(context, owner);

      await page.goto('/');
      await ready(page);
      // The list is drawn with the state of each client: one connected, one with nothing yet.
      await expect(page.locator('main table .c-badge--success')).toBeVisible();
      found.push(...(await findings(page, 'clients')));

      await accountMenu(page).click();
      await expect(page.getByRole('menu')).toBeVisible();
      found.push(...(await findings(page, 'account menu')));
      await page.keyboard.press('Escape');

      await switcher(page).click();
      await expect(page.getByRole('menu')).toBeVisible();
      found.push(...(await findings(page, 'client and agency menu')));
      await page.keyboard.press('Escape');

      await pageAction(page).click();
      await dialogSubmit(page).click();
      await expect(dialog(page).locator('.c-field__error')).toBeVisible();
      found.push(...(await findings(page, 'add-client dialog with an error')));
      await page.keyboard.press('Escape');
      await expect(dialog(page)).toBeHidden();

      await page.goto(connections);
      await ready(page);
      await expect(page.locator('main .c-coverage')).toBeVisible();
      found.push(...(await findings(page, 'connections')));

      // The dialog with everything a provider may need: here the account holder's approval.
      await pageAction(page).click();
      await dialog(page).locator('input[type="radio"][value="synthetic_youtube"]').check();
      await dialogSubmit(page).click();
      await expect(dialog(page).locator('.c-field__error')).toBeVisible();
      found.push(...(await findings(page, 'connect dialog with an error')));
      await page.keyboard.press('Escape');
      await expect(dialog(page)).toBeHidden();

      await page.locator('main .c-card__footer .c-btn--ghost').click();
      await dialogSubmit(page).click();
      await expect(dialog(page).locator('.c-field__error')).toBeVisible();
      found.push(...(await findings(page, 'disconnect dialog with an error')));
      await page.keyboard.press('Escape');
      await expect(dialog(page)).toBeHidden();

      await page.goto(`/agencies/${agencyId}/team`);
      await ready(page);
      await expect(page.locator('main table')).toBeVisible();
      found.push(...(await findings(page, 'team and access')));
      await pageAction(page).click();
      await dialogSubmit(page).click();
      await expect(dialog(page).locator('.c-field__error').first()).toBeVisible();
      found.push(...(await findings(page, 'invite dialog with errors')));
      await dialog(page).locator('.c-select').click();
      await expect(page.getByRole('listbox')).toBeVisible();
      found.push(...(await findings(page, 'role list')));
      await page.keyboard.press('Escape');
      await page.keyboard.press('Escape');
      await expect(dialog(page)).toBeHidden();

      await page.goto(`/agencies/${agencyId}/keys`);
      await ready(page);
      await expect(page.locator('main .c-empty')).toBeVisible();
      found.push(...(await findings(page, 'keys, none yet')));
      await page.locator('main .c-empty .c-btn--primary').click();
      await dialog(page).locator('#key-name').fill('Reporting sheet');
      await dialog(page).locator('.a-grants input[type="checkbox"]').first().check();
      found.push(...(await findings(page, 'key dialog')));
      await dialogSubmit(page).click();
      await expect(page.locator('#issued-key')).toBeVisible();
      found.push(...(await findings(page, 'key shown once')));
      await dialog(page).locator('.c-dialog__footer .c-btn').click();
      await expect(page.locator('main table')).toBeVisible();
      found.push(...(await findings(page, 'keys')));

      // A page that does not exist for this person, inside the frame of the workspace.
      await page.goto(`/agencies/${agencyId}/clients/00000000-0000-4000-8000-000000000000/connections`);
      await expect(page.locator('main .c-empty')).toBeVisible();
      found.push(...(await findings(page, 'not found in the workspace')));

      await page.goto('/account');
      await ready(page);
      found.push(...(await findings(page, 'account')));
      await page.locator('main .a-form button[type="submit"]').click();
      await expect(page.locator('.c-field__error').first()).toBeVisible();
      found.push(...(await findings(page, 'account with errors')));

      await page.locator('.c-btn--danger-quiet').click();
      await expect(page.getByRole('alertdialog')).toBeVisible();
      found.push(...(await findings(page, 'close-account dialog')));

      await report(testInfo, found);
    });

    test('the first-agency screen has no serious accessibility finding', async ({ page, context }, testInfo) => {
      const newcomer = await registered(newPerson(testInfo));
      await signedInBrowser(context, newcomer);
      await page.goto('/welcome');
      await ready(page);
      const found = await findings(page, 'first agency');
      await page.goto('/account');
      await ready(page);
      found.push(...(await findings(page, 'account without an agency')));
      await report(testInfo, found);
    });
  });
}

test.describe('on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('sign-in and the workspace have no serious accessibility finding', async ({ page, context }, testInfo) => {
    const found: Found[] = [];
    await page.goto('/sign-in');
    await ready(page);
    found.push(...(await findings(page, 'sign-in at 390')));

    const { owner, connections } = await agencyInUse(testInfo);
    await signedInBrowser(context, owner);
    await page.goto('/');
    await ready(page);
    await expect(page.locator('.c-tabbar')).toBeVisible();
    await expect(page.locator('main table .c-badge--success')).toBeVisible();
    found.push(...(await findings(page, 'clients at 390')));
    const overflowing = () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(await overflowing()).toBeLessThanOrEqual(0);

    await page.goto(connections);
    await ready(page);
    await expect(page.locator('main .c-coverage')).toBeVisible();
    found.push(...(await findings(page, 'connections at 390')));
    expect(await overflowing()).toBeLessThanOrEqual(0);
    await pageAction(page).click();
    await expect(dialog(page)).toBeVisible();
    found.push(...(await findings(page, 'connect dialog at 390')));
    await page.keyboard.press('Escape');

    await page.goto('/account');
    await ready(page);
    found.push(...(await findings(page, 'account at 390')));

    // Nothing spills past the edge of a narrow screen.
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
    await report(testInfo, found);
  });
});
