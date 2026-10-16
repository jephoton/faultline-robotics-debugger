export function usd(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return 'not recorded';
  return `US$${value.toFixed(digits)}`;
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return 'not recorded';
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h} h ${String(m).padStart(2, '0')} min`;
  if (m > 0) return `${m} min ${String(s).padStart(2, '0')} s`;
  return `${s} s`;
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return 'date not recorded';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return 'date not recorded';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())} UTC`;
}

export function percent(fraction: number): string {
  return `${Math.round(fraction * 1000) / 10}%`;
}

/** "libero_10" becomes "LIBERO-10". */
export function suiteLabel(suite: string | null | undefined): string {
  if (!suite) return 'suite not recorded';
  return suite.replace(/^libero_/, 'LIBERO-').replace(/_/g, ' ');
}

export function pluralise(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}
