import { startStack } from './stack.ts';

/** Starts the disposable stack once for the whole run and removes it afterwards. */
export default async function globalSetup(): Promise<() => void> {
  const running = await startStack((line) => console.log(`[stack] ${line}`));
  // The journeys run in worker processes, which inherit this environment. Everything in it is
  // synthetic and lives only as long as this run.
  process.env.CONNECT_E2E_PYTHON = running.python;
  process.env.CONNECT_E2E_BACKEND = JSON.stringify(running.backendEnvironment);
  return () => running.stop();
}
