import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { describeError, type ErrorMessage } from '@/api/errors';
import { campaignsQuery, contentQuery, domainsQuery, linksKey, managedLinksQuery, sitesQuery, updateLink, type ManagedLink } from '@/api/links';
import { useClient } from '@/app/tenant';
import { Badge } from '@/components/Badge';
import { InlineSelect, type Option } from '@/components/Choice';
import { copyText } from '@/components/CopyField';
import { EmptyState } from '@/components/EmptyState';
import { Field } from '@/components/Field';
import { FormDialog } from '@/components/FormDialog';
import { Icon } from '@/components/Icon';
import { ListNone, QueryStates } from '@/components/ListStates';
import { ErrorNotice } from '@/components/Notice';
import { RowMenu, type RowAction } from '@/components/RowMenu';
import { Day } from '@/components/Time';
import type { MessageId } from '@/i18n';
import { cx } from '@/lib/cx';

import type { LinksTabId } from './LinksPage';
import { NewLinkPanel } from './NewLinkPanel';
import { linkState, localValue, moment, readableAddress, shortAddress, type LinkState } from './rules';

const states: readonly LinkState[] = ['active', 'paused', 'expired'];

function StateBadge({ state }: { state: LinkState }) {
  if (state === 'active') {
    return (
      <Badge tone="success" icon="circle-check">
        <FormattedMessage id="links.state.active" />
      </Badge>
    );
  }
  return (
    <Badge icon={state === 'paused' ? 'circle-pause' : 'clock'}>
      <FormattedMessage id={`links.state.${state}`} />
    </Badge>
  );
}

/** Pauses a link after asking, since visitors who open it are turned away at once. */
function PauseDialog({ address, onConfirm, onClose, busy, problem }: { address: string; onConfirm: () => void; onClose: () => void; busy: boolean; problem: ErrorMessage | null }) {
  return (
    <FormDialog
      isOpen
      alert
      tone="danger"
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="links.pause.title" />}
      submitLabel={<FormattedMessage id="links.pause" />}
      cancelLabel={<FormattedMessage id="links.pause.keep" />}
      busy={busy}
      onSubmit={onConfirm}
    >
      <p>
        <FormattedMessage id="links.pause.text" values={{ address: readableAddress(address) }} />
      </p>
      <ErrorNotice message={problem} />
    </FormDialog>
  );
}

/** Gives a link an end, moves it, or removes it. The end is a local date and time. */
function ExpiryDialog({ link, onClose }: { link: ManagedLink; onClose: () => void }) {
  const { agencyId, clientId } = useClient();
  const queryClient = useQueryClient();
  const [value, setValue] = useState(localValue(link.expires_at));
  const [error, setError] = useState<MessageId | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const request = useMutation({
    mutationFn: (expiresAt: string | null) => updateLink(agencyId, clientId, link.id, { expires_at: expiresAt }),
    async onSuccess() {
      await queryClient.invalidateQueries({ queryKey: linksKey(agencyId, clientId, 'links') });
      onClose();
    },
    onError: (failure) => setProblem(describeError(failure)),
  });
  const submit = () => {
    const chosen = moment(value);
    const found: MessageId | null = value !== '' && (!chosen || new Date(chosen).getTime() <= Date.now()) ? 'links.rule.expiryPast' : null;
    setError(found);
    setProblem(null);
    if (!found) request.mutate(chosen);
  };
  return (
    <FormDialog
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={<FormattedMessage id="links.expiry.title" />}
      submitLabel={<FormattedMessage id="common.save" />}
      busy={request.isPending}
      onSubmit={submit}
    >
      <ErrorNotice message={problem} />
      <Field
        id="link-expiry"
        size="md"
        type="datetime-local"
        label={<FormattedMessage id="links.form.expiry" />}
        hint={<FormattedMessage id="links.form.expiryHint" />}
        value={value}
        onChange={setValue}
        error={error}
      />
    </FormDialog>
  );
}

interface LinksTabProps {
  creating: boolean;
  onCreate: () => void;
  onCloseCreate: () => void;
  onGoTo: (tab: LinksTabId) => void;
}

/** The links of the client with their campaign and content, and the panel that creates one. */
export function LinksTab({ creating, onCreate, onCloseCreate, onGoTo }: LinksTabProps) {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId, clientId, manager } = useClient();
  const links = useQuery(managedLinksQuery(agencyId, clientId));
  const campaigns = useQuery(campaignsQuery(agencyId, clientId));
  const content = useQuery(contentQuery(agencyId, clientId));
  const domains = useQuery(domainsQuery(agencyId, clientId));
  // The sites are read for the panel; reading them here as well keeps the panel quick to open.
  useQuery({ ...sitesQuery(agencyId, clientId), enabled: manager });

  const [search, setSearch] = useState('');
  const [campaign, setCampaign] = useState('all');
  const [view, setView] = useState<LinkState>('active');
  const [pausing, setPausing] = useState<ManagedLink | null>(null);
  const [expiring, setExpiring] = useState<ManagedLink | null>(null);
  const [copied, setCopied] = useState<MessageId | null>(null);
  const [pauseProblem, setPauseProblem] = useState<ErrorMessage | null>(null);
  const [rowProblem, setRowProblem] = useState<ErrorMessage | null>(null);

  const status = useMutation({
    mutationFn: ({ link, next }: { link: ManagedLink; next: 'active' | 'disabled' }) => updateLink(agencyId, clientId, link.id, { status: next }),
    async onSuccess() {
      await queryClient.invalidateQueries({ queryKey: linksKey(agencyId, clientId, 'links') });
      setPausing(null);
      setRowProblem(null);
    },
    onError: (failure, { next }) => (next === 'disabled' ? setPauseProblem(describeError(failure)) : setRowProblem(describeError(failure))),
  });

  const now = Date.now();
  const domainOf = (link: ManagedLink) => domains.data?.find((domain) => domain.id === link.domain_id) ?? null;
  const campaignName = (id: string | null) => (id ? campaigns.data?.find((item) => item.id === id)?.label : undefined);
  const contentName = (id: string | null) => {
    const found = id ? content.data?.find((item) => item.id === id) : undefined;
    return found ? (found.platform_label ?? found.external_code) : undefined;
  };

  const all = [...(links.data ?? [])].sort((first, second) => second.created_at.localeCompare(first.created_at));
  const wanted = search.trim().toLocaleLowerCase(intl.locale);
  const rows = all.filter((link) => {
    if (linkState(link, now) !== view) return false;
    if (campaign === 'none' ? link.campaign_id !== null : campaign !== 'all' && link.campaign_id !== campaign) return false;
    if (wanted === '') return true;
    const words = [link.slug, link.destination, campaignName(link.campaign_id) ?? '', contentName(link.content_reference_id) ?? '', domainOf(link)?.hostname ?? ''];
    return words.some((word) => word.toLocaleLowerCase(intl.locale).includes(wanted));
  });
  const counted = all.filter((link) => linkState(link, now) === view).length;

  const campaignOptions: Array<Option<string>> = [
    { value: 'all', label: intl.formatMessage({ id: 'links.filter.allCampaigns' }) },
    { value: 'none', label: intl.formatMessage({ id: 'links.filter.noCampaign' }) },
    ...(campaigns.data ?? []).map((item) => ({ value: item.id, label: item.label })),
  ];

  const copy = async (text: string, what: 'short' | 'target') => {
    setCopied((await copyText(text)) ? (what === 'short' ? 'links.copied.short' : 'links.copied.target') : 'links.copied.failed');
  };

  const actionsOf = (link: ManagedLink): RowAction[] => {
    const address = shortAddress(link.slug, domainOf(link));
    const state = linkState(link, now);
    const actions: RowAction[] = [
      {
        id: 'copy',
        label: <FormattedMessage id="links.action.copy" />,
        text: intl.formatMessage({ id: 'links.action.copy' }),
        onAction: () => void copy(address, 'short'),
      },
      {
        id: 'copy-target',
        label: <FormattedMessage id="links.action.copyTarget" />,
        text: intl.formatMessage({ id: 'links.action.copyTarget' }),
        onAction: () => void copy(link.target_url, 'target'),
      },
    ];
    if (!manager) return actions;
    actions.push({
      id: 'expiry',
      label: <FormattedMessage id="links.action.expiry" />,
      text: intl.formatMessage({ id: 'links.action.expiry' }),
      onAction: () => setExpiring(link),
    });
    if (state === 'paused') {
      actions.push({
        id: 'resume',
        label: <FormattedMessage id="links.action.resume" />,
        text: intl.formatMessage({ id: 'links.action.resume' }),
        onAction: () => status.mutate({ link, next: 'active' }),
      });
    } else {
      actions.push({
        id: 'pause',
        label: <FormattedMessage id="links.pause" />,
        text: intl.formatMessage({ id: 'links.pause' }),
        danger: true,
        onAction: () => {
          setPauseProblem(null);
          setPausing(link);
        },
      });
    }
    return actions;
  };

  const list = (
    <section className="c-card" aria-label={intl.formatMessage({ id: 'links.tab.links' })}>
      <div className="c-card__header">
        <label className="c-search">
          <span className="u-sr">
            <FormattedMessage id="links.search" />
          </span>
          <Icon name="search" size="sm" />
          <input
            className="c-search__input"
            type="search"
            placeholder={intl.formatMessage({ id: 'links.search' })}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <div className="l-cluster">
          <InlineSelect label={intl.formatMessage({ id: 'links.filter.campaign' })} value={campaign} onChange={setCampaign} options={campaignOptions} />
          <div className="c-seg" role="group" aria-label={intl.formatMessage({ id: 'links.filter.state' })}>
            {states.map((option) => (
              <button key={option} type="button" className={cx('c-seg__item', view === option && 'is-active')} aria-pressed={view === option} onClick={() => setView(option)}>
                <FormattedMessage id={`links.view.${option}`} />
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="c-card__body c-card__body--flush">
        <ErrorNotice message={rowProblem} />
        {rows.length === 0 ? (
          <ListNone>
            {wanted !== '' || campaign !== 'all' ? <FormattedMessage id="links.noMatch" /> : <FormattedMessage id={`links.none.${view}`} />}
          </ListNone>
        ) : (
          <div className="c-table-wrap">
            <table className="c-table">
              <thead>
                <tr>
                  <th scope="col">
                    <FormattedMessage id="links.column.link" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="links.column.campaign" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="links.column.content" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="links.column.created" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="links.column.ends" />
                  </th>
                  <th scope="col">
                    <span className="u-sr">
                      <FormattedMessage id="clients.column.actions" />
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((link) => {
                  const address = shortAddress(link.slug, domainOf(link));
                  const campaignLabel = campaignName(link.campaign_id);
                  const contentLabel = contentName(link.content_reference_id);
                  return (
                    <tr key={link.id}>
                      <td>
                        <span className="c-table__primary u-mono u-ltr">{readableAddress(address)}</span>
                        <span className="c-table__sub u-mono u-ltr u-truncate">{readableAddress(link.destination)}</span>
                      </td>
                      {campaignLabel ? (
                        <td>{campaignLabel}</td>
                      ) : (
                        <td className="is-absent">
                          <FormattedMessage id="links.noCampaign" />
                        </td>
                      )}
                      {contentLabel ? (
                        <td>{contentLabel}</td>
                      ) : (
                        <td className="is-absent">
                          <FormattedMessage id="links.noContent" />
                        </td>
                      )}
                      <td>
                        <Day value={link.created_at} />
                      </td>
                      <td>
                        {link.expires_at ? <Day value={link.expires_at} /> : <FormattedMessage id="links.never" />}
                        {view !== 'active' ? (
                          <>
                            {' '}
                            <StateBadge state={linkState(link, now)} />
                          </>
                        ) : null}
                      </td>
                      <td className="is-num">
                        <RowMenu label={intl.formatMessage({ id: 'links.actionsFor' }, { address: readableAddress(address) })} actions={actionsOf(link)} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <div className="c-card__footer">
        <span>
          <FormattedMessage id={`links.count.${view}`} values={{ shown: rows.length, total: counted }} />
        </span>
        <span className="u-end" role="status">
          {copied ? <FormattedMessage id={copied} /> : null}
        </span>
      </div>
    </section>
  );

  const emptyAll = links.isSuccess && all.length === 0;

  return (
    <>
      <QueryStates query={links} />
      {emptyAll && !creating ? (
        <div className="c-card">
          <EmptyState
            icon="link"
            title={<FormattedMessage id="links.empty.title" />}
            action={
              manager ? (
                <button type="button" className="c-btn c-btn--primary" onClick={onCreate}>
                  <Icon name="plus" size="sm" />
                  <FormattedMessage id="links.create" />
                </button>
              ) : undefined
            }
          >
            <FormattedMessage id={manager ? 'links.empty.text' : 'links.empty.textReader'} />
          </EmptyState>
        </div>
      ) : null}
      {links.isSuccess && !emptyAll ? (
        <div className={cx(creating && 'l-split')}>
          {list}
          {creating ? <NewLinkPanel onClose={onCloseCreate} onGoTo={onGoTo} /> : null}
        </div>
      ) : null}
      {emptyAll && creating ? (
        <div className="a-narrow">
          <NewLinkPanel onClose={onCloseCreate} onGoTo={onGoTo} />
        </div>
      ) : null}
      {pausing ? (
        <PauseDialog
          address={shortAddress(pausing.slug, domainOf(pausing))}
          busy={status.isPending}
          problem={pauseProblem}
          onConfirm={() => status.mutate({ link: pausing, next: 'disabled' })}
          onClose={() => setPausing(null)}
        />
      ) : null}
      {expiring ? <ExpiryDialog link={expiring} onClose={() => setExpiring(null)} /> : null}
    </>
  );
}
