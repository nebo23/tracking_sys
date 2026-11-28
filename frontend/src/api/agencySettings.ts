import { queryOptions } from '@tanstack/react-query';

import { tenantKey } from './agencies';
import { api, call } from './client';
import type { components } from './schema';

export type AgencyPlan = components['schemas']['AgencyPlanResponse'];
export type PlanLimitUse = components['schemas']['PlanLimitUse'];
export type Branding = components['schemas']['AgencyBrandingView'];
export type BrandingInput = components['schemas']['BrandingInput'];
export type Closure = components['schemas']['AgencyClosureResponse'];

const agency = (agencyId: string) => ({ params: { path: { agency_id: agencyId } } });

/** The agency's plan, each limit with its use, and the month's tracked events (017-A). */
export const planQuery = (agencyId: string) =>
  queryOptions({
    queryKey: tenantKey(agencyId, 'plan'),
    queryFn: () => call(api.GET('/agencies/{agency_id}/plan', agency(agencyId))),
  });

/** The agency's branding profile (016-C): its display name, accent color and logo. */
export const brandingQuery = (agencyId: string) =>
  queryOptions({
    queryKey: tenantKey(agencyId, 'branding'),
    queryFn: () => call(api.GET('/agencies/{agency_id}/branding', agency(agencyId))),
  });

/** The logo as a file, read with the session: the browser is never given a link to it. */
export const brandingLogoQuery = (agencyId: string, updatedAt: string | null | undefined) =>
  queryOptions({
    queryKey: tenantKey(agencyId, 'branding-logo', updatedAt ?? null),
    queryFn: async () => (await call(api.GET('/agencies/{agency_id}/branding/logo', { ...agency(agencyId), parseAs: 'blob' }))) as unknown as Blob,
    staleTime: Infinity,
  });

export function saveBranding(agencyId: string, input: BrandingInput) {
  return call(api.PUT('/agencies/{agency_id}/branding', { ...agency(agencyId), body: input }));
}

/** Uploads a PNG logo as the raw body the API expects (image/png). */
export function uploadLogo(agencyId: string, file: Blob) {
  return call(
    api.PUT('/agencies/{agency_id}/branding/logo', {
      ...agency(agencyId),
      body: file as never,
      bodySerializer: (body: unknown) => body as BodyInit,
      headers: { 'Content-Type': 'image/png' },
    }),
  );
}

export function removeLogo(agencyId: string) {
  return call(api.DELETE('/agencies/{agency_id}/branding/logo', agency(agencyId)));
}

/** Whether the agency is closing, and when; only its Owners may read it. */
export const closureQuery = (agencyId: string) =>
  queryOptions({
    queryKey: tenantKey(agencyId, 'closure'),
    queryFn: () => call(api.GET('/agencies/{agency_id}/closure', agency(agencyId))),
  });

/** Asks to close the agency: its exact name, and the password of an account that has one. */
export function requestClosure(agencyId: string, confirmName: string, password: string) {
  return call(
    api.POST('/agencies/{agency_id}/closure', { ...agency(agencyId), body: { confirm_name: confirmName, ...(password === '' ? {} : { password }) } }),
  );
}

/** Keeps a closing agency during its grace period. */
export function keepAgency(agencyId: string) {
  return call(api.DELETE('/agencies/{agency_id}/closure', agency(agencyId)));
}
