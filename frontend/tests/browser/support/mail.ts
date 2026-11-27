import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';

import { deliverMail, mailDirectory, stack, type BackendEnvironment } from './stack.ts';

// The API queues its mail; the worker writes each message to a file (local capture). Nothing is
// sent to a real mailbox. A journey reads its code or link from here, as a person reads their mail.

export type MailKind = 'Verify your email' | 'Reset your password' | 'Agency invitation';

export interface CapturedMail {
  file: string;
  to: string;
  subject: string;
  body: string;
  written: number;
}

/** Undoes the transfer encoding of a message body. A long line, such as a link, is sent folded. */
function decoded(body: string, encoding: string): string {
  if (/quoted-printable/i.test(encoding)) {
    return body.replace(/=\r?\n/g, '').replace(/=([0-9A-F]{2})/gi, (_match, hex: string) => String.fromCharCode(parseInt(hex, 16)));
  }
  if (/base64/i.test(encoding)) return Buffer.from(body, 'base64').toString('utf8');
  return body;
}

/** Every captured message, as a person would read it. */
export function capturedMail(): CapturedMail[] {
  return readdirSync(mailDirectory)
    .filter((name) => name.endsWith('.eml'))
    .map((name) => {
      const file = path.join(mailDirectory, name);
      const text = readFileSync(file, 'utf8');
      const split = text.search(/\r?\n\r?\n/);
      const head = text.slice(0, split);
      const header = (title: string) => new RegExp(`^${title}: (.*)$`, 'im').exec(head)?.[1]?.trim() ?? '';
      const body = decoded(text.slice(split).trim(), header('Content-Transfer-Encoding'));
      return { file: name, to: header('To'), subject: header('Subject'), body: body.trim(), written: statSync(file).mtimeMs };
    });
}

/** Delivers what is queued and returns the body of the newest message of a kind to an address. */
export function newestMail(to: string, kind: MailKind): string {
  const python = process.env.CONNECT_E2E_PYTHON;
  const backend = process.env.CONNECT_E2E_BACKEND;
  if (!python || !backend) throw new Error('The disposable stack is not running (see global-setup.ts).');
  deliverMail(python, JSON.parse(backend) as BackendEnvironment);
  const found = capturedMail()
    .filter((message) => message.to.toLowerCase() === to.toLowerCase() && message.subject === kind)
    .sort((one, other) => other.written - one.written)[0];
  if (!found) throw new Error(`No "${kind}" message to ${to} was captured.`);
  return found.body;
}

export function verificationCode(to: string): string {
  const code = /verification code: (\d{6})/.exec(newestMail(to, 'Verify your email'))?.[1];
  if (!code) throw new Error('The verification message holds no six-digit code.');
  return code;
}

/** The link of a reset or invitation message, as the path and fragment inside the application. */
export function linkIn(to: string, kind: Exclude<MailKind, 'Verify your email'>): string {
  const body = newestMail(to, kind);
  const start = body.indexOf(`${stack.webOrigin}/auth/`);
  if (start < 0) throw new Error(`The "${kind}" message holds no link to the application.`);
  const address = /^\S+/.exec(body.slice(start))?.[0] ?? '';
  return address.slice(stack.webOrigin.length);
}
