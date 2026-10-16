import { Link } from 'react-router-dom';
import { useDocumentTitle } from '../lib/useDocumentTitle';

export function NotFoundPage() {
  useDocumentTitle('Not found');
  return (
    <section>
      <h1>Page not found</h1>
      <p className="lede">There is nothing at this address.</p>
      <Link to="/" className="btn btn--secondary">
        Back to the start
      </Link>
    </section>
  );
}

/** Shown for routes that exist only in the local control panel when the page is a static gallery. */
export function LocalOnlyPage({ what }: { what: string }) {
  useDocumentTitle(what);
  return (
    <section>
      <h1>{what}</h1>
      <p className="lede">This page needs the local Faultline server, so it is not part of the published gallery.</p>
      <Link to="/" className="btn btn--secondary">
        Back to the cases
      </Link>
    </section>
  );
}
