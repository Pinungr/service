"""Search, dashboard entry, and the operational horizontal workflow."""
import json

from repairshop.lifecycle import Lifecycle
from repairshop.ui import MainWindow
from repairshop.ui_widgets import MetricCard
from test_lifecycle import approve, complete, diagnosis, route


def test_global_lookup_finds_mobile_job_and_physical_product(service, customer):
    first = service.intake(customer, 'Customer laptop', 'No power', guided=True)
    second = service.intake(customer, 'Customer printer', 'Paper jam', guided=True)
    life = Lifecycle(service)
    number = service.job(first)['number']
    device_id = service.job(first)['device_id']

    mobile = life.search_jobs('9990000001')
    assert [row['id'] for row in mobile] == [second, first]
    assert [row['id'] for row in life.search_jobs(number.lower())] == [first]
    assert first in [row['id'] for row in life.search_jobs(number[-6:])]
    assert [row['id'] for row in life.search_jobs(f'DEV-{device_id:06d}')] == [first]
    assert life.search_jobs('not-a-job') == []


def test_global_search_opens_exact_job_and_lists_mobile_matches(qtbot, service, customer, monkeypatch):
    first = service.intake(customer, 'Laptop', 'No power', guided=True)
    second = service.intake(customer, 'Printer', 'Paper jam', guided=True)
    window = MainWindow(service)
    window.timer.stop()
    qtbot.addWidget(window)
    opened = []
    monkeypatch.setattr(window, 'job_detail', opened.append)

    window.global_search.setText(service.job(first)['number'].lower())
    window.open_global_search()
    assert opened == [first]

    window.global_search.setText('9990000001')
    window.update_global_search()
    assert window.global_results.count() == 2
    assert [row['id'] for row in window.global_matches] == [second, first]
    window.open_global_item(window.global_results.item(0))
    assert opened == [first, second]
    window.pool.waitForDone(10000)


def test_job_opens_as_main_page_and_returns_to_repairs(qtbot, service, customer):
    ident = service.intake(customer, 'Laptop', 'No power', guided=True)
    window = MainWindow(service)
    window.timer.stop()
    qtbot.addWidget(window)
    window.navigate('Active Repairs')

    window.job_detail(ident)
    assert window.page_name == 'Job Workflow'
    assert window.stack.currentWidget() is window.job_workspace
    assert window.job_workspace.view['number'] == service.job(ident)['number']
    window.refresh()
    assert window.stack.currentWidget() is window.job_workspace

    window.job_workspace.close_workspace()
    assert window.page_name == 'Active Repairs'
    window.pool.waitForDone(10000)


def test_customer_overview_dismisses_before_opening_job_page(qtbot, service, customer):
    from PyQt6.QtWidgets import QDialog
    from repairshop.customer_ui import CustomerOverview

    ident = service.intake(customer, 'Laptop', 'No power', guided=True)
    window = MainWindow(service)
    window.timer.stop()
    qtbot.addWidget(window)
    overview = CustomerOverview(window, customer)
    qtbot.addWidget(overview)
    overview.show()
    overview.grids['outstanding'].selectRow(0)

    overview.open_job('outstanding')

    assert overview.result() == QDialog.DialogCode.Accepted
    assert window.page_name == 'Job Workflow'
    assert window.job_workspace.ident == ident
    window.pool.waitForDone(10000)


def test_current_stage_completes_inline_with_audit_and_future_is_read_only(qtbot, service, customer):
    ident = service.intake(customer, 'Laptop', 'No power', guided=True)
    life = Lifecycle(service)
    life.execute(ident, 'inspect')
    window = MainWindow(service)
    window.timer.stop()
    qtbot.addWidget(window)
    window.job_detail(ident)
    journey = window.job_workspace.journey
    assert journey.snapshot['primary'] == 'inspection_done'

    future = next(node for node in journey.nodes if node['status'] == 'upcoming')
    journey.show_history(future)
    assert not journey.primary.isVisible()
    assert life.snapshot(ident)['stage'] == 'inspection'

    current = next(node for node in journey.nodes if node['is_current'])
    journey.show_history(current)
    journey.inline_fields['notes'].setPlainText('Power supply failed inspection')
    journey.primary.click()

    assert life.snapshot(ident)['stage'] == 'warranty_check'
    assert window.job_workspace.journey.snapshot['stage'] == 'warranty_check'
    states = {node['key']: node['status'] for node in window.job_workspace.journey.nodes}
    assert states['inspection'] == 'completed'
    assert states['warranty_check'] == 'current'
    audit = service.db.one(
        "SELECT payload FROM audit WHERE entity='job' AND entity_id=? AND action='lifecycle' ORDER BY id DESC LIMIT 1",
        (ident,))
    assert json.loads(audit['payload'])['action'] == 'inspection_done'
    window.pool.waitForDone(10000)


def test_final_qc_uses_contextual_checks_and_advances(qtbot, service, customer):
    ident, life = route(service, customer)
    diagnosis(life, ident)
    approve(service, ident)
    complete(life, ident)
    if 'return_technician' in life.snapshot(ident)['actions']:
        life.execute(ident, 'return_technician',
                     {'condition': 'Intact', 'acknowledgment': 'QC desk received'})
    window = MainWindow(service)
    window.timer.stop()
    qtbot.addWidget(window)
    window.job_detail(ident)
    journey = window.job_workspace.journey
    assert journey.snapshot['primary'] == 'qc'
    journey.inline_fields['result'].setCurrentIndex(1)
    for key in ('functional', 'power', 'charging', 'display', 'connectivity', 'complaint'):
        journey.inline_fields[key].setCurrentIndex(1)
    journey.inline_fields['notes'].setPlainText('Final checks passed')
    journey.inline_fields['repair_warranty'].setText('90 days workmanship')
    journey.inline_fields['warranty_until'].setText('2099-01-01')
    journey.primary.click()

    assert window.job_workspace.view['stage'] == 'billing'
    assert life.snapshot(ident)['data']['qc']['checks']['functional'] == 'passed'
    window.pool.waitForDone(10000)


def test_dashboard_status_card_filters_jobs_and_result_opens_workflow(qtbot, service, customer, monkeypatch):
    received = service.intake(customer, 'Laptop', 'No power', guided=True)
    inspected = service.intake(customer, 'Printer', 'Paper jam', guided=True)
    Lifecycle(service).execute(inspected, 'inspect')
    window = MainWindow(service)
    window.timer.stop()
    qtbot.addWidget(window)
    opened = []
    monkeypatch.setattr(window, 'job_detail', opened.append)
    card = next(c for c in window.stack.currentWidget().findChildren(MetricCard)
                if c.caption.text() == 'Waiting inspection')
    assert card.value.text() == '1'

    card.click()
    assert window.page_name == 'Active Repairs'
    assert window.active_filter.currentData() == 'inspection'
    assert [row['id'] for row in window.active_grid.rows] == [inspected]
    assert window.active_grid.rows[0]['phone'].endswith('9990000001')
    assert window.active_grid.rows[0]['stage_age']
    window.active_grid.selectRow(0)
    window.active_grid.cellDoubleClicked.emit(0, 0)
    assert opened == [inspected]
    window.pool.waitForDone(10000)
