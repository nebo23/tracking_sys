import type { ProviderId } from '@/api/connections';
import { syntheticProvidersEnabled } from '@/app/config';
import type { MessageId } from '@/i18n';

type Glyph = 'instagram' | 'youtube' | 'meta';

export interface Provider {
  id: ProviderId;
  name: MessageId;
  /** What Connect reads from the account, in one sentence. */
  reads: MessageId;
  /** The provider's own mark. A provider without one is drawn with a plain icon. */
  glyph: Glyph | null;
  /** The account number the connect request must name (specification 014), if any. */
  account: { label: MessageId; hint: MessageId; pattern: RegExp } | null;
  /**
   * The version of the approval the account holder gives: the agency and the client's members
   * read the account as their agents (specification 011, D13). Null when none is needed.
   */
  approval: string | null;
  /** A stand-in used for development and the browser journeys. It contacts nobody. */
  synthetic: boolean;
}

// The number of a Meta ad account, with or without its "act_" prefix (contracts/openapi.json, ConnectInput).
const adAccount = /^(act_)?[1-9][0-9]{0,19}$/;
const adAccountField = { label: 'connections.connect.adAccount', hint: 'connections.connect.adAccountHint', pattern: adAccount } as const;

// The approval text of the development slice. The owner's wording replaces it with a new version.
const AGENT_APPROVAL = 'dev-agent-approval-1';

const product: Provider[] = [
  { id: 'instagram', name: 'provider.instagram', reads: 'provider.instagram.reads', glyph: 'instagram', account: null, approval: null, synthetic: false },
  { id: 'youtube', name: 'provider.youtube', reads: 'provider.youtube.reads', glyph: 'youtube', account: null, approval: AGENT_APPROVAL, synthetic: false },
  { id: 'meta_ads', name: 'provider.meta_ads', reads: 'provider.meta_ads.reads', glyph: 'meta', account: adAccountField, approval: null, synthetic: false },
];

const standIns: Provider[] = [
  { id: 'synthetic', name: 'provider.synthetic', reads: 'provider.synthetic.reads', glyph: null, account: null, approval: null, synthetic: true },
  {
    id: 'synthetic_instagram',
    name: 'provider.synthetic_instagram',
    reads: 'provider.synthetic.reads',
    glyph: 'instagram',
    account: null,
    approval: null,
    synthetic: true,
  },
  {
    id: 'synthetic_youtube',
    name: 'provider.synthetic_youtube',
    reads: 'provider.synthetic.reads',
    glyph: 'youtube',
    account: null,
    approval: AGENT_APPROVAL,
    synthetic: true,
  },
  {
    id: 'synthetic_meta_ads',
    name: 'provider.synthetic_meta_ads',
    reads: 'provider.synthetic.reads',
    glyph: 'meta',
    account: adAccountField,
    approval: null,
    synthetic: true,
  },
];

// Connections of a kind this page does not start are still named when the API lists them.
const named: Record<string, { name: MessageId; glyph: Glyph | null }> = {
  meta_capi: { name: 'provider.meta_capi', glyph: 'meta' },
  synthetic_meta_capi: { name: 'provider.synthetic_meta_capi', glyph: 'meta' },
};

const all = [...product, ...standIns];

/** The providers a person can choose when connecting an account. */
export const connectable: readonly Provider[] = syntheticProvidersEnabled ? all : product;

export const providerOf = (id: string): Provider | undefined => all.find((provider) => provider.id === id);

/** How a connection's provider is shown: its name and mark, or the API's own word for an unknown one. */
export function providerLabel(id: string): { name: MessageId | null; glyph: Glyph | null } {
  const known = providerOf(id) ?? named[id];
  return known ? { name: known.name, glyph: known.glyph } : { name: null, glyph: null };
}
