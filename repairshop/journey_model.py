"""Project the authoritative lifecycle snapshot into connected journey nodes.

Nothing here decides what happened to a repair. ``Lifecycle.tracker`` already
owns the stage list and the completed / current / upcoming split, ``jobs.stage``
names the one current stage and the audit timeline holds the evidence. This
module only translates those markers and layers on the waiting, cancelled and
skipped detail that the tracker has no vocabulary for, so the diagram can never
disagree with the backend it was built from.
"""
import json

from .lifecycle import LABELS, ROUTE_LABELS

# The three markers tracker() emits, mapped onto shared visual state names.
TRACKER_STATES = {'● CURRENT': 'current', '✓': 'completed', '○': 'upcoming'}

# Used only to place a stage tracker() did not list next to the ones it did.
# It never decides whether a stage happened, only where to draw it.
ORDER = ('received', 'inspection', 'warranty_check', 'route_selection',
         'ready_dispatch', 'external_diagnosis', 'diagnosis', 'awaiting_estimate',
         'awaiting_approval', 'approved', 'waiting_parts', 'under_repair',
         'technician_testing', 'return_unrepaired', 'awaiting_return', 'testing',
         'final_qc', 'billing', 'ready_repaired', 'ready_unrepaired', 'collected', 'closed')

# Stages tracker() folds into the step drawn for them, so evidence recorded
# against the old name still lands on the node the user can actually see.
ALIASES = {'ready_unrepaired': 'ready_repaired', 'testing': 'final_qc'}

# An unrepaired outcome is red either way; the wording picks which red label.
FAILURE_WORDS = ('fail', 'not repairable', 'unsuccessful')


def _position(key):
    return ORDER.index(key) if key in ORDER else None


def _insert(nodes, node):
    """Place a node by canonical order, or at the front of the unfinished work."""
    index = _position(node['key'])
    if index is None:
        target = next((i for i, n in enumerate(nodes) if n['status'] != 'completed'), len(nodes))
    else:
        target = next((i for i, n in enumerate(nodes)
                       if _position(n['key']) is not None and _position(n['key']) > index), len(nodes))
    nodes.insert(target, node)


def departures(snapshot):
    """Group the audit rows that prove a stage was left, keyed by that stage.

    tracker() counts a stage as complete from exactly these rows, so reading
    them the same way keeps every tick mark and its evidence in step.
    """
    found = {}
    for row in snapshot.get('timeline') or []:
        if row.get('action') != 'lifecycle':
            continue
        try:
            payload = json.loads(row.get('payload') or '{}')
        except (TypeError, ValueError):
            continue
        before, after = payload.get('before'), payload.get('after')
        if payload.get('action') == 'adopt' or before == after or not before:
            continue
        for key in {before, ALIASES.get(before, before)}:
            found.setdefault(key, []).append(row)
        # A recorded quote decision retires the approval wait even when the job
        # had already moved on, exactly as tracker() treats it.
        if payload.get('action') == 'decision' and before != 'awaiting_approval':
            found.setdefault('awaiting_approval', []).append(row)
    return found


def waiting_reason(snapshot):
    """Why the current stage cannot be finished by the shop on its own."""
    stage, route = snapshot.get('stage'), snapshot.get('route')
    data = snapshot.get('data') or {}
    if snapshot.get('hold_reason') and stage not in ('collected', 'closed'):
        return 'On hold · ' + str(snapshot['hold_reason'])
    if data.get('in_transit'):
        return snapshot.get('next_action') or 'The device is with the courier'
    if stage == 'awaiting_approval':
        return 'Waiting for the customer to approve the estimate'
    if stage == 'waiting_parts':
        return str(data.get('parts_order') or 'Waiting for the required parts')
    if route != 'in_house' and stage in ('external_diagnosis', 'under_repair',
                                         'awaiting_return', 'return_unrepaired'):
        if stage == 'return_unrepaired' and not snapshot.get('away'):
            return ''
        return snapshot.get('next_action') or 'Waiting for the external repairer'
    return ''


def outcome_status(reason):
    text = str(reason or '').lower()
    return 'failed' if any(word in text for word in FAILURE_WORDS) else 'cancelled'


def bypassed(snapshot, present):
    """Stages the recorded decisions provably skipped, so they stay visible."""
    data = snapshot.get('data') or {}
    rows = []
    if data.get('warranty_covered'):
        if 'awaiting_estimate' not in present:
            rows.append(('awaiting_estimate', 'Estimate',
                         'Not required · the service center accepted the warranty claim'))
        if 'awaiting_approval' not in present:
            rows.append(('awaiting_approval', 'Customer approval',
                         'Not required · the repair is covered under warranty'))
    if data.get('unrepaired') and 'under_repair' not in present:
        rows.append(('under_repair', 'Repair',
                     'Not applicable · the device is going back without repair'))
    return rows


def route_options(snapshot):
    """The routes still open at the decision point, straight from the backend.

    ``Lifecycle`` already decides when a route is undecided and says so in
    ``route_label``; reading that answer keeps the branch drawing and the state
    machine on one source of truth. These are choices, never promised stages, so
    no route-specific step is drawn until the shop has actually picked one.
    """
    if not str(snapshot.get('route_label') or '').startswith('NOT SELECTED'):
        return []
    return list(ROUTE_LABELS.values())


def current_node(snapshot, events, waiting):
    """Fall back to the job's own stage when tracker() lists no step for it.

    ``approved`` has no tracker step, and a legacy or reopened job can sit on a
    stage outside its route's path. The snapshot always names one current stage,
    so the diagram always shows one rather than losing the "you are here" mark.
    """
    stage = snapshot.get('stage') or ''
    label = LABELS.get(stage)
    return dict(key=stage, title=label.capitalize() if label else 'Legacy status · ' + str(stage),
                status='waiting' if waiting else 'current', detail=waiting,
                events=events.get(stage, []), is_current=True)


def build_journey(snapshot):
    """Return the ordered journey nodes for one lifecycle snapshot."""
    events = departures(snapshot)
    waiting = waiting_reason(snapshot)
    data = snapshot.get('data') or {}
    unrepaired = data.get('unrepaired')
    nodes = []
    for step in snapshot.get('tracker') or []:
        key = step.get('key') or ''
        status = TRACKER_STATES.get(step.get('state'), 'upcoming')
        current = status == 'current'
        details = []
        if key == 'return_unrepaired' and unrepaired:
            status = outcome_status(unrepaired)
            details.append(str(unrepaired))
        elif key == 'ready_repaired' and unrepaired:
            details.append('Returning without repair')
        if current and waiting:
            if status == 'current':
                status = 'waiting'
            details.append(waiting)
        nodes.append(dict(key=key, title=step.get('step') or LABELS.get(key, key),
                          status=status, detail='\n'.join(d for d in details if d),
                          events=events.get(key, []), is_current=current))
    options = route_options(snapshot)
    for node in nodes:
        if node['key'] == 'route_selection' and node['status'] != 'completed':
            node['options'] = options
    present = {n['key'] for n in nodes}
    for key, title, detail in bypassed(snapshot, present):
        _insert(nodes, dict(key=key, title=title, status='skipped', detail=detail,
                            events=events.get(key, []), is_current=False))
    if not any(n['is_current'] for n in nodes):
        _insert(nodes, current_node(snapshot, events, waiting))
    return nodes
