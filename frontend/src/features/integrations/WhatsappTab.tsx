import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { FormattedDate, FormattedMessage, useIntl } from 'react-intl';

import { describeError, type ErrorMessage } from '@/api/errors';
import { integrationsKey, numbersQuery, referralsQuery, registerNumber, updateNumber, type WhatsappNumber } from '@/api/integrations';
import { useClient } from '@/app/tenant';
import { Badge, type BadgeTone } from '@/components/Badge';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { EmptyState } from '@/components/EmptyState';
import { Field } from '@/components/Field';
import { FormDialog } from '@/components/FormDialog';
import { Icon, type IconName } from '@/components/Icon';
import { ListNone, QueryStates } from '@/components/ListStates';
import { ErrorNotice, Notice } from '@/components/Notice';
import { RowMenu, type RowAction } from '@/components/RowMenu';
import { dayFormat } from '@/components/Time';
import type { MessageId } from '@/i18n';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';

import { Figures, IntegrationCard, NAME_MAX, NameDialog, nameError } from './shared';

const PHONE_NUMBER_ID = /^[1-9][0-9]{0,31}$/;

const numberErrors: Partial<Record<string, MessageId>> = {
  verification_required: 'integrations.whatsapp.error.verification_required',
  claim_revoked: 'integrations.whatsapp.error.claim_revoked',
  number_already_bound: 'integrations.whatsapp.error.number_already_bound',
  state_conflict: 'integrations.whatsapp.error.exists',
};

const states: Record<string, { tone: BadgeTone; icon: IconName; word: MessageId }> = {
  pending: { tone: 'info', icon: 'hourglass', word: 'integrations.whatsapp.state.pending' },
  active: { tone: 'success', icon: 'circle-check', word: 'integrations.state.receiving' },
  disabled: { tone: 'neutral', icon: 'circle-pause', word: 'integrations.state.off' },
  revoked: { tone: 'neutral', icon: 'ban', word: 'integrations.whatsapp.state.revoked' },
};

function RegisterDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const { agencyId, clientId } = useClient();
  const [phone, setPhone] = useState('');
  const [name, setName] = useState('');
  const [errors, setErrors] = useState<{ phone?: MessageId | null; name?: MessageId | null }>({});
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const phoneRef = useRef<HTMLInputElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const request = useMutation({
    mutationFn: () => registerNumber(agencyId, clientId, { phone_number_id: phone.trim(), name: name.trim() }),
    async onSuccess() {
      await queryClient.invalidateQueries({ queryKey: integrationsKey(agencyId, clientId, 'whatsapp-numbers') });
      onClose();
    },
    onError: (failure) => setProblem(describeError(failure, numberErrors)),
  });
  const submit = () => {
    const id = phone.trim();
    const found = { phone: id === '' ? ('field.error.required' as const) : PHONE_NUMBER_ID.test(id) ? null : ('integrations.whatsapp.error.phoneId' as const), name: nameError(name) };
    setErrors(found);
    setProblem(null);
    if (!focusFirstInvalid([found.phone, phoneRef], [found.name, nameRef])) request.mutate();
  };
  return (
    <FormDialog
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="integrations.whatsapp.new" />}
      submitLabel={<FormattedMessage id="integrations.whatsapp.create" />}
      busy={request.isPending}
      onSubmit={submit}
    >
      <ErrorNotice message={problem} />
      <Field
        id="whatsapp-phone-id"
        ref={phoneRef}
        size="md"
        dir="ltr"
        inputMode="numeric"
        autoComplete="off"
        maxLength={32}
        label={<FormattedMessage id="integrations.whatsapp.phoneId" />}
        hint={<FormattedMessage id="integrations.whatsapp.phoneIdHint" />}
        // The dialog was opened to register this number.
        // eslint-disable-next-line jsx-a11y/no-autofocus
        autoFocus
        required
        value={phone}
        onChange={setPhone}
        error={errors.phone}
      />
      <Field
        id="whatsapp-name"
        ref={nameRef}
        size="md"
        autoComplete="off"
        maxLength={NAME_MAX}
        label={<FormattedMessage id="integrations.name" />}
        hint={<FormattedMessage id="integrations.whatsapp.nameHint" />}
        required
        value={name}
        onChange={setName}
        error={errors.name}
      />
      <Notice tone="info" quiet>
        <FormattedMessage id="integrations.whatsapp.claim" />
      </Notice>
    </FormDialog>
  );
}

function NumbersCard() {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId, clientId } = useClient();
  const numbers = useQuery(numbersQuery(agencyId, clientId));
  const [adding, setAdding] = useState(false);
  const [open, setOpen] = useState<{ number: WhatsappNumber; what: 'rename' | 'off' } | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: integrationsKey(agencyId, clientId, 'whatsapp-numbers') });
  const turnOn = useMutation({
    mutationFn: (number: WhatsappNumber) => updateNumber(agencyId, clientId, number.id, { status: 'active' }),
    onSuccess: () => {
      setProblem(null);
      return refresh();
    },
    onError: (failure) => setProblem(describeError(failure, numberErrors)),
  });
  const rows = [...(numbers.data ?? [])].sort((first, second) => first.created_at.localeCompare(second.created_at));
  const say = (id: MessageId) => ({ label: <FormattedMessage id={id} />, text: intl.formatMessage({ id }) });
  const actionsOf = (number: WhatsappNumber): RowAction[] => {
    const actions: RowAction[] = [{ id: 'rename', ...say('links.action.rename'), onAction: () => setOpen({ number, what: 'rename' }) }];
    // Only a binding the operator verified can be switched; a claim or a revoked number cannot.
    if (number.status === 'active') actions.push({ id: 'off', ...say('links.action.turnOff'), danger: true, onAction: () => setOpen({ number, what: 'off' }) });
    if (number.status === 'disabled') actions.push({ id: 'on', ...say('links.action.turnOn'), onAction: () => turnOn.mutate(number) });
    return actions;
  };

  return (
    <IntegrationCard
      id="whatsapp-numbers-title"
      glyph="whatsapp"
      title={<FormattedMessage id="integrations.whatsapp.title" />}
      lead={<FormattedMessage id="integrations.whatsapp.lead" />}
      action={
        numbers.isSuccess ? (
          <button type="button" className="c-btn c-btn--secondary c-btn--sm" onClick={() => setAdding(true)}>
            <Icon name="plus" size="sm" />
            <FormattedMessage id="integrations.whatsapp.new" />
          </button>
        ) : undefined
      }
    >
      <QueryStates query={numbers} />
      <div className="a-pad--x">
        <ErrorNotice message={problem} />
      </div>
      {numbers.isSuccess && rows.length === 0 ? (
        <EmptyState icon="message-circle" title={<FormattedMessage id="integrations.whatsapp.empty.title" />} level={3}>
          <FormattedMessage id="integrations.whatsapp.empty.text" />
        </EmptyState>
      ) : null}
      {rows.length > 0 ? (
        <div className="c-table-wrap">
          <table className="c-table">
            <thead>
              <tr>
                <th scope="col">
                  <FormattedMessage id="integrations.name" />
                </th>
                <th scope="col">
                  <FormattedMessage id="team.column.state" />
                </th>
                <th scope="col">
                  <span className="u-sr">
                    <FormattedMessage id="clients.column.actions" />
                  </span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((number) => {
                const state = states[number.status] ?? states.disabled;
                return (
                  <tr key={number.id}>
                    <td>
                      <span className="c-table__primary">{number.name}</span>
                      <span className="c-table__sub u-mono u-ltr">{number.phone_number_id}</span>
                    </td>
                    <td>
                      {state ? (
                        <Badge tone={state.tone} icon={state.icon}>
                          <FormattedMessage id={state.word} />
                        </Badge>
                      ) : null}
                      {number.status === 'pending' ? (
                        <span className="c-table__sub">
                          <FormattedMessage id="integrations.whatsapp.pendingText" />
                        </span>
                      ) : null}
                    </td>
                    <td className="is-num">
                      <RowMenu label={intl.formatMessage({ id: 'links.actionsForNamed' }, { name: number.name })} actions={actionsOf(number)} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
      {adding ? <RegisterDialog onClose={() => setAdding(false)} /> : null}
      {open?.what === 'rename' ? (
        <NameDialog
          title={<FormattedMessage id="integrations.rename" values={{ name: open.number.name }} />}
          initial={open.number.name}
          onSave={(name) => updateNumber(agencyId, clientId, open.number.id, { name }).then(refresh)}
          onClose={() => setOpen(null)}
        />
      ) : null}
      {open?.what === 'off' ? (
        <ConfirmDialog
          title="integrations.whatsapp.off.title"
          values={{ name: open.number.name }}
          text="integrations.whatsapp.off.text"
          submit="links.action.turnOff"
          keep="links.sites.off.keep"
          danger
          errors={numberErrors}
          onConfirm={async () => {
            await updateNumber(agencyId, clientId, open.number.id, { status: 'disabled' });
            await refresh();
            setOpen(null);
          }}
          onClose={() => setOpen(null)}
        />
      ) : null}
    </IntegrationCard>
  );
}

const sourceTypes = ['ad', 'post', 'other'] as const;

function ReferralsCard() {
  const intl = useIntl();
  const { agencyId, clientId } = useClient();
  const referrals = useQuery(referralsQuery(agencyId, clientId));
  const report = referrals.data;
  const day = (value: string) => <FormattedDate value={`${value}T00:00:00Z`} {...dayFormat} timeZone="UTC" />;
  // The API counts up to its until day without it: the last day counted is the one before.
  const dayBefore = (value: string) => new Date(Date.parse(`${value}T00:00:00Z`) - 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
  return (
    <IntegrationCard
      id="referrals-title"
      icon="megaphone"
      title={<FormattedMessage id="integrations.referrals.title" />}
      lead={
        report ? (
          <FormattedMessage id="integrations.referrals.range" values={{ from: day(report.since), through: day(dayBefore(report.until)) }} />
        ) : (
          <FormattedMessage id="integrations.referrals.lead" />
        )
      }
      footer={
        <>
          <Icon name="lock" size="sm" />
          <FormattedMessage id="integrations.referrals.footer" />
        </>
      }
    >
      <QueryStates query={referrals} lines={2} />
      {report ? (
        <Figures
          items={[
            { key: 'total', label: 'integrations.referrals.total', value: report.total },
            { key: 'referred', label: 'integrations.referrals.referred', value: report.total - report.unknown },
            { key: 'unknown', label: 'integrations.referrals.unknown', value: report.unknown },
          ]}
        />
      ) : null}
      {report && report.sources.length === 0 ? (
        <ListNone>
          <FormattedMessage id="integrations.referrals.none" />
        </ListNone>
      ) : null}
      {report && report.sources.length > 0 ? (
        <div className="c-table-wrap">
          <table className="c-table">
            <thead>
              <tr>
                <th scope="col">
                  <FormattedMessage id="integrations.referrals.source" />
                </th>
                <th scope="col" className="is-num">
                  <FormattedMessage id="integrations.referrals.messages" />
                </th>
                <th scope="col" className="is-num">
                  <FormattedMessage id="integrations.referrals.withClick" />
                </th>
              </tr>
            </thead>
            <tbody>
              {report.sources.map((source) => {
                const kind = sourceTypes.find((item) => item === source.source_type);
                return (
                  <tr key={`${source.source_type}-${source.source_id ?? 'none'}`}>
                    <td>
                      <span className="c-table__primary">{kind ? <FormattedMessage id={`integrations.referrals.type.${kind}`} /> : source.source_type}</span>
                      {source.source_id ? <span className="c-table__sub u-mono u-ltr">{source.source_id}</span> : null}
                    </td>
                    <td className="is-num"><span className="u-num">{intl.formatNumber(source.messages)}</span></td>
                    <td className="is-num"><span className="u-num">{intl.formatNumber(source.with_click_id)}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </IntegrationCard>
  );
}

/** The client's WhatsApp Business numbers, and the conversations that ads and posts started. */
export function WhatsappTab() {
  const { manager } = useClient();
  return (
    <div className="l-stack l-stack--loose">
      {manager ? <NumbersCard /> : null}
      <ReferralsCard />
    </div>
  );
}
