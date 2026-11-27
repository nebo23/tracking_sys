import { queryOptions } from '@tanstack/react-query';

import { api, call } from './client';
import { clientKey } from './clients';
import type { components } from './schema';

export type IngestionSource = components['schemas']['SourceResponse'];
export type IssuedIngestionSource = components['schemas']['app__api__collection_schemas__IssuedSource'];
export type SourceInput = components['schemas']['app__api__collection_schemas__SourceInput'];
export type SourceUpdate = components['schemas']['app__api__collection_schemas__SourceUpdate'];
export type CollectionForm = components['schemas']['FormResponse'];
export type FormField = components['schemas']['FormFieldDefinition'];
export type Diagnostic = components['schemas']['DiagnosticResponse'];
export type ErasureRequest = components['schemas']['ErasureRequestResponse'];
export type ErasureInput = components['schemas']['ErasureRequestInput'];

const scope = (agencyId: string, clientId: string) => ({ agency_id: agencyId, client_id: clientId });

// Every list of the tracking of a client has a key under that client (acceptance criterion 2).
export const trackingKey = (agencyId: string, clientId: string, list?: string) =>
  list ? clientKey(agencyId, clientId, 'tracking', list) : clientKey(agencyId, clientId, 'tracking');

/** The browser and webhook sources of a client. Owners and admins only, as the API allows. */
export const sourcesQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: trackingKey(agencyId, clientId, 'sources'),
    queryFn: () => call(api.GET('/agencies/{agency_id}/clients/{client_id}/ingestion-sources', { params: { path: scope(agencyId, clientId) } })),
  });

export const formsQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: trackingKey(agencyId, clientId, 'forms'),
    queryFn: () => call(api.GET('/agencies/{agency_id}/clients/{client_id}/collection-forms', { params: { path: scope(agencyId, clientId) } })),
  });

/** The daily counters of a range of at most 31 days, for every reader of the client. */
export const diagnosticsQuery = (agencyId: string, clientId: string, start: string, end: string) =>
  queryOptions({
    queryKey: clientKey(agencyId, clientId, 'tracking', 'diagnostics', start, end),
    queryFn: () =>
      call(
        api.GET('/agencies/{agency_id}/clients/{client_id}/event-diagnostics', {
          params: { path: scope(agencyId, clientId), query: { start, end } },
        }),
      ),
  });

export const erasuresQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: trackingKey(agencyId, clientId, 'erasures'),
    queryFn: () => call(api.GET('/agencies/{agency_id}/clients/{client_id}/deletion-requests', { params: { path: scope(agencyId, clientId) } })),
  });

/** A browser source answers with its public key; a webhook source with its signing secret, once. */
export function createSource(agencyId: string, clientId: string, input: SourceInput) {
  return call(api.POST('/agencies/{agency_id}/clients/{client_id}/ingestion-sources', { params: { path: scope(agencyId, clientId) }, body: input }));
}

export function updateSource(agencyId: string, clientId: string, sourceId: string, change: SourceUpdate) {
  return call(
    api.PATCH('/agencies/{agency_id}/clients/{client_id}/ingestion-sources/{source_id}', {
      params: { path: { ...scope(agencyId, clientId), source_id: sourceId } },
      body: change,
    }),
  );
}

/** A new signing secret, shown once. The previous one keeps working for 24 hours. */
export function rotateSecret(agencyId: string, clientId: string, sourceId: string) {
  return call(
    api.POST('/agencies/{agency_id}/clients/{client_id}/ingestion-sources/{source_id}/secret', {
      params: { path: { ...scope(agencyId, clientId), source_id: sourceId } },
    }),
  );
}

/** Registers a form, or replaces its fields with a new version. */
export function putForm(agencyId: string, clientId: string, formKey: string, fields: FormField[]) {
  return call(
    api.PUT('/agencies/{agency_id}/clients/{client_id}/collection-forms/{form_key}', {
      params: { path: { ...scope(agencyId, clientId), form_key: formKey } },
      body: { fields },
    }),
  );
}

/** Erases one visitor at once: their events, their consent records and their subject. */
export function requestErasure(agencyId: string, clientId: string, input: ErasureInput) {
  return call(api.POST('/agencies/{agency_id}/clients/{client_id}/deletion-requests', { params: { path: scope(agencyId, clientId) }, body: input }));
}
