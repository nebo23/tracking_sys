/**
 * Up to two letters for an avatar: the first letter of the first two words of a name. A word
 * that does not start with a letter or a digit, such as "&", is passed over.
 */
export function initials(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .filter((word) => /^[\p{L}\p{N}]/u.test(word))
    .slice(0, 2)
    .map((word) => Array.from(word)[0] ?? '')
    .join('')
    .toLocaleUpperCase();
}
