import type { Role } from '@/api/agencies';

/** The tabs of Agency settings (D7); the first is the default and is left out of the address. */
export const settingsTabs = ['plan', 'branding', 'closure'] as const;
export type SettingsTab = (typeof settingsTabs)[number];

/** Who may open Agency settings: everyone of the agency except its client viewers (section 4.6). */
export const maySeeSettings = (role: Role): boolean => role !== 'client_viewer';

/** The tabs a role sees: closing the agency is for its Owners only. */
export function settingsTabsFor(role: Role): SettingsTab[] {
  return settingsTabs.filter((tab) => tab !== 'closure' || role === 'owner');
}
