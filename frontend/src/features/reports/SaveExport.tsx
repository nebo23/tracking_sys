import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { FormattedMessage } from 'react-intl';

import { describeError, type ErrorMessage } from '@/api/errors';
import { createExport, exportsKey, type ExportInput, type ReportExport } from '@/api/reportDelivery';
import type { ReportFamily, ReportScope } from '@/api/reports';
import { FormDialog } from '@/components/FormDialog';
import { Icon } from '@/components/Icon';
import { ErrorNotice } from '@/components/Notice';
import type { MessageId } from '@/i18n';

import { previousPeriod, reportNameId, useModelLabel, usePeriodText } from './describe';
import { saleValueFamilies } from './rules';

/** What a report page downloads as CSV; the export keeps the same report. */
export interface ReportChoice {
  scope: ReportScope;
  family: ReportFamily;
  parameters: Record<string, string>;
}

/** Whether the report is compared: never a content cohort or the models side by side (016-A, 016-B). */
export function comparesWith(choice: ReportChoice): boolean {
  const { family, parameters, scope } = choice;
  return scope.compare && !(family === 'social' && parameters.view !== 'daily') && parameters.view !== 'models';
}

/** The body of the export: the family, the page's choices and its days (D2). */
export function exportInput(choice: ReportChoice): ExportInput {
  return {
    family: choice.family,
    start: choice.scope.range.start,
    end: choice.scope.range.end,
    ...choice.parameters,
    compare: comparesWith(choice) ? 'previous' : null,
  } as ExportInput;
}

export const saveErrors = {
  export_limit_reached: 'reports.save.error.export_limit_reached',
  not_configured: 'reports.save.error.not_configured',
} as const satisfies Record<string, MessageId>;

/** "Save as export" beside "Download CSV" on every report page (D9, E05). */
export function SaveExportButton({ choice, onSaved }: { choice: ReportChoice; onSaved: (saved: ReportExport) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className="c-btn c-btn--secondary" onClick={() => setOpen(true)}>
        <Icon name="bookmark" size="sm" />
        <FormattedMessage id="reports.save.open" />
      </button>
      {open ? (
        <SaveExportDialog
          choice={choice}
          onClose={() => setOpen(false)}
          onSaved={(saved) => {
            setOpen(false);
            onSaved(saved);
          }}
        />
      ) : null}
    </>
  );
}

function SaveExportDialog({ choice, onClose, onSaved }: { choice: ReportChoice; onClose: () => void; onSaved: (saved: ReportExport) => void }) {
  const queryClient = useQueryClient();
  const period = usePeriodText();
  const { agencyId, clientId, range } = choice.scope;
  const model = useModelLabel(agencyId, clientId, choice.parameters.model_version);
  const [problem, setProblem] = useState<ErrorMessage | null>(null);
  const save = useMutation({
    mutationFn: () => createExport(agencyId, clientId, exportInput(choice)),
    onSuccess: async (saved) => {
      await queryClient.invalidateQueries({ queryKey: exportsKey(agencyId, clientId) });
      onSaved(saved);
    },
    onError: (error) => setProblem(describeError(error, saveErrors)),
  });
  const previous = previousPeriod(range.start, range.end);
  const days = Math.round((Date.parse(`${range.end}T00:00:00Z`) - Date.parse(`${range.start}T00:00:00Z`)) / 86_400_000);

  return (
    <FormDialog
      isOpen
      onOpenChange={(isOpen) => {
        if (!isOpen) onClose();
      }}
      title={<FormattedMessage id="reports.save.title" />}
      submitLabel={<FormattedMessage id="reports.save.submit" />}
      busy={save.isPending}
      onSubmit={() => {
        if (save.isPending) return;
        setProblem(null);
        save.mutate();
      }}
    >
      <dl className="c-dl c-dl--split">
        <dt>
          <FormattedMessage id="reports.detail.report" />
        </dt>
        <dd>
          <FormattedMessage id={reportNameId(choice.family, choice.parameters)} />
        </dd>
        {model ? (
          <>
            <dt>
              <FormattedMessage id="attribution.model.label" />
            </dt>
            <dd>{model}</dd>
          </>
        ) : null}
        <dt>
          <FormattedMessage id="reports.detail.period" />
        </dt>
        <dd>
          <FormattedMessage id="reports.detail.periodDays" values={{ period: period(range.start, range.end), days }} />
        </dd>
        {comparesWith(choice) ? (
          <>
            <dt>
              <FormattedMessage id="reports.detail.comparedWith" />
            </dt>
            <dd>{period(previous.start, previous.end)}</dd>
          </>
        ) : null}
        {saleValueFamilies.has(choice.family) ? (
          <>
            <dt>
              <FormattedMessage id="reports.detail.saleValues" />
            </dt>
            <dd>
              <FormattedMessage id="reports.save.saleValues" />
            </dd>
          </>
        ) : null}
      </dl>
      <p>
        <FormattedMessage id="reports.save.text" />
      </p>
      <ErrorNotice message={problem} />
    </FormDialog>
  );
}
