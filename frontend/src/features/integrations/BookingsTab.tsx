import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { describeError, type ErrorMessage } from '@/api/errors';
import {
  bookingsQuery,
  createIntegrationSource,
  createStageRule,
  dealsQuery,
  integrationSourcesQuery,
  integrationsKey,
  replaceIntegrationSecret,
  stageRulesQuery,
  updateIntegrationSource,
  updateStageRule,
  type IntegrationKind,
  type IntegrationSource,
  type StageRule,
} from '@/api/integrations';
import { useClient } from '@/app/tenant';
import { Badge } from '@/components/Badge';
import { SelectField, type Option } from '@/components/Choice';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { CopyField } from '@/components/CopyField';
import { EmptyState } from '@/components/EmptyState';
import { Field, PasswordField } from '@/components/Field';
import { FormDialog } from '@/components/FormDialog';
import { Icon } from '@/components/Icon';
import { QueryStates } from '@/components/ListStates';
import { ErrorNotice } from '@/components/Notice';
import { RowMenu, type RowAction } from '@/components/RowMenu';
import { ShownOnceDialog } from '@/components/ShownOnceDialog';
import type { MessageId } from '@/i18n';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';

import { callbackAddress, Figures, IntegrationCard, NAME_MAX, NameDialog, nameError, OnOff, SecretDialog, secretError } from './shared';

const RULE_TEXT_MAX = 128;

function AddSourceDialog({ onCreated, onClose }: { onCreated: (source: IntegrationSource, secret: string | null) => void; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { agencyId, clientId } = useClient();
  const [kind, setKind] = useState<IntegrationKind>('cal_com');
  const [name, setName] = useState('');
  const [secret, setSecret] = useState('');
  const [errors, setErrors] = useState<{ name?: MessageId | null; secret?: MessageId | null }>({});
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const secretRef = useRef<HTMLInputElement>(null);
  const request = useMutation({
    mutationFn: () => createIntegrationSource(agencyId, clientId, kind === 'cal_com' ? { kind, name: name.trim(), secret } : { kind, name: name.trim() }),
    // The answer of a signed webhook source holds its secret. It is handed on and not kept.
    gcTime: 0,
    async onSuccess(issued) {
      await queryClient.invalidateQueries({ queryKey: integrationsKey(agencyId, clientId, 'integration-sources') });
      onCreated(issued.source, issued.signing_secret ?? null);
    },
    onError: (failure) => setProblem(describeError(failure, { validation_failed: 'integrations.sources.error.refused' })),
  });
  const submit = () => {
    const found = { name: nameError(name), secret: kind === 'cal_com' ? secretError(secret) : null };
    setErrors(found);
    setProblem(null);
    if (!focusFirstInvalid([found.name, nameRef], [found.secret, secretRef])) request.mutate();
  };
  const choice = (value: IntegrationKind) => (
    <label className="c-choice a-choice--card">
      <input className="c-radio" type="radio" name="integration-kind" value={value} checked={kind === value} onChange={() => setKind(value)} />
      {value === 'cal_com' ? <span className="c-glyph c-glyph--caldotcom" aria-hidden="true" /> : <Icon name="webhook" />}
      <span className="u-strong">
        <FormattedMessage id={`integrations.kind.${value}`} />
      </span>
      <span className="u-secondary a-choice__more">
        <FormattedMessage id={`integrations.kind.${value}.hint`} />
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
      title={<FormattedMessage id="integrations.sources.new" />}
      submitLabel={<FormattedMessage id="integrations.sources.create" />}
      busy={request.isPending}
      onSubmit={submit}
    >
      <ErrorNotice message={problem} />
      <fieldset className="a-fieldset">
        <legend className="c-field__label">
          <FormattedMessage id="integrations.sources.kind" />
        </legend>
        <div className="l-stack l-stack--tight">
          {choice('cal_com')}
          {choice('signed_webhook')}
        </div>
      </fieldset>
      <Field
        id="integration-name"
        ref={nameRef}
        size="md"
        autoComplete="off"
        maxLength={NAME_MAX}
        label={<FormattedMessage id="integrations.name" />}
        required
        value={name}
        onChange={setName}
        error={errors.name}
      />
      {kind === 'cal_com' ? (
        <PasswordField
          id="integration-secret"
          ref={secretRef}
          size="md"
          dir="ltr"
          autoComplete="off"
          spellCheck={false}
          maxLength={256}
          label={<FormattedMessage id="integrations.calcom.secret" />}
          hint={<FormattedMessage id="integrations.calcom.secretHint" />}
          required
          value={secret}
          onChange={setSecret}
          error={errors.secret}
        />
      ) : null}
    </FormDialog>
  );
}

/** What to set in Cal.com: the address, the triggers and the same secret. */
function CalcomSetup({ source, onClose }: { source: IntegrationSource; onClose: () => void }) {
  return (
    <FormDialog
      isOpen
      wide
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="integrations.calcom.setup.title" values={{ name: source.name }} />}
    >
      <CopyField id={`calcom-${source.id}`} label={<FormattedMessage id="integrations.callback" />} value={callbackAddress(source.callback_path)} />
      <ol className="a-steps">
        <li>
          <FormattedMessage id="integrations.calcom.setup.webhook" />
        </li>
        <li>
          <FormattedMessage id="integrations.calcom.setup.triggers" />
        </li>
        <li>
          <FormattedMessage id="integrations.calcom.setup.secret" />
        </li>
        <li>
          <FormattedMessage id="integrations.calcom.setup.subject" values={{ field: <span className="u-mono u-ltr">ts_subject</span> }} />
        </li>
      </ol>
    </FormDialog>
  );
}

function SignatureRule() {
  return (
    <p className="c-field__hint">
      <FormattedMessage id="tracking.webhook.signature" values={{ header: <span className="u-mono u-ltr">X-Tracking-Signature: t=…,v1=…</span> }} />
    </p>
  );
}

function SourcesCard() {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId, clientId } = useClient();
  const sources = useQuery(integrationSourcesQuery(agencyId, clientId));
  const [adding, setAdding] = useState(false);
  const [setup, setSetup] = useState<IntegrationSource | null>(null);
  const [secret, setSecret] = useState<{ source: IntegrationSource; value: string; replaced: boolean } | null>(null);
  const [open, setOpen] = useState<{ source: IntegrationSource; what: 'secret' | 'rename' | 'off' | 'issue' } | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: integrationsKey(agencyId, clientId, 'integration-sources') });
  const turnOn = useMutation({
    mutationFn: (source: IntegrationSource) => updateIntegrationSource(agencyId, clientId, source.id, { status: 'active' }),
    onSuccess: () => {
      setProblem(null);
      return refresh();
    },
    onError: (failure) => setProblem(describeError(failure)),
  });
  const rows = [...(sources.data ?? [])].sort((first, second) => first.created_at.localeCompare(second.created_at));
  const say = (id: MessageId) => ({ label: <FormattedMessage id={id} />, text: intl.formatMessage({ id }) });
  const actionsOf = (source: IntegrationSource): RowAction[] => [
    ...(source.kind === 'cal_com' ? [{ id: 'setup', ...say('integrations.calcom.setupAction'), onAction: () => setSetup(source) }] : []),
    { id: 'secret', ...say('integrations.action.replaceSecret'), onAction: () => setOpen({ source, what: source.kind === 'cal_com' ? 'secret' : 'issue' }) },
    { id: 'rename', ...say('links.action.rename'), onAction: () => setOpen({ source, what: 'rename' }) },
    source.status === 'active'
      ? { id: 'off', ...say('links.action.turnOff'), danger: true, onAction: () => setOpen({ source, what: 'off' }) }
      : { id: 'on', ...say('links.action.turnOn'), onAction: () => turnOn.mutate(source) },
  ];

  return (
    <IntegrationCard
      id="integration-sources-title"
      glyph="caldotcom"
      title={<FormattedMessage id="integrations.sources.title" />}
      lead={<FormattedMessage id="integrations.sources.lead" />}
      action={
        sources.isSuccess ? (
          <button type="button" className="c-btn c-btn--secondary c-btn--sm" onClick={() => setAdding(true)}>
            <Icon name="plus" size="sm" />
            <FormattedMessage id="integrations.sources.new" />
          </button>
        ) : undefined
      }
    >
      <QueryStates query={sources} />
      <div className="a-pad--x">
        <ErrorNotice message={problem} />
      </div>
      {sources.isSuccess && rows.length === 0 ? (
        <EmptyState icon="webhook" title={<FormattedMessage id="integrations.sources.empty.title" />} level={3}>
          <FormattedMessage id="integrations.sources.empty.text" />
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
                  <FormattedMessage id="integrations.callback" />
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
                      <FormattedMessage id={source.kind === 'cal_com' ? 'integrations.kind.cal_com' : 'integrations.kind.signed_webhook'} />
                    </span>
                  </td>
                  <td>
                    <OnOff on={source.status === 'active'} onWord="integrations.state.receiving" />
                  </td>
                  <td>
                    <span className="u-mono u-ltr a-break">{callbackAddress(source.callback_path)}</span>
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
      {adding ? (
        <AddSourceDialog
          onClose={() => setAdding(false)}
          onCreated={(source, value) => {
            setAdding(false);
            if (value) setSecret({ source, value, replaced: false });
            else setSetup(source);
          }}
        />
      ) : null}
      {setup ? <CalcomSetup source={setup} onClose={() => setSetup(null)} /> : null}
      {secret ? (
        <ShownOnceDialog
          title={<FormattedMessage id={secret.replaced ? 'tracking.secret.rotated' : 'tracking.secret.title'} values={{ name: secret.source.name }} />}
          notice={<FormattedMessage id={secret.replaced ? 'tracking.secret.onceRotated' : 'tracking.secret.once'} />}
          values={[
            { id: 'integration-secret-value', label: <FormattedMessage id="tracking.secret.label" />, value: secret.value },
            { id: 'integration-secret-address', label: <FormattedMessage id="integrations.callback" />, value: callbackAddress(secret.source.callback_path) },
          ]}
          onClose={() => setSecret(null)}
        >
          <SignatureRule />
        </ShownOnceDialog>
      ) : null}
      {open?.what === 'secret' ? (
        <SecretDialog
          title={<FormattedMessage id="integrations.calcom.replaceSecret" values={{ name: open.source.name }} />}
          label="integrations.calcom.secret"
          hint="integrations.calcom.secretHint"
          text={<FormattedMessage id="integrations.secret.overlap" />}
          onSave={(value) => replaceIntegrationSecret(agencyId, clientId, open.source.id, value).then(refresh)}
          onClose={() => setOpen(null)}
        />
      ) : null}
      {open?.what === 'issue' ? (
        <ConfirmDialog
          title="tracking.rotate.title"
          text="tracking.rotate.text"
          submit="integrations.action.replaceSecret"
          keep="tracking.rotate.keep"
          onConfirm={async () => {
            const issued = await replaceIntegrationSecret(agencyId, clientId, open.source.id, null);
            setOpen(null);
            if (issued.signing_secret) setSecret({ source: issued.source, value: issued.signing_secret, replaced: true });
          }}
          onClose={() => setOpen(null)}
        />
      ) : null}
      {open?.what === 'rename' ? (
        <NameDialog
          title={<FormattedMessage id="integrations.rename" values={{ name: open.source.name }} />}
          initial={open.source.name}
          onSave={(name) => updateIntegrationSource(agencyId, clientId, open.source.id, { name }).then(refresh)}
          onClose={() => setOpen(null)}
        />
      ) : null}
      {open?.what === 'off' ? (
        <ConfirmDialog
          title="integrations.sources.off.title"
          values={{ name: open.source.name }}
          text="integrations.sources.off.text"
          submit="links.action.turnOff"
          keep="links.sites.off.keep"
          danger
          onConfirm={async () => {
            await updateIntegrationSource(agencyId, clientId, open.source.id, { status: 'disabled' });
            await refresh();
            setOpen(null);
          }}
          onClose={() => setOpen(null)}
        />
      ) : null}
    </IntegrationCard>
  );
}

function BookingsCard() {
  const { agencyId, clientId } = useClient();
  const bookings = useQuery(bookingsQuery(agencyId, clientId));
  const totals = bookings.data?.totals;
  return (
    <IntegrationCard
      id="bookings-title"
      icon="calendar"
      title={<FormattedMessage id="integrations.bookings.title" />}
      lead={<FormattedMessage id="integrations.bookings.lead" />}
      footer={
        <>
          <Icon name="info" size="sm" />
          <FormattedMessage id="integrations.bookings.footer" />
        </>
      }
    >
      <QueryStates query={bookings} lines={2} />
      {bookings.isSuccess ? (
        <Figures
          items={[
            { key: 'requested', label: 'integrations.bookings.requested', value: totals?.requested },
            { key: 'scheduled', label: 'integrations.bookings.scheduled', value: totals?.scheduled },
            { key: 'completed', label: 'integrations.bookings.completed', value: totals?.completed },
            { key: 'cancelled', label: 'integrations.bookings.cancelled', value: totals?.cancelled },
            { key: 'rejected', label: 'integrations.bookings.rejected', value: totals?.rejected },
            { key: 'linked', label: 'integrations.bookings.linked', value: totals?.linked },
          ]}
        />
      ) : null}
    </IntegrationCard>
  );
}

function RuleDialog({ onClose }: { onClose: () => void }) {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId, clientId } = useClient();
  const [pipeline, setPipeline] = useState('');
  const [stage, setStage] = useState('');
  const [outcome, setOutcome] = useState<'won' | 'lost'>('won');
  const [errors, setErrors] = useState<{ pipeline?: MessageId | null; stage?: MessageId | null }>({});
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const pipelineRef = useRef<HTMLInputElement>(null);
  const stageRef = useRef<HTMLInputElement>(null);
  const request = useMutation({
    mutationFn: () => createStageRule(agencyId, clientId, { pipeline: pipeline.trim(), stage: stage.trim(), outcome }),
    async onSuccess() {
      await queryClient.invalidateQueries({ queryKey: integrationsKey(agencyId, clientId, 'stage-rules') });
      await queryClient.invalidateQueries({ queryKey: integrationsKey(agencyId, clientId, 'deals') });
      onClose();
    },
    onError: (failure) => setProblem(describeError(failure, { state_conflict: 'integrations.crm.error.exists' })),
  });
  const text = (value: string): MessageId | null => (value.trim() === '' ? 'field.error.required' : value.trim().length > RULE_TEXT_MAX ? 'links.rule.labelLong' : null);
  const submit = () => {
    const found = { pipeline: text(pipeline), stage: text(stage) };
    setErrors(found);
    setProblem(null);
    if (!focusFirstInvalid([found.pipeline, pipelineRef], [found.stage, stageRef])) request.mutate();
  };
  const outcomes: Array<Option<'won' | 'lost'>> = [
    { value: 'won', label: intl.formatMessage({ id: 'integrations.crm.outcome.won' }), hint: intl.formatMessage({ id: 'integrations.crm.outcome.won.hint' }) },
    { value: 'lost', label: intl.formatMessage({ id: 'integrations.crm.outcome.lost' }) },
  ];
  return (
    <FormDialog
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="integrations.crm.new" />}
      submitLabel={<FormattedMessage id="integrations.crm.create" />}
      busy={request.isPending}
      onSubmit={submit}
    >
      <ErrorNotice message={problem} />
      <Field
        id="rule-pipeline"
        ref={pipelineRef}
        size="md"
        autoComplete="off"
        maxLength={RULE_TEXT_MAX}
        label={<FormattedMessage id="integrations.crm.pipeline" />}
        hint={<FormattedMessage id="integrations.crm.pipelineHint" />}
        // The dialog was opened to add this rule.
        // eslint-disable-next-line jsx-a11y/no-autofocus
        autoFocus
        required
        value={pipeline}
        onChange={setPipeline}
        error={errors.pipeline}
      />
      <Field
        id="rule-stage"
        ref={stageRef}
        size="md"
        autoComplete="off"
        maxLength={RULE_TEXT_MAX}
        label={<FormattedMessage id="integrations.crm.stage" />}
        hint={<FormattedMessage id="integrations.crm.stageHint" />}
        required
        value={stage}
        onChange={setStage}
        error={errors.stage}
      />
      <SelectField label={<FormattedMessage id="integrations.crm.outcome" />} value={outcome} onChange={setOutcome} options={outcomes} />
    </FormDialog>
  );
}

function CrmCard() {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId, clientId, manager } = useClient();
  const deals = useQuery(dealsQuery(agencyId, clientId));
  const rules = useQuery({ ...stageRulesQuery(agencyId, clientId), enabled: manager });
  const [adding, setAdding] = useState(false);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const change = useMutation({
    mutationFn: ({ rule, next }: { rule: StageRule; next: { outcome?: 'won' | 'lost'; status?: 'active' | 'disabled' } }) => updateStageRule(agencyId, clientId, rule.id, next),
    async onSuccess() {
      setProblem(null);
      await queryClient.invalidateQueries({ queryKey: integrationsKey(agencyId, clientId, 'stage-rules') });
      await queryClient.invalidateQueries({ queryKey: integrationsKey(agencyId, clientId, 'deals') });
    },
    onError: (failure) => setProblem(describeError(failure)),
  });
  const totals = deals.data?.totals;
  const say = (id: MessageId) => ({ label: <FormattedMessage id={id} />, text: intl.formatMessage({ id }) });
  const rows = [...(rules.data ?? [])].sort((first, second) => first.pipeline.localeCompare(second.pipeline) || first.stage.localeCompare(second.stage));

  return (
    <IntegrationCard
      id="crm-title"
      icon="route"
      title={<FormattedMessage id="integrations.crm.title" />}
      lead={<FormattedMessage id="integrations.crm.lead" />}
      action={
        manager && rules.isSuccess ? (
          <button type="button" className="c-btn c-btn--secondary c-btn--sm" onClick={() => setAdding(true)}>
            <Icon name="plus" size="sm" />
            <FormattedMessage id="integrations.crm.new" />
          </button>
        ) : undefined
      }
    >
      <QueryStates query={deals} lines={2} />
      {deals.isSuccess ? (
        <Figures
          items={[
            { key: 'open', label: 'integrations.crm.open', value: totals?.open },
            { key: 'won_verified', label: 'integrations.crm.wonVerified', value: totals?.won_verified },
            { key: 'won_unverified', label: 'integrations.crm.wonUnverified', value: totals?.won_unverified },
            { key: 'lost', label: 'integrations.crm.lost', value: totals?.lost },
          ]}
        />
      ) : null}
      {manager ? (
        <>
          <QueryStates query={rules} lines={2} />
          <div className="a-pad--x">
            <ErrorNotice message={problem} />
          </div>
          {rules.isSuccess && rows.length === 0 ? (
            <p className="a-none" role="status">
              <FormattedMessage id="integrations.crm.none" />
            </p>
          ) : null}
          {rows.length > 0 ? (
            <div className="c-table-wrap">
              <table className="c-table">
                <thead>
                  <tr>
                    <th scope="col">
                      <FormattedMessage id="integrations.crm.pipeline" />
                    </th>
                    <th scope="col">
                      <FormattedMessage id="integrations.crm.stage" />
                    </th>
                    <th scope="col">
                      <FormattedMessage id="integrations.crm.outcome" />
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
                  {rows.map((rule) => {
                    const won = rule.outcome === 'won';
                    const actions: RowAction[] = [
                      { id: 'outcome', ...say(won ? 'integrations.crm.makeLost' : 'integrations.crm.makeWon'), onAction: () => change.mutate({ rule, next: { outcome: won ? 'lost' : 'won' } }) },
                      rule.status === 'active'
                        ? { id: 'off', ...say('links.action.turnOff'), onAction: () => change.mutate({ rule, next: { status: 'disabled' } }) }
                        : { id: 'on', ...say('links.action.turnOn'), onAction: () => change.mutate({ rule, next: { status: 'active' } }) },
                    ];
                    return (
                      <tr key={rule.id}>
                        <td>{rule.pipeline}</td>
                        <td>
                          <span className="c-table__primary">{rule.stage}</span>
                        </td>
                        <td>
                          <Badge tone={won ? 'success' : 'neutral'} icon={won ? 'circle-check' : 'circle-x'}>
                            <FormattedMessage id={won ? 'integrations.crm.outcome.won' : 'integrations.crm.outcome.lost'} />
                          </Badge>
                        </td>
                        <td>
                          <OnOff on={rule.status === 'active'} />
                        </td>
                        <td className="is-num">
                          <RowMenu label={intl.formatMessage({ id: 'links.actionsForNamed' }, { name: `${rule.pipeline} · ${rule.stage}` })} actions={actions} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
        </>
      ) : null}
      {adding ? <RuleDialog onClose={() => setAdding(false)} /> : null}
    </IntegrationCard>
  );
}

/** Bookings from Cal.com and other tools, and the CRM stages that make a deal won or lost. */
export function BookingsTab() {
  const { manager } = useClient();
  return (
    <div className="l-stack l-stack--loose">
      {manager ? <SourcesCard /> : null}
      <BookingsCard />
      <CrmCard />
    </div>
  );
}
