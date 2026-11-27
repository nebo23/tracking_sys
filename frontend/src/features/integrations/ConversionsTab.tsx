import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { connectionsQuery, type Connection } from '@/api/connections';
import { describeError, isApiError, type ErrorMessage } from '@/api/errors';
import {
  createDestination,
  deliveriesQuery,
  destinationsQuery,
  dismissDelivery,
  integrationsKey,
  requeueDelivery,
  updateDestination,
  type ConversionDelivery,
  type ConversionDestination,
} from '@/api/integrations';
import { useClient } from '@/app/tenant';
import { Badge, type BadgeTone } from '@/components/Badge';
import { SelectField, type Option } from '@/components/Choice';
import { ConfirmDialog } from '@/components/ConfirmDialog';
import { EmptyState } from '@/components/EmptyState';
import { Field } from '@/components/Field';
import { FormDialog } from '@/components/FormDialog';
import { Icon, type IconName } from '@/components/Icon';
import { ListNone, QueryStates } from '@/components/ListStates';
import { ErrorNotice, Notice } from '@/components/Notice';
import { RowMenu, type RowAction } from '@/components/RowMenu';
import { Moment } from '@/components/Time';
import { ConnectDialog } from '@/features/connections/ConnectDialog';
import { datasetProviders, isDataset } from '@/features/connections/providers';
import { reasonMessage } from '@/features/tracking/rules';
import type { MessageId } from '@/i18n';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';

import { IntegrationCard, OnOff } from './shared';

// The rules of the API for a destination (DestinationInput): Meta's own limits for these values.
const EVENT_NAME = /^[A-Za-z][A-Za-z0-9_]{0,39}$/;
const TEST_CODE = /^[A-Za-z0-9]{1,32}$/;

const destinationErrors: Partial<Record<string, MessageId>> = {
  not_a_delivery_connection: 'integrations.conversions.error.not_a_delivery_connection',
  connection_not_active: 'integrations.conversions.error.connection_not_active',
  destination_exists: 'integrations.conversions.error.destination_exists',
  invalid_event_name: 'integrations.conversions.error.eventName',
  invalid_test_event_code: 'integrations.conversions.error.testCode',
};

const deliveryStates: Record<string, { tone: BadgeTone; icon: IconName }> = {
  queued: { tone: 'neutral', icon: 'clock' },
  sending: { tone: 'info', icon: 'loader-circle' },
  delivered: { tone: 'success', icon: 'circle-check' },
  blocked: { tone: 'neutral', icon: 'ban' },
  cancelled: { tone: 'neutral', icon: 'circle-slash' },
  expired: { tone: 'warning', icon: 'clock' },
  rejected: { tone: 'danger', icon: 'circle-alert' },
  undeliverable: { tone: 'danger', icon: 'circle-alert' },
  dismissed: { tone: 'neutral', icon: 'circle-x' },
};
const deliveryWords = ['queued', 'sending', 'delivered', 'blocked', 'cancelled', 'expired', 'rejected', 'undeliverable', 'dismissed'] as const;
const deliveryReasons = ['deadline_passed', 'destination_disabled', 'connection_ended'] as const;

/** How a dataset is named: the label its provider gives it, or its number. */
const accountName = (connection: Connection): string => connection.account?.label ?? connection.account?.external_account_id ?? connection.id;

/** The reason of a delivery in words where the interface has them; otherwise the API's code. */
function DeliveryReason({ delivery }: { delivery: ConversionDelivery }) {
  if (delivery.rejection_class) return <FormattedMessage id={`integrations.deliveries.rejection.${delivery.rejection_class}`} />;
  if (!delivery.reason) return null;
  const own = deliveryReasons.find((item) => item === delivery.reason);
  if (own) return <FormattedMessage id={`integrations.deliveries.reason.${own}`} />;
  const consent = reasonMessage(delivery.reason);
  return consent ? <FormattedMessage id={consent} /> : <span className="u-mono u-ltr">{delivery.reason}</span>;
}

function DestinationDialog({ destination, datasets, onClose }: { destination: ConversionDestination | null; datasets: readonly Connection[]; onClose: () => void }) {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId, clientId } = useClient();
  const [connection, setConnection] = useState(destination?.connection_id ?? datasets[0]?.id ?? '');
  const [eventName, setEventName] = useState(destination?.event_name ?? 'Purchase');
  const [testCode, setTestCode] = useState(destination?.test_event_code ?? '');
  const [errors, setErrors] = useState<{ event?: MessageId | null; test?: MessageId | null }>({});
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const eventRef = useRef<HTMLInputElement>(null);
  const testRef = useRef<HTMLInputElement>(null);
  const request = useMutation({
    mutationFn: () => {
      const code = testCode.trim();
      if (!destination) return createDestination(agencyId, clientId, { connection_id: connection, event_name: eventName.trim(), test_event_code: code === '' ? null : code });
      return updateDestination(agencyId, clientId, destination.id, code === '' ? { event_name: eventName.trim(), clear_test_event_code: true } : { event_name: eventName.trim(), test_event_code: code });
    },
    async onSuccess() {
      await queryClient.invalidateQueries({ queryKey: integrationsKey(agencyId, clientId, 'destinations') });
      onClose();
    },
    onError: (failure) => setProblem(describeError(failure, destinationErrors)),
  });
  const submit = () => {
    const name = eventName.trim();
    const code = testCode.trim();
    const found = {
      event: name === '' ? ('field.error.required' as const) : EVENT_NAME.test(name) ? null : ('integrations.conversions.error.eventName' as const),
      test: code === '' || TEST_CODE.test(code) ? null : ('integrations.conversions.error.testCode' as const),
    };
    setErrors(found);
    setProblem(null);
    if (!focusFirstInvalid([found.event, eventRef], [found.test, testRef])) request.mutate();
  };
  const options: Array<Option<string>> = datasets.map((item) => ({ value: item.id, label: accountName(item), hint: item.account?.external_account_id }));
  return (
    <FormDialog
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={destination ? <FormattedMessage id="integrations.conversions.change" /> : <FormattedMessage id="integrations.conversions.new" />}
      submitLabel={<FormattedMessage id={destination ? 'common.save' : 'integrations.conversions.create'} />}
      busy={request.isPending}
      onSubmit={submit}
    >
      <ErrorNotice message={problem} />
      {destination ? null : (
        <SelectField label={<FormattedMessage id="integrations.conversions.dataset" />} value={connection} onChange={setConnection} options={options} />
      )}
      <Field
        id="destination-event"
        ref={eventRef}
        size="md"
        dir="ltr"
        autoComplete="off"
        spellCheck={false}
        maxLength={40}
        label={<FormattedMessage id="integrations.conversions.eventName" />}
        hint={<FormattedMessage id="integrations.conversions.eventNameHint" />}
        required
        value={eventName}
        onChange={setEventName}
        error={errors.event}
      />
      <Field
        id="destination-test"
        ref={testRef}
        size="md"
        dir="ltr"
        autoComplete="off"
        spellCheck={false}
        maxLength={32}
        label={<FormattedMessage id="integrations.conversions.testCode" />}
        hint={<FormattedMessage id="integrations.conversions.testCodeHint" />}
        placeholder={intl.formatMessage({ id: 'integrations.conversions.testCodeNone' })}
        value={testCode}
        onChange={setTestCode}
        error={errors.test}
      />
      {destination ? null : (
        <Notice tone="info" quiet>
          <FormattedMessage id="integrations.conversions.startsOff" />
        </Notice>
      )}
    </FormDialog>
  );
}

function DestinationsCard() {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId, clientId, client, manager } = useClient();
  const destinations = useQuery(destinationsQuery(agencyId, clientId));
  const connections = useQuery(connectionsQuery(agencyId, clientId));
  const [dialog, setDialog] = useState<ConversionDestination | 'new' | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [turningOff, setTurningOff] = useState<ConversionDestination | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: integrationsKey(agencyId, clientId, 'destinations') });
  const turnOn = useMutation({
    mutationFn: (destination: ConversionDestination) => updateDestination(agencyId, clientId, destination.id, { enabled: true }),
    onSuccess: () => {
      setProblem(null);
      return refresh();
    },
    onError: (failure) => setProblem(describeError(failure, destinationErrors)),
  });

  const datasets = (connections.data ?? []).filter((item) => isDataset(item.provider) && item.status === 'active');
  const taken = new Set((destinations.data ?? []).map((item) => item.connection_id));
  const free = datasets.filter((item) => !taken.has(item.id));
  const datasetName = (connectionId: string) => {
    const found = connections.data?.find((item) => item.id === connectionId);
    return found ? accountName(found) : null;
  };
  const say = (id: MessageId) => ({ label: <FormattedMessage id={id} />, text: intl.formatMessage({ id }) });
  const rows = destinations.data ?? [];

  const action = manager ? (
    <div className="l-cluster">
      <button type="button" className="c-btn c-btn--ghost c-btn--sm" onClick={() => setConnecting(true)}>
        <Icon name="plug" size="sm" />
        <FormattedMessage id="integrations.conversions.connect" />
      </button>
      {free.length > 0 ? (
        <button type="button" className="c-btn c-btn--secondary c-btn--sm" onClick={() => setDialog('new')}>
          <Icon name="plus" size="sm" />
          <FormattedMessage id="integrations.conversions.new" />
        </button>
      ) : null}
    </div>
  ) : undefined;

  return (
    <IntegrationCard
      id="destinations-title"
      glyph="meta"
      title={<FormattedMessage id="integrations.conversions.title" />}
      lead={<FormattedMessage id="integrations.conversions.lead" />}
      action={action}
      footer={
        <>
          <Icon name="shield-check" size="sm" />
          <FormattedMessage id="integrations.conversions.footer" />
        </>
      }
    >
      <QueryStates query={destinations} />
      <div className="a-pad--x">
        <ErrorNotice message={problem} />
      </div>
      {destinations.isSuccess && rows.length === 0 ? (
        <EmptyState icon="send" title={<FormattedMessage id="integrations.conversions.empty.title" />} level={3}>
          <FormattedMessage id={manager ? (datasets.length > 0 ? 'integrations.conversions.empty.ready' : 'integrations.conversions.empty.connect') : 'integrations.conversions.empty.reader'} />
        </EmptyState>
      ) : null}
      {rows.length > 0 ? (
        <div className="c-table-wrap">
          <table className="c-table">
            <thead>
              <tr>
                <th scope="col">
                  <FormattedMessage id="integrations.conversions.dataset" />
                </th>
                <th scope="col">
                  <FormattedMessage id="integrations.conversions.eventName" />
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
              {rows.map((destination) => {
                const name = datasetName(destination.connection_id) ?? intl.formatMessage({ id: 'integrations.conversions.datasetGone' });
                const actions: RowAction[] = destination.actions.update
                  ? [
                      { id: 'change', ...say('integrations.conversions.changeAction'), onAction: () => setDialog(destination) },
                      destination.enabled
                        ? { id: 'off', ...say('links.action.turnOff'), danger: true, onAction: () => setTurningOff(destination) }
                        : { id: 'on', ...say('links.action.turnOn'), onAction: () => turnOn.mutate(destination) },
                    ]
                  : [];
                return (
                  <tr key={destination.id}>
                    <td>
                      <span className="c-table__primary">{name}</span>
                    </td>
                    <td>
                      <span className="u-mono u-ltr">{destination.event_name}</span>
                      {destination.test_event_code ? (
                        <span className="c-table__sub">
                          <FormattedMessage id="integrations.conversions.testing" values={{ code: destination.test_event_code }} />
                        </span>
                      ) : null}
                    </td>
                    <td>
                      <OnOff on={destination.enabled} onWord="integrations.conversions.sending" />
                    </td>
                    <td className="is-num">
                      {actions.length > 0 ? <RowMenu label={intl.formatMessage({ id: 'links.actionsForNamed' }, { name })} actions={actions} /> : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
      {dialog ? <DestinationDialog destination={dialog === 'new' ? null : dialog} datasets={dialog === 'new' ? free : datasets} onClose={() => setDialog(null)} /> : null}
      {connecting ? (
        <ConnectDialog agencyId={agencyId} clientId={clientId} clientName={client.name} providers={datasetProviders} place="integrations" onClose={() => setConnecting(false)} />
      ) : null}
      {turningOff ? (
        <ConfirmDialog
          title="integrations.conversions.off.title"
          text="integrations.conversions.off.text"
          submit="links.action.turnOff"
          keep="links.sites.off.keep"
          danger
          onConfirm={async () => {
            await updateDestination(agencyId, clientId, turningOff.id, { enabled: false });
            await refresh();
            setTurningOff(null);
          }}
          onClose={() => setTurningOff(null)}
        />
      ) : null}
    </IntegrationCard>
  );
}

function DeliveriesCard() {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId, clientId } = useClient();
  const deliveries = useQuery(deliveriesQuery(agencyId, clientId));
  const [dismissing, setDismissing] = useState<ConversionDelivery | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: integrationsKey(agencyId, clientId, 'deliveries') });
  const requeue = useMutation({
    mutationFn: (delivery: ConversionDelivery) => requeueDelivery(agencyId, clientId, delivery.id),
    onSuccess: () => {
      setProblem(null);
      return refresh();
    },
    onError: (failure) => setProblem(describeError(failure, { requeue_not_available: 'integrations.deliveries.error.requeue' })),
  });
  // Deliveries carry the value of each sale: without financial access the API refuses the list.
  const refused = deliveries.isError && isApiError(deliveries.error) && deliveries.error.status === 403;
  const rows = deliveries.data ?? [];
  const say = (id: MessageId) => ({ label: <FormattedMessage id={id} />, text: intl.formatMessage({ id }) });
  const value = (delivery: ConversionDelivery) => {
    const amount = Number(delivery.value);
    if (!Number.isFinite(amount)) return `${delivery.value} ${delivery.currency}`;
    try {
      return intl.formatNumber(amount, { style: 'currency', currency: delivery.currency });
    } catch {
      return `${delivery.value} ${delivery.currency}`;
    }
  };

  return (
    <IntegrationCard id="deliveries-title" icon="send" title={<FormattedMessage id="integrations.deliveries.title" />} lead={<FormattedMessage id="integrations.deliveries.lead" />}>
      {refused ? (
        <div className="a-pad">
          <Notice tone="info" quiet>
            <FormattedMessage id="integrations.deliveries.financial" />
          </Notice>
        </div>
      ) : (
        <QueryStates query={deliveries} />
      )}
      <div className="a-pad--x">
        <ErrorNotice message={problem} />
      </div>
      {deliveries.isSuccess && rows.length === 0 ? (
        <ListNone>
          <FormattedMessage id="integrations.deliveries.none" />
        </ListNone>
      ) : null}
      {rows.length > 0 ? (
        <div className="c-table-wrap">
          <table className="c-table">
            <thead>
              <tr>
                <th scope="col">
                  <FormattedMessage id="integrations.deliveries.event" />
                </th>
                <th scope="col">
                  <FormattedMessage id="team.column.state" />
                </th>
                <th scope="col" className="is-num">
                  <FormattedMessage id="integrations.deliveries.value" />
                </th>
                <th scope="col" className="is-num">
                  <FormattedMessage id="integrations.deliveries.attempts" />
                </th>
                <th scope="col">
                  <span className="u-sr">
                    <FormattedMessage id="clients.column.actions" />
                  </span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((delivery) => {
                const state = deliveryWords.find((item) => item === delivery.status);
                const look = deliveryStates[delivery.status] ?? { tone: 'neutral' as const, icon: 'circle-dot' as const };
                const actions: RowAction[] = [
                  ...(delivery.actions.requeue ? [{ id: 'requeue', ...say('integrations.deliveries.requeue'), onAction: () => requeue.mutate(delivery) }] : []),
                  ...(delivery.actions.dismiss ? [{ id: 'dismiss', ...say('integrations.deliveries.dismiss'), danger: true, onAction: () => setDismissing(delivery) }] : []),
                ];
                return (
                  <tr key={delivery.id}>
                    <td>
                      <span className="c-table__primary u-mono u-ltr">{delivery.event_name}</span>
                      <span className="c-table__sub">
                        <Moment value={delivery.event_time} />
                      </span>
                    </td>
                    <td>
                      <Badge tone={look.tone} icon={look.icon}>
                        {state ? <FormattedMessage id={`integrations.deliveries.state.${state}`} /> : delivery.status}
                      </Badge>
                      <span className="c-table__sub">
                        <DeliveryReason delivery={delivery} />
                      </span>
                    </td>
                    <td className="is-num u-num">{value(delivery)}</td>
                    <td className="is-num u-num">{intl.formatNumber(delivery.attempts)}</td>
                    <td className="is-num">
                      {actions.length > 0 ? <RowMenu label={intl.formatMessage({ id: 'links.actionsForNamed' }, { name: delivery.event_name })} actions={actions} /> : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
      {dismissing ? (
        <ConfirmDialog
          title="integrations.deliveries.dismiss.title"
          text="integrations.deliveries.dismiss.text"
          submit="integrations.deliveries.dismiss"
          keep="integrations.deliveries.dismiss.keep"
          danger
          errors={{ dismiss_not_available: 'integrations.deliveries.error.dismiss' }}
          onConfirm={async () => {
            await dismissDelivery(agencyId, clientId, dismissing.id);
            await refresh();
            setDismissing(null);
          }}
          onClose={() => setDismissing(null)}
        />
      ) : null}
    </IntegrationCard>
  );
}

/** Verified sales sent back to a Meta dataset for ad measurement, with the visitor's consent (specification 014). */
export function ConversionsTab() {
  return (
    <div className="l-stack l-stack--loose">
      <DestinationsCard />
      <DeliveriesCard />
    </div>
  );
}
