// npm run sandbox: a throwaway copy of the whole application to try by hand. It starts the
// disposable stack and prepares an agency with a few clients and connected sample accounts, so
// the screens have something to show. While it runs it delivers queued mail, prints each captured
// message (a verification code or a link can be read here) and runs the connector worker, so a
// requested sync or removal is carried out. Ctrl+C removes everything again.
//
// Everything is synthetic. The sample providers keep made-up accounts in files and contact nobody.
import { randomBytes } from 'node:crypto';

import { registered, send, signedIn, withAgency, type Person } from './api.ts';
import { capturedMail } from './mail.ts';
import { deliverMail, runConnectorWorker, stack, startStack } from './stack.ts';
import { inviteAs, standInAccount, withClient, withConnection } from './tenants.ts';

const running = await startStack((line) => console.log(`- ${line}`));
process.env.CONNECT_E2E_PYTHON = running.python;
process.env.CONNECT_E2E_BACKEND = JSON.stringify(running.backendEnvironment);

// A person of this run only: the password is random and is gone when the sandbox stops.
const owner: Person = { name: 'Mona Hassan', email: 'mona@sandbox.example.test', password: `sandbox-${randomBytes(8).toString('hex')}` };

async function prepare(): Promise<void> {
  console.log('- Preparing an agency with clients and sample accounts');
  await registered(owner);
  const agencyId = await withAgency(owner, 'Lumen Studio');
  // One sign-in for the whole preparation: the API limits how often an account signs in.
  const session = await signedIn(owner);
  const olive = await withClient(session, agencyId, 'Olive & Thyme');
  const cedar = await withClient(session, agencyId, 'Cedar Fitness');
  await withClient(session, agencyId, 'Nile Home');
  await withConnection(session, agencyId, olive, standInAccount('@olive.thyme'));
  await withConnection(session, agencyId, olive, standInAccount('Olive & Thyme Kitchen', 'synthetic_youtube'));
  await withConnection(session, agencyId, cedar, standInAccount('@cedar.fitness', 'synthetic_instagram'));
  await inviteAs(session, agencyId, 'youssef@sandbox.example.test', 'analyst', [{ client_id: olive, can_view_financials: true }]);
  await send('POST /auth/logout', undefined, session);
  runConnectorWorker(running.python, running.backendEnvironment);
}

let stopping = false;
const stop = (code = 0) => {
  if (stopping) return;
  stopping = true;
  console.log('\nStopping and removing the disposable data');
  running.stop();
  process.exit(code);
};
process.on('SIGINT', () => stop());
process.on('SIGTERM', () => stop());

try {
  await prepare();
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  stop(1);
}

console.log(`
Connect is running at ${stack.webOrigin} on disposable data. Press Ctrl+C to stop and remove it.

  Sign in as   ${owner.email}
  Password     ${owner.password}

The agency "Lumen Studio" has three clients, three connected sample accounts and one invitation.
A new sample account cannot be connected by hand: its provider's consent page exists only in the
browser journeys. Everything else works, and mail is printed here as it is captured.
`);

const shown = new Set<string>(capturedMail().map((mail) => mail.file));
const timer = setInterval(() => {
  try {
    deliverMail(running.python, running.backendEnvironment);
    for (const message of capturedMail().filter((mail) => !shown.has(mail.file))) {
      shown.add(message.file);
      console.log(`--- mail to ${message.to}: ${message.subject}\n${message.body}\n`);
    }
    runConnectorWorker(running.python, running.backendEnvironment);
  } catch (error) {
    console.error(error instanceof Error ? error.message : error);
  }
}, 4000);
process.on('exit', () => clearInterval(timer));
