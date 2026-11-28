// The disposable stack behind the browser journeys: a PostgreSQL container of its own, the real
// API and the built application, each on a port that nothing else in the project uses.
//
// It never touches the owner's database (D-015). Every setting that could point the API somewhere
// else is set here explicitly, inherited TRACKING_ variables are dropped, and the API's own view
// of its settings is checked before anything connects. Every secret is random and lives for one run.
import { spawn, spawnSync, type ChildProcess } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { createWriteStream, existsSync, mkdirSync, rmSync } from 'node:fs';
import { createConnection } from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
export const frontendRoot = path.resolve(here, '../../..');
export const repositoryRoot = path.resolve(frontendRoot, '..');
const backendRoot = path.join(repositoryRoot, 'backend');

/** Build, captured mail and logs of a run. Ignored by git and removed when the stack stops. */
export const workDirectory = path.join(frontendRoot, '.e2e');
export const mailDirectory = path.join(workDirectory, 'mail');
/** The files in which the stand-in providers keep their made-up accounts. They contact nobody. */
const providerDirectory = path.join(workDirectory, 'providers');

export const stack = {
  composeProject: 'tracking-e2e-frontend',
  databaseName: 'tracking_e2e_frontend',
  databasePort: 56434,
  apiPort: 8010,
  webPort: 5183,
  apiOrigin: 'http://127.0.0.1:8010',
  webOrigin: 'http://127.0.0.1:5183',
} as const;

export type BackendEnvironment = Record<string, string>;

const hex = (bytes: number) => randomBytes(bytes).toString('hex');

/** The interpreter of the project's virtual environment (D-011), or the one named by the caller. */
function findPython(): string {
  const named = process.env.TRACKING_E2E_PYTHON;
  if (named) return named;
  const candidates = [repositoryRoot, path.resolve(repositoryRoot, '../..')].flatMap((root) => [
    path.join(root, '.venv', 'Scripts', 'python.exe'),
    path.join(root, '.venv', 'bin', 'python'),
  ]);
  const found = candidates.find((candidate) => existsSync(candidate));
  if (!found) {
    throw new Error('No project virtual environment was found. Set TRACKING_E2E_PYTHON to its Python interpreter.');
  }
  return found;
}

/** The parent's environment without anything that configures the backend, PostgreSQL, Python or the build. */
function neutralEnvironment(): Record<string, string> {
  const kept: Record<string, string> = {};
  for (const [name, value] of Object.entries(process.env)) {
    if (value !== undefined && !/^(TRACKING_|PG|PYTHON|VITE_)/i.test(name)) kept[name] = value;
  }
  return kept;
}

function newBackendEnvironment(): BackendEnvironment {
  return {
    TRACKING_ENVIRONMENT: 'development',
    TRACKING_DATABASE_HOST: '127.0.0.1',
    TRACKING_DATABASE_PORT: String(stack.databasePort),
    TRACKING_DATABASE_NAME: stack.databaseName,
    TRACKING_DATABASE_USER: 'tracking_app',
    TRACKING_DATABASE_PASSWORD: hex(24),
    TRACKING_MIGRATION_USER: 'tracking_migrator',
    TRACKING_MIGRATION_PASSWORD: hex(24),
    TRACKING_LIFECYCLE_PASSWORD: hex(24),
    TRACKING_POSTGRES_PASSWORD: hex(24),
    TRACKING_AUTH_SECRET: hex(32),
    TRACKING_OTP_SECRET: hex(32),
    // A Fernet key: 32 random bytes in URL-safe base64 with its padding.
    TRACKING_MAIL_ENCRYPTION_KEY: `${randomBytes(32).toString('base64url')}=`,
    TRACKING_COOKIE_SECURE: 'false',
    TRACKING_ALLOWED_ORIGINS: JSON.stringify([stack.webOrigin]),
    TRACKING_FRONTEND_ORIGIN: stack.webOrigin,
    // Mail is captured as files. Nothing is sent to a real mailbox and no provider is contacted.
    TRACKING_MAIL_MODE: 'local',
    TRACKING_MAIL_DIRECTORY: mailDirectory,
    TRACKING_GOOGLE_SIGN_IN_ENABLED: 'false',
    // Both browsers run from one address, so the per-address limit is raised. The limits per
    // account stay at their defaults; one journey shows the message a person sees at that limit.
    TRACKING_AUTH_REQUESTS_PER_MINUTE: '1000',
    // Connections use the stand-in providers only. Their tokens are sealed with a key of this run.
    TRACKING_TOKEN_KEYRING: `dev1:${randomBytes(32).toString('base64url')}`,
    TRACKING_TOKEN_KEYRING_ACTIVE: 'dev1',
    TRACKING_CONNECTOR_SYNTHETIC_STATE: path.join(providerDirectory, 'synthetic.sqlite'),
    TRACKING_CONNECTOR_REDIRECT_URI: `${stack.apiOrigin}/connectors/oauth/callback`,
    TRACKING_CONNECTOR_INSTAGRAM_ENABLED: 'false',
    TRACKING_CONNECTOR_YOUTUBE_ENABLED: 'false',
    TRACKING_CONNECTOR_META_ADS_ENABLED: 'false',
    // Short links (018-D) are served by this API itself, as a platform host.
    TRACKING_LINK_PLATFORM_HOSTS: JSON.stringify([`127.0.0.1:${stack.apiPort}`]),
    // Erasure writes tombstones under a keyring of its own, also random for one run.
    TRACKING_TOMBSTONE_KEYRING: `tomb1:${hex(32)}`,
    TRACKING_TOMBSTONE_KEYRING_ACTIVE: 'tomb1',
    // The integrations are switched on so their screens can be used. Nothing here calls Paymob,
    // Cal.com or Meta: the journeys sign their own synthetic callbacks with secrets of this run.
    TRACKING_PAYMENTS_PAYMOB_ENABLED: 'true',
    TRACKING_INTEGRATIONS_CALCOM_ENABLED: 'true',
    TRACKING_INTEGRATIONS_WEBHOOK_ENABLED: 'true',
    TRACKING_WHATSAPP_ENABLED: 'true',
    TRACKING_WHATSAPP_APP_SECRET: hex(24),
    TRACKING_WHATSAPP_VERIFY_TOKEN: hex(24),
  };
}

function run(command: string, args: string[], options: { cwd: string; env: Record<string, string> }, what: string): string {
  const result = spawnSync(command, args, { ...options, encoding: 'utf8', windowsHide: true });
  if (result.error) throw new Error(`${what} could not start: ${result.error.message}`);
  if (result.status !== 0) {
    throw new Error(`${what} failed (exit ${result.status}).\n${result.stdout ?? ''}\n${result.stderr ?? ''}`);
  }
  return result.stdout ?? '';
}

function portInUse(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = createConnection({ host: '127.0.0.1', port });
    socket.once('connect', () => {
      socket.destroy();
      resolve(true);
    });
    socket.once('error', () => resolve(false));
    socket.setTimeout(1000, () => {
      socket.destroy();
      resolve(false);
    });
  });
}

interface Service {
  child: ChildProcess;
  /** The last lines the process wrote, for the message of a failed start. */
  recent: string[];
}

function start(command: string, args: string[], options: { cwd: string; env: Record<string, string> }, log: string): Service {
  const child = spawn(command, args, { ...options, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
  const file = createWriteStream(path.join(workDirectory, log));
  const recent: string[] = [];
  for (const stream of [child.stdout, child.stderr]) {
    stream?.pipe(file, { end: false });
    stream?.on('data', (chunk: Buffer) => {
      recent.push(...chunk.toString('utf8').split(/\r?\n/).filter(Boolean));
      recent.splice(0, Math.max(0, recent.length - 40));
    });
  }
  return { child, recent };
}

async function waitFor(url: string, what: string, service: Service, seconds = 90): Promise<void> {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    if (service.child.exitCode !== null) {
      throw new Error(`${what} stopped early (exit ${service.child.exitCode}).\n${service.recent.join('\n')}`);
    }
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // Not listening yet.
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`${what} did not answer at ${url} within ${seconds} seconds.\n${service.recent.join('\n')}`);
}

/** Ends a process and what it started. On Windows a virtual environment's python starts a second one. */
function stopTree(child: ChildProcess): void {
  if (child.exitCode !== null || child.pid === undefined) return;
  if (process.platform === 'win32') spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true });
  else child.kill('SIGTERM');
}

function compose(env: Record<string, string>, args: string[], what: string): void {
  run(
    'docker',
    ['compose', '-p', stack.composeProject, '-f', path.join(repositoryRoot, 'infra', 'docker', 'compose.yaml'), ...args],
    { cwd: repositoryRoot, env },
    what,
  );
}

// Asks the backend itself which settings it will use, before anything connects to a database.
const settingsCheck = `
from app.config import MigrationSettings, Settings
s, m = Settings(), MigrationSettings()
expected = ("127.0.0.1", ${stack.databasePort}, "${stack.databaseName}")
assert (s.database_host, s.database_port, s.database_name) == expected, "runtime database"
assert (m.database_host, m.database_port, m.database_name) == expected, "migration database"
assert s.environment == "development" and s.mail_mode == "local", "mail"
assert not s.google_sign_in_enabled, "google"
assert s.allowed_origins == ["${stack.webOrigin}"] and s.frontend_origin == "${stack.webOrigin}", "origins"
live = (s.connector_instagram_enabled, s.connector_youtube_enabled, s.connector_meta_ads_enabled)
assert s.connector_synthetic_state is not None and not any(live), "providers"
assert s.connector_redirect_uri == "${stack.apiOrigin}/connectors/oauth/callback", "provider callback"
assert s.connector_completion_url == "${stack.webOrigin}/connections/complete", "provider return"
assert s.link_platform_hosts == ["127.0.0.1:${stack.apiPort}"] and not s.link_allow_loopback_destinations, "links"
assert s.link_domain_verification != "live", "domain checks"
print("settings-ok")
`;

export interface RunningStack {
  backendEnvironment: BackendEnvironment;
  python: string;
  stop: () => void;
}

export async function startStack(announce: (line: string) => void = () => {}): Promise<RunningStack> {
  const python = findPython();
  const backendEnvironment = newBackendEnvironment();
  const env = { ...neutralEnvironment(), ...backendEnvironment };
  const backend = { cwd: backendRoot, env };

  for (const port of [stack.apiPort, stack.webPort]) {
    if (await portInUse(port)) throw new Error(`Port ${port} is already in use. Stop what uses it, then run again.`);
  }

  rmSync(workDirectory, { recursive: true, force: true });
  mkdirSync(mailDirectory, { recursive: true });
  mkdirSync(providerDirectory, { recursive: true });

  announce('Checking the settings the API will use');
  if (!run(python, ['-c', settingsCheck], backend, 'The settings check').includes('settings-ok')) {
    throw new Error('The settings check did not confirm the disposable database.');
  }

  announce(`Starting a disposable PostgreSQL on 127.0.0.1:${stack.databasePort}`);
  compose(env, ['down', '--volumes', '--remove-orphans'], 'Removing an earlier disposable database');
  compose(env, ['up', '--detach', '--wait', 'database'], 'Starting the disposable database');

  const started: Service[] = [];
  const stop = () => {
    for (const service of started) stopTree(service.child);
    try {
      compose(env, ['down', '--volumes', '--remove-orphans'], 'Removing the disposable database');
    } finally {
      rmSync(workDirectory, { recursive: true, force: true });
    }
  };

  try {
    announce('Applying the migrations');
    run(python, ['-m', 'alembic', '-c', 'alembic.ini', 'upgrade', 'head'], backend, 'The migration');

    announce(`Starting the API on ${stack.apiOrigin}`);
    const api = start(
      python,
      ['-m', 'uvicorn', 'app.main:create_app', '--factory', '--host', '127.0.0.1', '--port', String(stack.apiPort), '--no-access-log'],
      backend,
      'api.log',
    );
    started.push(api);
    await waitFor(`${stack.apiOrigin}/health/ready`, 'The API', api);

    announce('Building the application');
    const vite = path.join(frontendRoot, 'node_modules', 'vite', 'bin', 'vite.js');
    const build = path.join(workDirectory, 'app');
    const web = {
      cwd: frontendRoot,
      env: { ...neutralEnvironment(), VITE_API_ORIGIN: stack.apiOrigin, VITE_GOOGLE_SIGN_IN: 'false', VITE_SYNTHETIC_PROVIDERS: 'true' },
    };
    run(process.execPath, [vite, 'build', '--outDir', build, '--emptyOutDir'], web, 'The build');

    announce(`Serving the application on ${stack.webOrigin}`);
    const preview = start(
      process.execPath,
      [vite, 'preview', '--outDir', build, '--host', '127.0.0.1', '--port', String(stack.webPort), '--strictPort'],
      web,
      'web.log',
    );
    started.push(preview);
    await waitFor(stack.webOrigin, 'The application', preview);
  } catch (error) {
    stop();
    throw error;
  }

  return { backendEnvironment, python, stop };
}

/** Runs one batch of the mail worker: queued messages become .eml files in the mail directory. */
export function deliverMail(python: string, backendEnvironment: BackendEnvironment): void {
  run(python, ['-m', 'app.mail_worker'], { cwd: backendRoot, env: { ...neutralEnvironment(), ...backendEnvironment } }, 'The mail worker');
}

// Stands in for a provider's own consent page, which no browser can open: the stand-in providers
// live in files. Approves an authorization for one made-up account and prints the code the
// provider would hand back.
const approval = `
import sys
from app.config import Settings
from app.services.connectors import build_providers
provider, url, account, label = sys.argv[1:5]
stand_in = build_providers(Settings())[provider]
if provider == "synthetic_meta_capi":
    # A dataset is made up first, then the business grants it.
    stand_in.define_dataset(account, label)
    print(stand_in.approve(url, (account,)))
elif provider == "synthetic_meta_ads":
    # The ad account was made up with its campaigns before; the business grants it.
    print(stand_in.approve(url, (account,)))
else:
    print(stand_in.approve(url, account, label))
`;

export interface StandInAccount {
  provider: 'synthetic' | 'synthetic_instagram' | 'synthetic_youtube' | 'synthetic_meta_capi' | 'synthetic_meta_ads';
  /** The account's identifier at the stand-in provider. */
  account: string;
  /** The name the provider gives the account, as a person knows it. */
  label: string;
}

/**
 * Approves the authorization a connection started and returns the address the provider would
 * send the browser to: the API's own callback, with the code and the state of that authorization.
 */
export function approveAtProvider(python: string, backendEnvironment: BackendEnvironment, authorizationUrl: string, account: StandInAccount): string {
  const options = { cwd: backendRoot, env: { ...neutralEnvironment(), ...backendEnvironment } };
  const code = run(python, ['-c', approval, account.provider, authorizationUrl, account.account, account.label], options, 'The approval').trim();
  const asked = new URL(authorizationUrl).searchParams;
  const back = new URL(asked.get('redirect_uri') ?? '');
  back.searchParams.set('code', code);
  back.searchParams.set('state', asked.get('state') ?? '');
  return back.toString();
}

// Makes up an ad account at the stand-in Meta ads provider, in Cairo time and Egyptian pounds,
// with its campaigns, ad sets and ads; an ad spends the same every day from its first day on.
const adAccount = `
import json, sys
from datetime import date
from app.config import Settings
from app.services.connectors import build_providers
account, label, objects = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
stand_in = build_providers(Settings())["synthetic_meta_ads"]
stand_in.define_account(account, currency="EGP", zone="Africa/Cairo", name=label)
for item in objects:
    first = date.fromisoformat(item.pop("first")) if item.get("first") else None
    stand_in.define_object(account, item.pop("id"), item.pop("level"), first=first, **item)
print("defined")
`;

export interface StandInAdObject {
  id: string;
  level: 'campaign' | 'adset' | 'ad';
  name: string;
  campaign?: string;
  adset?: string;
  first?: string;
  spend?: string;
  impressions?: number;
  clicks?: number;
}

export function defineAdAccount(python: string, backendEnvironment: BackendEnvironment, account: string, label: string, objects: StandInAdObject[]): void {
  run(python, ['-c', adAccount, account, label, JSON.stringify(objects)], { cwd: backendRoot, env: { ...neutralEnvironment(), ...backendEnvironment } }, 'The ad account');
}

/** Runs one pass of the connector worker: removals, the schedule and the queued reads. Returns its counts. */
export function runConnectorWorker(python: string, backendEnvironment: BackendEnvironment): string {
  return run(python, ['-m', 'app.connector_worker'], { cwd: backendRoot, env: { ...neutralEnvironment(), ...backendEnvironment } }, 'The connector worker');
}
