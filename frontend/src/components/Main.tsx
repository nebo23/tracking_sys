import { createContext, useContext, type ComponentProps, type ReactNode } from 'react';

const InsideMain = createContext(false);

/** The main region of a page. What is drawn inside it knows not to open a second one. */
export function Main({ children, ...region }: ComponentProps<'main'>) {
  return (
    <InsideMain value={true}>
      <main {...region}>{children}</main>
    </InsideMain>
  );
}

/**
 * A message that stands for a whole page, such as "not found" or "could not be shown". The router
 * draws it where the page would have been: at the top of the document it is the main region
 * itself, and inside a frame that already has one it is a plain block.
 */
export function PageMessage({ children }: { children: ReactNode }) {
  const inside = useContext(InsideMain);
  if (inside) return <div className="a-center">{children}</div>;
  return <Main className="a-center">{children}</Main>;
}
