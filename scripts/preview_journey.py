"""Render the real Repair Lifecycle screen at representative lifecycle states.

Every screenshot is driven through Lifecycle.execute() against a throwaway
database, so what you see is the production widget reading production state.
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage, QColor
from repairshop.customer_records import CustomerRecords
from repairshop.persistence import Database
from repairshop.services import Service
from repairshop.lifecycle import Lifecycle
from repairshop.lifecycle_ui import JobWorkspace
from repairshop.ui import MainWindow
from repairshop.ui_widgets import STYLE


def intake(service, customer):
    ident = service.intake(customer, 'Dell Inspiron 15', 'Shuts down after 15 minutes', guided=True,
                           accessories=[dict(type='accessory', description='Adapter', quantity=1)])
    return ident, Lifecycle(service)


def to_route(service, customer, kind='in_house', warranty=False):
    ident, life = intake(service, customer)
    life.execute(ident, 'inspect')
    life.execute(ident, 'inspection_done', {'notes': 'Power fault confirmed; condition checked'})
    life.execute(ident, 'verify_warranty', {'warranty_status': 'under_warranty' if warranty else 'out_of_warranty',
                                            'notes': 'Purchase evidence reviewed'})
    p = {'route': kind, 'confirmed': True, 'technician_id': service.user['id']}
    if kind == 'in_house':
        p.update(handed_over=True, bench='Bench 2', condition='Intact', acknowledgment='Technician received')
    else:
        p['contact_id'] = service.save_master('centre' if kind == 'warranty_centre' else 'vendor', kind + ' partner')
    life.execute(ident, 'select_route', p)
    return ident, life


def shot(window, ident, output, name, size=(1500, 980)):
    view = JobWorkspace(window, ident)
    view.resize(*size)
    view.show()
    QApplication.instance().processEvents()
    view.grab().save(str(output / (name + '.png')))
    view.close()
    QApplication.instance().processEvents()


def render(output):
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    service = Service(Database(output / 'synthetic-data'))
    service.setup('Demo Repair Shop', 'owner', 'PreviewOnly123!')
    customer = service.save_customer('Demo Customer', '9990001234', address='123 Demo Street')
    picture = QImage(64, 64, QImage.Format.Format_RGB32)
    picture.fill(QColor('#97bfb4'))
    CustomerRecords(service).save_photo(picture, customer)
    window = MainWindow(service)
    window.timer.stop()

    ident, life = intake(service, customer)
    shot(window, ident, output, 'journey-1-received')
    shot(window, ident, output, 'journey-1-received-narrow', size=(900, 1000))

    # The decision point: routes are offered, but no route's stages are drawn yet.
    ident, life = intake(service, customer)
    life.execute(ident, 'inspect')
    life.execute(ident, 'inspection_done', {'notes': 'Power fault confirmed; condition checked'})
    life.execute(ident, 'verify_warranty', {'warranty_status': 'out_of_warranty', 'notes': 'Purchase evidence reviewed'})
    shot(window, ident, output, 'journey-1b-route-selection')

    ident, life = to_route(service, customer)
    life.execute(ident, 'diagnose', dict(notes='Faulty power board', repairable=True,
                                         parts='Power board', parts_available=True))
    service.issue_quote(ident, 'Replace power board', [{'description': 'Parts and labour', 'amount': 120000}])
    shot(window, ident, output, 'journey-2-awaiting-approval')

    quote = service.db.one('SELECT id FROM quotes WHERE job_id=? ORDER BY id DESC', (ident,))
    service.decide_quote(quote['id'], 'approved', 'Device owner', 'in_person')
    life.execute(ident, 'start_repair')
    shot(window, ident, output, 'journey-3-under-repair')

    ident, life = to_route(service, customer)
    life.execute(ident, 'diagnose', dict(notes='Board is burnt beyond repair', repairable=False,
                                         parts='', parts_available=False))
    shot(window, ident, output, 'journey-4-not-repairable')

    ident, life = to_route(service, customer, 'warranty_centre', warranty=True)
    life.execute(ident, 'prepare_dispatch', dict(items=[r['id'] for r in life.holdings(ident)], consent=True,
                                                 condition='Intact', expected_return='2099-01-01'))
    life.execute(ident, 'dispatch', dict(counterparty='Repairer', condition='Intact', acknowledgment='Receipt D1', carrier=''))
    life.execute(ident, 'diagnose', dict(notes='Mainboard fault', repairable=True, parts='Mainboard', parts_available=True))
    life.execute(ident, 'warranty_result', dict(decision='accepted', rma='RMA-1', notes='Claim accepted',
                                                covered='Mainboard replacement', excluded='', terms='Manufacturer warranty'))
    shot(window, ident, output, 'journey-5-warranty-covered')
    shot(window, ident, output, 'journey-6-narrow', size=(880, 1000))

    window.close()
    window.pool.waitForDone(10000)


if __name__ == '__main__':
    render(Path(sys.argv[1]).resolve())
