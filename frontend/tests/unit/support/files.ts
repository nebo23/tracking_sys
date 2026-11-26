import { existsSync } from 'node:fs';
import path from 'node:path';

// Vitest runs from frontend/, so the repository is one folder up.
const root = path.resolve(process.cwd(), '..');

/** A path inside the repository, for the tests that compare the interface with the API. */
export function inRepository(...parts: string[]): string {
  const target = path.join(root, ...parts);
  if (!existsSync(target)) throw new Error(`${target} was not found. Run the tests from frontend/.`);
  return target;
}
