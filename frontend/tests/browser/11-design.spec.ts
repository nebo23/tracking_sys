import path from 'node:path';
import { pathToFileURL } from 'node:url';

import { expect, test, type Page } from '@playwright/test';

import { repositoryRoot } from './support/stack.ts';

// The built sign-in screen beside the page the owner approved (D-079):
// docs/design/preview/screens/sign-in.html. The comparison is of places and sizes. Both pages are
// measured without web fonts, so a font that failed to arrive cannot hide or fake a difference;
// that the application really shows IBM Plex is checked on its own below.

const reference = pathToFileURL(path.join(repositoryRoot, 'docs', 'design', 'preview', 'screens', 'sign-in.html')).href;

const parts: Record<string, string> = {
  'brand side': '.l-auth__brand',
  logo: '.l-auth__brand > img',
  picture: '.l-auth__art',
  statement: '.l-auth__statement',
  points: '.l-auth__points',
  note: '.l-auth__note',
  'pause control': '.l-auth__motion',
  'language switch': '.l-auth__lang .c-seg',
  heading: 'main h1',
  lead: 'main h1 + p',
  'email field': '#signin-email',
  'password field': '#signin-password',
  'show-password control': '.c-input-wrap button',
  'forgot-password link': '.c-field__link',
  'agreement box': '#signin-terms',
  'sign-in button': 'main form .c-btn--primary',
  'new-account line': 'main > p',
};

type Box = { x: number; y: number; width: number; height: number } | null;

async function measure(page: Page): Promise<Record<string, Box>> {
  const boxes: Record<string, Box> = {};
  for (const [name, selector] of Object.entries(parts)) {
    const element = page.locator(selector).first();
    boxes[name] = (await element.isVisible()) ? await element.boundingBox() : null;
  }
  return boxes;
}

for (const size of [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
]) {
  test(`the sign-in screen has the places and sizes of the approved design at ${size.width} pixels`, async ({ browser }, testInfo) => {
    const context = await browser.newContext({ viewport: size, locale: 'en-US', colorScheme: 'light', reducedMotion: 'reduce' });
    await context.route(/fonts\.(googleapis|gstatic)\.com|\.woff2?(\?|$)/, (route) => route.abort());

    const approved = await context.newPage();
    await approved.goto(reference);
    // The approved page shows the Google button; this build has Google sign-in switched off.
    await approved.evaluate(() => {
      document.querySelector('main form .c-btn--secondary')?.remove();
      document.querySelector('main form .c-divider')?.remove();
    });
    const built = await context.newPage();
    await built.goto('/sign-in');
    await expect(built.locator('main h1')).toBeVisible();

    const expected = await measure(approved);
    const actual = await measure(built);
    await testInfo.attach('approved.png', { body: await approved.screenshot(), contentType: 'image/png' });
    await testInfo.attach('built.png', { body: await built.screenshot(), contentType: 'image/png' });

    const differences: string[] = [];
    for (const name of Object.keys(parts)) {
      const one = expected[name] ?? null;
      const other = actual[name] ?? null;
      if (one === null || other === null) {
        if (one !== other) differences.push(`${name}: ${one ? 'shown' : 'hidden'} in the design, ${other ? 'shown' : 'hidden'} in the application`);
        continue;
      }
      for (const side of ['x', 'y', 'width', 'height'] as const) {
        if (Math.abs(one[side] - other[side]) > 1) differences.push(`${name}.${side}: design ${one[side]}, application ${other[side]}`);
      }
    }
    expect(differences).toEqual([]);
    await context.close();
  });
}

test('the application shows IBM Plex from its own files, in both scripts', async ({ page }) => {
  const elsewhere: string[] = [];
  page.on('request', (request) => {
    const host = new URL(request.url()).host;
    if (!host.startsWith('127.0.0.1')) elsewhere.push(request.url());
  });

  await page.goto('/sign-in');
  await page.getByRole('radio', { name: 'العربية' }).click();
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  await page.evaluate(() => document.fonts.ready);

  const loaded = await page.evaluate(() => [...document.fonts].filter((font) => font.status === 'loaded').map((font) => font.family.replaceAll('"', '')));
  expect(loaded).toContain('IBM Plex Sans');
  expect(loaded).toContain('IBM Plex Sans Arabic');
  // No font service, no analytics, nothing outside the application and its API.
  expect(elsewhere).toEqual([]);
});
