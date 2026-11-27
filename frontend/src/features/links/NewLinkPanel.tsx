import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { describeError, type ErrorMessage } from '@/api/errors';
import {
  campaignsQuery,
  contentQuery,
  createLink,
  domainsQuery,
  linksKey,
  sitesQuery,
  templatesQuery,
  type LinkInput,
  type ManagedLink,
} from '@/api/links';
import { shortLinkOrigin } from '@/app/config';
import { useClient } from '@/app/tenant';
import { SelectField, type Option } from '@/components/Choice';
import { CopyField } from '@/components/CopyField';
import { Field } from '@/components/Field';
import { Icon } from '@/components/Icon';
import { QueryStates } from '@/components/ListStates';
import { ErrorNotice, Notice } from '@/components/Notice';
import { SubmitButton } from '@/components/SubmitButton';
import type { MessageId } from '@/i18n';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';

import type { LinksTabId } from './LinksPage';
import { destinationError, moment, readableAddress, shortAddress, slugError, SLUG_MAX, UTM_NAMES, utmValues, type UtmName } from './rules';

const NONE = 'none';
const PLATFORM = 'platform';

interface NewLinkPanelProps {
  onClose: () => void;
  onGoTo: (tab: LinksTabId) => void;
}

type Errors = Partial<Record<'destination' | 'slug' | 'expiry' | UtmName, MessageId | null>>;

/**
 * Draws up a link beside the list: where it leads, its short address, and what it carries with
 * it. The address visitors arrive at is made by the API and shown once the link exists.
 */
export function NewLinkPanel({ onClose, onGoTo }: NewLinkPanelProps) {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId, clientId } = useClient();
  const sites = useQuery(sitesQuery(agencyId, clientId));
  const domains = useQuery(domainsQuery(agencyId, clientId));
  const campaigns = useQuery(campaignsQuery(agencyId, clientId));
  const content = useQuery(contentQuery(agencyId, clientId));
  const templates = useQuery(templatesQuery(agencyId, clientId));

  const [destination, setDestination] = useState('');
  const [domain, setDomain] = useState(PLATFORM);
  const [slug, setSlug] = useState('');
  const [campaign, setCampaign] = useState(NONE);
  const [reference, setReference] = useState(NONE);
  const [template, setTemplate] = useState(NONE);
  const [utmOpen, setUtmOpen] = useState(false);
  const [utm, setUtm] = useState<Partial<Record<UtmName, string>>>({});
  const [expiry, setExpiry] = useState('');
  const [errors, setErrors] = useState<Errors>({});
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const [created, setCreated] = useState<ManagedLink | null>(null);
  const destinationRef = useRef<HTMLInputElement>(null);
  const slugRef = useRef<HTMLInputElement>(null);
  const expiryRef = useRef<HTMLInputElement>(null);
  const utmRefs = useRef<Partial<Record<UtmName, HTMLInputElement | null>>>({});
  const panel = useRef<HTMLFormElement>(null);

  // The panel opens beside the list, or under it on a narrow screen: it is brought into view.
  useEffect(() => {
    panel.current?.scrollIntoView?.({ block: 'nearest' });
  }, []);

  const activeSites = (sites.data ?? []).filter((site) => site.status === 'active');
  const usableDomains = (domains.data ?? []).filter((item) => item.status !== 'disabled');
  const chosenDomain = usableDomains.find((item) => item.id === domain) ?? null;
  const active = <T extends { status: string }>(items: readonly T[] | undefined) => (items ?? []).filter((item) => item.status === 'active');

  const none = (id: MessageId): Option<string> => ({ value: NONE, label: intl.formatMessage({ id }) });
  const domainOptions: Array<Option<string>> = [
    { value: PLATFORM, label: readableAddress(shortLinkOrigin) },
    ...usableDomains.map((item) => ({
      value: item.id,
      label: item.hostname,
      hint: item.status === 'verified' ? undefined : intl.formatMessage({ id: 'links.form.domainPending' }),
    })),
  ];
  const campaignOptions = [none('links.form.noCampaign'), ...active(campaigns.data).map((item) => ({ value: item.id, label: item.label, hint: item.public_code }))];
  const contentOptions = [
    none('links.form.noContent'),
    ...active(content.data).map((item) => ({ value: item.id, label: item.platform_label ?? item.external_code, hint: item.platform_label ? item.external_code : undefined })),
  ];
  const templateOptions = [
    none('links.form.noTemplate'),
    ...active(templates.data).map((item) => ({
      value: item.id,
      label: item.name,
      hint: Object.entries(item.parameters)
        .map(([name, value]) => `${name}=${value}`)
        .join(' '),
    })),
  ];

  const request = useMutation({
    mutationFn: (input: LinkInput) => createLink(agencyId, clientId, input),
    async onSuccess(link) {
      await queryClient.invalidateQueries({ queryKey: linksKey(agencyId, clientId, 'links') });
      setCreated(link);
    },
    onError: (failure) =>
      setProblem(describeError(failure, { state_conflict: 'links.error.slugTaken', validation_failed: 'links.error.refused' })),
  });

  const submit = () => {
    const values = utmValues(utm);
    const until = moment(expiry);
    const found: Errors = {
      destination: destinationError(destination, activeSites),
      slug: slugError(slug.trim()),
      ...Object.fromEntries(values.invalid.map((name) => [name, 'links.rule.code'])),
      expiry: expiry !== '' && (!until || new Date(until).getTime() <= Date.now()) ? 'links.rule.expiryPast' : null,
    };
    if (values.invalid.length > 0) setUtmOpen(true);
    setErrors(found);
    setProblem(null);
    const firstUtm = values.invalid[0];
    const invalid = focusFirstInvalid(
      [found.destination, destinationRef],
      [found.slug, slugRef],
      [firstUtm, { current: firstUtm ? (utmRefs.current[firstUtm] ?? null) : null }],
      [found.expiry, expiryRef],
    );
    if (invalid) return;
    request.mutate({
      slug: slug.trim(),
      destination: destination.trim(),
      domain_id: chosenDomain?.id ?? null,
      campaign_id: campaign === NONE ? null : campaign,
      content_reference_id: reference === NONE ? null : reference,
      template_id: template === NONE ? null : template,
      ...(Object.keys(values.values).length > 0 ? { utm: values.values } : {}),
      expires_at: until,
    });
  };

  const again = () => {
    setCreated(null);
    setSlug('');
    setErrors({});
    setProblem(null);
    slugRef.current?.focus();
  };

  const header = (
    <div className="c-card__header">
      <div>
        <h2 className="c-card__title" id="new-link-title">
          <FormattedMessage id={created ? 'links.created.title' : 'links.form.title'} />
        </h2>
        <p className="c-card__subtitle">
          <FormattedMessage id={created ? 'links.created.subtitle' : 'links.form.subtitle'} />
        </p>
      </div>
      <button type="button" className="c-btn c-btn--ghost c-btn--sm c-btn--icon" aria-label={intl.formatMessage({ id: 'links.form.close' })} onClick={onClose}>
        <Icon name="x" size="sm" />
      </button>
    </div>
  );

  if (created) {
    const address = shortAddress(created.slug, usableDomains.find((item) => item.id === created.domain_id));
    return (
      <section className="c-card" aria-labelledby="new-link-title">
        {header}
        <div className="c-card__body l-stack">
          <Notice tone="success">
            <FormattedMessage id="links.created.text" />
          </Notice>
          <CopyField id="created-short" label={<FormattedMessage id="links.created.short" />} value={address} />
          <CopyField
            id="created-target"
            label={<FormattedMessage id="links.created.target" />}
            value={created.target_url}
            hint={<FormattedMessage id="links.created.targetHint" />}
            multiline
          />
        </div>
        <div className="c-card__footer">
          <button type="button" className="c-btn c-btn--primary" onClick={again}>
            <FormattedMessage id="links.created.another" />
          </button>
          <button type="button" className="c-btn c-btn--ghost" onClick={onClose}>
            <FormattedMessage id="common.done" />
          </button>
        </div>
      </section>
    );
  }

  const preview = slug.trim() !== '' && !slugError(slug.trim()) ? shortAddress(slug.trim(), chosenDomain) : null;

  return (
    <form
      ref={panel}
      className="c-card"
      aria-labelledby="new-link-title"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (!request.isPending) submit();
      }}
    >
      {header}
      <div className="c-card__body l-stack">
        <QueryStates query={sites} lines={2} />
        {sites.isSuccess && activeSites.length === 0 ? (
          <Notice
            tone="warning"
            quiet
            title={<FormattedMessage id="links.form.noSites.title" />}
            action={
              <button type="button" className="c-btn c-btn--secondary c-btn--sm" onClick={() => onGoTo('sites')}>
                <FormattedMessage id="links.form.noSites.action" />
              </button>
            }
          >
            <FormattedMessage id="links.form.noSites.text" />
          </Notice>
        ) : null}
        <ErrorNotice message={problem} />
        <Field
          id="link-destination"
          ref={destinationRef}
          size="md"
          type="url"
          dir="ltr"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          label={<FormattedMessage id="links.form.destination" />}
          hint={
            activeSites.length > 0 ? (
              <FormattedMessage
                id="links.form.destinationHint"
                values={{ sites: activeSites.map((site) => readableAddress(site.origin)).join(', ') }}
              />
            ) : (
              <FormattedMessage id="links.form.destinationHintNone" />
            )
          }
          placeholder="https://"
          // The panel was opened to write this link.
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus
          value={destination}
          onChange={setDestination}
          error={errors.destination}
        />
        {usableDomains.length > 0 ? (
          <SelectField label={<FormattedMessage id="links.form.domain" />} value={domain} onChange={setDomain} options={domainOptions} />
        ) : null}
        <Field
          id="link-slug"
          ref={slugRef}
          size="md"
          dir="ltr"
          autoComplete="off"
          spellCheck={false}
          maxLength={SLUG_MAX}
          label={<FormattedMessage id="links.form.slug" />}
          hint={
            preview ? (
              <FormattedMessage id="links.form.slugPreview" values={{ address: readableAddress(preview) }} />
            ) : (
              <FormattedMessage id="links.form.slugHint" />
            )
          }
          value={slug}
          onChange={(value) => setSlug(value.toLowerCase())}
          error={errors.slug}
        />
        <SelectField label={<FormattedMessage id="links.form.campaign" />} value={campaign} onChange={setCampaign} options={campaignOptions} />
        <SelectField label={<FormattedMessage id="links.form.content" />} value={reference} onChange={setReference} options={contentOptions} />
        <SelectField
          label={<FormattedMessage id="links.form.template" />}
          value={template}
          onChange={setTemplate}
          options={templateOptions}
          hint={<FormattedMessage id="links.form.templateHint" />}
        />
        <div className="l-stack l-stack--tight">
          <button
            type="button"
            className="c-btn c-btn--ghost c-btn--sm a-disclosure"
            aria-expanded={utmOpen}
            aria-controls="link-utm"
            onClick={() => setUtmOpen((open) => !open)}
          >
            <Icon name="chevron-down" size="sm" className={utmOpen ? 'a-turned' : undefined} />
            <FormattedMessage id="links.form.utm" />
          </button>
          <fieldset id="link-utm" className="a-fieldset" hidden={!utmOpen}>
            <legend className="u-sr">
              <FormattedMessage id="links.form.utm" />
            </legend>
            <p className="c-field__hint">
              <FormattedMessage id="links.form.utmHint" />
            </p>
            {UTM_NAMES.map((name) => (
              <Field
                key={name}
                id={`link-${name}`}
                ref={(element) => {
                  utmRefs.current[name] = element;
                }}
                size="md"
                dir="ltr"
                autoComplete="off"
                spellCheck={false}
                maxLength={64}
                label={<span className="u-mono">{name}</span>}
                value={utm[name] ?? ''}
                onChange={(value) => setUtm((current) => ({ ...current, [name]: value }))}
                error={errors[name]}
              />
            ))}
          </fieldset>
        </div>
        <Field
          id="link-expiry-new"
          ref={expiryRef}
          size="md"
          type="datetime-local"
          label={<FormattedMessage id="links.form.expiry" />}
          hint={<FormattedMessage id="links.form.expiryHint" />}
          value={expiry}
          onChange={setExpiry}
          error={errors.expiry}
        />
      </div>
      <div className="c-card__footer">
        <SubmitButton size="md" block={false} busy={request.isPending}>
          <FormattedMessage id="links.create" />
        </SubmitButton>
        <button type="button" className="c-btn c-btn--ghost" onClick={onClose}>
          <FormattedMessage id="common.cancel" />
        </button>
      </div>
    </form>
  );
}
