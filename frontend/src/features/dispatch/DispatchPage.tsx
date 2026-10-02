import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api, operationId } from '../../api/client';
import type { FormField } from '../../api/types';
import { PageTitle } from '../../app/Layout';
import { FieldForm } from '../../components/FieldForm';
import { DataTable, ErrorBox, Modal } from '../../components/ui';

interface Holding { id: number; job_id: number; number: string; description: string; type: string; serial: string; location: string; available: number; holder: { name: string; role: string } }

/**
 * Record an actual handover of selected items. Guided repair steps (dispatch, arrival,
 * return) are done from the repair itself; this screen is the general custody ledger.
 */
export function DispatchPage() {
  const client = useQueryClient();
  const holdings = useQuery({ queryKey: ['holdings'], queryFn: () => api.get<Holding[]>('/custody/holdings') });
  const destinations = useQuery({ queryKey: ['custody-destinations'], queryFn: () => api.get<{ value: string; label: string }[]>('/custody/destinations') });
  const [item, setItem] = useState<Holding | null>(null);
  const op = useRef(operationId());
  const move = useMutation({
    mutationFn: (v: Record<string, any>) => api.post('/custody/movements', { ...v, item_id: item!.id, source: item!.location, quantity: Number(v.quantity), operation_id: op.current }),
    onSuccess: () => { op.current = operationId(); setItem(null); client.invalidateQueries({ queryKey: ['holdings'] }); client.invalidateQueries({ queryKey: ['repair-tab'] }); },
  });
  const fields: FormField[] = item ? [
    { key: 'destination', label: 'Actual destination', type: 'select', required: true, options: (destinations.data ?? []).map((d) => ({ value: d.value, label: d.label })) },
    { key: 'quantity', label: `Units handed over (of ${item.available})`, type: 'number', default: item.available, required: true },
    { key: 'counterparty', label: 'Person / carrier receiving the items', type: 'text', required: true },
    { key: 'reference', label: 'Tracking / ticket / handover reference', type: 'text' },
    { key: 'condition', label: 'Condition at handover', type: 'text' },
    { key: 'acknowledgment', label: 'Acknowledgment (required for customer collection)', type: 'textarea' },
    { key: 'notes', label: 'Notes / exception reason', type: 'textarea' },
  ] : [];
  return (
    <div className="stack">
      <PageTitle title="Dispatch & receive" subtitle="Choose the actual items handed over; accessories can stay at the shop" />
      <DataTable rows={holdings.data} onOpen={(h) => { op.current = operationId(); setItem(h); }} empty="No items are currently held for open repairs." columns={[
        { key: 'number', label: 'Job', render: (h) => <Link to={'/repairs/' + h.job_id} onClick={(e) => e.stopPropagation()}>{h.number}</Link> },
        { key: 'description', label: 'Item' }, { key: 'type', label: 'Type' }, { key: 'serial', label: 'Serial' },
        { key: 'holder', label: 'Held by', render: (h) => `${h.holder.name} · ${h.holder.role}` }, { key: 'available', label: 'Qty' }]} />
      {item && (
        <Modal title={`Record handover · ${item.number} · ${item.description}`} onClose={() => setItem(null)} wide>
          <p className="muted">Currently with {item.holder.name}. A departure to a carrier is recorded as in transit; the receiver's acknowledgment completes it.</p>
          <FieldForm fields={fields} busy={move.isPending} onSubmit={(v) => move.mutate(v)} error={<ErrorBox error={move.error} />} onCancel={() => setItem(null)} />
        </Modal>
      )}
    </div>
  );
}
