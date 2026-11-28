import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { describeError, type ErrorMessage } from '@/api/errors';
import { createSource, rotateSecret, sourcesQuery, trackingKey, updateSource, type IngestionSource, type SourceUpdate } from '@/api/tracking';
import { apiOrigin } from '@/app/config';
import { useClient } from '@/app/tenant';
import { Badge } from '@/components/Badge';
import { CopyField } from '@/components/CopyField';
import { EmptyState } from '@/components/EmptyState';
import { Field, TextAreaField } from '@/components/Field';
import { FormDialog } from '@/components/FormDialog';
import { Icon } from '@/components/Icon';
import { QueryStates } from '@/components/ListStates';
import { ErrorNotice, Notice } from '@/components/Notice';
import { RowMenu, type RowAction } from '@/components/RowMenu';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { ShownOnceDialog } from '@/components/ShownOnceDialog';
import { Day } from '@/components/Time';
import type { MessageId } from '@/i18n';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';

import { exactOrigins, installCode, noticeDigest, sourceNameError, SOURCE_NAME_MAX, splitOrigins, TRACKER_VERSION } from './rules';

type Kind = 'browser' | 'webhook';

/** The address a server sends its signed events to. */
export const webhookAddress = (sourceId: string) => `${apiOrigin}/webhooks/v1/${sourceId}/events`;

/** The digest of the text in a notice field, calculated as it is typed. */
function useDigest(text: string): string | null {
  const [digest, setDigest] = useState<string | null>(null);
  useEffect(() => {
    let current = true;
    if (text === '') {
      setDigest(null);
      return;
    }
    void noticeDigest(text).then((value) => {
      if (current) setDigest(value);
    });
    return () => {
      current = false;
    };
  }, [text]);
  return digest;
}

interface SourceDialogProps {
  source: IngestionSource | null;
  onCreated: (source: IngestionSource, secret: string | null) => void;
  onClose: () => void;
}

/** Creates a browser or webhook source, or changes one: its name, and for a website its sites and notice. */
function SourceDialog({ source, onCreated, onClose }: SourceDialogProps) {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId, clientId } = useClient();
  const [kind, setKind] = useState<Kind>(source?.kind === 'webhook' ? 'webhook' : 'browser');
  const [name, setName] = useState(source?.name ?? '');
  const [sites, setSites] = useState((source?.allowed_origins ?? []).join('\n'));
  const [notice, setNotice] = useState('');
  const [errors, setErrors] = useState<{ name?: MessageId | null; sites?: MessageId | null; notice?: MessageId | null }>({});
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const sitesRef = useRef<HTMLTextAreaElement>(null);
  const noticeRef = useRef<HTMLTextAreaElement>(null);
  const digest = useDigest(notice);
  const browser = kind === 'browser';

  const request = useMutation({
    mutationFn: async (change: { name: string; origins: string[]; digest: string | null }) => {
      if (source) {
        const update: SourceUpdate = {};
        if (change.name !== source.name) update.name = change.name;
        if (source.kind === 'browser' && change.origins.join() !== (source.allowed_origins ?? []).join()) update.allowed_origins = change.origins;
        if (source.kind === 'browser' && change.digest) update.notice_sha256 = change.digest;
        if (Object.keys(update).length > 0) await updateSource(agencyId, clientId, source.id, update);
        return null;
      }
      return createSource(
        agencyId,
        clientId,
        browser ? { kind, name: change.name, allowed_origins: change.origins, notice_sha256: change.digest } : { kind, name: change.name },
      );
    },
    // The answer of a webhook source holds its secret. It is handed on and not kept by the request.
    gcTime: 0,
    async onSuccess(issued) {
      await queryClient.invalidateQueries({ queryKey: trackingKey(agencyId, clientId, 'sources') });
      if (issued) onCreated(issued.source, issued.signing_secret ?? null);
      else onClose();
    },
    onError: (failure) => setProblem(describeError(failure, { validation_failed: 'tracking.sources.error.refused' })),
  });

  const submit = async () => {
    const origins = browser ? exactOrigins(splitOrigins(sites)) : { origins: [], error: null };
    // A new website source needs its notice; a change keeps the notice unless a new text is given.
    const noticeNeeded = browser && !source && notice === '';
    const found = { name: sourceNameError(name), sites: origins.error, notice: noticeNeeded ? ('field.error.required' as const) : null };
    setErrors(found);
    setProblem(null);
    if (focusFirstInvalid([found.name, nameRef], [found.sites, sitesRef], [found.notice, noticeRef])) return;
    request.mutate({ name: name.trim(), origins: origins.origins, digest: browser && notice !== '' ? await noticeDigest(notice) : null });
  };

  const kindChoice = (value: Kind) => (
    <label className="c-choice a-choice--card">
      <input className="c-radio" type="radio" name="source-kind" value={value} checked={kind === value} onChange={() => setKind(value)} />
      <span className="u-strong">
        <FormattedMessage id={`tracking.kind.${value}`} />
      </span>
      <span className="u-secondary a-choice__more">
        <FormattedMessage id={`tracking.kind.${value}.hint`} />
      </span>
    </label>
  );

  return (
    <FormDialog
      isOpen
      wide
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={source ? <FormattedMessage id="tracking.sources.change" values={{ name: source.name }} /> : <FormattedMessage id="tracking.sources.new" />}
      submitLabel={<FormattedMessage id={source ? 'common.save' : 'tracking.sources.create'} />}
      busy={request.isPending}
      onSubmit={() => void submit()}
    >
      <ErrorNotice message={problem} />
      {source ? null : (
        <fieldset className="a-fieldset">
          <legend className="c-field__label">
            <FormattedMessage id="tracking.sources.kind" />
          </legend>
          <div className="l-stack l-stack--tight">
            {kindChoice('browser')}
            {kindChoice('webhook')}
          </div>
        </fieldset>
      )}
      <Field
        id="source-name"
        ref={nameRef}
        size="md"
        autoComplete="off"
        maxLength={SOURCE_NAME_MAX}
        label={<FormattedMessage id="tracking.sources.name" />}
        hint={<FormattedMessage id="tracking.sources.nameHint" />}
        required
        value={name}
        onChange={setName}
        error={errors.name}
      />
      {browser ? (
        <>
          <TextAreaField
            id="source-sites"
            ref={sitesRef}
            ltr
            rows={3}
            label={<FormattedMessage id="tracking.sources.sites" />}
            hint={<FormattedMessage id="tracking.sources.sitesHint" />}
            required
            value={sites}
            onChange={setSites}
            error={errors.sites}
          />
          <TextAreaField
            id="source-notice"
            ref={noticeRef}
            rows={4}
            label={<FormattedMessage id={source ? 'tracking.sources.noticeNew' : 'tracking.sources.notice'} />}
            hint={<FormattedMessage id="tracking.sources.noticeHint" />}
            required={!source}
            value={notice}
            onChange={setNotice}
            error={errors.notice}
          />
          <p className="c-field__hint">
            {digest ? (
              <FormattedMessage id="tracking.sources.digest" values={{ digest: <span className="u-mono u-ltr a-break">{digest}</span> }} />
            ) : source?.notice_sha256 ? (
              <FormattedMessage id="tracking.sources.digestKept" values={{ digest: <span className="u-mono u-ltr a-break">{source.notice_sha256}</span> }} />
            ) : (
              intl.formatMessage({ id: 'tracking.sources.digestNone' })
            )}
          </p>
        </>
      ) : null}
    </FormDialog>
  );
}

/** What a website installs to send its visitors' consent and events to this source. */
function InstallDialog({ source, onClose }: { source: IngestionSource; onClose: () => void }) {
  return (
    <FormDialog
      isOpen
      wide
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="tracking.install.title" values={{ name: source.name }} />}
    >
      <Notice tone="info" quiet>
        <FormattedMessage id="tracking.install.public" />
      </Notice>
      <CopyField id="install-key" label={<FormattedMessage id="tracking.install.key" />} value={source.public_key ?? ''} />
      <CopyField id="install-code" label={<FormattedMessage id="tracking.install.code" />} value={installCode(apiOrigin, source.public_key ?? '')} multiline />
      <ol className="a-steps">
        <li>
          <FormattedMessage id="tracking.install.step.files" values={{ version: TRACKER_VERSION }} />
        </li>
        <li>
          <FormattedMessage id="tracking.install.step.policy" values={{ collector: apiOrigin }} />
        </li>
        <li>
          <FormattedMessage id="tracking.install.step.consent" />
        </li>
        <li>
          <FormattedMessage id="tracking.install.step.forms" />
        </li>
      </ol>
    </FormDialog>
  );
}

/** Where a server sends signed events, and how it signs them. */
function WebhookFacts({ source }: { source: IngestionSource }) {
  return (
    <>
      <CopyField id={`webhook-address-${source.id}`} label={<FormattedMessage id="tracking.webhook.address" />} value={webhookAddress(source.id)} />
      <p className="c-field__hint">
        <FormattedMessage id="tracking.webhook.signature" values={{ header: <span className="u-mono u-ltr">X-Tracking-Signature: t=…,v1=…</span> }} />
      </p>
    </>
  );
}

function WebhookDialog({ source, onClose }: { source: IngestionSource; onClose: () => void }) {
  return (
    <FormDialog
      isOpen
      wide
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="tracking.webhook.title" values={{ name: source.name }} />}
    >
      <WebhookFacts source={source} />
    </FormDialog>
  );
}

/** The browser and webhook sources of the client, with what each needs to send events. Owners and admins only. */
export function SourcesCard() {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId, clientId } = useClient();
  const sources = useQuery(sourcesQuery(agencyId, clientId));
  const [dialog, setDialog] = useState<IngestionSource | 'new' | null>(null);
  const [installing, setInstalling] = useState<IngestionSource | null>(null);
  const [addressing, setAddressing] = useState<IngestionSource | null>(null);
  const [secret, setSecret] = useState<{ source: IngestionSource; value: string; rotated: boolean } | null>(null);
  const [rotating, setRotating] = useState<IngestionSource | null>(null);
  const [turningOff, setTurningOff] = useState<IngestionSource | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: trackingKey(agencyId, clientId, 'sources') });
  const turnOn = useMutation({
    mutationFn: (source: IngestionSource) => updateSource(agencyId, clientId, source.id, { status: 'active' }),
    onSuccess: () => {
      setProblem(null);
      return refresh();
    },
    onError: (failure) => setProblem(describeError(failure)),
  });

  const rows = [...(sources.data ?? [])].sort((first, second) => {
    if ((first.status === 'active') !== (second.status === 'active')) return first.status === 'active' ? -1 : 1;
    return second.created_at.localeCompare(first.created_at);
  });

  const actionsOf = (source: IngestionSource): RowAction[] => {
    const say = (id: MessageId) => ({ label: <FormattedMessage id={id} />, text: intl.formatMessage({ id }) });
    const actions: RowAction[] = [];
    if (source.kind === 'browser') actions.push({ id: 'install', ...say('tracking.action.install'), onAction: () => setInstalling(source) });
    if (source.kind === 'webhook') {
      actions.push({ id: 'address', ...say('tracking.action.address'), onAction: () => setAddressing(source) });
      actions.push({ id: 'rotate', ...say('tracking.action.rotate'), onAction: () => setRotating(source) });
    }
    actions.push({ id: 'change', ...say(source.kind === 'browser' ? 'tracking.action.change' : 'links.action.rename'), onAction: () => setDialog(source) });
    actions.push(
      source.status === 'active'
        ? { id: 'off', ...say('links.action.turnOff'), danger: true, onAction: () => setTurningOff(source) }
        : { id: 'on', ...say('links.action.turnOn'), onAction: () => turnOn.mutate(source) },
    );
    return actions;
  };

  return (
    <section className="c-card" aria-labelledby="sources-title">
      <div className="c-card__header">
        <div>
          <h2 className="c-card__title" id="sources-title">
            <FormattedMessage id="tracking.sources.title" />
          </h2>
          <p className="c-card__subtitle">
            <FormattedMessage id="tracking.sources.lead" />
          </p>
        </div>
        {sources.isSuccess ? (
          <button type="button" className="c-btn c-btn--secondary c-btn--sm" onClick={() => setDialog('new')}>
            <Icon name="plus" size="sm" />
            <FormattedMessage id="tracking.sources.new" />
          </button>
        ) : null}
      </div>
      <div className="c-card__body c-card__body--flush">
        <QueryStates query={sources} />
        <div className="a-pad--x">
          <ErrorNotice message={problem} />
        </div>
        {sources.isSuccess && rows.length === 0 ? (
          <EmptyState icon="activity" title={<FormattedMessage id="tracking.sources.empty.title" />} level={3}>
            <FormattedMessage id="tracking.sources.empty.text" />
          </EmptyState>
        ) : null}
        {rows.length > 0 ? (
          <div className="c-table-wrap">
            <table className="c-table">
              <thead>
                <tr>
                  <th scope="col">
                    <FormattedMessage id="tracking.sources.name" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="team.column.state" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="tracking.sources.sites" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="links.column.created" />
                  </th>
                  <th scope="col">
                    <span className="u-sr">
                      <FormattedMessage id="clients.column.actions" />
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((source) => (
                  <tr key={source.id}>
                    <td>
                      <span className="c-table__primary">{source.name}</span>
                      <span className="c-table__sub">
                        <FormattedMessage id={source.kind === 'webhook' ? 'tracking.kind.webhook' : 'tracking.kind.browser'} />
                        {source.public_key ? (
                          <>
                            {' · '}
                            <span className="u-mono u-ltr">{source.public_key}</span>
                          </>
                        ) : null}
                      </span>
                    </td>
                    <td>
                      {source.status === 'active' ? (
                        <Badge tone="success" icon="circle-check">
                          <FormattedMessage id="tracking.state.on" />
                        </Badge>
                      ) : (
                        <Badge icon="circle-pause">
                          <FormattedMessage id="tracking.state.off" />
                        </Badge>
                      )}
                    </td>
                    {source.allowed_origins && source.allowed_origins.length > 0 ? (
                      <td>
                        <span className="l-cluster a-chips">
                          {source.allowed_origins.map((origin) => (
                            <span key={origin} className="c-chip u-mono u-ltr">
                              {origin.replace(/^https?:\/\//, '')}
                            </span>
                          ))}
                        </span>
                      </td>
                    ) : (
                      <td className="is-absent">
                        <FormattedMessage id="tracking.sources.server" />
                      </td>
                    )}
                    <td>
                      <Day value={source.created_at} />
                    </td>
                    <td className="is-num">
                      <RowMenu label={intl.formatMessage({ id: 'links.actionsForNamed' }, { name: source.name })} actions={actionsOf(source)} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
      {dialog ? (
        <SourceDialog
          source={dialog === 'new' ? null : dialog}
          onClose={() => setDialog(null)}
          onCreated={(source, value) => {
            setDialog(null);
            if (value) setSecret({ source, value, rotated: false });
            else setInstalling(source);
          }}
        />
      ) : null}
      {installing ? <InstallDialog source={installing} onClose={() => setInstalling(null)} /> : null}
      {addressing ? <WebhookDialog source={addressing} onClose={() => setAddressing(null)} /> : null}
      {rotating ? (
        <ConfirmDialog
          title="tracking.rotate.title"
          text="tracking.rotate.text"
          submit="tracking.action.rotate"
          keep="tracking.rotate.keep"
          onClose={() => setRotating(null)}
          onConfirm={async () => {
            const issued = await rotateSecret(agencyId, clientId, rotating.id);
            setSecret({ source: rotating, value: issued.signing_secret, rotated: true });
            setRotating(null);
          }}
        />
      ) : null}
      {turningOff ? (
        <ConfirmDialog
          title={turningOff.kind === 'browser' ? 'tracking.off.browser.title' : 'tracking.off.webhook.title'}
          text={turningOff.kind === 'browser' ? 'tracking.off.browser.text' : 'tracking.off.webhook.text'}
          submit="links.action.turnOff"
          keep="links.sites.off.keep"
          danger
          onClose={() => setTurningOff(null)}
          onConfirm={async () => {
            await updateSource(agencyId, clientId, turningOff.id, { status: 'disabled' });
            await refresh();
            setTurningOff(null);
          }}
        />
      ) : null}
      {secret ? (
        <ShownOnceDialog
          title={<FormattedMessage id={secret.rotated ? 'tracking.secret.rotated' : 'tracking.secret.title'} values={{ name: secret.source.name }} />}
          notice={<FormattedMessage id={secret.rotated ? 'tracking.secret.onceRotated' : 'tracking.secret.once'} />}
          values={[{ id: 'webhook-secret', label: <FormattedMessage id="tracking.secret.label" />, value: secret.value }]}
          onClose={() => setSecret(null)}
        >
          <WebhookFacts source={secret.source} />
        </ShownOnceDialog>
      ) : null}
    </section>
  );
}

