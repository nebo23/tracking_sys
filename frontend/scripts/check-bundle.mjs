// Searches the production build for anything that must never reach a browser (acceptance
// criterion 5 of specification 018): secrets, keys, tokens and backend settings.
// Usage: npm run build, then node scripts/check-bundle.mjs [build folder]
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(process.argv[2] ?? fileURLToPath(new URL('../dist', import.meta.url)));

// What a leaked secret or backend setting looks like. Each pattern names what it would be.
const forbidden = [
  ['a backend setting name', /TRACKING_[A-Z][A-Z_]{3,}/g],
  ['a private key', /-----BEGIN [A-Z ]*PRIVATE KEY-----/g],
  ['a database address', /postgres(?:ql)?(?:\+\w+)?:\/\/[^\s"'`]+/g],
  ['a Google client secret', /GOCSPX-[0-9A-Za-z_-]{10,}/g],
  ['a Google API key', /AIza[0-9A-Za-z_-]{35}/g],
  ['a Google client id', /\d{6,}-[0-9a-z]{20,}\.apps\.googleusercontent\.com/g],
  ['an AWS access key', /\b(?:AKIA|ASIA)[0-9A-Z]{16}\b/g],
  ['a signed token', /\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/g],
  ['a key of this project (service, webhook, ingest or integration)', /\b(?:tsk|whsec|isk|pk|sbj)_[A-Za-z0-9_-]{24,}/g],
  ['a payment provider key', /\b(?:sk|rk)_(?:live|test)_[0-9A-Za-z]{10,}/g],
  ['a session cookie value', /tracking_session=[A-Za-z0-9_-]{16,}/g],
  ['a source map', /\/\/[#@] sourceMappingURL=/g],
];

function files(folder) {
  return readdirSync(folder).flatMap((name) => {
    const file = path.join(folder, name);
    return statSync(file).isDirectory() ? files(file) : [file];
  });
}

const text = /\.(?:js|mjs|css|html|json|svg|txt|map)$/;
const all = files(root);
const findings = [];
const origins = new Set();
let bytes = 0;

for (const file of all) {
  bytes += statSync(file).size;
  if (file.endsWith('.map')) findings.push(`${path.relative(root, file)}: a source map file`);
  if (!text.test(file)) continue;
  const content = readFileSync(file, 'utf8');
  for (const [what, pattern] of forbidden) {
    for (const match of content.matchAll(pattern)) {
      findings.push(`${path.relative(root, file)}: ${what}: ${match[0].slice(0, 24)}...`);
    }
  }
  for (const match of content.matchAll(/https?:\/\/[A-Za-z0-9.-]+(?::\d+)?/g)) origins.add(match[0]);
}

console.log(`Checked ${all.length} files (${(bytes / 1024).toFixed(0)} KiB) in ${root}`);
console.log(`Addresses named in the build:\n  ${[...origins].sort().join('\n  ')}`);
if (findings.length > 0) {
  console.error(`\n${findings.length} finding(s):\n  ${findings.join('\n  ')}`);
  process.exit(1);
}
console.log('\nNo secret, key, token or backend setting was found.');
