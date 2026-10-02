import { Fragment } from 'react';
import type { Journey, NodeStatus } from '../../api/types';
import { formatDateTime } from '../../shared/dates';

const STATE: Record<NodeStatus, string> = {
  completed: '✓ Completed', current: '● Action required', waiting: '! Waiting', future: '○ Upcoming',
  failed: '× Failed', cancelled: '× Cancelled', skipped: '— Not applicable',
};

/**
 * The current path of this repair, left to right. Every node, its state and its order
 * come from the backend's journey projection; nothing is decided here.
 */
export function JourneyBar({ journey }: { journey: Journey }) {
  return (
    <div className="journey" role="list" aria-label="Repair journey">
      {journey.nodes.map((node, index) => {
        const last = node.events[node.events.length - 1];
        const title = [node.detail, last ? `${formatDateTime(last.created)} · ${last.actor ?? ''} · ${last.details ?? ''}` : '']
          .filter(Boolean).join('\n');
        return (
          <Fragment key={node.key + index}>
            {index > 0 && <div className="jlink" aria-hidden="true" />}
            <div className="jnode" role="listitem" aria-current={node.current ? 'step' : undefined}>
              <div className={'jstep ' + node.status} title={title}>
                <div className="jlabel">{node.label}</div>
                <div className="jstate">{STATE[node.status] ?? node.status}</div>
                {node.current && node.detail && <div className="small" style={{ marginTop: 4, whiteSpace: 'pre-line' }}>{node.detail}</div>}
                {node.options.length > 0 && <div className="small muted" style={{ marginTop: 4 }}>{node.options.join(' / ')}</div>}
              </div>
            </div>
          </Fragment>
        );
      })}
    </div>
  );
}
