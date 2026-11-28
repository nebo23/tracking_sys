/** The tabs of the page, in order. Payments are configured by owners and admins only. */
export const integrationTabs = ['payments', 'bookings', 'whatsapp', 'conversions'] as const;
export type IntegrationTabId = (typeof integrationTabs)[number];
