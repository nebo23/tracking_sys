import { queryOptions } from '@tanstack/react-query';

import { api, call } from './client';
import { clientKey } from './clients';
import type { components } from './schema';

export type PaymentSource = components['schemas']['PaymentSourceResponse'];
export type PaymentSourceInput = components['schemas']['PaymentSourceInput'];
export type IntegrationSource = components['schemas']['SourceView'];
export type IssuedIntegrationSource = components['schemas']['app__api__integrations__IssuedSource'];
export type IntegrationKind = components['schemas']['app__api__integrations__SourceInput']['kind'];
export type BookingReport = components['schemas']['BookingReport'];
export type StageRule = components['schemas']['RuleView'];
export type DealReport = components['schemas']['DealReport'];
export type WhatsappNumber = components['schemas']['NumberView'];
export type ReferralReport = components['schemas']['ReferralReport'];
export type ConversionDestination = components['schemas']['DestinationResponse'];
export type ConversionDelivery = components['schemas']['DeliveryResponse'];

const scope = (agencyId: string, clientId: string) => ({ agency_id: agencyId, client_id: clientId });

// Every list of the integrations of a client has a key under that client (acceptance criterion 2).
export const integrationsKey = (agencyId: string, clientId: string, list?: string) =>
  list ? clientKey(agencyId, clientId, 'integrations', list) : clientKey(agencyId, clientId, 'integrations');

// ---------------------------------------------------------------- Payments --
/** The Paymob sources of a client. Owners and admins only, as the API allows. */
export const paymentSourcesQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: integrationsKey(agencyId, clientId, 'payment-sources'),
    queryFn: () => call(api.GET('/agencies/{agency_id}/clients/{client_id}/payment-sources', { params: { path: scope(agencyId, clientId) } })),
  });

/** The merchant's HMAC secret is sent once and never returned. */
export function createPaymentSource(agencyId: string, clientId: string, input: PaymentSourceInput) {
  return call(api.POST('/agencies/{agency_id}/clients/{client_id}/payment-sources', { params: { path: scope(agencyId, clientId) }, body: input }));
}

export function updatePaymentSource(
  agencyId: string,
  clientId: string,
  sourceId: string,
  change: { name?: string; status?: 'active' | 'disabled'; live_integration_ids?: number[] },
) {
  return call(
    api.PATCH('/agencies/{agency_id}/clients/{client_id}/payment-sources/{source_id}', {
      params: { path: { ...scope(agencyId, clientId), source_id: sourceId } },
      body: change,
    }),
  );
}

/** Replaces the HMAC secret. The previous one keeps working for 24 hours. */
export function replacePaymentSecret(agencyId: string, clientId: string, sourceId: string, hmacSecret: string) {
  return call(
    api.PUT('/agencies/{agency_id}/clients/{client_id}/payment-sources/{source_id}/secret', {
      params: { path: { ...scope(agencyId, clientId), source_id: sourceId } },
      body: { hmac_secret: hmacSecret },
    }),
  );
}

// ------------------------------------------------------ Bookings and the CRM --
export const integrationSourcesQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: integrationsKey(agencyId, clientId, 'integration-sources'),
    queryFn: () => call(api.GET('/agencies/{agency_id}/clients/{client_id}/integration-sources', { params: { path: scope(agencyId, clientId) } })),
  });

/** A Cal.com source takes the client's own secret; a signed webhook source is issued one, returned once. */
export function createIntegrationSource(agencyId: string, clientId: string, input: { kind: IntegrationKind; name: string; secret?: string }) {
  return call(api.POST('/agencies/{agency_id}/clients/{client_id}/integration-sources', { params: { path: scope(agencyId, clientId) }, body: input }));
}

export function updateIntegrationSource(agencyId: string, clientId: string, sourceId: string, change: { name?: string; status?: 'active' | 'disabled' }) {
  return call(
    api.PATCH('/agencies/{agency_id}/clients/{client_id}/integration-sources/{source_id}', {
      params: { path: { ...scope(agencyId, clientId), source_id: sourceId } },
      body: change,
    }),
  );
}

/** A Cal.com source takes its new secret; a signed webhook source sends none and is issued one. */
export function replaceIntegrationSecret(agencyId: string, clientId: string, sourceId: string, secret: string | null) {
  return call(
    api.PUT('/agencies/{agency_id}/clients/{client_id}/integration-sources/{source_id}/secret', {
      params: { path: { ...scope(agencyId, clientId), source_id: sourceId } },
      body: secret === null ? {} : { secret },
    }),
  );
}

/** The booking totals of a client, for every reader. No personal field is part of them. */
export const bookingsQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: integrationsKey(agencyId, clientId, 'bookings'),
    queryFn: () => call(api.GET('/agencies/{agency_id}/clients/{client_id}/bookings', { params: { path: scope(agencyId, clientId) } })),
  });

export const stageRulesQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: integrationsKey(agencyId, clientId, 'stage-rules'),
    queryFn: () => call(api.GET('/agencies/{agency_id}/clients/{client_id}/crm/stage-rules', { params: { path: scope(agencyId, clientId) } })),
  });

export function createStageRule(agencyId: string, clientId: string, input: { pipeline: string; stage: string; outcome: 'won' | 'lost' }) {
  return call(api.POST('/agencies/{agency_id}/clients/{client_id}/crm/stage-rules', { params: { path: scope(agencyId, clientId) }, body: input }));
}

export function updateStageRule(agencyId: string, clientId: string, ruleId: string, change: { outcome?: 'won' | 'lost'; status?: 'active' | 'disabled' }) {
  return call(
    api.PATCH('/agencies/{agency_id}/clients/{client_id}/crm/stage-rules/{rule_id}', {
      params: { path: { ...scope(agencyId, clientId), rule_id: ruleId } },
      body: change,
    }),
  );
}

/** The deal totals of a client, without amounts, for every reader. */
export const dealsQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: integrationsKey(agencyId, clientId, 'deals'),
    queryFn: () => call(api.GET('/agencies/{agency_id}/clients/{client_id}/crm/deals', { params: { path: scope(agencyId, clientId) } })),
  });

// ---------------------------------------------------------------- WhatsApp --
export const numbersQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: integrationsKey(agencyId, clientId, 'whatsapp-numbers'),
    queryFn: () => call(api.GET('/agencies/{agency_id}/clients/{client_id}/whatsapp-numbers', { params: { path: scope(agencyId, clientId) } })),
  });

/** Registers a claim on a number. It routes nothing until the platform operator verifies it. */
export function registerNumber(agencyId: string, clientId: string, input: { phone_number_id: string; name: string }) {
  return call(api.POST('/agencies/{agency_id}/clients/{client_id}/whatsapp-numbers', { params: { path: scope(agencyId, clientId) }, body: input }));
}

export function updateNumber(agencyId: string, clientId: string, numberId: string, change: { name?: string; status?: 'active' | 'disabled' }) {
  return call(
    api.PATCH('/agencies/{agency_id}/clients/{client_id}/whatsapp-numbers/{number_id}', {
      params: { path: { ...scope(agencyId, clientId), number_id: numberId } },
      body: change,
    }),
  );
}

/** Messages by the ad or post that started them, over UTC days (the last 30 when none are given). */
export const referralsQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: integrationsKey(agencyId, clientId, 'referrals'),
    queryFn: () => call(api.GET('/agencies/{agency_id}/clients/{client_id}/whatsapp/referrals', { params: { path: scope(agencyId, clientId) } })),
  });

// -------------------------------------------------------- Meta conversions --
export const destinationsQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: integrationsKey(agencyId, clientId, 'destinations'),
    queryFn: () => call(api.GET('/agencies/{agency_id}/clients/{client_id}/conversion-destinations', { params: { path: scope(agencyId, clientId) } })),
  });

/** A destination is created off; turning it on starts deliveries of verified sales with consent. */
export function createDestination(agencyId: string, clientId: string, input: { connection_id: string; event_name: string; test_event_code: string | null }) {
  return call(
    api.POST('/agencies/{agency_id}/clients/{client_id}/conversion-destinations', { params: { path: scope(agencyId, clientId) }, body: input }),
  );
}

export function updateDestination(
  agencyId: string,
  clientId: string,
  destinationId: string,
  change: { enabled?: boolean; event_name?: string; test_event_code?: string; clear_test_event_code?: boolean },
) {
  return call(
    api.PATCH('/agencies/{agency_id}/clients/{client_id}/conversion-destinations/{destination_id}', {
      params: { path: { ...scope(agencyId, clientId), destination_id: destinationId } },
      // The API reads a missing clear_test_event_code as false; the contract lists it as present.
      body: { clear_test_event_code: false, ...change },
    }),
  );
}

/** The newest deliveries with their values. The API asks for financial access. */
export const deliveriesQuery = (agencyId: string, clientId: string) =>
  queryOptions({
    queryKey: integrationsKey(agencyId, clientId, 'deliveries'),
    queryFn: () => call(api.GET('/agencies/{agency_id}/clients/{client_id}/conversion-deliveries', { params: { path: scope(agencyId, clientId) } })),
  });

export function requeueDelivery(agencyId: string, clientId: string, deliveryId: string) {
  return call(
    api.POST('/agencies/{agency_id}/clients/{client_id}/conversion-deliveries/{delivery_id}/requeue', {
      params: { path: { ...scope(agencyId, clientId), delivery_id: deliveryId } },
    }),
  );
}

export function dismissDelivery(agencyId: string, clientId: string, deliveryId: string) {
  return call(
    api.POST('/agencies/{agency_id}/clients/{client_id}/conversion-deliveries/{delivery_id}/dismiss', {
      params: { path: { ...scope(agencyId, clientId), delivery_id: deliveryId } },
    }),
  );
}
