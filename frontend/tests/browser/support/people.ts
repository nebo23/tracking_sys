import { expect, type BrowserContext, type Page, type TestInfo } from '@playwright/test';

import { verificationCode } from './mail.ts';
import { stack } from './stack.ts';

// Synthetic people for the journeys. Each has an address of its own, so the limits the API keeps
// per address never carry over from one journey to the next.

export interface Person {
  name: string;
  email: string;
  password: string;
}

let made = 0;

export function newPerson(testInfo: TestInfo, name = 'Mona Hassan'): Person {
  made += 1;
  const tag = `${testInfo.project.name}-${Date.now().toString(36)}-${made}`;
  return { name, email: `journey-${tag}@example.test`, password: `a long password for ${tag}` };
}

interface Signed {
  cookie: string;
  token: string;
}

/** A request to the API as the application's origin sends it, outside the browser. */
async function send(route: string, body?: unknown, signed?: Signed): Promise<Response> {
  const headers: Record<string, string> = { Origin: stack.webOrigin };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (signed) {
    headers.Cookie = signed.cookie;
    headers['X-CSRF-Token'] = signed.token;
  }
  const [method, path] = route.split(' ') as [string, string];
  return fetch(`${stack.apiOrigin}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
}

async function expectStatus(response: Response, status: number, what: string): Promise<void> {
  if (response.status !== status) throw new Error(`${what}: the API answered ${response.status} ${await response.text()}`);
}

export interface Agreements {
  terms: string;
  privacy: string;
}

/** The agreement versions the API asks for now (GET /auth/agreements, 017-A). */
export async function currentAgreements(): Promise<Agreements> {
  const response = await send('GET /auth/agreements');
  await expectStatus(response, 200, 'Reading the agreement versions');
  const { terms, privacy } = (await response.json()) as Agreements;
  return { terms, privacy };
}

/** Registers a person and confirms their address with the mailed code, through the API. */
export async function registered(person: Person): Promise<Person> {
  const agreements = await currentAgreements();
  await expectStatus(
    await send('POST /auth/register', { display_name: person.name, email: person.email, password: person.password, agreements }),
    202,
    'Registration',
  );
  await expectStatus(
    await send('POST /auth/verify-email-code', { email: person.email, code: verificationCode(person.email) }),
    204,
    'Verification',
  );
  return person;
}

async function signedIn(person: Person): Promise<Signed> {
  const agreements = await currentAgreements();
  const response = await send('POST /auth/login', { email: person.email, password: person.password, agreements });
  await expectStatus(response, 200, 'Sign-in');
  const cookie = response.headers.getSetCookie().map((value) => value.split(';')[0]).join('; ');
  const { csrf_token: token } = (await response.json()) as { csrf_token: string };
  return { cookie, token };
}

/** Gives a registered person an agency of their own, through the API. Returns the agency's id. */
export async function withAgency(person: Person, agencyName: string): Promise<string> {
  const signed = await signedIn(person);
  const response = await send('POST /agencies', { name: agencyName }, signed);
  await expectStatus(response, 201, 'Creating the agency');
  const { id } = (await response.json()) as { id: string };
  await send('POST /auth/logout', undefined, signed);
  return id;
}

/** Has the owner invite an address to the agency. The invitation arrives as captured mail. */
export async function invite(owner: Person, agencyId: string, email: string): Promise<void> {
  const signed = await signedIn(owner);
  await expectStatus(await send(`POST /agencies/${agencyId}/invitations`, { email, role: 'admin' }, signed), 201, 'The invitation');
  await send('POST /auth/logout', undefined, signed);
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
  await expect(page.getByRole('heading', { name: 'Overview', level: 1 })).toBeVisible();
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
