/** The tabs of Reports (E03, E04); the first is the default and is left out of the address. */
export const reportTabs = ['exports', 'schedules'] as const;
export type ReportTab = (typeof reportTabs)[number];
