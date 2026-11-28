import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { describeError, type ErrorMessage } from '@/api/errors';
import { changeSchedule, createSchedule, schedulesKey, type ReportSchedule, type ScheduleReport } from '@/api/reportDelivery';
import { modelVersionsQuery, type ReportFamily, type SpendLevel } from '@/api/reports';
import { membersQuery } from '@/api/team';
import { useClient } from '@/app/tenant';
import { Checkbox, SelectField, type Option } from '@/components/Choice';
import { Field } from '@/components/Field';
import { FormDialog } from '@/components/FormDialog';
import { ErrorNotice } from '@/components/Notice';
import { accountName, useSocialConnections, useSpendConnections } from '@/features/analyze/shared';
import { orderedVersions, useModelName } from '@/features/attribution/parts';
import type { MessageId } from '@/i18n';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';

import { reportNameId } from './describe';
import { browserZone, cadencePeriods, cadences, connectionFamilies, families, mayReceive, RECIPIENT_LIMIT, saleValueFamilies, scheduleNameProblem, timeZones, type Cadence } from './rules';

type Group = 'campaign' | 'content' | 'link' | 'recipient';
type SocialView = 'daily' | 'content_cohort';

interface Draft {
  name: string;
  family: ReportFamily;
  connectionId: string;
  view: SocialView;
  level: SpendLevel;
  group: Group;
  /** Empty for the client's default model. */
  modelVersion: string;
  compare: boolean;
  saleValues: boolean;
  cadence: Cadence;
  weekday: number;
  hour: number;
  timeZone: string;
  recipients: string[];
}

export const scheduleFormErrors = {
  invalid_schedule: 'reports.schedule.error.invalid_schedule',
  invalid_time_zone: 'reports.schedule.error.invalid_time_zone',
  invalid_recipient: 'reports.schedule.error.invalid_recipient',
  schedule_limit_reached: 'reports.schedule.error.schedule_limit_reached',
  source_unavailable: 'reports.schedule.error.source_unavailable',
  not_a_social_connection: 'reports.schedule.error.wrong_account',
  not_a_spend_connection: 'reports.schedule.error.wrong_account',
} as const satisfies Record<string, MessageId>;

const text = (value: unknown, fallback: string): string => (typeof value === 'string' && value !== '' ? value : fallback);

function draftOf(schedule: ReportSchedule | null): Draft {
  if (!schedule) {
    return {
      name: '',
      family: 'revenue',
      connectionId: '',
      view: 'daily',
      level: 'campaign',
      group: 'campaign',
      modelVersion: '',
      compare: true,
      saleValues: false,
      cadence: 'weekly',
      weekday: 1,
      hour: 9,
      timeZone: browserZone(),
      recipients: [],
    };
  }
  const report = schedule.report as Record<string, unknown>;
  return {
    name: schedule.name,
    family: report.family as ReportFamily,
    connectionId: text(report.connection_id, ''),
    view: text(report.view, 'daily') === 'content_cohort' ? 'content_cohort' : 'daily',
    level: text(report.level, 'ad') as SpendLevel,
    group: text(report.group_by, 'campaign') as Group,
    modelVersion: text(report.model_version, ''),
    compare: report.compare === true,
    saleValues: schedule.sale_values,
    cadence: schedule.cadence,
    weekday: schedule.weekday ?? 1,
    hour: schedule.hour,
    timeZone: schedule.time_zone,
    recipients: schedule.recipients ?? [],
  };
}

/** Whether the report is compared: a content cohort never is (016-A). */
const comparable = (draft: Draft) => !(draft.family === 'social' && draft.view !== 'daily');

/** The report of the schedule, as the API takes it: the family's parameters, without days. */
export function reportOf(draft: Draft): ScheduleReport {
  const compare = draft.compare && comparable(draft) ? ('previous' as const) : null;
  const model = draft.modelVersion === '' ? null : draft.modelVersion;
  switch (draft.family) {
    case 'social':
      return { family: 'social', connection_id: draft.connectionId, view: draft.view, compare };
    case 'spend':
      return { family: 'spend', connection_id: draft.connectionId, level: draft.level, compare };
    case 'revenue':
      return { family: 'revenue', compare };
    case 'attribution':
      return { family: 'attribution', group_by: draft.group, view: 'groups', model_version: model, compare };
    case 'funnel':
      return { family: 'funnel', group_by: draft.group === 'recipient' ? 'campaign' : draft.group, model_version: model, compare };
    case 'roas':
      return { family: 'roas', connection_id: draft.connectionId, level: draft.level, model_version: model, compare };
  }
}

/** The schedule form (E06): a report and its choices, when it runs, and who receives it (D8, D9). */
export function ScheduleDialog({ schedule, onClose }: { schedule: ReportSchedule | null; onClose: () => void }) {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId, clientId, client } = useClient();
  const [draft, setDraft] = useState<Draft>(() => draftOf(schedule));
  const [errors, setErrors] = useState<{ name?: MessageId | null; connection?: MessageId | null; recipients?: MessageId | null }>({});
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const social = useSocialConnections(agencyId, clientId);
  const spend = useSpendConnections(agencyId, clientId);
  const models = useQuery(modelVersionsQuery(agencyId, clientId));
  const members = useQuery(membersQuery(agencyId));
  const modelName = useModelName();
  const update = (change: Partial<Draft>) => setDraft((current) => ({ ...current, ...change }));

  const accounts = draft.family === 'social' ? social.data : draft.family === 'spend' || draft.family === 'roas' ? spend.data : undefined;
  const connectionId = accounts?.some((item) => item.id === draft.connectionId) ? draft.connectionId : (accounts?.[0]?.id ?? '');
  const versions = orderedVersions(models.data?.versions);
  const defaultVersion = versions.find((version) => version.is_default) ?? versions[0];
  const saleValues = saleValueFamilies.has(draft.family) && draft.saleValues;
  const people = (members.data ?? []).filter((member) => member.status === 'active' && member.account === 'active');
  // The schedule's recipients who are no longer active members stay listed, and chosen, until they
  // are unticked: the API refuses any change while one of them is kept, and skips them at each run.
  const former = members.data ? (schedule?.recipients ?? []).filter((id) => !people.some((member) => member.id === id)) : [];
  const eligible = (memberId: string) => {
    const member = people.find((item) => item.id === memberId);
    return member ? mayReceive(member, clientId, draft.family, saleValues) : false;
  };

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: draft.name.trim(),
        report: reportOf({ ...draft, connectionId }),
        sale_values: saleValues,
        cadence: draft.cadence,
        weekday: draft.cadence === 'weekly' ? draft.weekday : null,
        hour: draft.hour,
        time_zone: draft.timeZone,
        recipients: draft.recipients,
      };
      return schedule ? changeSchedule(agencyId, clientId, schedule.id, body) : createSchedule(agencyId, clientId, body);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: schedulesKey(agencyId, clientId) });
      onClose();
    },
    onError: (error) => setProblem(describeError(error, scheduleFormErrors)),
  });

  const submit = () => {
    if (save.isPending) return;
    const nameProblem = scheduleNameProblem(draft.name);
    const found = {
      name: nameProblem ? (`reports.schedule.name.${nameProblem}` as MessageId) : null,
      connection: connectionFamilies.has(draft.family) && connectionId === '' ? ('reports.schedule.account.required' as MessageId) : null,
      recipients:
        draft.recipients.length > RECIPIENT_LIMIT
          ? ('reports.schedule.recipients.tooMany' as MessageId)
          : draft.recipients.some((id) => !eligible(id))
            ? ('reports.schedule.recipients.notAllowed' as MessageId)
            : null,
    };
    setErrors(found);
    setProblem(null);
    if (!focusFirstInvalid([found.name, nameRef]) && !found.connection && !found.recipients) save.mutate();
  };

  const familyOptions: Option<ReportFamily>[] = families.map((family) => ({
    value: family,
    label: intl.formatMessage({ id: `reports.family.${family}` }),
  }));
  const hours: Option<string>[] = Array.from({ length: 24 }, (_, hour) => ({ value: String(hour), label: `${String(hour).padStart(2, '0')}:00` }));
  const weekdays: Option<string>[] = Array.from({ length: 7 }, (_, index) => ({
    value: String(index + 1),
    label: intl.formatDate(new Date(Date.UTC(2024, 0, index + 1)), { weekday: 'long', timeZone: 'UTC' }),
  }));
  const zones: Option<string>[] = timeZones().map((zone) => ({ value: zone, label: zone }));

  return (
    <FormDialog
      isOpen
      wide
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id={schedule ? 'reports.schedule.editTitle' : 'reports.schedule.newTitle'} />}
      submitLabel={<FormattedMessage id={schedule ? 'reports.schedule.save' : 'reports.schedule.create'} />}
      busy={save.isPending}
      onSubmit={submit}
    >
      <ErrorNotice message={problem} />
      <Field
        id="schedule-name"
        ref={nameRef}
        size="md"
        label={<FormattedMessage id="reports.schedule.name" />}
        hint={<FormattedMessage id="reports.schedule.nameHint" />}
        value={draft.name}
        onChange={(name) => update({ name })}
        maxLength={120}
        error={errors.name}
      />

      <fieldset className="l-stack a-fieldset">
        <legend className="c-section-title">
          <FormattedMessage id="reports.schedule.report" />
        </legend>
        {schedule ? (
          <p>
            <FormattedMessage id={reportNameId(draft.family, {})} />
            <span className="c-field__hint">
              <FormattedMessage id="reports.schedule.familyKept" />
            </span>
          </p>
        ) : (
          <SelectField<ReportFamily> label={<FormattedMessage id="reports.schedule.report" />} value={draft.family} onChange={(family) => update({ family })} options={familyOptions} />
        )}
        {connectionFamilies.has(draft.family) ? (
          accounts && accounts.length > 0 ? (
            <SelectField<string>
              label={<FormattedMessage id="reports.schedule.account" />}
              value={connectionId}
              onChange={(value) => update({ connectionId: value })}
              options={accounts.map((account) => ({ value: account.id, label: accountName(account, intl) }))}
            />
          ) : (
            <p className="c-field__error">
              <FormattedMessage id="reports.schedule.account.none" />
            </p>
          )
        ) : null}
        {errors.connection ? (
          <p className="c-field__error">
            <FormattedMessage id={errors.connection} />
          </p>
        ) : null}
        {draft.family === 'social' ? (
          <SelectField<SocialView>
            label={<FormattedMessage id="reports.schedule.view" />}
            value={draft.view}
            onChange={(view) => update({ view })}
            options={[
              { value: 'daily', label: intl.formatMessage({ id: 'reports.name.social.daily' }) },
              { value: 'content_cohort', label: intl.formatMessage({ id: 'reports.name.social.content_cohort' }) },
            ]}
          />
        ) : null}
        {draft.family === 'spend' || draft.family === 'roas' ? (
          <SelectField<SpendLevel>
            label={<FormattedMessage id="reports.schedule.level" />}
            value={draft.level}
            onChange={(level) => update({ level })}
            options={(['campaign', 'adset', 'ad'] as const).map((level) => ({ value: level, label: intl.formatMessage({ id: `analyze.spend.level.${level}` }) }))}
          />
        ) : null}
        {draft.family === 'attribution' || draft.family === 'funnel' ? (
          <SelectField<Group>
            label={<FormattedMessage id="attribution.group.label" />}
            value={draft.family === 'funnel' && draft.group === 'recipient' ? 'campaign' : draft.group}
            onChange={(group) => update({ group })}
            options={(draft.family === 'attribution' ? (['campaign', 'content', 'link', 'recipient'] as const) : (['campaign', 'content', 'link'] as const)).map((group) => ({
              value: group,
              label: intl.formatMessage({ id: `attribution.group.${group}` }),
            }))}
          />
        ) : null}
        {(draft.family === 'attribution' || draft.family === 'funnel' || draft.family === 'roas') && versions.length > 0 ? (
          <SelectField<string>
            label={<FormattedMessage id="attribution.model.label" />}
            value={draft.modelVersion}
            onChange={(modelVersion) => update({ modelVersion })}
            options={[
              { value: '', label: intl.formatMessage({ id: 'reports.schedule.modelDefault' }, { model: defaultVersion ? modelName(defaultVersion) : '' }) },
              ...versions.map((version) => ({ value: version.id, label: modelName(version) })),
            ]}
          />
        ) : null}
        {comparable(draft) ? (
          <label className="c-choice">
            <input className="c-switch" type="checkbox" checked={draft.compare} onChange={(event) => update({ compare: event.target.checked })} />
            <span>
              <FormattedMessage id="analyze.compare" />
            </span>
          </label>
        ) : null}
        {saleValueFamilies.has(draft.family) ? (
          <Checkbox id="schedule-sale-values" checked={draft.saleValues} onChange={(checked) => update({ saleValues: checked })} describedBy="schedule-sale-values-hint">
            <FormattedMessage id="reports.schedule.saleValues" />
            <span className="c-field__hint" id="schedule-sale-values-hint">
              <FormattedMessage id="reports.schedule.saleValuesHint" values={{ client: client.name }} />
            </span>
          </Checkbox>
        ) : null}
      </fieldset>

      <fieldset className="l-stack a-fieldset">
        <legend className="c-section-title">
          <FormattedMessage id="reports.schedule.when" />
        </legend>
        <SelectField<Cadence>
          label={<FormattedMessage id="reports.schedule.cadence" />}
          value={draft.cadence}
          onChange={(cadence) => update({ cadence })}
          options={cadences.map((cadence) => ({ value: cadence, label: intl.formatMessage({ id: `reports.cadence.${cadence}` }) }))}
          hint={<FormattedMessage id={cadencePeriods[draft.cadence]} />}
        />
        {draft.cadence === 'weekly' ? (
          <SelectField<string> label={<FormattedMessage id="reports.schedule.weekday" />} value={String(draft.weekday)} onChange={(value) => update({ weekday: Number(value) })} options={weekdays} />
        ) : null}
        <SelectField<string> label={<FormattedMessage id="reports.schedule.hour" />} value={String(draft.hour)} onChange={(value) => update({ hour: Number(value) })} options={hours} />
        <SelectField<string> label={<FormattedMessage id="reports.schedule.zone" />} value={draft.timeZone} onChange={(timeZone) => update({ timeZone })} options={zones} />
      </fieldset>

      <fieldset className="l-stack a-fieldset" aria-describedby="schedule-recipients-hint">
        <legend className="c-section-title">
          <FormattedMessage id="reports.schedule.recipients" />
        </legend>
        {people.map((member) => {
          const allowed = mayReceive(member, clientId, draft.family, saleValues);
          const chosen = draft.recipients.includes(member.id);
          return (
            <Checkbox
              key={member.id}
              id={`schedule-recipient-${member.id}`}
              checked={chosen}
              disabled={!allowed && !chosen}
              invalid={chosen && !allowed}
              onChange={(checked) => update({ recipients: checked ? [...draft.recipients, member.id] : draft.recipients.filter((id) => id !== member.id) })}
            >
              <span className="u-strong">{member.display_name ?? member.email_normalized}</span>{' '}
              <span className="u-secondary">
                <FormattedMessage id={`role.${member.role}`} />
              </span>
              {allowed ? null : (
                <span className="c-field__hint">
                  {/* A member with a grant of the client lacks financial access; anyone else lacks the client. */}
                  <FormattedMessage
                    id={member.clients.some((grant) => grant.client_id === clientId) ? 'reports.schedule.recipient.noFinance' : 'reports.schedule.recipient.noAccess'}
                  />
                </span>
              )}
            </Checkbox>
          );
        })}
        {former.map((id) => {
          const known = members.data?.find((member) => member.id === id);
          // A closed account is never named under its pseudonyms (B1): it reads as a former member.
          const named = known && known.account !== 'closed' ? (known.display_name ?? known.email_normalized) : null;
          const chosen = draft.recipients.includes(id);
          return (
            <Checkbox
              key={id}
              id={`schedule-recipient-${id}`}
              checked={chosen}
              disabled={!chosen}
              invalid={chosen}
              onChange={(checked) => update({ recipients: checked ? [...draft.recipients, id] : draft.recipients.filter((item) => item !== id) })}
            >
              <span className="u-strong">{named ?? <FormattedMessage id="reports.schedule.recipient.former" />}</span>{' '}
              {named && known ? (
                <span className="u-secondary">
                  <FormattedMessage id={`role.${known.role}`} />
                </span>
              ) : null}
              <span className="c-field__hint">
                <FormattedMessage id="reports.schedule.recipient.inactive" />
              </span>
            </Checkbox>
          );
        })}
        <p className="c-field__hint" id="schedule-recipients-hint">
          <FormattedMessage id="reports.schedule.recipientsHint" values={{ chosen: draft.recipients.length, limit: RECIPIENT_LIMIT }} />
        </p>
        {errors.recipients ? (
          <p className="c-field__error">
            <FormattedMessage id={errors.recipients} />
          </p>
        ) : null}
      </fieldset>
      <p className="u-secondary">
        <FormattedMessage id="reports.schedule.owner" />
      </p>
    </FormDialog>
  );
}
