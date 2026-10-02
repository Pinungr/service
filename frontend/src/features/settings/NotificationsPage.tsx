import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { PageTitle } from '../../app/Layout';
import { DataTable, ErrorBox, Modal } from '../../components/ui';

interface Message { id: number; job_id: number | null; event: string; channel: string; destination: string; state: string; status: string; attempts: number; error: string; created: string }

export function NotificationsPage() {
  const client = useQueryClient();
  const rows = useQuery({ queryKey: ['notifications'], queryFn: () => api.get<Message[]>('/notifications'), refetchInterval: 30_000 });
  const [selected, setSelected] = useState<Message | null>(null);
  const preview = useQuery({ queryKey: ['notification', selected?.id], queryFn: () => api.get<{ subject: string; body: string; provider_id: string | null }>('/notifications/' + selected!.id), enabled: Boolean(selected) });
  const refresh = () => client.invalidateQueries({ queryKey: ['notifications'] });
  const action = useMutation({ mutationFn: ({ id, act }: { id: number; act: 'retry' | 'cancel' }) => api.post(`/notifications/${id}/${act}`), onSuccess: refresh });
  const process = useMutation({ mutationFn: () => api.post<{ processed: number }>('/notifications/process'), onSuccess: refresh });
  return (
    <div className="stack">
      <PageTitle title="Notifications" subtitle="Captured = local test only. Accepted = provider accepted; delivery unknown. Uncertain outcomes are never resent automatically."
                 actions={<button onClick={() => process.mutate()} disabled={process.isPending}>Process queue now</button>} />
      <ErrorBox error={action.error || process.error} />
      <DataTable rows={rows.data} onOpen={setSelected} columns={[{ key: 'created', label: 'Queued' }, { key: 'event', label: 'Event' }, { key: 'channel', label: 'Channel' },
        { key: 'destination', label: 'To' }, { key: 'status', label: 'Status' }, { key: 'attempts', label: 'Attempts' }, { key: 'error', label: 'Problem' }]} />
      {selected && <Modal title="Notification" onClose={() => setSelected(null)} wide footer={<>
        <button onClick={() => action.mutate({ id: selected.id, act: 'retry' })}>Retry confirmed failure</button>
        <button onClick={() => action.mutate({ id: selected.id, act: 'cancel' })}>Cancel message</button>
        <button onClick={() => setSelected(null)}>Close</button></>}>
        <p className="muted">To {selected.destination} via {selected.channel} · {selected.status}</p>
        {preview.data && <><h3>{preview.data.subject}</h3><div className="info-box">{preview.data.body}</div></>}
      </Modal>}
    </div>
  );
}
