"""The visual journey must never disagree with the lifecycle state machine.

Every assertion here drives real transitions through ``Lifecycle.execute`` and
then reads the projection, so a node can only be wrong if the backend is.
"""
import uuid

import pytest
from PyQt6.QtCore import Qt

from repairshop.journey_model import build_journey
from repairshop.lifecycle import Lifecycle
from repairshop.repair_journey import JOURNEY_STATES, RepairJourney
from test_lifecycle import fresh, route, dispatch, qc

CURRENT_ALIAS = {'ready_unrepaired': 'ready_repaired', 'testing': 'final_qc'}


def project(life, ident):
    """Read one snapshot and project it, exactly as the screen does."""
    v = life.snapshot(ident)
    nodes = build_journey(v)
    current = [n for n in nodes if n['is_current']]
    assert len(current) == 1, [n['key'] for n in current] or 'no current node for ' + v['stage']
    assert current[0]['key'] == CURRENT_ALIAS.get(v['stage'], v['stage'])
    assert current[0]['status'] in ('current', 'waiting', 'failed', 'cancelled')
    for node in nodes:
        assert node['status'] in JOURNEY_STATES and node['title'] and node['key']
        # A tick mark is only ever drawn over recorded evidence.
        if node['status'] == 'completed':
            assert node['events'], 'completed without evidence: ' + node['key']
    assert len(nodes) == len({n['key'] for n in nodes})
    return v, nodes, current[0]


def states(nodes):
    return {n['key']: n['status'] for n in nodes}


def test_journey_follows_the_in_house_repair_through_every_lifecycle_stage(service, customer):
    ident, life = fresh(service, customer)

    v, nodes, current = project(life, ident)
    assert current['key'] == 'received'
    # Before the route is chosen the path ahead is unknown, so nothing is invented.
    assert [n['key'] for n in nodes] == ['received', 'inspection', 'warranty_check', 'route_selection']
    assert all(n['status'] == 'upcoming' for n in nodes[1:])
    assert 'NOT SELECTED' in v['route_label']

    life.execute(ident, 'inspect')
    v, nodes, current = project(life, ident)
    assert current['key'] == 'inspection' and states(nodes)['received'] == 'completed'

    life.execute(ident, 'inspection_done', {'notes': 'Power fault confirmed; condition checked'})
    v, nodes, current = project(life, ident)
    assert current['key'] == 'warranty_check' and states(nodes)['inspection'] == 'completed'

    life.execute(ident, 'verify_warranty', {'warranty_status': 'out_of_warranty', 'notes': 'Purchase evidence reviewed'})
    v, nodes, current = project(life, ident)
    assert current['key'] == 'route_selection' and states(nodes)['warranty_check'] == 'completed'
    assert len(nodes) == 4

    life.execute(ident, 'select_route', dict(route='in_house', confirmed=True, technician_id=service.user['id'],
                                             handed_over=True, bench='Bench 2', condition='Intact',
                                             acknowledgment='Technician received'))
    v, nodes, current = project(life, ident)
    keys = [n['key'] for n in nodes]
    assert current['key'] == 'diagnosis' and states(nodes)['route_selection'] == 'completed'
    assert v['assigned_technician'] and 'IN-HOUSE' in v['route_label']
    # The in-house path is now known end to end, and no external stage appears.
    assert 'ready_dispatch' not in keys and 'external_diagnosis' not in keys and 'awaiting_return' not in keys
    assert keys[-1] == 'closed'

    life.execute(ident, 'diagnose', dict(notes='Faulty power board', repairable=True, parts='Power board', parts_available=True))
    v, nodes, current = project(life, ident)
    assert current['key'] == 'awaiting_estimate' and states(nodes)['diagnosis'] == 'completed'

    life.execute(ident, 'wait_parts', {'notes': 'Power board on order from supplier'})
    v, nodes, current = project(life, ident)
    assert current['key'] == 'waiting_parts' and current['status'] == 'waiting'
    assert 'Power board on order from supplier' in current['detail']

    life.execute(ident, 'parts_received', {'notes': 'Power board received'})
    v, nodes, current = project(life, ident)
    assert current['key'] == 'awaiting_estimate' and states(nodes)['waiting_parts'] == 'completed'

    quote = service.issue_quote(ident, 'Replace power board', [{'description': 'Parts and labour', 'amount': 120000}])
    v, nodes, current = project(life, ident)
    assert current['key'] == 'awaiting_approval' and current['status'] == 'waiting'
    assert 'approve' in current['detail'].lower()

    service.decide_quote(quote, 'approved', 'Device owner', 'in_person')
    v, nodes, current = project(life, ident)
    # tracker() lists no step for `approved`; the job's own stage still shows.
    assert v['stage'] == 'approved' and current['key'] == 'approved'
    assert states(nodes)['awaiting_approval'] == 'completed'
    assert [n['key'] for n in nodes].index('approved') < [n['key'] for n in nodes].index('under_repair')

    life.execute(ident, 'start_repair')
    v, nodes, current = project(life, ident)
    assert current['key'] == 'under_repair' and current['status'] == 'current'
    assert states(nodes)['final_qc'] == 'upcoming' and states(nodes)['collected'] == 'upcoming'

    life.execute(ident, 'complete_repair', dict(notes='Power board replaced', parts='Power board'))
    v, nodes, current = project(life, ident)
    assert current['key'] == 'technician_testing'

    life.execute(ident, 'test', dict(result='passed', notes='Power on test passed'))
    v, nodes, current = project(life, ident)
    assert current['key'] == 'final_qc' and states(nodes)['under_repair'] == 'completed'

    qc(life, ident)
    v, nodes, current = project(life, ident)
    assert current['key'] == 'billing'

    life.execute(ident, 'bill', {'confirmed': True})
    v, nodes, current = project(life, ident)
    assert current['key'] == 'ready_repaired' and 'Returning without repair' not in current['detail']

    service.post('customer', customer, 'receipt', 120000, uuid.uuid4().hex, job_id=ident)
    life.execute(ident, 'handover', dict(demonstrated=True, accepted=True, accessories_returned=True,
                                         payment_checked=True, received_by='Owner', acknowledgment='Signed receipt'))
    v, nodes, current = project(life, ident)
    assert current['key'] == 'collected'

    life.execute(ident, 'close')
    v, nodes, current = project(life, ident)
    assert current['key'] == 'closed'
    assert [n['status'] for n in nodes[:-1]] == ['completed'] * (len(nodes) - 1)


@pytest.mark.parametrize('kind,warranty,expected,absent', [
    ('warranty_centre', True, 'Service center dispatch', 'Third-party dispatch'),
    ('third_party', False, 'Third-party dispatch', 'Service center dispatch'),
])
def test_route_selection_branches_the_visible_path(service, customer, kind, warranty, expected, absent):
    ident, life = route(service, customer, kind, warranty)
    v, nodes, current = project(life, ident)
    titles = [n['title'] for n in nodes]
    keys = [n['key'] for n in nodes]
    assert expected in titles and absent not in titles
    assert 'external_diagnosis' in keys and 'awaiting_return' in keys
    assert 'diagnosis' not in keys and 'technician_testing' not in keys
    assert current['key'] == 'ready_dispatch'


def test_in_transit_and_external_stages_read_as_waiting_not_as_shop_work(service, customer):
    ident, life = route(service, customer, 'third_party')
    life.execute(ident, 'prepare_dispatch', dict(items=[r['id'] for r in life.holdings(ident)], consent=True,
                                                 condition='Intact', expected_return='2099-01-01'))
    life.execute(ident, 'dispatch', dict(counterparty='Courier', condition='Intact',
                                         acknowledgment='Receipt D1', carrier='Blue Dart'))
    v, nodes, current = project(life, ident)
    assert current['status'] == 'waiting' and current['detail']
    assert v['data']['in_transit']

    life.execute(ident, 'arrive', dict(counterparty='Repairer', condition='Intact', acknowledgment='Arrival A1'))
    v, nodes, current = project(life, ident)
    assert current['key'] == 'external_diagnosis' and current['status'] == 'waiting'
    assert states(nodes)['ready_dispatch'] == 'completed'


def test_accepted_warranty_claim_marks_estimate_and_approval_as_skipped(service, customer):
    ident, life = route(service, customer, 'warranty_centre', warranty=True)
    dispatch(service, ident, life)
    life.execute(ident, 'diagnose', dict(notes='Mainboard fault', repairable=True, parts='Mainboard', parts_available=True))
    life.execute(ident, 'warranty_result', dict(decision='accepted', rma='RMA-1', notes='Claim accepted by the service center',
                                                covered='Mainboard replacement', excluded='', terms='Manufacturer warranty'))
    v, nodes, current = project(life, ident)
    assert v['data']['warranty_covered'] and v['stage'] == 'approved'
    assert current['key'] == 'approved'
    marks = states(nodes)
    assert marks['awaiting_estimate'] == 'skipped' and marks['awaiting_approval'] == 'skipped'
    keys = [n['key'] for n in nodes]
    assert keys.index('awaiting_estimate') < keys.index('awaiting_approval') < keys.index('approved') < keys.index('under_repair')
    for node in nodes:
        if node['status'] == 'skipped':
            assert 'warranty' in node['detail'].lower()


def test_not_repairable_outcome_shows_red_and_skips_the_repair_stage(service, customer):
    ident, life = route(service, customer, 'in_house')
    life.execute(ident, 'diagnose', dict(notes='Board is burnt beyond repair', repairable=False, parts='', parts_available=False))
    v, nodes, current = project(life, ident)
    assert current['key'] == 'return_unrepaired' and current['status'] == 'failed'
    assert 'Not repairable' in current['detail']
    marks = states(nodes)
    assert marks['under_repair'] == 'skipped'
    keys = [n['key'] for n in nodes]
    assert keys.index('under_repair') < keys.index('return_unrepaired')
    assert 'Return condition check' in [n['title'] for n in nodes]

    qc(life, ident)
    life.execute(ident, 'bill', {'confirmed': True})
    v, nodes, current = project(life, ident)
    assert current['key'] == 'ready_repaired' and 'Returning without repair' in current['detail']
    assert states(nodes)['return_unrepaired'] == 'failed'


def test_a_hold_turns_the_current_stage_amber_with_its_recorded_reason(service, customer):
    ident, life = route(service, customer, 'in_house')
    service.hold(ident, 'Customer asked to pause until payday')
    v, nodes, current = project(life, ident)
    assert current['status'] == 'waiting'
    assert 'Customer asked to pause until payday' in current['detail']
    service.hold(ident, '')
    v, nodes, current = project(life, ident)
    assert current['status'] == 'current' and not current['detail']


def test_legacy_records_still_open_with_one_current_stage(service, customer):
    ident = service.intake(customer, 'Legacy laptop', 'No display')
    life = Lifecycle(service)
    v, nodes, current = project(life, ident)
    assert not v['lifecycle_version'] and v['primary'] == 'adopt'
    assert nodes and all(n['status'] in JOURNEY_STATES for n in nodes)


def test_completed_stages_carry_their_recorded_history(service, customer):
    ident, life = route(service, customer, 'in_house')
    v, nodes, current = project(life, ident)
    warranty = next(n for n in nodes if n['key'] == 'warranty_check')
    assert warranty['status'] == 'completed' and len(warranty['events']) == 1
    event = warranty['events'][0]
    assert event['actor'] and event['time'] and event['event']
    assert all(e in v['timeline'] for n in nodes for e in n['events'])
    # Stages still ahead never claim history they do not have.
    assert all(not n['events'] for n in nodes if n['key'] in ('under_repair', 'billing', 'collected'))


def test_primary_button_reuses_the_backend_action_and_sits_in_the_current_card(qtbot, service, customer):
    ident, life = fresh(service, customer)
    v = life.snapshot(ident)
    view = RepairJourney()
    qtbot.addWidget(view)
    view.set_snapshot(v)
    seen = []
    view.action_requested.connect(seen.append)
    view.primary.click()
    assert seen == [v['primary']] == ['inspect']
    assert view.primary.parent() is view.current_node

    view.set_snapshot(v, readonly=True)
    assert not view.primary.isEnabled()
    view.primary.click()
    assert len(seen) == 1


def test_legend_explains_only_the_states_drawn_for_this_repair(qtbot, service, customer):
    ident, life = fresh(service, customer)
    view = RepairJourney()
    qtbot.addWidget(view)
    view.show()
    view.set_snapshot(life.snapshot(ident))
    qtbot.wait(20)
    assert view.legend_labels['completed'].isVisible() and view.legend_labels['upcoming'].isVisible()
    assert not view.legend_labels['failed'].isVisible()
    assert not view.legend_labels['skipped'].isVisible()

    other, life2 = route(service, customer, 'in_house')
    life2.execute(other, 'diagnose', dict(notes='Board is burnt beyond repair', repairable=False, parts='', parts_available=False))
    view.set_snapshot(life2.snapshot(other))
    qtbot.wait(20)
    assert view.legend_labels['failed'].isVisible()
    assert view.legend_labels['skipped'].isVisible()


def test_workspace_keeps_every_tab_and_reflows_instead_of_clipping(qtbot, service, customer):
    from repairshop.ui import MainWindow
    from repairshop.lifecycle_ui import JobWorkspace
    ident, life = route(service, customer, 'in_house')
    window = MainWindow(service)
    window.timer.stop()
    qtbot.addWidget(window)
    d = JobWorkspace(window, ident)
    qtbot.addWidget(d)
    d.show()
    titles = [d.tabs.tabText(i) for i in range(d.tabs.count())]
    for title in ('Repair workspace', 'Repair timeline', 'Items and location', 'Job Cards', 'Parts', 'Warranty', 'Internal costing'):
        assert title in titles
    assert d.next is d.journey.current_action
    assert 'Initial inspection' in d.tracker.text()

    d.resize(1400, 900)
    qtbot.wait(30)
    assert d.splitter.orientation() == Qt.Orientation.Horizontal
    d.resize(820, 900)
    qtbot.wait(30)
    assert d.splitter.orientation() == Qt.Orientation.Vertical
    assert [d.tabs.tabText(i) for i in range(d.tabs.count())] == titles
    for card in d.journey.node_widgets:
        assert card.width() <= d.journey.width()
    window.pool.waitForDone(10000)


def test_route_options_offer_the_backend_routes_only_while_the_route_is_open(service, customer):
    """The branch drawn at the decision point is the backend's own route list."""
    from repairshop.lifecycle import ROUTE_LABELS
    ident, life = fresh(service, customer)
    v, nodes, current = project(life, ident)
    decision = next(n for n in nodes if n['key'] == 'route_selection')
    assert decision['options'] == list(ROUTE_LABELS.values())
    # Offering a choice is not the same as promising its stages.
    assert [n['key'] for n in nodes] == ['received', 'inspection', 'warranty_check', 'route_selection']

    chosen, life2 = route(service, customer, 'in_house')
    v2, nodes2, current2 = project(life2, chosen)
    settled = next(n for n in nodes2 if n['key'] == 'route_selection')
    assert settled['status'] == 'completed' and not settled.get('options')


def test_rail_mode_keeps_every_stage_visible_and_switches_back(qtbot, service, customer):
    """Placed above the tabs the journey becomes a pinned rail, not a column."""
    ident, life = route(service, customer, 'in_house')
    view = RepairJourney()
    qtbot.addWidget(view)
    view.resize(900, 420)
    view.show()
    view.set_snapshot(life.snapshot(ident))
    qtbot.wait(30)
    assert not view.rail_holder.isVisible()
    expected = [node['title'] for node in view.nodes]

    view.set_orientation(Qt.Orientation.Horizontal)
    qtbot.wait(30)
    assert view.rail_holder.isVisible()
    rail = view.rail_layout.itemAt(0).widget()
    chips = [rail.flow.itemAt(i).widget() for i in range(rail.flow.count())]
    named = [c.accessibleName().rsplit(' · ', 1)[0] for c in chips if c.accessibleName()]
    assert named == expected
    # The strip must really occupy the height its wrapped rows need.
    assert rail.height() >= rail.flow.heightForWidth(rail.width()) > 0
    # The current stage is still expanded, with its action inside it.
    assert view.current_node is not None and view.primary.isVisible()
    assert view.primary.parent() is view.current_node

    view.set_orientation(Qt.Orientation.Vertical)
    qtbot.wait(30)
    assert not view.rail_holder.isVisible()
    assert [node['title'] for node in view.nodes] == expected
    assert view.primary.parent() is view.current_node


def test_clicking_a_stage_only_opens_its_history(qtbot, service, customer, monkeypatch):
    """Stage clicks are for reading. They must never dispatch a transition."""
    ident, life = route(service, customer, 'in_house')
    view = RepairJourney()
    qtbot.addWidget(view)
    view.resize(420, 900)
    view.show()
    view.set_snapshot(life.snapshot(ident))
    qtbot.wait(20)
    dispatched, opened = [], []
    view.action_requested.connect(dispatched.append)
    monkeypatch.setattr(RepairJourney, 'show_history', lambda self, node: opened.append(node['key']))
    card = view.node_widgets[0]
    qtbot.mouseClick(card, Qt.MouseButton.LeftButton)
    assert opened == [view.nodes[0]['key']]
    assert dispatched == []
    # Every node carries its own readable summary for hover.
    assert all(w.toolTip() and w.accessibleName() for w in view.node_widgets)


def test_workspace_separates_stage_actions_from_general_tools(qtbot, service, customer):
    from repairshop.ui import MainWindow
    from repairshop.lifecycle_ui import JobWorkspace
    ident, life = fresh(service, customer)
    window = MainWindow(service)
    window.timer.stop()
    qtbot.addWidget(window)
    d = JobWorkspace(window, ident)
    qtbot.addWidget(d)
    d.show()
    tools = [d.tools.itemAt(i).widget().text() for i in range(d.tools.count())]
    stage = [d.buttons.itemAt(i).widget().text() for i in range(d.buttons.count())]
    assert set(tools) == {'Check shop inventory / manage required parts', 'Manual warranty check',
                          'Review internal repair costs', 'Hand product to another staff member'}
    assert not set(tools) & set(stage)
    # A newly received job has no other stage action, so its caption stays hidden.
    assert stage == [] and not d.actions_caption.isVisible() and d.tools_caption.isVisible()
    # Qt reads a lone "&" as a mnemonic; the caption must show a real ampersand.
    toggles = [b for b in d.findChildren(type(d.primary)) if 'administrative' in b.text()]
    assert toggles and toggles[0].text() == 'Utilities && administrative actions'
    assert toggles[0].accessibleName() == 'Utilities & administrative actions'

    life.execute(ident, 'inspect')
    d.reload()
    assert d.actions_caption.isVisible() == (d.buttons.count() > 0)
    window.pool.waitForDone(10000)
