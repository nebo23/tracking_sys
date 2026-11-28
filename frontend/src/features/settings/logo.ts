// The logo rules of the branding profile (016-C, backend/app/services/branding.py): a PNG of at
// least 67 bytes and at most 256 KiB, of 1 to 1024 pixels each way. They are checked here before
// anything is sent, so a wrong file is refused at once; the API checks the whole structure again.
// A unit test reads the same numbers in the backend source.

export const MIN_LOGO_BYTES = 67;
export const MAX_LOGO_BYTES = 256 * 1024;
export const MAX_LOGO_PIXELS = 1024;

const SIGNATURE = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];

export type LogoProblem = 'not_png' | 'too_small' | 'too_large' | 'too_big';

export interface LogoCheck {
  problem: LogoProblem | null;
  width?: number;
  height?: number;
}

/** Checks a chosen file: its type, its size, the PNG signature and the size the IHDR chunk gives. */
export async function checkLogo(file: Blob & { name?: string }): Promise<LogoCheck> {
  if (file.type !== 'image/png') return { problem: 'not_png' };
  if (file.size > MAX_LOGO_BYTES) return { problem: 'too_large' };
  if (file.size < MIN_LOGO_BYTES) return { problem: 'too_small' };
  const head = new Uint8Array(await file.slice(0, 24).arrayBuffer());
  if (!SIGNATURE.every((byte, index) => head[index] === byte)) return { problem: 'not_png' };
  // The first chunk is IHDR: its length (13), its type, then the width and the height, big-endian.
  const isHeader = String.fromCharCode(head[12] ?? 0, head[13] ?? 0, head[14] ?? 0, head[15] ?? 0) === 'IHDR';
  if (!isHeader) return { problem: 'not_png' };
  const view = new DataView(head.buffer);
  const width = view.getUint32(16);
  const height = view.getUint32(20);
  if (width < 1 || height < 1) return { problem: 'not_png' };
  if (width > MAX_LOGO_PIXELS || height > MAX_LOGO_PIXELS) return { problem: 'too_big', width, height };
  return { problem: null, width, height };
}

/** A display name the API accepts: 1 to 100 characters, none of them a control character. */
export function displayNameProblem(value: string): 'required' | 'too_long' | 'invalid' | null {
  const trimmed = value.trim();
  if (trimmed === '') return 'required';
  if ([...trimmed].length > 100) return 'too_long';
  // Control characters (U+0000 to U+001F and U+007F) are refused by the API.
  for (const character of trimmed) {
    const code = character.codePointAt(0) ?? 0;
    if (code < 0x20 || code === 0x7f) return 'invalid';
  }
  return null;
}

export const isAccentColor = (value: string): boolean => /^#[0-9A-Fa-f]{6}$/.test(value);
