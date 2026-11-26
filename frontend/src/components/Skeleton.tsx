import { useIntl } from 'react-intl';

/** Stands in for a few lines of text while they load. */
export function Skeleton({ lines = 3 }: { lines?: number }) {
  const intl = useIntl();
  return (
    <div className="l-stack l-stack--tight a-skeleton" role="status" aria-label={intl.formatMessage({ id: 'common.loading' })}>
      {Array.from({ length: lines }, (_, index) => (
        <span key={index} className="c-skel" />
      ))}
    </div>
  );
}
