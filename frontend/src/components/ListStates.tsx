import type { ReactNode } from 'react';
import { FormattedMessage } from 'react-intl';

import { describeError } from '@/api/errors';

import { ErrorNotice } from './Notice';
import { Skeleton } from './Skeleton';

// The states of a list inside a card, drawn the same way on every page (design language, D9).

export function ListLoading({ lines = 3 }: { lines?: number }) {
  return (
    <div className="a-pad">
      <Skeleton lines={lines} />
    </div>
  );
}

/** A list that could not be read, with the sentence of its error and a way to ask again. */
export function ListFailed({ error, retry }: { error: unknown; retry: () => void }) {
  return (
    <div className="a-pad">
      <ErrorNotice
        message={describeError(error)}
        action={
          <button type="button" className="c-btn c-btn--secondary c-btn--sm" onClick={retry}>
            <FormattedMessage id="common.retry" />
          </button>
        }
      />
    </div>
  );
}

/** A sentence that stands where the rows of a list would be. */
export function ListNone({ children }: { children: ReactNode }) {
  return (
    <p className="a-none" role="status">
      {children}
    </p>
  );
}

/** The loading and error states of a query, or nothing once it has data. */
export function QueryStates({ query, lines }: { query: { isPending: boolean; isError: boolean; error: unknown; refetch: () => unknown }; lines?: number }) {
  if (query.isPending) return <ListLoading lines={lines} />;
  if (query.isError) return <ListFailed error={query.error} retry={() => void query.refetch()} />;
  return null;
}
