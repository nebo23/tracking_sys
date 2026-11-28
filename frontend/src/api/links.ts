import { queryOptions } from '@tanstack/react-query';

import { api, call } from './client';
import { clientKey } from './clients';
import { PAGE_SIZE, readAll } from './pages';
import type { components } from './schema';

export type ManagedLink = components['schemas']['LinkResponse'];
export type LinkInput = components['schemas']['LinkInput'];
export type Campaign = components['schemas']['CampaignResponse'];
export type ContentReference = components['schemas']['ContentResponse'];
export type UtmTemplate = components['schemas']['TemplateResponse'];
export type DestinationSite = components['schemas']['OriginResponse'];
export type LinkDomain = components['schemas']['DomainResponse'];
export type DomainChallenge = components['schemas']['ChallengeResponse'];
export type DomainCheck = components['schemas']['VerificationResponse'];

const scope = (agencyId: string, clientId: string) => ({ agency_id: agencyId, client_id: clientId });

// Each list of the links of a client has a key under that client (acceptance criterion 2).
export const linksKey = (agencyId: string, clientId: string, list?: string) =>
  list ? clientKey(agencyId, clientId, 'links', list) : clientKey(agencyId, clientId, 'links');

// Every list is read to its end, 100 at a time. Readers of the client may list; managers change.
export const managedLinksQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: linksKey(agencyId, clientId, 'links'),
    queryFn: () =>
      readAll((offset) =>
        call(
          api.GET('/agencies/{agency_id}/clients/{client_id}/managed-links', {
            params: { path: scope(agencyId, clientId), query: { limit: PAGE_SIZE, offset } },
          }),
        ),
      ),
  });

export const campaignsQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: linksKey(agencyId, clientId, 'campaigns'),
    queryFn: () =>
      readAll((offset) =>
        call(
          api.GET('/agencies/{agency_id}/clients/{client_id}/link-campaigns', {
            params: { path: scope(agencyId, clientId), query: { limit: PAGE_SIZE, offset } },
          }),
        ),
      ),
  });

export const contentQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: linksKey(agencyId, clientId, 'content'),
    queryFn: () =>
      readAll((offset) =>
        call(
          api.GET('/agencies/{agency_id}/clients/{client_id}/link-content-references', {
            params: { path: scope(agencyId, clientId), query: { limit: PAGE_SIZE, offset } },
          }),
        ),
      ),
  });

export const templatesQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: linksKey(agencyId, clientId, 'templates'),
    queryFn: () =>
      readAll((offset) =>
        call(
          api.GET('/agencies/{agency_id}/clients/{client_id}/link-utm-templates', {
            params: { path: scope(agencyId, clientId), query: { limit: PAGE_SIZE, offset } },
          }),
        ),
      ),
  });

export const sitesQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: linksKey(agencyId, clientId, 'sites'),
    queryFn: () =>
      readAll((offset) =>
        call(
          api.GET('/agencies/{agency_id}/clients/{client_id}/link-destination-origins', {
            params: { path: scope(agencyId, clientId), query: { limit: PAGE_SIZE, offset } },
          }),
        ),
      ),
  });

export const domainsQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: linksKey(agencyId, clientId, 'domains'),
    queryFn: () =>
      readAll((offset) =>
        call(
          api.GET('/agencies/{agency_id}/clients/{client_id}/link-domains', {
            params: { path: scope(agencyId, clientId), query: { limit: PAGE_SIZE, offset } },
          }),
        ),
      ),
  });

export function createLink(agencyId: string, clientId: string, input: LinkInput) {
  return call(api.POST('/agencies/{agency_id}/clients/{client_id}/managed-links', { params: { path: scope(agencyId, clientId) }, body: input }));
}

/** Pauses or resumes a link, or changes its expiry. Its address never changes. */
export function updateLink(
  agencyId: string,
  clientId: string,
  linkId: string,
  change: { status?: 'active' | 'disabled'; expires_at?: string | null },
) {
  return call(
    api.PATCH('/agencies/{agency_id}/clients/{client_id}/managed-links/{link_id}', {
      params: { path: { ...scope(agencyId, clientId), link_id: linkId } },
      body: change,
    }),
  );
}

export function createCampaign(agencyId: string, clientId: string, input: { public_code: string; label: string }) {
  return call(api.POST('/agencies/{agency_id}/clients/{client_id}/link-campaigns', { params: { path: scope(agencyId, clientId) }, body: input }));
}

export function updateCampaign(agencyId: string, clientId: string, campaignId: string, change: { label?: string; status?: 'active' | 'archived' }) {
  return call(
    api.PATCH('/agencies/{agency_id}/clients/{client_id}/link-campaigns/{campaign_id}', {
      params: { path: { ...scope(agencyId, clientId), campaign_id: campaignId } },
      body: change,
    }),
  );
}

export function createContent(agencyId: string, clientId: string, input: { external_code: string; platform_label?: string | null }) {
  return call(
    api.POST('/agencies/{agency_id}/clients/{client_id}/link-content-references', { params: { path: scope(agencyId, clientId) }, body: input }),
  );
}

export function updateContent(
  agencyId: string,
  clientId: string,
  contentId: string,
  change: { platform_label?: string; status?: 'active' | 'archived' },
) {
  return call(
    api.PATCH('/agencies/{agency_id}/clients/{client_id}/link-content-references/{content_id}', {
      params: { path: { ...scope(agencyId, clientId), content_id: contentId } },
      body: change,
    }),
  );
}

export function createTemplate(agencyId: string, clientId: string, input: { name: string; parameters: Record<string, string> }) {
  return call(api.POST('/agencies/{agency_id}/clients/{client_id}/link-utm-templates', { params: { path: scope(agencyId, clientId) }, body: input }));
}

/** A template keeps its name; a change of its values raises its revision, and issued links keep theirs. */
export function updateTemplate(
  agencyId: string,
  clientId: string,
  templateId: string,
  change: { parameters?: Record<string, string>; status?: 'active' | 'archived' },
) {
  return call(
    api.PATCH('/agencies/{agency_id}/clients/{client_id}/link-utm-templates/{template_id}', {
      params: { path: { ...scope(agencyId, clientId), template_id: templateId } },
      body: change,
    }),
  );
}

export function createSite(agencyId: string, clientId: string, input: { origin: string; query_names: string[] }) {
  return call(
    api.POST('/agencies/{agency_id}/clients/{client_id}/link-destination-origins', { params: { path: scope(agencyId, clientId) }, body: input }),
  );
}

export function updateSite(
  agencyId: string,
  clientId: string,
  originId: string,
  change: { query_names?: string[]; status?: 'active' | 'disabled' },
) {
  return call(
    api.PATCH('/agencies/{agency_id}/clients/{client_id}/link-destination-origins/{origin_id}', {
      params: { path: { ...scope(agencyId, clientId), origin_id: originId } },
      body: change,
    }),
  );
}

export function claimDomain(agencyId: string, clientId: string, hostname: string) {
  return call(api.POST('/agencies/{agency_id}/clients/{client_id}/link-domains', { params: { path: scope(agencyId, clientId) }, body: { hostname } }));
}

/** Turns a domain off at once. Its name stays reserved to the client. */
export function disableDomain(agencyId: string, clientId: string, domainId: string) {
  return call(
    api.PATCH('/agencies/{agency_id}/clients/{client_id}/link-domains/{domain_id}', {
      params: { path: { ...scope(agencyId, clientId), domain_id: domainId } },
      body: { status: 'disabled' },
    }),
  );
}

/** A new DNS record for the domain. Its value is in this answer only; earlier records stop counting. */
export function issueChallenge(agencyId: string, clientId: string, domainId: string) {
  return call(
    api.POST('/agencies/{agency_id}/clients/{client_id}/link-domains/{domain_id}/challenge', {
      params: { path: { ...scope(agencyId, clientId), domain_id: domainId } },
    }),
  );
}

export function checkDomain(agencyId: string, clientId: string, domainId: string) {
  return call(
    api.POST('/agencies/{agency_id}/clients/{client_id}/link-domains/{domain_id}/verify', {
      params: { path: { ...scope(agencyId, clientId), domain_id: domainId } },
    }),
  );
}
