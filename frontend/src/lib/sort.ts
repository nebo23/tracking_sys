/** Orders things by name as a person of the given language expects, with numbers in their natural order. */
export function byName<T extends { name: string }>(locale: string): (first: T, second: T) => number {
  const collator = new Intl.Collator(locale, { numeric: true, sensitivity: 'base' });
  return (first, second) => collator.compare(first.name, second.name);
}
