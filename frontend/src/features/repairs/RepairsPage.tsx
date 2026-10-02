import { useEffect, useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api, qs } from '../../api/client';
import type { Option, Page, RepairSummary } from '../../api/types';
import { PageTitle } from '../../app/Layout';
import { Badge, DataTable, ErrorBox, Pager, statusTone } from '../../components/ui';

const TITLES: Record<string, string> = { ready: 'Ready for Delivery', history: 'Repair History' };

export function RepairsPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const filter = params.get('filter') ?? '';
  const [text, setText] = useState('');
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  useEffect(() => { const t = setTimeout(() => { setSearch(text.trim()); setOffset(0); }, 250); return () => clearTimeout(t); }, [text]);
  useEffect(() => setOffset(0), [filter]);
  const filters = useQuery({ queryKey: ['repair-filters'], queryFn: () => api.get<Option<string>[]>('/repairs/filters'), staleTime: Infinity });
  const rows = useQuery({
    queryKey: ['repairs', search, filter, offset],
    queryFn: () => api.get<Page<RepairSummary>>('/repairs' + qs({ search, filter, offset })),
    placeholderData: keepPreviousData,
  });
  return (
    <div className="stack">
      <PageTitle title={TITLES[filter] ?? 'Active Repairs'} subtitle="Find a repair and continue its next step" />
      <div className="row">
        <input className="grow" style={{ maxWidth: 520 }} placeholder="Search job, customer, phone, device or serial…" value={text}
               onChange={(e) => setText(e.target.value)} aria-label="Search repairs" />
        <select style={{ maxWidth: 280 }} value={filter} aria-label="Repair filter"
                onChange={(e) => setParams(e.target.value ? { filter: e.target.value } : {})}>
          {(filters.data ?? [{ value: '', label: 'All active repairs' }]).map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
        </select>
      </div>
      <ErrorBox error={rows.error} />
      <DataTable rows={rows.data?.items} onOpen={(r) => navigate('/repairs/' + r.id)}
                 empty="No repairs match. Adjust the search or filter."
                 columns={[
                   { key: 'number', label: 'Job' },
                   { key: 'customer', label: 'Customer', render: (r) => <>{r.customer}<div className="small muted">{r.phone}</div></> },
                   { key: 'device', label: 'Device' },
                   { key: 'stage_age', label: 'In stage' },
                   { key: 'route', label: 'Route' },
                   { key: 'status', label: 'Status', render: (r) => <Badge tone={statusTone(r.status)}>{r.status}</Badge> },
                   { key: 'responsible', label: 'Responsible' },
                   { key: 'next_action', label: 'Next action' },
                   { key: 'attention', label: 'Attention' },
                 ]} />
      <Pager offset={offset} hasMore={Boolean(rows.data?.has_more)} onChange={setOffset} />
    </div>
  );
}
