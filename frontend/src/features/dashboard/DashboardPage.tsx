import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { PageTitle } from '../../app/Layout';
import { useCan } from '../../app/session';
import { DataTable, ErrorBox, Loading, Panel } from '../../components/ui';
import { formatPaise } from '../../shared/money';
import { formatDateTime } from '../../shared/dates';

interface Card { key: string; label: string; tone: string; count: number }
interface Dashboard {
  mine_only: boolean;
  queue: Card[];
  places: Card[];
  attention: { id: number; number: string; customer: string; device: string; location: string; attention: string; next_action: string }[];
  balances: { account_type: string; balance: number }[];
  sales_awaiting_collection: number | null;
  loose_accessories: number;
  last_backup: string | null;
  messaging_mode: string;
}

export function DashboardPage() {
  const navigate = useNavigate();
  const can = useCan();
  const data = useQuery({ queryKey: ['dashboard'], queryFn: () => api.get<Dashboard>('/dashboard'), refetchInterval: 60_000 });
  const list = (key: string) => navigate('/repairs?filter=' + encodeURIComponent(key));
  if (data.error) return <ErrorBox error={data.error} />;
  if (!data.data) return <Loading />;
  const d = data.data;
  return (
    <div className="stack">
      <PageTitle title="Dashboard" subtitle="Your shop at a glance · physical items and work progress"
                 actions={can('intake') ? <button className="primary" onClick={() => navigate('/intake')}>+ New intake</button> : null} />
      <h2>{d.mine_only ? 'My work queue' : 'Work queue'}</h2>
      <div className="grid4">
        {d.queue.map((card) => (
          <button key={card.key} className={'card-metric ' + card.tone} onClick={() => list(card.key)}>
            <div className="muted">{d.mine_only ? 'My ' + card.label.toLowerCase() : card.label}</div>
            <div className="value">{card.count}</div>
          </button>
        ))}
      </div>
      <Panel title="Location & history">
        <div className="row">
          {d.places.map((p) => <button key={p.key} onClick={() => list(p.key)}>{p.label} · {p.count}</button>)}
        </div>
        <p className="small muted">These views can include the same repair, so the counts are not added together.</p>
      </Panel>
      <h2>Attention required</h2>
      <DataTable rows={d.attention} onOpen={(r) => navigate('/repairs/' + r.id)}
                 empty="Nothing needs attention right now. Start a new intake when a customer arrives."
                 columns={[{ key: 'number', label: 'Job' }, { key: 'customer', label: 'Customer' }, { key: 'device', label: 'Device' },
                           { key: 'location', label: 'Location' }, { key: 'attention', label: 'Attention' }, { key: 'next_action', label: 'Next action' }]} />
      <Panel title="Shop status">
        <div className="stack small">
          {d.balances.map((b) => <div key={b.account_type}>{b.account_type === 'customer' ? 'Customer' : 'Vendor'} balance: {formatPaise(b.balance)}</div>)}
          {d.sales_awaiting_collection !== null && <div>Products awaiting collection: {d.sales_awaiting_collection}</div>}
          <div>Loose accessories: {d.loose_accessories}</div>
          <div>Last verified backup: {d.last_backup ? formatDateTime(d.last_backup) : 'No backup yet'} · Messaging: {d.messaging_mode} mode</div>
        </div>
      </Panel>
    </div>
  );
}
