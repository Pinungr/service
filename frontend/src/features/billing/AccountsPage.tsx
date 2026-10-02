import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { api, operationId, qs } from '../../api/client';
import type { CustomerSummary, FormField, Page } from '../../api/types';
import { PageTitle } from '../../app/Layout';
import { useCan, useMe } from '../../app/session';
import { FieldForm } from '../../components/FieldForm';
import { DataTable, ErrorBox, KeyValues, Modal, Panel } from '../../components/ui';
import { shopToday } from '../../shared/dates';
import { formatPaise, parseRupees } from '../../shared/money';

interface Entry { id: number; account_id: number; account: string; job_id: number | null; number: string | null; posted: string; kind: string; amount: number; method: string; reference: string; notes: string; reversed: number }
interface Ledger { opening: number; closing: number; start: string; end: string; rows: any[]; unconfirmed_estimates?: any[] }

export function AccountsPage() {
  const type = (useParams().accountType === 'vendor' ? 'vendor' : 'customer') as 'customer' | 'vendor';
  const me = useMe();
  const can = useCan();
  const client = useQueryClient();
  const entries = useQuery({ queryKey: ['entries', type], queryFn: () => api.get<Entry[]>(`/accounts/${type}/entries`) });
  const balances = useQuery({ queryKey: ['balances', type], queryFn: () => api.get<any[]>(`/accounts/${type}/balances`), enabled: me.role === 'owner' });
  const parties = useQuery({ queryKey: ['vendor-parties'], queryFn: () => api.get<{ id: number; name: string; kind: string }[]>('/accounts/vendor/parties'), enabled: type === 'vendor' });
  const [selected, setSelected] = useState<Entry | null>(null);
  const [form, setForm] = useState<'entry' | 'reverse' | 'ledger' | 'expense' | null>(null);
  const [account, setAccount] = useState<number | null>(null);
  const [ledger, setLedger] = useState<Ledger | null>(null);
  const op = useRef(operationId());
  const refresh = () => { op.current = operationId(); setForm(null); client.invalidateQueries({ queryKey: ['entries'] }); client.invalidateQueries({ queryKey: ['balances'] }); };
  const post = useMutation({ mutationFn: (v: Record<string, any>) => api.post(`/accounts/${type}/entries`, { ...v, account_id: account ?? v.account_id, job_id: v.job_id ? Number(v.job_id) : null, operation_id: op.current }), onSuccess: refresh });
  const reverse = useMutation({ mutationFn: (v: Record<string, any>) => api.post(`/entries/${selected!.id}/reverse`, { ...v, operation_id: op.current }), onSuccess: refresh });
  const loadLedger = useMutation({ mutationFn: (v: Record<string, any>) => api.get<Ledger>(`/accounts/${type}/${account ?? v.account_id}/ledger` + qs({ start: v.start, end: v.end })),
                                   onSuccess: (d) => { setLedger(d); setForm(null); } });
  const expense = useMutation({
    mutationFn: (v: { allocations: string } & Record<string, any>) => {
      const allocations: Record<number, number> = {};
      for (const line of v.allocations.split('\n').filter((l: string) => l.trim())) {
        const [job, amount] = line.split('|').map((x: string) => x.trim());
        const paise = parseRupees(amount ?? '');
        if (!job || paise === null) throw new Error('Enter allocations as "Job ID | amount", one per line.');
        allocations[Number(job)] = paise;
      }
      const { allocations: _, method, carrier, destination, reason, ...rest } = v;
      return api.post('/expenses', { ...rest, allocations, details: { method, carrier, destination, reason }, included_entry_id: rest.included_entry_id ? Number(rest.included_entry_id) : null, operation_id: op.current });
    },
    onSuccess: refresh,
  });
  const kinds = me.role === 'counter' ? ['receipt'] : type === 'customer' ? ['receipt', 'refund', 'credit', 'opening', 'adjustment'] : ['charge', 'payment', 'credit', 'refund', 'opening', 'adjustment'];
  const accountField: FormField = type === 'vendor'
    ? { key: 'account_id', label: 'Vendor / service centre', type: 'select', required: true, options: (parties.data ?? []).map((p) => ({ value: p.id, label: p.name + ' · ' + p.kind })) }
    : { key: 'account_info', label: 'Customer', type: 'info', default: account ? 'Selected customer #' + account : 'Choose the customer above first.' };
  return (
    <div className="stack">
      <PageTitle title={type === 'customer' ? 'Customer accounts' : 'Vendor accounts'} subtitle="Positive = owed to the shop / vendor. Recording payments never transfers money." />
      {type === 'customer' && <CustomerChooser value={account} onChange={setAccount} />}
      <div className="row">
        <button className="primary" disabled={type === 'customer' && !account} onClick={() => setForm('entry')}>+ Record entry</button>
        <button disabled={type === 'customer' && !account} onClick={() => setForm('ledger')}>Account statement</button>
        {selected && can('correct_finance') && <button onClick={() => setForm('reverse')}>Reverse selected entry</button>}
        {can('view_internal_cost') && <button onClick={() => setForm('expense')}>+ Shared transport / expense</button>}
      </div>
      {balances.data && <DataTable rows={balances.data} rowKey="account_id" columns={Object.keys(balances.data[0] ?? { account_id: 0 }).map((k) => ({ key: k, label: k.replace(/_/g, ' '), money: k === 'balance' }))} />}
      <DataTable rows={entries.data?.filter((e) => type === 'vendor' || !account || e.account_id === account)} onOpen={setSelected} selected={selected?.id} columns={[
        { key: 'posted', label: 'Posted', date: true }, { key: 'account', label: type === 'customer' ? 'Customer' : 'Vendor' }, { key: 'number', label: 'Job' },
        { key: 'kind', label: 'Type' }, { key: 'amount', label: 'Amount', money: true }, { key: 'method', label: 'Method' }, { key: 'reference', label: 'Reference' },
        { key: 'reversed', label: 'Reversed', render: (e) => (e.reversed ? 'Yes' : '') }]} />
      {ledger && (
        <Panel title={`Statement · ${ledger.start} to ${ledger.end}`} actions={<button onClick={() => setLedger(null)}>Close</button>}>
          <KeyValues items={[['Opening', formatPaise(ledger.opening)], ['Closing', formatPaise(ledger.closing)]]} />
          <DataTable rows={ledger.rows} columns={[{ key: 'posted', label: 'Date', date: true }, { key: 'number', label: 'Job' }, { key: 'kind', label: 'Type' },
            { key: 'amount', label: 'Amount', money: true }, { key: 'running_balance', label: 'Balance', money: true }, { key: 'reference', label: 'Reference' }]} />
          {ledger.unconfirmed_estimates && ledger.unconfirmed_estimates.length > 0 && <><h3>Unconfirmed estimates (excluded from payable totals)</h3>
            <DataTable rows={ledger.unconfirmed_estimates} rowKey="number" columns={[{ key: 'number', label: 'Job' }, { key: 'device', label: 'Device' }, { key: 'reference', label: 'Reference' }, { key: 'estimate', label: 'Estimate', money: true }]} /></>}
        </Panel>
      )}
      {form === 'entry' && <Modal title={`Record ${type} account entry`} onClose={() => setForm(null)}>
        <FieldForm compact busy={post.isPending} error={<ErrorBox error={post.error} />} onSubmit={(v) => post.mutate(v)} onCancel={() => setForm(null)} fields={[
          accountField, { key: 'kind', label: 'Entry type', type: 'select', default: kinds[0], options: kinds.map((k) => ({ value: k, label: k })), required: true },
          { key: 'amount', label: 'Amount (INR; adjustments may be negative)', type: 'money', required: true }, { key: 'job_id', label: 'Job ID (optional)', type: 'number' },
          { key: 'posted', label: 'Posting date', type: 'date', default: shopToday() }, { key: 'method', label: 'Payment method', type: 'text' },
          { key: 'reference', label: 'Receipt / bank / UPI / bill reference', type: 'text' }, { key: 'notes', label: 'Reason / notes', type: 'textarea' }]} />
      </Modal>}
      {form === 'reverse' && selected && <Modal title="Reverse financial entry" onClose={() => setForm(null)}>
        <p className="muted">The original stays in history. This posts an equal and opposite correcting entry.</p>
        <FieldForm compact busy={reverse.isPending} error={<ErrorBox error={reverse.error} />} onSubmit={(v) => reverse.mutate(v)} onCancel={() => setForm(null)}
                   fields={[{ key: 'reason', label: 'Correction reason', type: 'textarea', required: true }]} />
      </Modal>}
      {form === 'ledger' && <Modal title="Account statement" onClose={() => setForm(null)}>
        <FieldForm compact busy={loadLedger.isPending} error={<ErrorBox error={loadLedger.error} />} onSubmit={(v) => loadLedger.mutate(v)} onCancel={() => setForm(null)} submitLabel="Show statement"
                   fields={[...(type === 'vendor' ? [accountField] : []), { key: 'start', label: 'From posting date', type: 'date', default: shopToday().slice(0, 8) + '01' },
                            { key: 'end', label: 'Through posting date', type: 'date', default: shopToday() }]} />
      </Modal>}
      {form === 'expense' && <Modal title="Shared transport / direct expense" onClose={() => setForm(null)} wide>
        <p className="muted">Allocate the actual total once across jobs. Customer charges belong in a quotation. Recording this does not move items.</p>
        <FieldForm busy={expense.isPending} error={<ErrorBox error={expense.error} />} onSubmit={(v) => expense.mutate(v as any)} onCancel={() => setForm(null)} fields={[
          { key: 'kind', label: 'Expense type', type: 'select', default: 'outbound_transport', options: ['outbound_transport', 'return_transport', 'part', 'handling', 'additional_vendor_charge'].map((k) => ({ value: k, label: k.replace(/_/g, ' ') })) },
          { key: 'amount', label: 'Actual total cost (INR)', type: 'money', required: true }, { key: 'payer', label: 'Paid / payable by', type: 'text' },
          { key: 'reference', label: 'Receipt / tracking reference', type: 'text' }, { key: 'allocations', label: 'Job ID | allocated INR, one per line', type: 'textarea', required: true },
          { key: 'included_entry_id', label: 'Already included in vendor bill entry ID', type: 'number' }, { key: 'method', label: 'Bus / courier / other method', type: 'text' },
          { key: 'carrier', label: 'Carrier / contact', type: 'text' }, { key: 'destination', label: 'Destination', type: 'text' }, { key: 'reason', label: 'Reason / evidence', type: 'text' }]} />
      </Modal>}
    </div>
  );
}

function CustomerChooser({ value, onChange }: { value: number | null; onChange: (id: number | null) => void }) {
  const [text, setText] = useState('');
  const results = useQuery({ queryKey: ['customers', text, 0], queryFn: () => api.get<Page<CustomerSummary>>('/customers' + qs({ search: text })), enabled: text.length > 1 });
  const chosen = results.data?.items.find((c) => c.id === value);
  return (
    <div className="row">
      <input style={{ maxWidth: 360 }} placeholder="Find customer by name or phone…" value={text} onChange={(e) => setText(e.target.value)} />
      <select style={{ maxWidth: 360 }} value={value ?? ''} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
        <option value="">All customers</option>
        {(results.data?.items ?? []).map((c) => <option key={c.id} value={c.id}>{c.name} · {c.phone}</option>)}
        {value && !chosen && <option value={value}>Customer #{value}</option>}
      </select>
    </div>
  );
}

