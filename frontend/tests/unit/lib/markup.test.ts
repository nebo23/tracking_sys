import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

import { inRepository } from '../support/files';

// What the reference styles of docs/design/ promise the markup, read from both sources. The
// tests in jsdom never draw a layout, so these are the checks that catch a page drawn wrong.

const sources = (): Array<{ name: string; text: string }> => {
  const root = inRepository('frontend', 'src');
  return readdirSync(root, { recursive: true, encoding: 'utf8' })
    .filter((name) => name.endsWith('.tsx'))
    .map((name) => ({ name, text: readFileSync(path.join(root, name), 'utf8') }));
};

describe('the markup of the application', () => {
  it('names only icons that the icon set draws', () => {
    const css = readFileSync(inRepository('docs', 'design', 'ui', 'connect-icons.css'), 'utf8');
    const drawn = new Set([...css.matchAll(/\.c-icon--([a-z0-9-]+)\s*[{,]/g)].map((match) => match[1]));
    const union = readFileSync(inRepository('frontend', 'src', 'components', 'Icon.tsx'), 'utf8');
    const named = [...union.matchAll(/^\s*\|\s*'([a-z0-9-]+)'/gm)].map((match) => match[1]);
    expect(named.length).toBeGreaterThan(20);
    // A name the set does not draw shows a filled square where the icon should be.
    expect(named.filter((name) => !drawn.has(name))).toEqual([]);
  });

  it('never puts the inline utility u-num on a table cell', () => {
    // `.u-num` is an inline block; on a <td> or <th> it takes the cell out of its column.
    const cells = sources().flatMap(({ name, text }) => [...text.matchAll(/<t[dh]\b[^>]*\bu-num\b[^>]*>/g)].map((match) => `${name}: ${match[0]}`));
    expect(cells).toEqual([]);
  });
});
