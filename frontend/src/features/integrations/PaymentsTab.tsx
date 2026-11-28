import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { describeError, type ErrorMessage } from '@/api/errors';
import {
  createPaymentSource,
  integrationsKey,
  paymentSourcesQuery,
  replacePaymentSecret,
  updatePaymentSource,
  type PaymentSource,
} from '@/api/integrations';
import { useClient } from '@/app/tenant';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { CopyField } from '@/components/CopyField';
import { EmptyState } from '@/components/EmptyState';
import { Field, PasswordField } from '@/components/Field';
import { FormDialog } from '@/components/FormDialog';
import { Icon } from '@/components/Icon';
import { QueryStates } from '@/components/ListStates';
import { ErrorNotice, Notice } from '@/components/Notice';
import { RowMenu, type RowAction } from '@/components/RowMenu';
import type { MessageId } from '@/i18n';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';

import { callbackAddress, IntegrationCard, NAME_MAX, NameDialog, nameError, OnOff, SecretDialog, secretError } from './shared';

/** Paymob integration identifiers: 1 to 20 positive whole numbers (PaymentSourceInput). */
export function integrationIds(text: string): { ids: number[]; error: MessageId | null } {
  const parts = text
    .split(/[\s,]+/)
    .map((part) => part.trim())
    .filter(Boolean);
  if (parts.length === 0) return { ids: [], error: 'integrations.paymob.error.idsNone' };
  if (parts.length > 20) return { ids: [], error: 'integrations.paymob.error.idsMany' };
  if (!parts.every((part) => /^[1-9][0-9]{0,17}$/.test(part))) return { ids: [], error: 'integrations.paymob.error.ids' };
  const ids = parts.map(Number);
  if (new Set(ids).size !== ids.length) return { ids: [], error: 'integrations.paymob.error.idsTwice' };
  return { ids, error: null };
}

function AddDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const { agencyId, clientId } = useClient();
  const [name, setName] = useState('');
  const [secret, setSecret] = useState('');
  const [ids, setIds] = useState('');
  const [errors, setErrors] = useState<{ name?: MessageId | null; secret?: MessageId | null; ids?: MessageId | null }>({});
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const secretRef = useRef<HTMLInputElement>(null);
  const idsRef = useRef<HTMLInputElement>(null);
  const request = useMutation({
    mutationFn: (live: number[]) =>
      createPaymentSource(agencyId, clientId, { provider: 'paymob', region: 'egypt', name: name.trim(), hmac_secret: secret, live_integration_ids: live }),
    async onSuccess() {
      await queryClient.invalidateQueries({ queryKey: integrationsKey(agencyId, clientId, 'payment-sources') });
      onClose();
    },
    onError: (failure) => setProblem(describeError(failure, { validation_failed: 'integrations.paymob.error.refused' })),
  });
  const submit = () => {
    const live = integrationIds(ids);
    const found = { name: nameError(name), secret: secretError(secret), ids: live.error };
    setErrors(found);
    setProblem(null);
    if (!focusFirstInvalid([found.name, nameRef], [found.secret, secretRef], [found.ids, idsRef])) request.mutate(live.ids);
  };
  return (
    <FormDialog
      isOpen
      wide
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="integrations.paymob.new" />}
      submitLabel={<FormattedMessage id="integrations.paymob.create" />}
      busy={request.isPending}
      onSubmit={submit}
    >
      <ErrorNotice message={problem} />
      <Field
        id="paymob-name"
        ref={nameRef}
        size="md"
        autoComplete="off"
        maxLength={NAME_MAX}
        label={<FormattedMessage id="integrations.name" />}
        hint={<FormattedMessage id="integrations.paymob.nameHint" />}
        // The dialog was opened to add this source.
        // eslint-disable-next-line jsx-a11y/no-autofocus
        autoFocus
        required
        value={name}
        onChange={setName}
        error={errors.name}
      />
      <PasswordField
        id="paymob-secret"
        ref={secretRef}
        size="md"
        dir="ltr"
        autoComplete="off"
        spellCheck={false}
        maxLength={256}
        label={<FormattedMessage id="integrations.paymob.secret" />}
        hint={<FormattedMessage id="integrations.paymob.secretHint" />}
        required
        value={secret}
        onChange={setSecret}
        error={errors.secret}
      />
      <Field
        id="paymob-ids"
        ref={idsRef}
        size="md"
        dir="ltr"
        inputMode="numeric"
        autoComplete="off"
        label={<FormattedMessage id="integrations.paymob.ids" />}
        hint={<FormattedMessage id="integrations.paymob.idsHint" />}
        required
        value={ids}
        onChange={setIds}
        error={errors.ids}
      />
      <Notice tone="warning" quiet>
        <FormattedMessage id="integrations.paymob.idsWarning" />
      </Notice>
    </FormDialog>
  );
}

function IdsDialog({ source, onClose }: { source: PaymentSource; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { agencyId, clientId } = useClient();
  const [ids, setIds] = useState(source.live_integration_ids.join(', '));
  const [error, setError] = useState<MessageId | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const field = useRef<HTMLInputElement>(null);
  const request = useMutation({
    mutationFn: (live: number[]) => updatePaymentSource(agencyId, clientId, source.id, { live_integration_ids: live }),
    async onSuccess() {
      await queryClient.invalidateQueries({ queryKey: integrationsKey(agencyId, clientId, 'payment-sources') });
      onClose();
    },
    onError: (failure) => setProblem(describeError(failure)),
  });
  const submit = () => {
    const live = integrationIds(ids);
    setError(live.error);
    setProblem(null);
    if (!focusFirstInvalid([live.error, field])) request.mutate(live.ids);
  };
  return (
    <FormDialog
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="integrations.paymob.changeIds" values={{ name: source.name }} />}
      submitLabel={<FormattedMessage id="common.save" />}
      busy={request.isPending}
      onSubmit={submit}
    >
      <ErrorNotice message={problem} />
      <Field
        id="paymob-ids-change"
        ref={field}
        size="md"
        dir="ltr"
        inputMode="numeric"
        autoComplete="off"
        label={<FormattedMessage id="integrations.paymob.ids" />}
        hint={<FormattedMessage id="integrations.paymob.idsHint" />}
        // The dialog was opened to change these numbers.
        // eslint-disable-next-line jsx-a11y/no-autofocus
        autoFocus
        required
        value={ids}
        onChange={setIds}
        error={error}
      />
      <Notice tone="warning" quiet>
        <FormattedMessage id="integrations.paymob.idsWarning" />
      </Notice>
    </FormDialog>
  );
}

/** One Paymob source: where Paymob sends its callbacks, which integrations count as live, and its secret. */
function SourceCard({ source }: { source: PaymentSource }) {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId, clientId } = useClient();
  const [open, setOpen] = useState<'secret' | 'ids' | 'rename' | 'off' | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: integrationsKey(agencyId, clientId, 'payment-sources') });
  const turnOn = useMutation({
    mutationFn: () => updatePaymentSource(agencyId, clientId, source.id, { status: 'active' }),
    onSuccess: () => {
      setProblem(null);
      return refresh();
    },
    onError: (failure) => setProblem(describeError(failure)),
  });
  const active = source.status === 'active';
  const say = (id: MessageId) => ({ label: <FormattedMessage id={id} />, text: intl.formatMessage({ id }) });
  const actions: RowAction[] = [
    { id: 'secret', ...say('integrations.action.replaceSecret'), onAction: () => setOpen('secret') },
    { id: 'ids', ...say('integrations.paymob.changeIdsAction'), onAction: () => setOpen('ids') },
    { id: 'rename', ...say('links.action.rename'), onAction: () => setOpen('rename') },
    active ? { id: 'off', ...say('links.action.turnOff'), danger: true, onAction: () => setOpen('off') } : { id: 'on', ...say('links.action.turnOn'), onAction: () => turnOn.mutate() },
  ];
  const titleId = `paymob-${source.id}`;
  return (
    <article className="c-card" aria-labelledby={titleId}>
      <div className="c-card__header">
        <div className="l-cluster a-person">
          <span className="c-avatar c-avatar--lg c-avatar--provider" aria-hidden="true">
            <Icon name="credit-card" size="md" />
          </span>
          <div>
            <h3 className="c-card__title" id={titleId}>
              {source.name}
            </h3>
            <p className="c-card__subtitle">
              <FormattedMessage id="integrations.paymob.subtitle" values={{ count: source.live_integration_ids.length }} />
            </p>
          </div>
        </div>
        <div className="l-cluster">
          <OnOff on={active} onWord="integrations.state.receiving" />
          <RowMenu label={intl.formatMessage({ id: 'links.actionsForNamed' }, { name: source.name })} actions={actions} />
        </div>
      </div>
      <div className="c-card__body l-stack">
        <ErrorNotice message={problem} />
        <CopyField id={`paymob-callback-${source.id}`} label={<FormattedMessage id="integrations.callback" />} value={callbackAddress(source.callback_path)} hint={<FormattedMessage id="integrations.paymob.callbackHint" />} />
        <dl className="c-dl">
          <dt>
            <FormattedMessage id="integrations.paymob.ids" />
          </dt>
          <dd>
            <span className="l-cluster a-chips">
              {source.live_integration_ids.map((id) => (
                <span key={id} className="c-chip u-mono u-ltr">
                  {id}
                </span>
              ))}
            </span>
          </dd>
        </dl>
      </div>
      {open === 'secret' ? (
        <SecretDialog
          title={<FormattedMessage id="integrations.paymob.replaceSecret" values={{ name: source.name }} />}
          label="integrations.paymob.secret"
          hint="integrations.paymob.secretHint"
          text={<FormattedMessage id="integrations.secret.overlap" />}
          onSave={(secret) => replacePaymentSecret(agencyId, clientId, source.id, secret).then(refresh)}
          onClose={() => setOpen(null)}
        />
      ) : null}
      {open === 'ids' ? <IdsDialog source={source} onClose={() => setOpen(null)} /> : null}
      {open === 'rename' ? (
        <NameDialog
          title={<FormattedMessage id="integrations.rename" values={{ name: source.name }} />}
          initial={source.name}
          onSave={(name) => updatePaymentSource(agencyId, clientId, source.id, { name }).then(refresh)}
          onClose={() => setOpen(null)}
        />
      ) : null}
      {open === 'off' ? (
        <ConfirmDialog
          title="integrations.paymob.off.title"
          values={{ name: source.name }}
          text="integrations.paymob.off.text"
          submit="links.action.turnOff"
          keep="links.sites.off.keep"
          danger
          onConfirm={async () => {
            await updatePaymentSource(agencyId, clientId, source.id, { status: 'disabled' });
            await refresh();
            setOpen(null);
          }}
          onClose={() => setOpen(null)}
        />
      ) : null}
    </article>
  );
}

/** Payments the client receives through Paymob, recorded as verified revenue once Paymob confirms them. */
export function PaymentsTab() {
  const { agencyId, clientId } = useClient();
  const sources = useQuery(paymentSourcesQuery(agencyId, clientId));
  const [adding, setAdding] = useState(false);
  const rows = [...(sources.data ?? [])].sort((first, second) => first.created_at.localeCompare(second.created_at));
  return (
    <IntegrationCard
      id="payments-title"
      icon="credit-card"
      title={<FormattedMessage id="integrations.paymob.title" />}
      lead={<FormattedMessage id="integrations.paymob.lead" />}
      action={
        sources.isSuccess ? (
          <button type="button" className="c-btn c-btn--secondary c-btn--sm" onClick={() => setAdding(true)}>
            <Icon name="plus" size="sm" />
            <FormattedMessage id="integrations.paymob.new" />
          </button>
        ) : undefined
      }
      footer={
        <>
          <Icon name="lock" size="sm" />
          <FormattedMessage id="integrations.paymob.footer" />
        </>
      }
    >
      <QueryStates query={sources} />
      {sources.isSuccess && rows.length === 0 ? (
        <EmptyState icon="credit-card" title={<FormattedMessage id="integrations.paymob.empty.title" />} level={3}>
          <FormattedMessage id="integrations.paymob.empty.text" />
        </EmptyState>
      ) : null}
      {rows.length > 0 ? (
        <div className="l-grid l-grid--2 a-pad">
          {rows.map((source) => (
            <SourceCard key={source.id} source={source} />
          ))}
        </div>
      ) : null}
      {adding ? <AddDialog onClose={() => setAdding(false)} /> : null}
    </IntegrationCard>
  );
}
