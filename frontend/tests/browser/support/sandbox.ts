// npm run sandbox: a throwaway copy of the whole application to try by hand. It starts the
// disposable stack, delivers queued mail every few seconds and prints each captured message, so
// a verification code or a reset link can be read here. Ctrl+C removes everything again.
import { capturedMail } from './mail.ts';
import { deliverMail, stack, startStack } from './stack.ts';

const running = await startStack((line) => console.log(`- ${line}`));
console.log(`\nConnect is running at ${stack.webOrigin} on disposable data. Press Ctrl+C to stop and remove it.\n`);

const shown = new Set<string>();
const timer = setInterval(() => {
  try {
    deliverMail(running.python, running.backendEnvironment);
    for (const message of capturedMail().filter((mail) => !shown.has(mail.file))) {
      shown.add(message.file);
      console.log(`--- mail to ${message.to}: ${message.subject}\n${message.body}\n`);
    }
  } catch (error) {
    console.error(error instanceof Error ? error.message : error);
  }
}, 4000);

let stopping = false;
const stop = () => {
  if (stopping) return;
  stopping = true;
  clearInterval(timer);
  console.log('\nStopping and removing the disposable data');
  running.stop();
  process.exit(0);
};
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
