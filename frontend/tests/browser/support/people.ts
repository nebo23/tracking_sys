import { expect, type BrowserContext, type Page, type TestInfo } from '@playwright/test';

import { signedIn, type Person } from './api.ts';

export {
  currentAgreements,
  expectStatus,
  invite,
  registered,
  send,
  signedIn,
  withAgency,
  type Agreements,
  type Person,
  type Signed,
} from './api.ts';

// Synthetic people for the journeys. Each has an address of its own, so the limits the API keeps
// per address never carry over from one journey to the next.

let made = 0;

export function newPerson(testInfo: TestInfo, name = 'Mona Hassan'): Person {
  made += 1;
  const tag = `${testInfo.project.name}-${Date.now().toString(36)}-${made}`;
  return { name, email: `journey-${tag}@example.test`, password: `a long password for ${tag}` };
}

export const agreement = (page: Page) => page.getByRole('checkbox', { name: /I agree|أوافق/ });

/** Signs in on the sign-in screen, in English, as a person does. */
export async function signInOnScreen(page: Page, person: Person, password = person.password): Promise<void> {
  await page.getByLabel('Email').fill(person.email);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await agreement(page).check();
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
}

/** Opens the application and signs in; ends on the first page of the workspace. */
export async function enterWorkspace(page: Page, person: Person): Promise<void> {
  await page.goto('/sign-in');
  await signInOnScreen(page, person);
  await expect(page.getByRole('heading', { name: 'Clients', level: 1 })).toBeVisible();
}

export const accountMenu = (page: Page, person: Person) => page.getByRole('button', { name: `Account: ${person.name}` });

/** Every request the page made, as method and address, to check that a secret never travelled in one. */
export function recordRequests(page: Page): string[] {
  const requests: string[] = [];
  page.on('request', (request) => requests.push(request.method() + ' ' + request.url()));
  return requests;
}

/**
 * Signs the browser in without the sign-in screen, for journeys that are about something else.
 * The session cookie is the same opaque cookie the API sets after the screen.
 */
export async function signedInBrowser(context: BrowserContext, person: Person): Promise<void> {
  const { cookie } = await signedIn(person);
  const [name, ...value] = cookie.split('=');
  await context.addCookies([
    { name: name ?? '', value: value.join('='), domain: '127.0.0.1', path: '/', httpOnly: true, sameSite: 'Lax' },
  ]);
}
