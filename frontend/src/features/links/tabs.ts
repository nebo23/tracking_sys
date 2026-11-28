/** The tabs of the page. The first is the default and is left out of the address. */
export const linksTabs = ['links', 'campaigns', 'content', 'templates', 'sites', 'domains'] as const;
export type LinksTabId = (typeof linksTabs)[number];
