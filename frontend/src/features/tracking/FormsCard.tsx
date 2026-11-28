import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { FormattedMessage, useIntl } from 'react-intl';

import { describeError, type ErrorMessage } from '@/api/errors';
import { formsQuery, putForm, trackingKey, type CollectionForm } from '@/api/tracking';
import { useClient } from '@/app/tenant';
import { SelectField, type Option } from '@/components/Choice';
import { EmptyState } from '@/components/EmptyState';
import { Field, TextAreaField } from '@/components/Field';
import { FormDialog } from '@/components/FormDialog';
import { Icon } from '@/components/Icon';
import { QueryStates } from '@/components/ListStates';
import { ErrorNotice } from '@/components/Notice';
import { RowMenu } from '@/components/RowMenu';
import { Day } from '@/components/Time';
import type { MessageId } from '@/i18n';
import { focusFirstInvalid } from '@/lib/focusFirstInvalid';

import { draftsOf, FIELD_LABEL_MAX, FIELD_NAME_MAX, fieldClasses, formFields, formKeyError, FORM_FIELDS_MAX, type FieldClass, type FieldDraft, type FieldErrors } from './rules';

type Draft = FieldDraft & { id: number };

// Each field drawn in the editor keeps one identity while fields are added and removed.
let drawn = 0;
const withId = (draft: FieldDraft): Draft => ({ ...draft, id: (drawn += 1) });
const blank = (): Draft => withId({ name: '', label: '', dataClass: 'form.option', options: '' });

const classWords = { 'form.option': 'option', 'form.code': 'code', 'form.quantity': 'quantity' } as const;

/** Registers a form, or gives a registered one new fields. The tracker reads only what is listed here. */
function FormDialogEditor({ form, onClose }: { form: CollectionForm | null; onClose: () => void }) {
  const intl = useIntl();
  const queryClient = useQueryClient();
  const { agencyId, clientId } = useClient();
  const [key, setKey] = useState('');
  const [drafts, setDrafts] = useState<Draft[]>(() => (form ? draftsOf(form.fields.fields).map(withId) : [blank()]));
  const [keyError, setKeyError] = useState<MessageId | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors[]>([]);
  const [listError, setListError] = useState<MessageId | null>(null);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const keyRef = useRef<HTMLInputElement>(null);
  const firstNames = useRef<Array<HTMLInputElement | null>>([]);

  const classes: Array<Option<FieldClass>> = fieldClasses.map((value) => ({
    value,
    label: intl.formatMessage({ id: `tracking.field.class.${classWords[value]}` }),
    hint: intl.formatMessage({ id: `tracking.field.class.${classWords[value]}.hint` }),
  }));

  const request = useMutation({
    mutationFn: (fields: ReturnType<typeof formFields>['fields']) => putForm(agencyId, clientId, form?.form_key ?? key.trim(), fields),
    async onSuccess() {
      await queryClient.invalidateQueries({ queryKey: trackingKey(agencyId, clientId, 'forms') });
      onClose();
    },
    onError: (failure) => setProblem(describeError(failure, { validation_failed: 'tracking.forms.error.refused' })),
  });

  const change = (index: number, patch: Partial<FieldDraft>) => setDrafts((current) => current.map((draft, at) => (at === index ? { ...draft, ...patch } : draft)));

  const submit = () => {
    const checked = formFields(drafts);
    const foundKey = form ? null : formKeyError(key.trim());
    setKeyError(foundKey);
    setFieldErrors(checked.errors);
    setListError(checked.error);
    setProblem(null);
    const firstBad = checked.errors.findIndex((item) => Object.values(item).some(Boolean));
    const invalid = focusFirstInvalid([foundKey, keyRef], [firstBad >= 0 ? 'field' : null, { current: firstNames.current[firstBad] ?? null }]);
    if (!invalid && !checked.error) request.mutate(checked.fields);
  };

  return (
    <FormDialog
      isOpen
      wide
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={form ? <FormattedMessage id="tracking.forms.change" values={{ name: form.form_key }} /> : <FormattedMessage id="tracking.forms.new" />}
      submitLabel={<FormattedMessage id={form ? 'common.save' : 'tracking.forms.create'} />}
      busy={request.isPending}
      onSubmit={submit}
    >
      <ErrorNotice message={problem} />
      <p className="c-field__hint">
        <FormattedMessage id="tracking.forms.never" />
      </p>
      {form ? null : (
        <Field
          id="form-key"
          ref={keyRef}
          size="md"
          dir="ltr"
          autoComplete="off"
          spellCheck={false}
          maxLength={100}
          label={<FormattedMessage id="tracking.forms.key" />}
          hint={<FormattedMessage id="tracking.forms.keyHint" />}
          // The dialog was opened to register a form.
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus
          required
          value={key}
          onChange={(value) => setKey(value.toLowerCase())}
          error={keyError}
        />
      )}
      {listError ? (
        <p className="c-field__error" role="alert">
          <Icon name="circle-alert" size="xs" />
          <FormattedMessage id={listError} />
        </p>
      ) : null}
      <ol className="a-fields">
        {drafts.map((draft, index) => {
          const errors = fieldErrors[index] ?? {};
          const number = index + 1;
          return (
            <li key={draft.id} className="a-fields__item">
              <fieldset className="a-fieldset">
                <legend className="c-field__label">
                  <FormattedMessage id="tracking.field.legend" values={{ position: number }} />
                </legend>
                <div className="l-grid l-grid--2">
                  <Field
                    id={`field-name-${number}`}
                    ref={(element) => {
                      firstNames.current[index] = element;
                    }}
                    size="md"
                    dir="ltr"
                    autoComplete="off"
                    spellCheck={false}
                    maxLength={FIELD_NAME_MAX}
                    label={<FormattedMessage id="tracking.field.name" />}
                    hint={<FormattedMessage id="tracking.field.nameHint" />}
                    value={draft.name}
                    onChange={(value) => change(index, { name: value })}
                    error={errors.name}
                  />
                  <Field
                    id={`field-label-${number}`}
                    size="md"
                    autoComplete="off"
                    maxLength={FIELD_LABEL_MAX}
                    label={<FormattedMessage id="tracking.field.label" />}
                    value={draft.label}
                    onChange={(value) => change(index, { label: value })}
                    error={errors.label}
                  />
                </div>
                <SelectField label={<FormattedMessage id="tracking.field.class" />} value={draft.dataClass} onChange={(value) => change(index, { dataClass: value })} options={classes} />
                {draft.dataClass === 'form.option' ? (
                  <TextAreaField
                    id={`field-options-${number}`}
                    rows={3}
                    label={<FormattedMessage id="tracking.field.options" />}
                    hint={<FormattedMessage id="tracking.field.optionsHint" />}
                    value={draft.options}
                    onChange={(value) => change(index, { options: value })}
                    error={errors.options}
                  />
                ) : null}
                {drafts.length > 1 ? (
                  <button
                    type="button"
                    className="c-btn c-btn--ghost c-btn--sm a-disclosure"
                    onClick={() => {
                      setDrafts((current) => current.filter((_, at) => at !== index));
                      setFieldErrors([]);
                    }}
                  >
                    <Icon name="trash-2" size="sm" />
                    <FormattedMessage id="tracking.field.remove" values={{ position: number }} />
                  </button>
                ) : null}
              </fieldset>
            </li>
          );
        })}
      </ol>
      {drafts.length < FORM_FIELDS_MAX ? (
        <button type="button" className="c-btn c-btn--secondary c-btn--sm a-disclosure" onClick={() => setDrafts((current) => [...current, blank()])}>
          <Icon name="plus" size="sm" />
          <FormattedMessage id="tracking.field.add" />
        </button>
      ) : null}
    </FormDialog>
  );
}

/** The forms the tracker may read, field by field. Owners and admins only. */
export function FormsCard() {
  const intl = useIntl();
  const { agencyId, clientId } = useClient();
  const forms = useQuery(formsQuery(agencyId, clientId));
  const [dialog, setDialog] = useState<CollectionForm | 'new' | null>(null);
  const rows = [...(forms.data ?? [])].sort((first, second) => first.form_key.localeCompare(second.form_key));

  return (
    <section className="c-card" aria-labelledby="forms-title">
      <div className="c-card__header">
        <div>
          <h2 className="c-card__title" id="forms-title">
            <FormattedMessage id="tracking.forms.title" />
          </h2>
          <p className="c-card__subtitle">
            <FormattedMessage id="tracking.forms.lead" />
          </p>
        </div>
        {forms.isSuccess ? (
          <button type="button" className="c-btn c-btn--secondary c-btn--sm" onClick={() => setDialog('new')}>
            <Icon name="plus" size="sm" />
            <FormattedMessage id="tracking.forms.new" />
          </button>
        ) : null}
      </div>
      <div className="c-card__body c-card__body--flush">
        <QueryStates query={forms} />
        {forms.isSuccess && rows.length === 0 ? (
          <EmptyState icon="file-text" title={<FormattedMessage id="tracking.forms.empty.title" />} level={3}>
            <FormattedMessage id="tracking.forms.empty.text" />
          </EmptyState>
        ) : null}
        {rows.length > 0 ? (
          <div className="c-table-wrap">
            <table className="c-table">
              <thead>
                <tr>
                  <th scope="col">
                    <FormattedMessage id="tracking.forms.key" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="tracking.forms.fields" />
                  </th>
                  <th scope="col">
                    <FormattedMessage id="tracking.forms.updated" />
                  </th>
                  <th scope="col">
                    <span className="u-sr">
                      <FormattedMessage id="clients.column.actions" />
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((form) => (
                  <tr key={form.id}>
                    <td>
                      <span className="c-table__primary u-mono u-ltr">{form.form_key}</span>
                      <span className="c-table__sub">
                        <FormattedMessage id="links.templates.revision" values={{ count: form.version }} />
                      </span>
                    </td>
                    <td>
                      <span className="l-cluster a-chips">
                        {form.fields.fields.map((field) => (
                          <span key={field.name} className="c-chip u-mono u-ltr">
                            {field.name}
                          </span>
                        ))}
                      </span>
                    </td>
                    <td>
                      <Day value={form.updated_at} />
                    </td>
                    <td className="is-num">
                      <RowMenu
                        label={intl.formatMessage({ id: 'links.actionsForNamed' }, { name: form.form_key })}
                        actions={[
                          {
                            id: 'change',
                            label: <FormattedMessage id="tracking.forms.changeAction" />,
                            text: intl.formatMessage({ id: 'tracking.forms.changeAction' }),
                            onAction: () => setDialog(form),
                          },
                        ]}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
      {dialog ? <FormDialogEditor form={dialog === 'new' ? null : dialog} onClose={() => setDialog(null)} /> : null}
    </section>
  );
}
