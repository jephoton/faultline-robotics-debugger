import { useId, type ReactNode } from 'react';

export function Section({ title, children, hint }: { title: string; children: ReactNode; hint?: ReactNode }) {
  const id = useId();
  return (
    <section className="section" aria-labelledby={id}>
      <h2 id={id}>{title}</h2>
      {hint ? <p className="muted section__hint">{hint}</p> : null}
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}
