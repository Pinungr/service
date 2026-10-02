import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import type { FormField } from '../../api/types';
import { PageTitle } from '../../app/Layout';
import { useCan } from '../../app/session';
import { FieldForm } from '../../components/FieldForm';
import { DataTable, ErrorBox, Modal } from '../../components/ui';
import { shopToday } from '../../shared/dates';
import { CustomerPicker } from '../intake/CustomerPicker';

interface Sale { id: number; customer: string; device: string; serial: string; invoice_ref: string; sale_date: string; amount: number; cost?: number; provider?: string; warranty_end: string | null; collected: number }

export function SalesPage() {
  const can = useCan();
  const client = useQueryClient();
  const sales = useQuery({ queryKey: ['sales'], queryFn: () => api.get<Sale[]>('/sales') });
  const categories = useQuery({ queryKey: ['setup', 'category'], queryFn: () => api.get<{ id: number; name: string; active: number }[]>('/setup/category') });
  const [creating, setCreating] = useState(false);
  const [customer, setCustomer] = useState<{ id: number; name: string } | null>(null);
  const [collecting, setCollecting] = useState<Sale | null>(null);
  const done = () => { setCreating(false); setCollecting(null); setCustomer(null); client.invalidateQueries({ queryKey: ['sales'] }); };
  const register = useMutation({ mutationFn: (v: Record<string, any>) => api.post('/sales', { ...v, customer_id: customer!.id, category_id: v.category_id || null,
    sale_date: v.sale_date || null, invoice_date: v.invoice_date || null, warranty_start: v.warranty_start || null, warranty_end: v.warranty_end || null }), onSuccess: done });
  const collect = useMutation({ mutationFn: (v: Record<string, any>) => api.post(`/sales/${collecting!.id}/collect`, v), onSuccess: done });
  const fields: FormField[] = [
    { key: 'category_id', label: 'Category', type: 'select', options: (categories.data ?? []).filter((c) => c.active).map((c) => ({ value: c.id, label: c.name })) },
    { key: 'device', label: 'Brand / model', type: 'text', required: true }, { key: 'serial', label: 'Serial number (optional)', type: 'text' },
    { key: 'invoice_ref', label: 'Invoice reference', type: 'text' }, { key: 'sale_date', label: 'Sale date', type: 'date', default: shopToday() },
    { key: 'invoice_date', label: 'Invoice date', type: 'date', default: shopToday() }, { key: 'warranty_start', label: 'Warranty starts', type: 'date' },
    { key: 'warranty_end', label: 'Warranty ends', type: 'date' }, { key: 'warranty_terms', label: 'Warranty terms', type: 'textarea' },
    { key: 'amount', label: 'Sale amount (INR)', type: 'money', default: 0 },
    ...(can('view_internal_cost') ? [{ key: 'cost', label: 'Shop cost (INR)', type: 'money' as const, default: 0 }, { key: 'provider', label: 'Warranty / supplier provider', type: 'text' as const }] : []),
  ];
  return (
    <div className="stack">
      <PageTitle title="Products sold" subtitle="Record sales, warranties and customer collection" actions={<button className="primary" onClick={() => setCreating(true)}>+ Sold product</button>} />
      <DataTable rows={sales.data} onOpen={(s) => (s.collected ? undefined : setCollecting(s))} columns={[
        { key: 'customer', label: 'Customer' }, { key: 'device', label: 'Product' }, { key: 'serial', label: 'Serial' }, { key: 'invoice_ref', label: 'Invoice' },
        { key: 'sale_date', label: 'Sold', date: true }, { key: 'amount', label: 'Amount', money: true },
        ...(can('view_internal_cost') ? [{ key: 'cost', label: 'Cost', money: true }] : []), { key: 'warranty_end', label: 'Warranty ends', date: true },
        { key: 'collected', label: 'Collected', render: (s: Sale) => (s.collected ? 'Yes' : 'Click to record collection') }]} />
      {creating && <Modal title="Register a sold product" onClose={() => { setCreating(false); setCustomer(null); }} wide>
        {!customer ? <CustomerPicker onPick={(c) => setCustomer(c)} /> : <>
          <p><strong>{customer.name}</strong> <button className="link" onClick={() => setCustomer(null)}>change</button></p>
          <FieldForm fields={fields} busy={register.isPending} onSubmit={(v) => register.mutate(v)} error={<ErrorBox error={register.error} />} />
        </>}
      </Modal>}
      {collecting && <Modal title={`Product collection · ${collecting.device}`} onClose={() => setCollecting(null)}>
        <FieldForm compact busy={collect.isPending} onSubmit={(v) => collect.mutate(v)} error={<ErrorBox error={collect.error} />} onCancel={() => setCollecting(null)}
                   fields={[{ key: 'collector', label: "Collector's name / relationship", type: 'text', required: true },
                            { key: 'acknowledgment', label: 'Acknowledgment / reference', type: 'textarea', required: true }]} />
      </Modal>}
    </div>
  );
}
