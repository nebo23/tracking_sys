// Regenerate the contract types into a temporary file with the same command as
// "npm run api:types" and compare them with the committed file, so the client cannot
// drift from contracts/openapi.json. Usage: npm run api:check
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const at = (relative) => fileURLToPath(new URL(relative, import.meta.url));
const cli = at('../node_modules/openapi-typescript/bin/cli.js');
const contract = at('../../contracts/openapi.json');
const committed = at('../src/api/schema.d.ts');

const normalize = (text) => text.replace(/\r\n/g, '\n').trim();
const folder = mkdtempSync(join(tmpdir(), 'connect-api-types-'));
try {
  const fresh = join(folder, 'schema.d.ts');
  execFileSync(process.execPath, [cli, contract, '-o', fresh], { stdio: 'ignore' });
  if (normalize(readFileSync(fresh, 'utf8')) !== normalize(readFileSync(committed, 'utf8'))) {
    console.error('src/api/schema.d.ts does not match contracts/openapi.json. Run: npm run api:types');
    process.exitCode = 1;
  } else {
    console.log('The contract types match contracts/openapi.json.');
  }
} finally {
  rmSync(folder, { recursive: true, force: true });
}
