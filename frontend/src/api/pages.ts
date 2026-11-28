// The API returns lists a page at a time. A screen that counts or filters needs the whole list.
export const PAGE_SIZE = 100;

// A list longer than this is not read to its end; no agency of the product comes near it.
const MOST_PAGES = 50;

/** Reads a paged list to its end, one page after the other. */
export async function readAll<T>(page: (offset: number) => Promise<T[]>): Promise<T[]> {
  const all: T[] = [];
  for (let index = 0; index < MOST_PAGES; index += 1) {
    const items = await page(index * PAGE_SIZE);
    all.push(...items);
    if (items.length < PAGE_SIZE) break;
  }
  return all;
}
