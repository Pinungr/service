import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, qs } from '../../api/client';
import { PageTitle } from '../../app/Layout';
import { DataTable, ErrorBox } from '../../components/ui';
import { shopToday } from '../../shared/dates';

const MONEY = new Set(['amount', 'balance', 'total', 'total_expense', 'allocated', 'revenue', 'costs', 'margin', 'margin_before_overheads', 'purchase_cost', 'customer_price']);

export function ReportsPage() {
  const meta = useQuery({ queryKey: ['reports-meta'], queryFn: () => api.get<{ kinds: string[]; routes: string[] }>('/reports') });
  const [kind, setKind] = useState('jobs');
  const [start, setStart] = useState(shopToday().slice(0, 8) + '01');
  const [end, setEnd] = useState(shopToday());
  const [route, setRoute] = useState('');
  const [run, setRun] = useState<Record<string, string> | null>(null);
  const report = useQuery({ queryKey: ['report', run], queryFn: () => api.get<Record<string, any>[]>(`/reports/${run!.kind}` + qs(run!)), enabled: Boolean(run) });
  const params = { kind, start, end, route };
  const rows = report.data ?? [];
  const columns = Object.keys(rows[0] ?? {}).filter((k) => k !== 'payload').map((k) => ({ key: k, label: k.replace(/_/g, ' '), money: MONEY.has(k) }));
  return (
    <div className="stack">
      <PageTitle title="Reports" subtitle="Dues are current balances. Payments use posting dates; job reports use intake dates. Margin is before overheads." />
      <div className="row">
        <select style={{ maxWidth: 220 }} value={kind} onChange={(e) => setKind(e.target.value)}>
          {(meta.data?.kinds ?? ['jobs']).map((k) => <option key={k} value={k}>{k.replace(/_/g, ' ')}</option>)}
        </select>
        <label className="row">From <input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></label>
        <label className="row">To <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></label>
        <select style={{ maxWidth: 200 }} value={route} onChange={(e) => setRoute(e.target.value)}>
          <option value="">All routes</option>{(meta.data?.routes ?? []).map((r) => <option key={r} value={r}>{r.replace(/_/g, ' ')}</option>)}
        </select>
        <button className="primary" onClick={() => setRun({ ...params })}>Run report</button>
        {run && ['xlsx', 'csv', 'pdf'].map((format) => (
          <a key={format} className="button" href={`/api/reports/${run.kind}/export` + qs({ ...run, format })}>Export {format.toUpperCase()}</a>
        ))}
      </div>
      <ErrorBox error={report.error} />
      {run && <DataTable rows={report.isLoading ? undefined : rows.map((r, i) => ({ ...r, __row: i }))} rowKey="__row" columns={columns} empty="No rows match this report." />}
    </div>
  );
}
