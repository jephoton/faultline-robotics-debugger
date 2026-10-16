import { useDocumentTitle } from '../lib/useDocumentTitle';

export function HomePage() {
  useDocumentTitle(null);
  return (
    <section>
      <h1>Faultline</h1>
      <p className="lede">Find a robot-policy failure, confirm it repeats, reduce it to its cause and keep it as a replayable test.</p>
    </section>
  );
}
