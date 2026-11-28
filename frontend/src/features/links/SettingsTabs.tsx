import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState, type ReactNode } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { describeError, type ErrorMessage } from '@/api/errors';
import {
  campaignsQuery,
  contentQuery,
  createCampaign,
  createContent,
  createSite,
  createTemplate,
  linksKey,
  sitesQuery,
  templatesQuery,
  updateCampaign,
  updateContent,
  updateSite,
  updateTemplate,
  type DestinationSite,
  type UtmTemplate,
} from '@/api/links';
import { useClient } from '@/app/tenant';
import { Badge } from '@/components/Badge';
import { EmptyState } from '@/components/EmptyState';
import { Field } from '@/components/Field';
import { FormDialog } from '@/components/FormDialog';
import { Icon, type IconName } from '@/components/Icon';
import { QueryStates } from '@/components/ListStates';
import { ErrorNotice } from '@/components/Notice';
import { RowMenu, type RowAction } from '@/components/RowMenu';
import { Day } from '@/components/Time';
import type { MessageId } from '@/i18n';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';

import {
  CONTENT_CODE_MAX,
  CONTENT_LABEL_MAX,
  LABEL_MAX,
  codeError,
  contentCodeError,
  labelError,
  queryNamesError,
  readableAddress,
  siteOrigin,
  splitNames,
  UTM_NAMES,
  utmValues,
  type UtmName,
} from './rules';

// The settings a link is made of. Each list is read by every reader of the client and changed by
// its owners and admins; the API audits each change.

const conflicts = (code: MessageId): Partial<Record<string, MessageId>> => ({ state_conflict: code, validation_failed: 'links.error.settingRefused' });

function StatusBadge({ active, off }: { active: boolean; off: MessageId }) {
  return active ? (
    <Badge tone="success" icon="circle-check">
      <FormattedMessage id="links.setting.active" />
    </Badge>
  ) : (
    <Badge icon="circle-pause">
      <FormattedMessage id={off} />
    </Badge>
  );
}

interface SettingCardProps {
  id: string;
  title: MessageId;
  lead: MessageId;
  newLabel: MessageId;
  onNew: (() => void) | null;
  children: ReactNode;
}

/** A card with the list of one setting and, for a manager, the button that adds one. */
function SettingCard({ id, title, lead, newLabel, onNew, children }: SettingCardProps) {
  return (
    <section className="c-card" aria-labelledby={id}>
      <div className="c-card__header">
        <div>
          <h2 className="c-card__title" id={id}>
            <FormattedMessage id={title} />
          </h2>
          <p className="c-card__subtitle">
            <FormattedMessage id={lead} />
          </p>
        </div>
        {onNew ? (
          <button type="button" className="c-btn c-btn--secondary c-btn--sm" onClick={onNew}>
            <Icon name="plus" size="sm" />
            <FormattedMessage id={newLabel} />
          </button>
        ) : null}
      </div>
      <div className="c-card__body c-card__body--flush">{children}</div>
    </section>
  );
}

function Empty({ icon, title, text }: { icon: IconName; title: MessageId; text: MessageId }) {
  return (
    <EmptyState icon={icon} title={<FormattedMessage id={title} />} level={3}>
      <FormattedMessage id={text} />
    </EmptyState>
  );
}

/** Newest first, the active ones before those that were set aside. */
const ordered = <T extends { status: string; created_at: string }>(items: readonly T[] | undefined): T[] =>
  [...(items ?? [])].sort((first, second) => {
    if ((first.status === 'active') !== (second.status === 'active')) return first.status === 'active' ? -1 : 1;
    return second.created_at.localeCompare(first.created_at);
  });

interface CodeLabelDialogProps {
  title: ReactNode;
  submitLabel: ReactNode;
  /** The code is given once, when the item is created, and never changes. */
  code: { label: MessageId; hint: MessageId; max: number; check: (value: string) => MessageId | null } | null;
  label: { label: MessageId; hint?: MessageId; max: number; required: boolean };
  initial?: string;
  conflict: MessageId;
  onSave: (code: string, label: string) => Promise<unknown>;
  onClose: () => void;
}

/** Creates a campaign or a content reference with its code and its name, or renames one. */
function CodeLabelDialog({ title, submitLabel, code, label, initial = '', conflict, onSave, onClose }: CodeLabelDialogProps) {
  const [codeValue, setCodeValue] = useState('');
  const [labelValue, setLabelValue] = useState(initial);
  const [errors, setErrors] = useState<{ code?: MessageId | null; label?: MessageId | null }>({});
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const codeRef = useRef<HTMLInputElement>(null);
  const labelRef = useRef<HTMLInputElement>(null);
  const request = useMutation({
    mutationFn: () => onSave(codeValue.trim(), labelValue.trim()),
    onSuccess: onClose,
    onError: (failure) => setProblem(describeError(failure, conflicts(conflict))),
  });
  const submit = () => {
    const found = {
      code: code ? code.check(codeValue.trim()) : null,
      label: label.required || labelValue.trim() !== '' ? labelError(labelValue, label.max) : null,
    };
    setErrors(found);
    setProblem(null);
    if (!focusFirstInvalid([found.code, codeRef], [found.label, labelRef])) request.mutate();
  };
  return (
    <FormDialog
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={title}
      submitLabel={submitLabel}
      busy={request.isPending}
      onSubmit={submit}
    >
      <ErrorNotice message={problem} />
      {code ? (
        <Field
          id="setting-code"
          ref={codeRef}
          size="md"
          dir="ltr"
          autoComplete="off"
          spellCheck={false}
          maxLength={code.max}
          label={<FormattedMessage id={code.label} />}
          hint={<FormattedMessage id={code.hint} />}
          // The dialog was opened to type this code.
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus
          required
          value={codeValue}
          onChange={setCodeValue}
          error={errors.code}
        />
      ) : null}
      <Field
        id="setting-label"
        ref={labelRef}
        size="md"
        autoComplete="off"
        maxLength={label.max}
        label={<FormattedMessage id={label.label} />}
        hint={label.hint ? <FormattedMessage id={label.hint} /> : undefined}
        // When the code is fixed, the dialog was opened to change this name.
        // eslint-disable-next-line jsx-a11y/no-autofocus
        autoFocus={!code}
        required={label.required}
        value={labelValue}
        onChange={setLabelValue}
        error={errors.label}
      />
    </FormDialog>
  );
}

// ------------------------------------------------------------------ Campaigns --
export function CampaignsTab() {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId, clientId, manager } = useClient();
  const campaigns = useQuery(campaignsQuery(agencyId, clientId));
  const [dialog, setDialog] = useState<{ id: string; label: string } | 'new' | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: linksKey(agencyId, clientId, 'campaigns') });
  const status = useMutation({
    mutationFn: ({ id, next }: { id: string; next: 'active' | 'archived' }) => updateCampaign(agencyId, clientId, id, { status: next }),
    onSuccess: () => {
      setProblem(null);
      return refresh();
    },
    onError: (failure) => setProblem(describeError(failure)),
  });
  const rows = ordered(campaigns.data);
  return (
    <SettingCard
      id="campaigns-title"
      title="links.campaigns.title"
      lead="links.campaigns.lead"
      newLabel="links.campaigns.new"
      onNew={manager ? () => setDialog('new') : null}
    >
      <QueryStates query={campaigns} />
      <ErrorNotice message={problem} />
      {campaigns.isSuccess && rows.length === 0 ? <Empty icon="megaphone" title="links.campaigns.empty.title" text="links.campaigns.empty.text" /> : null}
      {rows.length > 0 ? (
        <div className="c-table-wrap">
          <table className="c-table">
            <thead>
              <tr>
                <th scope="col">
                  <FormattedMessage id="links.column.campaign" />
                </th>
                <th scope="col">
                  <FormattedMessage id="team.column.state" />
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
              {rows.map((item) => {
                const actions: RowAction[] = [
                  { id: 'rename', label: <FormattedMessage id="links.action.rename" />, text: intl.formatMessage({ id: 'links.action.rename' }), onAction: () => setDialog({ id: item.id, label: item.label }) },
                  item.status === 'active'
                    ? { id: 'archive', label: <FormattedMessage id="links.action.archive" />, text: intl.formatMessage({ id: 'links.action.archive' }), onAction: () => status.mutate({ id: item.id, next: 'archived' }) }
                    : { id: 'restore', label: <FormattedMessage id="links.action.restore" />, text: intl.formatMessage({ id: 'links.action.restore' }), onAction: () => status.mutate({ id: item.id, next: 'active' }) },
                ];
                return (
                  <tr key={item.id}>
                    <td>
                      <span className="c-table__primary">{item.label}</span>
                      <span className="c-table__sub u-mono u-ltr">{item.public_code}</span>
                    </td>
                    <td>
                      <StatusBadge active={item.status === 'active'} off="links.setting.archived" />
                    </td>
                    <td>
                      <Day value={item.created_at} />
                    </td>
                    <td className="is-num">{manager ? <RowMenu label={intl.formatMessage({ id: 'links.actionsForNamed' }, { name: item.label })} actions={actions} /> : null}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
      {dialog ? (
        <CodeLabelDialog
          title={<FormattedMessage id={dialog === 'new' ? 'links.campaigns.new' : 'links.campaigns.rename'} />}
          submitLabel={<FormattedMessage id={dialog === 'new' ? 'links.campaigns.create' : 'common.save'} />}
          code={dialog === 'new' ? { label: 'links.campaigns.code', hint: 'links.campaigns.codeHint', max: 64, check: codeError } : null}
          label={{ label: 'links.campaigns.label', max: LABEL_MAX, required: true }}
          initial={dialog === 'new' ? '' : dialog.label}
          conflict="links.campaigns.error.exists"
          onSave={async (code, label) => {
            await (dialog === 'new' ? createCampaign(agencyId, clientId, { public_code: code, label }) : updateCampaign(agencyId, clientId, dialog.id, { label }));
            await refresh();
          }}
          onClose={() => setDialog(null)}
        />
      ) : null}
    </SettingCard>
  );
}

// -------------------------------------------------------------------- Content --
export function ContentTab() {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId, clientId, manager } = useClient();
  const content = useQuery(contentQuery(agencyId, clientId));
  const [dialog, setDialog] = useState<{ id: string; label: string } | 'new' | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: linksKey(agencyId, clientId, 'content') });
  const status = useMutation({
    mutationFn: ({ id, next }: { id: string; next: 'active' | 'archived' }) => updateContent(agencyId, clientId, id, { status: next }),
    onSuccess: () => {
      setProblem(null);
      return refresh();
    },
    onError: (failure) => setProblem(describeError(failure)),
  });
  const rows = ordered(content.data);
  return (
    <SettingCard id="content-title" title="links.content.title" lead="links.content.lead" newLabel="links.content.new" onNew={manager ? () => setDialog('new') : null}>
      <QueryStates query={content} />
      <ErrorNotice message={problem} />
      {content.isSuccess && rows.length === 0 ? <Empty icon="file-text" title="links.content.empty.title" text="links.content.empty.text" /> : null}
      {rows.length > 0 ? (
        <div className="c-table-wrap">
          <table className="c-table">
            <thead>
              <tr>
                <th scope="col">
                  <FormattedMessage id="links.column.content" />
                </th>
                <th scope="col">
                  <FormattedMessage id="team.column.state" />
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
              {rows.map((item) => {
                const name = item.platform_label ?? item.external_code;
                const actions: RowAction[] = [
                  { id: 'rename', label: <FormattedMessage id="links.action.rename" />, text: intl.formatMessage({ id: 'links.action.rename' }), onAction: () => setDialog({ id: item.id, label: item.platform_label ?? '' }) },
                  item.status === 'active'
                    ? { id: 'archive', label: <FormattedMessage id="links.action.archive" />, text: intl.formatMessage({ id: 'links.action.archive' }), onAction: () => status.mutate({ id: item.id, next: 'archived' }) }
                    : { id: 'restore', label: <FormattedMessage id="links.action.restore" />, text: intl.formatMessage({ id: 'links.action.restore' }), onAction: () => status.mutate({ id: item.id, next: 'active' }) },
                ];
                return (
                  <tr key={item.id}>
                    <td>
                      <span className="c-table__primary">{name}</span>
                      {item.platform_label ? <span className="c-table__sub u-mono u-ltr">{item.external_code}</span> : null}
                    </td>
                    <td>
                      <StatusBadge active={item.status === 'active'} off="links.setting.archived" />
                    </td>
                    <td>
                      <Day value={item.created_at} />
                    </td>
                    <td className="is-num">{manager ? <RowMenu label={intl.formatMessage({ id: 'links.actionsForNamed' }, { name })} actions={actions} /> : null}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
      {dialog ? (
        <CodeLabelDialog
          title={<FormattedMessage id={dialog === 'new' ? 'links.content.new' : 'links.content.rename'} />}
          submitLabel={<FormattedMessage id={dialog === 'new' ? 'links.content.create' : 'common.save'} />}
          code={dialog === 'new' ? { label: 'links.content.code', hint: 'links.content.codeHint', max: CONTENT_CODE_MAX, check: contentCodeError } : null}
          // A content reference may go without a name; once it has one, a rename gives it another.
          label={{ label: 'links.content.label', hint: 'links.content.labelHint', max: CONTENT_LABEL_MAX, required: dialog !== 'new' }}
          initial={dialog === 'new' ? '' : dialog.label}
          conflict="links.content.error.exists"
          onSave={async (code, label) => {
            await (dialog === 'new'
              ? createContent(agencyId, clientId, { external_code: code, platform_label: label === '' ? null : label })
              : updateContent(agencyId, clientId, dialog.id, { platform_label: label }));
            await refresh();
          }}
          onClose={() => setDialog(null)}
        />
      ) : null}
    </SettingCard>
  );
}

// ------------------------------------------------------------------ Templates --
function TemplateDialog({ template, onClose }: { template: UtmTemplate | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { agencyId, clientId } = useClient();
  const [name, setName] = useState('');
  const [values, setValues] = useState<Partial<Record<UtmName, string>>>(template?.parameters ?? {});
  const [errors, setErrors] = useState<Partial<Record<'name' | 'values' | UtmName, MessageId | null>>>({});
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const valueRefs = useRef<Partial<Record<UtmName, HTMLInputElement | null>>>({});
  const request = useMutation({
    mutationFn: (parameters: Record<string, string>) =>
      template ? updateTemplate(agencyId, clientId, template.id, { parameters }) : createTemplate(agencyId, clientId, { name: name.trim(), parameters }),
    async onSuccess() {
      await queryClient.invalidateQueries({ queryKey: linksKey(agencyId, clientId, 'templates') });
      onClose();
    },
    onError: (failure) => setProblem(describeError(failure, conflicts('links.templates.error.exists'))),
  });
  const submit = () => {
    const checked = utmValues(values);
    const found = {
      name: template ? null : labelError(name, LABEL_MAX),
      values: Object.keys(checked.values).length === 0 && checked.invalid.length === 0 ? ('links.templates.error.empty' as const) : null,
      ...Object.fromEntries(checked.invalid.map((item) => [item, 'links.rule.code'])),
    };
    setErrors(found);
    setProblem(null);
    // With no value at all the first field is where to start; otherwise the first value that breaks the rule.
    const valueField = found.values ? UTM_NAMES[0] : checked.invalid[0];
    const target = { current: valueField ? (valueRefs.current[valueField] ?? null) : null };
    if (!focusFirstInvalid([found.name, nameRef], [found.values ?? valueField, target])) request.mutate(checked.values);
  };
  return (
    <FormDialog
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={template ? <FormattedMessage id="links.templates.change" values={{ name: template.name }} /> : <FormattedMessage id="links.templates.new" />}
      submitLabel={<FormattedMessage id={template ? 'common.save' : 'links.templates.create'} />}
      busy={request.isPending}
      onSubmit={submit}
    >
      <ErrorNotice message={problem} />
      {template ? (
        <p>
          <FormattedMessage id="links.templates.changeText" />
        </p>
      ) : (
        <Field
          id="template-name"
          ref={nameRef}
          size="md"
          autoComplete="off"
          maxLength={LABEL_MAX}
          label={<FormattedMessage id="links.templates.name" />}
          hint={<FormattedMessage id="links.templates.nameHint" />}
          // The dialog was opened to name a template.
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus
          required
          value={name}
          onChange={setName}
          error={errors.name}
        />
      )}
      <fieldset className="a-fieldset">
        <legend className="c-field__label">
          <FormattedMessage id="links.templates.values" />
        </legend>
        <p className="c-field__hint">
          <FormattedMessage id="links.templates.valuesHint" />
        </p>
        {errors.values ? (
          <p className="c-field__error">
            <Icon name="circle-alert" size="xs" />
            <FormattedMessage id={errors.values} />
          </p>
        ) : null}
        {UTM_NAMES.map((item) => (
          <Field
            key={item}
            id={`template-${item}`}
            ref={(element) => {
              valueRefs.current[item] = element;
            }}
            size="md"
            dir="ltr"
            autoComplete="off"
            spellCheck={false}
            maxLength={64}
            label={<span className="u-mono">{item}</span>}
            value={values[item] ?? ''}
            onChange={(value) => setValues((current) => ({ ...current, [item]: value }))}
            error={errors[item]}
          />
        ))}
      </fieldset>
    </FormDialog>
  );
}

export function TemplatesTab() {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId, clientId, manager } = useClient();
  const templates = useQuery(templatesQuery(agencyId, clientId));
  const [dialog, setDialog] = useState<UtmTemplate | 'new' | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const status = useMutation({
    mutationFn: ({ id, next }: { id: string; next: 'active' | 'archived' }) => updateTemplate(agencyId, clientId, id, { status: next }),
    onSuccess: () => {
      setProblem(null);
      return queryClient.invalidateQueries({ queryKey: linksKey(agencyId, clientId, 'templates') });
    },
    onError: (failure) => setProblem(describeError(failure)),
  });
  const rows = ordered(templates.data);
  return (
    <SettingCard
      id="templates-title"
      title="links.templates.title"
      lead="links.templates.lead"
      newLabel="links.templates.new"
      onNew={manager ? () => setDialog('new') : null}
    >
      <QueryStates query={templates} />
      <ErrorNotice message={problem} />
      {templates.isSuccess && rows.length === 0 ? <Empty icon="tag" title="links.templates.empty.title" text="links.templates.empty.text" /> : null}
      {rows.length > 0 ? (
        <div className="c-table-wrap">
          <table className="c-table">
            <thead>
              <tr>
                <th scope="col">
                  <FormattedMessage id="links.templates.name" />
                </th>
                <th scope="col">
                  <FormattedMessage id="links.templates.values" />
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
              {rows.map((item) => {
                const actions: RowAction[] = [
                  { id: 'change', label: <FormattedMessage id="links.action.changeValues" />, text: intl.formatMessage({ id: 'links.action.changeValues' }), onAction: () => setDialog(item) },
                  item.status === 'active'
                    ? { id: 'archive', label: <FormattedMessage id="links.action.archive" />, text: intl.formatMessage({ id: 'links.action.archive' }), onAction: () => status.mutate({ id: item.id, next: 'archived' }) }
                    : { id: 'restore', label: <FormattedMessage id="links.action.restore" />, text: intl.formatMessage({ id: 'links.action.restore' }), onAction: () => status.mutate({ id: item.id, next: 'active' }) },
                ];
                return (
                  <tr key={item.id}>
                    <td>
                      <span className="c-table__primary">{item.name}</span>
                      <span className="c-table__sub">
                        <FormattedMessage id="links.templates.revision" values={{ count: item.revision }} />
                      </span>
                    </td>
                    <td>
                      <span className="l-cluster a-chips">
                        {Object.entries(item.parameters).map(([name, value]) => (
                          <span key={name} className="c-chip u-mono u-ltr">
                            {name}={value}
                          </span>
                        ))}
                      </span>
                    </td>
                    <td>
                      <StatusBadge active={item.status === 'active'} off="links.setting.archived" />
                    </td>
                    <td className="is-num">{manager ? <RowMenu label={intl.formatMessage({ id: 'links.actionsForNamed' }, { name: item.name })} actions={actions} /> : null}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
      {dialog ? <TemplateDialog template={dialog === 'new' ? null : dialog} onClose={() => setDialog(null)} /> : null}
    </SettingCard>
  );
}

// ---------------------------------------------------------- Destination sites --
function SiteDialog({ site, onClose }: { site: DestinationSite | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { agencyId, clientId } = useClient();
  const [origin, setOrigin] = useState('');
  const [names, setNames] = useState(site?.query_names.join(', ') ?? '');
  const [errors, setErrors] = useState<{ origin?: MessageId | null; names?: MessageId | null }>({});
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const originRef = useRef<HTMLInputElement>(null);
  const namesRef = useRef<HTMLInputElement>(null);
  const request = useMutation({
    mutationFn: ({ canonical, kept }: { canonical: string; kept: string[] }) =>
      site ? updateSite(agencyId, clientId, site.id, { query_names: kept }) : createSite(agencyId, clientId, { origin: canonical, query_names: kept }),
    async onSuccess() {
      await queryClient.invalidateQueries({ queryKey: linksKey(agencyId, clientId, 'sites') });
      onClose();
    },
    onError: (failure) => setProblem(describeError(failure, { ...conflicts('links.sites.error.exists'), host_conflict: 'links.sites.error.hostConflict' })),
  });
  const submit = () => {
    const parsed = site ? { origin: site.origin, error: null } : siteOrigin(origin);
    const kept = splitNames(names);
    const found = { origin: parsed.error, names: queryNamesError(kept) };
    setErrors(found);
    setProblem(null);
    if (!focusFirstInvalid([found.origin, originRef], [found.names, namesRef]) && parsed.origin) request.mutate({ canonical: parsed.origin, kept });
  };
  return (
    <FormDialog
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={site ? <FormattedMessage id="links.sites.change" values={{ site: readableAddress(site.origin) }} /> : <FormattedMessage id="links.sites.new" />}
      submitLabel={<FormattedMessage id={site ? 'common.save' : 'links.sites.create'} />}
      busy={request.isPending}
      onSubmit={submit}
    >
      <ErrorNotice message={problem} />
      {site ? null : (
        <Field
          id="site-origin"
          ref={originRef}
          size="md"
          type="url"
          dir="ltr"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          placeholder="https://"
          label={<FormattedMessage id="links.sites.origin" />}
          hint={<FormattedMessage id="links.sites.originHint" />}
          // The dialog was opened to name a site.
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus
          required
          value={origin}
          onChange={setOrigin}
          error={errors.origin}
        />
      )}
      <Field
        id="site-names"
        ref={namesRef}
        size="md"
        dir="ltr"
        autoComplete="off"
        spellCheck={false}
        label={<FormattedMessage id="links.sites.names" />}
        hint={<FormattedMessage id="links.sites.namesHint" />}
        // When the site is fixed, the dialog was opened to change these names.
        // eslint-disable-next-line jsx-a11y/no-autofocus
        autoFocus={Boolean(site)}
        value={names}
        onChange={setNames}
        error={errors.names}
      />
    </FormDialog>
  );
}

/** Turns a site off after asking: the links that lead to it stop working while it is off. */
function SiteOffDialog({ site, onClose }: { site: DestinationSite; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { agencyId, clientId } = useClient();
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const request = useMutation({
    mutationFn: () => updateSite(agencyId, clientId, site.id, { status: 'disabled' }),
    async onSuccess() {
      await queryClient.invalidateQueries({ queryKey: linksKey(agencyId, clientId, 'sites') });
      onClose();
    },
    onError: (failure) => setProblem(describeError(failure)),
  });
  return (
    <FormDialog
      isOpen
      alert
      tone="danger"
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="links.sites.off.title" values={{ site: readableAddress(site.origin) }} />}
      submitLabel={<FormattedMessage id="links.action.turnOff" />}
      cancelLabel={<FormattedMessage id="links.sites.off.keep" />}
      busy={request.isPending}
      onSubmit={() => {
        setProblem(null);
        request.mutate();
      }}
    >
      <p>
        <FormattedMessage id="links.sites.off.text" />
      </p>
      <ErrorNotice message={problem} />
    </FormDialog>
  );
}

export function SitesTab() {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId, clientId, manager } = useClient();
  const sites = useQuery(sitesQuery(agencyId, clientId));
  const [dialog, setDialog] = useState<DestinationSite | 'new' | null>(null);
  const [turningOff, setTurningOff] = useState<DestinationSite | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const turnOn = useMutation({
    mutationFn: (site: DestinationSite) => updateSite(agencyId, clientId, site.id, { status: 'active' }),
    onSuccess: () => {
      setProblem(null);
      return queryClient.invalidateQueries({ queryKey: linksKey(agencyId, clientId, 'sites') });
    },
    onError: (failure) => setProblem(describeError(failure, { host_conflict: 'links.sites.error.hostConflict' })),
  });
  const rows = ordered(sites.data);
  return (
    <SettingCard id="sites-title" title="links.sites.title" lead="links.sites.lead" newLabel="links.sites.new" onNew={manager ? () => setDialog('new') : null}>
      <QueryStates query={sites} />
      <ErrorNotice message={problem} />
      {sites.isSuccess && rows.length === 0 ? <Empty icon="globe" title="links.sites.empty.title" text="links.sites.empty.text" /> : null}
      {rows.length > 0 ? (
        <div className="c-table-wrap">
          <table className="c-table">
            <thead>
              <tr>
                <th scope="col">
                  <FormattedMessage id="links.sites.origin" />
                </th>
                <th scope="col">
                  <FormattedMessage id="links.sites.kept" />
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
              {rows.map((site) => {
                const actions: RowAction[] = [
                  { id: 'change', label: <FormattedMessage id="links.action.changeNames" />, text: intl.formatMessage({ id: 'links.action.changeNames' }), onAction: () => setDialog(site) },
                  site.status === 'active'
                    ? { id: 'off', label: <FormattedMessage id="links.action.turnOff" />, text: intl.formatMessage({ id: 'links.action.turnOff' }), danger: true, onAction: () => setTurningOff(site) }
                    : { id: 'on', label: <FormattedMessage id="links.action.turnOn" />, text: intl.formatMessage({ id: 'links.action.turnOn' }), onAction: () => turnOn.mutate(site) },
                ];
                return (
                  <tr key={site.id}>
                    <td>
                      <span className="c-table__primary u-mono u-ltr">{readableAddress(site.origin)}</span>
                      <span className="c-table__sub">
                        <FormattedMessage id="links.sites.added" values={{ date: intl.formatDate(site.created_at, { day: 'numeric', month: 'short', year: 'numeric' }) }} />
                      </span>
                    </td>
                    {site.query_names.length > 0 ? (
                      <td>
                        <span className="l-cluster a-chips">
                          {site.query_names.map((name) => (
                            <span key={name} className="c-chip u-mono u-ltr">
                              {name}
                            </span>
                          ))}
                        </span>
                      </td>
                    ) : (
                      <td className="is-absent">
                        <FormattedMessage id="links.sites.keptNone" />
                      </td>
                    )}
                    <td>
                      <StatusBadge active={site.status === 'active'} off="links.setting.off" />
                    </td>
                    <td className="is-num">
                      {manager ? <RowMenu label={intl.formatMessage({ id: 'links.actionsForNamed' }, { name: readableAddress(site.origin) })} actions={actions} /> : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
      {dialog ? <SiteDialog site={dialog === 'new' ? null : dialog} onClose={() => setDialog(null)} /> : null}
      {turningOff ? <SiteOffDialog site={turningOff} onClose={() => setTurningOff(null)} /> : null}
    </SettingCard>
  );
}
