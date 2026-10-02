import { ReactNode, useEffect, useRef } from 'react';
import { messageOf } from '../api/client';
import { formatPaise } from '../shared/money';
import { formatDate, formatDateTime, looksLikeTimestamp } from '../shared/dates';

export function Panel({ title, children, actions, className = '' }: { title?: ReactNode; children: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <section className={'panel ' + className}>
      {(title || actions) && (
        <div className="row between" style={{ marginBottom: 10 }}>
          {title ? <h2 style={{ margin: 0 }}>{title}</h2> : <span />}
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="error" role="alert">{messageOf(error)}</div>;
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return <div className="empty" aria-busy="true">{label}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Badge({ tone = 'neutral', children }: { tone?: 'ok' | 'warn' | 'bad' | 'info' | 'neutral'; children: ReactNode }) {
  return <span className={'badge ' + tone}>{children}</span>;
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { key: T; label: string }[]; value: T; onChange: (key: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button key={tab.key} role="tab" aria-selected={tab.key === value} className={tab.key === value ? 'active' : ''} onClick={() => onChange(tab.key)}>
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export function Modal({ title, children, footer, onClose, wide = false }: { title: ReactNode; children: ReactNode; footer?: ReactNode; onClose: () => void; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    ref.current?.querySelector<HTMLElement>('input,select,textarea,button')?.focus();
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={'modal' + (wide ? ' wide' : '')} role="dialog" aria-modal="true" ref={ref}>
        <header><h2>{title}</h2></header>
        <div className="body">{children}</div>
        {footer && <footer>{footer}</footer>}
      </div>
    </div>
  );
}

export interface Column<T> {
  key: string;
  label: string;
  render?: (row: T) => ReactNode;
  money?: boolean;
  date?: boolean;
  className?: string;
}

export function display(value: unknown, money = false, date = false): ReactNode {
  if (value === null || value === undefined || value === '') return '—';
  if (money && typeof value === 'number') return formatPaise(value);
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (date && typeof value === 'string') return formatDate(value);
  if (looksLikeTimestamp(value)) return formatDateTime(value);
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export function DataTable<T extends Record<string, any>>({ rows, columns, onOpen, empty = 'No records yet.', selected, rowKey = 'id' }: {
  rows: T[] | undefined; columns: Column<T>[]; onOpen?: (row: T) => void; empty?: ReactNode; selected?: unknown; rowKey?: string;
}) {
  if (!rows) return <Loading />;
  if (!rows.length) return <div className="table-wrap"><Empty>{empty}</Empty></div>;
  return (
    <div className="table-wrap">
      <table>
        <thead><tr>{columns.map((c) => <th key={c.key} className={c.money ? 'right' : ''}>{c.label}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={String(row[rowKey] ?? index)} className={(onOpen ? 'clickable ' : '') + (selected !== undefined && row[rowKey] === selected ? 'selected' : '')}
                onClick={onOpen ? () => onOpen(row) : undefined}
                onKeyDown={onOpen ? (e) => { if (e.key === 'Enter') onOpen(row); } : undefined}
                tabIndex={onOpen ? 0 : undefined}>
              {columns.map((c) => (
                <td key={c.key} className={(c.money ? 'right nowrap ' : '') + (c.className ?? '')}>
                  {c.render ? c.render(row) : display(row[c.key], c.money, c.date)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function KeyValues({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="kv">
      {items.map(([k, v]) => [<dt key={k + ':k'}>{k}</dt>, <dd key={k + ':v'}>{v === '' || v === null || v === undefined ? '—' : v}</dd>])}
    </dl>
  );
}

export function Pager({ offset, hasMore, onChange, size = 50 }: { offset: number; hasMore: boolean; onChange: (offset: number) => void; size?: number }) {
  if (!offset && !hasMore) return null;
  return (
    <div className="row" style={{ justifyContent: 'flex-end', marginTop: 8 }}>
      <button disabled={!offset} onClick={() => onChange(Math.max(0, offset - size))}>← Previous</button>
      <button disabled={!hasMore} onClick={() => onChange(offset + size)}>Next {size} →</button>
    </div>
  );
}

const TONES: Record<string, 'ok' | 'warn' | 'bad' | 'info' | 'neutral'> = {
  completed: 'ok', current: 'warn', waiting: 'warn', failed: 'bad', cancelled: 'bad', skipped: 'neutral', future: 'neutral',
};

export function statusTone(status: string): 'ok' | 'warn' | 'bad' | 'info' | 'neutral' {
  if (TONES[status]) return TONES[status];
  const s = status.toUpperCase();
  if (s.includes('READY') || s.includes('DELIVERED') || s.includes('CLOSED')) return 'ok';
  if (s.includes('WAIT') || s.includes('PENDING') || s.includes('ATTENTION')) return 'warn';
  if (s.includes('UNREPAIRED') || s.includes('FAIL')) return 'bad';
  return 'info';
}
