import { verificationCode } from './mail.ts';
import { stack } from './stack.ts';

// Requests to the API as the application's origin sends them, outside a browser: the journeys
// and the sandbox prepare synthetic people and agencies with them.

export interface Person {
  name: string;
  email: string;
  password: string;
}

export interface Signed {
  cookie: string;
  token: string;
}

/**
 * A request to the API as the application's origin sends it, outside the browser. The API closes
 * a connection that was idle for a few seconds, and a request can meet one just as it closes; it
 * then never reached the API, so it is sent once more on a new connection.
 */
export async function send(route: string, body?: unknown, signed?: Signed): Promise<Response> {
  const headers: Record<string, string> = { Origin: stack.webOrigin };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (signed) {
    headers.Cookie = signed.cookie;
    headers['X-CSRF-Token'] = signed.token;
  }
  const [method, path] = route.split(' ') as [string, string];
  const once = () => fetch(`${stack.apiOrigin}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), redirect: 'manual' });
  try {
    return await once();
  } catch (error) {
    if (!(error instanceof TypeError)) throw error;
    return once();
  }
}

export async function expectStatus(response: Response, status: number, what: string): Promise<void> {
  if (response.status !== status) throw new Error(`${what}: the API answered ${response.status} ${await response.text()}`);
}

/** Registers a person and confirms their address with the mailed code, through the API. */
export async function registered(person: Person): Promise<Person> {
  await expectStatus(
    await send('POST /auth/register', { display_name: person.name, email: person.email, password: person.password }),
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

/** Signs a person in through the API: the session cookie and the token that mutations carry. */
export async function signedIn(person: Person): Promise<Signed> {
  const response = await send('POST /auth/login', { email: person.email, password: person.password });
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
