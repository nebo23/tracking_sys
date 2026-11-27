import { createHmac, randomUUID } from 'node:crypto';

import { stack } from './stack.ts';

// What a client's website and servers send to the collector, made up for the journeys: a consent,
// a page view and signed webhooks. Every value is synthetic and goes to the disposable API only.

/** A visitor of a website agrees to first-party analytics. Returns the visitor's token. */
export async function grantConsent(publicKey: string, site: string): Promise<string> {
  const response = await fetch(`${stack.apiOrigin}/collect/v1/${publicKey}/consent`, {
    method: 'POST',
    headers: { Origin: site, 'Content-Type': 'text/plain' },
    body: JSON.stringify({ choices: { 'analytics.first_party': 'granted' } }),
  });
  if (response.status !== 200) throw new Error(`The consent was not recorded: ${response.status} ${await response.text()}`);
  const token = ((await response.json()) as { subject_token: string | null }).subject_token;
  if (!token) throw new Error('The consent gave no visitor token.');
  return token;
}

/** The same visitor views a page. The public route answers 202 whatever it decides. */
export async function sendPageView(publicKey: string, site: string, token: string): Promise<void> {
  const response = await fetch(`${stack.apiOrigin}/collect/v1/${publicKey}/events`, {
    method: 'POST',
    headers: { Origin: site, 'Content-Type': 'text/plain' },
    body: JSON.stringify({
      schema_version: 1,
      event_id: randomUUID(),
      event_type: 'page_view',
      occurred_at: new Date().toISOString(),
      subject_token: token,
      payload: { url: `${site}/ramadan-box` },
    }),
  });
  if (response.status !== 202) throw new Error(`The page view was not received: ${response.status} ${await response.text()}`);
}

/** Posts a body signed as the project's webhooks are: X-Tracking-Signature t=<seconds>,v1=<HMAC-SHA256 of "t.body">. */
export async function signedPost(address: string, secret: string, body: unknown): Promise<Response> {
  const text = JSON.stringify(body);
  const seconds = Math.floor(Date.now() / 1000);
  const signature = createHmac('sha256', secret).update(`${seconds}.${text}`).digest('hex');
  return fetch(address, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Tracking-Signature': `t=${seconds},v1=${signature}` }, body: text });
}

/** A booking made in another booking tool, delivered through a signed webhook source. */
export const bookingCreated = (bookingId: string) => {
  const start = new Date(Date.now() + 2 * 24 * 60 * 60 * 1000);
  return {
    type: 'booking.created',
    id: `evt-${randomUUID()}`,
    occurred_at: new Date().toISOString(),
    booking: { id: bookingId, event_type: 'consultation', start_at: start.toISOString(), end_at: new Date(start.getTime() + 30 * 60 * 1000).toISOString() },
  };
};

/** A deal that reached a stage in the client's CRM, delivered through a signed webhook source. */
export const dealStage = (dealId: string, pipeline: string, stage: string) => ({
  type: 'deal.stage_changed',
  id: `evt-${randomUUID()}`,
  occurred_at: new Date().toISOString(),
  deal: { id: dealId, pipeline, stage },
});
