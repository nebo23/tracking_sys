import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { brandingLogoQuery, brandingQuery, removeLogo, saveBranding, uploadLogo, type Branding } from '@/api/agencySettings';
import { describeError, type ErrorMessage } from '@/api/errors';
import { Field } from '@/components/Field';
import { QueryStates } from '@/components/ListStates';
import { ErrorNotice, Notice } from '@/components/Notice';
import { SubmitButton } from '@/components/SubmitButton';
import type { MessageId } from '@/i18n';

import { checkLogo, displayNameProblem, isAccentColor, MAX_LOGO_BYTES, MAX_LOGO_PIXELS } from './logo';

const logoErrors = {
  unsupported_media_type: 'settings.branding.logo.not_png',
  invalid_png: 'settings.branding.logo.invalid',
  request_too_large: 'settings.branding.logo.too_large',
  branding_profile_required: 'settings.branding.logo.first',
} as const;

/**
 * The branding profile (B14, D8 of the completion entry review): the display name, accent color
 * and logo that report emails use. Owners and Admins edit it, others read it; in this round it
 * is only previewed here, never shown on the screens of client viewers.
 */
export function BrandingTab({ agencyId, editable }: { agencyId: string; editable: boolean }) {
  const branding = useQuery(brandingQuery(agencyId));
  if (!branding.data) return <QueryStates query={branding} />;
  return <BrandingForm agencyId={agencyId} branding={branding.data} editable={editable} />;
}

function BrandingForm({ agencyId, branding, editable }: { agencyId: string; branding: Branding; editable: boolean }) {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const [name, setName] = useState(branding.display_name ?? '');
  const [color, setColor] = useState(branding.accent_color ?? '#0E7C7B');
  const [errors, setErrors] = useState<{ name?: MessageId | null; color?: MessageId | null }>({});
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const [saved, setSaved] = useState(false);
  const refresh = () => queryClient.invalidateQueries({ queryKey: brandingQuery(agencyId).queryKey });

  const save = useMutation({
    mutationFn: () => saveBranding(agencyId, { display_name: name.trim(), accent_color: color }),
    onSuccess: async (stored) => {
      // The form shows what the API kept: the trimmed name and the color in upper case.
      setName(stored.display_name ?? '');
      setColor(stored.accent_color ?? color);
      setSaved(true);
      await refresh();
    },
    // The API checks the name and the color again, with the same rules.
    onError: (error) => setProblem(describeError(error, { invalid_branding: 'settings.branding.error.invalid' })),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!editable || save.isPending) return;
    const nameProblem = displayNameProblem(name);
    const found = {
      name: nameProblem ? (`settings.branding.name.${nameProblem}` as MessageId) : null,
      color: isAccentColor(color) ? null : ('settings.branding.color.invalid' as MessageId),
    };
    setErrors(found);
    setProblem(null);
    setSaved(false);
    if (!found.name && !found.color) save.mutate();
  };

  return (
    <div className="l-split">
      <article className="c-card">
        <div className="c-card__header">
          <div>
            <h2 className="c-card__title">
              <FormattedMessage id="settings.branding.title" />
            </h2>
            <p className="c-card__subtitle">
              <FormattedMessage id={editable ? 'settings.branding.lead' : 'settings.branding.readOnly'} />
            </p>
          </div>
        </div>
        <form className="c-card__body l-stack" noValidate onSubmit={submit}>
          {saved ? (
            <Notice tone="success">
              <FormattedMessage id="settings.branding.saved" />
            </Notice>
          ) : null}
          <ErrorNotice message={problem} />
          <Field
            id="branding-name"
            size="md"
            label={<FormattedMessage id="settings.branding.name" />}
            value={name}
            onChange={setName}
            maxLength={100}
            readOnly={!editable}
            error={errors.name}
            hint={<FormattedMessage id="settings.branding.nameHint" />}
          />
          <div className="c-field">
            <label className="c-field__label" htmlFor="branding-color">
              <FormattedMessage id="settings.branding.color" />
            </label>
            <div className="l-cluster">
              <input
                id="branding-color"
                className="a-color"
                type="color"
                value={isAccentColor(color) ? color : '#000000'}
                onChange={(event) => setColor(event.target.value.toUpperCase())}
                disabled={!editable}
                aria-describedby="branding-color-hint"
              />
              <input
                className="c-input u-ltr a-color__text"
                aria-label={intl.formatMessage({ id: 'settings.branding.colorText' })}
                value={color}
                onChange={(event) => setColor(event.target.value)}
                readOnly={!editable}
                aria-invalid={errors.color ? true : undefined}
              />
            </div>
            <p className="c-field__hint" id="branding-color-hint">
              <FormattedMessage id="settings.branding.colorHint" />
            </p>
            {errors.color ? (
              <p className="c-field__error">
                <FormattedMessage id={errors.color} />
              </p>
            ) : null}
          </div>
          {editable ? (
            <SubmitButton busy={save.isPending}>
              <FormattedMessage id="settings.branding.save" />
            </SubmitButton>
          ) : null}
        </form>
        <LogoField agencyId={agencyId} branding={branding} editable={editable} onChanged={refresh} />
      </article>
      <Preview agencyId={agencyId} branding={branding} name={name} color={isAccentColor(color) ? color : null} />
    </div>
  );
}

/** The logo: a PNG checked before it is sent, then checked again by the API. The API keeps a logo only with a saved profile. */
function LogoField({ agencyId, branding, editable, onChanged }: { agencyId: string; branding: Branding; editable: boolean; onChanged: () => Promise<unknown> }) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const upload = useMutation({
    mutationFn: async (file: File) => {
      const check = await checkLogo(file);
      if (check.problem) throw new Error(check.problem);
      return uploadLogo(agencyId, file);
    },
    onSuccess: async () => {
      setProblem(null);
      await onChanged();
    },
    onError: (error) => {
      const local = error instanceof Error && ['not_png', 'too_small', 'too_large', 'too_big'].includes(error.message) ? error.message : null;
      setProblem(local ? { id: `settings.branding.logo.${local}` as MessageId, values: { kib: MAX_LOGO_BYTES / 1024, pixels: MAX_LOGO_PIXELS } } : describeError(error, logoErrors));
    },
  });
  const remove = useMutation({ mutationFn: () => removeLogo(agencyId), onSuccess: () => onChanged(), onError: (error) => setProblem(describeError(error)) });
  return (
    <div className="c-card__body l-stack a-logo">
      <h3 className="c-card__title">
        <FormattedMessage id="settings.branding.logo" />
      </h3>
      <p className="u-secondary">
        {branding.logo ? (
          <FormattedMessage id="settings.branding.logo.current" values={{ width: branding.logo.width, height: branding.logo.height, kib: Math.ceil(branding.logo.byte_size / 1024) }} />
        ) : (
          <FormattedMessage id="settings.branding.logo.none" />
        )}
      </p>
      <ErrorNotice message={problem} />
      {editable && !branding.configured ? (
        <p className="u-secondary">
          <FormattedMessage id="settings.branding.logo.first" />
        </p>
      ) : null}
      {editable && branding.configured ? (
        <div className="l-cluster">
          <label className="c-btn c-btn--secondary" htmlFor={id}>
            <FormattedMessage id={branding.logo ? 'settings.branding.logo.replace' : 'settings.branding.logo.upload'} />
          </label>
          <input
            ref={input}
            id={id}
            className="u-sr"
            type="file"
            accept="image/png"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) upload.mutate(file);
              event.target.value = '';
            }}
          />
          {branding.logo ? (
            <button type="button" className="c-btn c-btn--ghost" disabled={remove.isPending} onClick={() => remove.mutate()}>
              <FormattedMessage id="settings.branding.logo.remove" />
            </button>
          ) : null}
        </div>
      ) : null}
      <p className="c-field__hint">
        <FormattedMessage id="settings.branding.logo.hint" values={{ kib: MAX_LOGO_BYTES / 1024, pixels: MAX_LOGO_PIXELS }} />
      </p>
    </div>
  );
}

/** How report emails name the agency: a preview on this page only (D8). */
function Preview({ agencyId, branding, name, color }: { agencyId: string; branding: Branding; name: string; color: string | null }) {
  const logo = useQuery({ ...brandingLogoQuery(agencyId, branding.updated_at), enabled: branding.logo !== null });
  // A local address for the logo the API keeps, made from that very file and revoked with it.
  const [made, setMade] = useState<{ file: Blob; url: string } | null>(null);
  useEffect(() => {
    if (!logo.data) return undefined;
    const next = { file: logo.data, url: URL.createObjectURL(logo.data) };
    setMade(next);
    return () => URL.revokeObjectURL(next.url);
  }, [logo.data]);
  // Nothing is drawn once the logo is removed, nor while a replaced one is still being read.
  const address = branding.logo && made && made.file === logo.data ? made.url : null;
  return (
    <article className="c-card" aria-labelledby="branding-preview-title">
      <div className="c-card__header">
        <div>
          <h2 className="c-card__title" id="branding-preview-title">
            <FormattedMessage id="settings.branding.preview" />
          </h2>
          <p className="c-card__subtitle">
            <FormattedMessage id="settings.branding.previewLead" />
          </p>
        </div>
      </div>
      <div className="c-card__body l-stack">
        <div className="a-brand-preview" style={color ? { borderBlockStartColor: color } : undefined}>
          {address ? <img src={address} alt="" className="a-brand-preview__logo" /> : null}
          <p className="a-brand-preview__name">{name.trim() || <FormattedMessage id="settings.branding.previewDefault" />}</p>
          <p className="u-secondary">
            <FormattedMessage id="settings.branding.previewText" />
          </p>
        </div>
      </div>
    </article>
  );
}
