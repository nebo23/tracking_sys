import { useId, useState } from 'react';
import { FormattedMessage } from 'react-intl';
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { Icon } from '@/components/Icon';
import { TableScroll } from '@/components/TableScroll';

/** One day of a series: this period's value and, when compared, the matching day of the previous one. */
export interface SeriesPoint {
  date: string;
  /** Null where the value is not available: the chart leaves a gap and the table names why. */
  current: number | null;
  previous?: number | null;
  previousDate?: string;
  /** The words for a value that is not available on this day, shown in the table. */
  gap?: string;
}

interface SeriesChartProps {
  /** The chart's name, for its table and for assistive technology. */
  title: string;
  /** One sentence that says what the chart shows, for everyone who cannot see it. */
  summary: string;
  points: readonly SeriesPoint[];
  compare: boolean;
  kind?: 'line' | 'bar';
  format: (value: number) => string;
  formatDate: (date: string) => string;
  currentLabel: string;
  previousLabel: string;
  /** The total of each period, for the legend, when the series has one. */
  totals?: { current?: string; previous?: string };
  /** The words for the day of a point, in the table's first column. */
  dayLabel: string;
}

interface TipProps {
  active?: boolean;
  payload?: ReadonlyArray<{ dataKey?: unknown; value?: unknown; payload?: unknown }>;
  label?: unknown;
  format: (value: number) => string;
  formatDate: (date: string) => string;
  currentLabel: string;
}

function Tip({ active, payload, label, format, formatDate, currentLabel }: TipProps) {
  if (!active || !payload?.length) return null;
  const point = payload[0]?.payload as SeriesPoint | undefined;
  return (
    <div className="c-tip">
      <span className="c-tip__title">{formatDate(String(label))}</span>
      {payload.map((entry) => (
        <span key={String(entry.dataKey)} className="c-tip__row">
          <span className={`c-legend__line ${entry.dataKey === 'current' ? 'b1' : 'b0'}`} />
          {entry.dataKey === 'current' ? currentLabel : point?.previousDate ? formatDate(point.previousDate) : ''}
          <span className="c-tip__value u-num">{typeof entry.value === 'number' ? format(entry.value) : point?.gap}</span>
        </span>
      ))}
    </div>
  );
}

/**
 * A series of days (D3 of the completion entry review): a line or bars for this period and a
 * thinner line for the previous one, with a table of the same points and a one-sentence
 * summary. Time runs left to right in both languages (D-083), and the chart is reached and read
 * with the keyboard through the Recharts accessibility layer.
 */
export function SeriesChart(props: SeriesChartProps) {
  const { title, summary, points, compare, kind = 'line', format, formatDate, currentLabel, previousLabel, totals, dayLabel } = props;
  const [asTable, setAsTable] = useState(false);
  const tableId = useId();
  const data = [...points];
  const tooltip = (
    <Tooltip
      content={({ active, payload, label }) => (
        <Tip active={active} payload={payload} label={label} format={format} formatDate={formatDate} currentLabel={currentLabel} />
      )}
    />
  );
  const axes = (
    <>
      <CartesianGrid className="c-chart__grid" vertical={false} />
      <XAxis dataKey="date" tickFormatter={formatDate} tickLine={false} className="c-chart__axis" minTickGap={24} />
      <YAxis tickFormatter={format} tickLine={false} axisLine={false} width={64} />
    </>
  );

  return (
    <figure className="a-series l-stack l-stack--tight">
      <div className="a-series__head">
        <div className="c-legend">
          <span className="c-legend__item">
            <span className="c-legend__line b1" />
            {currentLabel}
            {totals?.current ? <span className="c-legend__value u-num">{totals.current}</span> : null}
          </span>
          {compare ? (
            <span className="c-legend__item">
              <span className="c-legend__line b0" />
              {previousLabel}
              {totals?.previous ? <span className="c-legend__value u-num">{totals.previous}</span> : null}
            </span>
          ) : null}
        </div>
        <button
          type="button"
          className="c-btn c-btn--ghost c-btn--sm"
          aria-pressed={asTable}
          aria-controls={asTable ? tableId : undefined}
          onClick={() => setAsTable((shown) => !shown)}
        >
          <Icon name="table-2" size="sm" />
          <FormattedMessage id="chart.table" />
        </button>
      </div>
      {asTable ? (
        <div className="a-series__table" id={tableId}>
          <TableScroll label={title}>
            <table className="c-table">
              <caption className="u-sr">{title}</caption>
              <thead>
                <tr>
                  <th scope="col">{dayLabel}</th>
                  <th scope="col" className="is-num">
                    {currentLabel}
                  </th>
                  {compare ? (
                    <th scope="col" className="is-num">
                      {previousLabel}
                    </th>
                  ) : null}
                </tr>
              </thead>
              <tbody>
                {points.map((point) => (
                  <tr key={point.date}>
                    <th scope="row">{formatDate(point.date)}</th>
                    <td className="is-num u-num">{point.current === null ? point.gap : format(point.current)}</td>
                    {compare ? (
                      <td className="is-num u-num">{point.previous === null || point.previous === undefined ? point.gap : format(point.previous)}</td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        </div>
      ) : (
        <div className="c-chart-wrap" dir="ltr">
          <ResponsiveContainer width="100%" height={240} initialDimension={{ width: 640, height: 240 }}>
            {kind === 'bar' ? (
              <BarChart data={data} className="c-chart" title={title} desc={summary} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                {axes}
                {tooltip}
                {compare ? <Bar dataKey="previous" className="f0" isAnimationActive={false} /> : null}
                <Bar dataKey="current" className="f1" isAnimationActive={false} />
              </BarChart>
            ) : (
              <LineChart data={data} className="c-chart" title={title} desc={summary} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                {axes}
                {tooltip}
                {compare ? (
                  <Line dataKey="previous" className="c-chart__line c-chart__line--context s0" dot={false} isAnimationActive={false} />
                ) : null}
                <Line dataKey="current" className="c-chart__line s1" dot={false} isAnimationActive={false} />
              </LineChart>
            )}
          </ResponsiveContainer>
        </div>
      )}
      <figcaption className="u-secondary a-series__summary">{summary}</figcaption>
    </figure>
  );
}
