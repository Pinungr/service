import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { PageTitle } from '../../app/Layout';
import { useCan } from '../../app/session';
import { DataTable } from '../../components/ui';
import { QuoteDecision } from '../repairs/RepairTabs';

interface Quote { id: number; job_id: number; number: string; device: string; customer: string; version: number; state: string; scope: string; total: number; valid_until: string | null }

export function QuotesPage() {
  const can = useCan();
  const navigate = useNavigate();
  const client = useQueryClient();
  const quotes = useQuery({ queryKey: ['quotes'], queryFn: () => api.get<Quote[]>('/quotes') });
  const [selected, setSelected] = useState<Quote | null>(null);
  const [deciding, setDeciding] = useState(false);
  return (
    <div className="stack">
      <PageTitle title="Quotations" subtitle="Quotations are issued from the repair. Record the customer's explicit decision here or there." />
      <div className="row">
        {selected && <button className="primary" onClick={() => navigate('/repairs/' + selected.job_id)}>Open repair</button>}
        {selected && can('approve_quote') && <button onClick={() => setDeciding(true)}>Record customer decision</button>}
      </div>
      <DataTable rows={quotes.data} onOpen={setSelected} selected={selected?.id} columns={[
        { key: 'number', label: 'Job' }, { key: 'customer', label: 'Customer' }, { key: 'device', label: 'Device' }, { key: 'version', label: 'Version' },
        { key: 'state', label: 'State' }, { key: 'scope', label: 'Scope' }, { key: 'total', label: 'Total', money: true }, { key: 'valid_until', label: 'Valid until', date: true }]} />
      {deciding && selected && <QuoteDecision quoteId={selected.id} onClose={() => setDeciding(false)}
                                              onDone={() => { setDeciding(false); client.invalidateQueries({ queryKey: ['quotes'] }); }} />}
    </div>
  );
}
