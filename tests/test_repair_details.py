from copy import deepcopy

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel

from repairshop.domain import rupees
from repairshop.repair_details import RepairDetails


def snapshot():
    return dict(responsible='Shop counter', pending_since='14 Sep 2026', warranty_status='Unknown',
                complaint='<b>Customer text</b>', damage='Scratched', return_due=None, collection_due='2026-09-20',
                assignment={'technician': 'Alex'}, quote={'total': 125000, 'state': 'issued'}, paid=25000, balance=100000,
                data={'diagnosis': 'Power supply fault', 'parts_available': False,
                      'route_details': {'reference': 'REF-123', 'vendor_total': 987654321,
                                        'customer_price': 456789123,
                                        'inspection': {'findings': 'Corrosion', 'purchase_cost': 123456789}}})


def test_details_preserve_values_and_privacy_without_changing_snapshot(qtbot):
    view = RepairDetails()
    qtbot.addWidget(view)
    value = snapshot()
    before = deepcopy(value)
    view.set_snapshot(value)
    assert value == before
    assert len(view.forms) == 6
    assert view.values['Customer estimate'].text() == rupees(125000)
    assert view.values['Balance due'].text() == rupees(100000)
    assert view.values['Parts availability'].text() == 'Pending'
    assert view.values['Expected return'].text() == 'Not recorded'
    assert view.values['Reference'].text() == 'REF-123'
    assert view.values['Reported fault'].text() == '<b>Customer text</b>'
    assert view.values['Reported fault'].textFormat() == Qt.TextFormat.PlainText
    captions = [label for label in view.findChildren(QLabel) if label.objectName() == 'subtitle']
    assert all(label.minimumWidth() > 0 for label in captions)
    text = '\n'.join(label.text() for label in view.findChildren(QLabel))
    assert 'Corrosion' in text
    assert all(secret not in text for secret in ('987654321', '456789123', '123456789'))


def test_details_refresh_removes_stale_route_fields_and_adapts_width(qtbot):
    view = RepairDetails()
    qtbot.addWidget(view)
    view.set_snapshot(snapshot())
    view.resize(1100, 900)
    view.show()
    qtbot.wait(25)
    assert view.grid.columns == 3
    value = snapshot()
    value['data'] = {'diagnosis': 'Long description ' * 30}
    value['quote'] = {}
    view.set_snapshot(value)
    view.resize(320, 1600)
    qtbot.wait(25)
    assert view.grid.columns == 1
    assert 'Reference' not in view.values
    assert view.values['Customer estimate'].text() == 'Not issued'
    assert view.values['QC result'].text() == 'Pending'
    assert view.values['Confirmed diagnosis'].wordWrap()
    assert all(card.geometry().right() < view.width() for card in view.grid.cards)


def test_details_name_the_warranty_route_and_physical_custody_in_words(qtbot):
    """Stored codes are shown in the wording staff already see elsewhere."""
    view = RepairDetails()
    qtbot.addWidget(view)
    value = snapshot()
    value.update(warranty_status='out_of_warranty', current_custodian='Alex',
                 current_location='IN SHOP · Bench 2')
    view.set_snapshot(value)
    assert view.values['Warranty route'].text() == 'Out of warranty'
    assert view.values['Current custodian'].text() == 'Alex'
    assert view.values['Physical location'].text() == 'IN SHOP · Bench 2'

    value['warranty_status'] = 'under_warranty'
    view.set_snapshot(value)
    assert view.values['Warranty route'].text() == 'Under manufacturer warranty'
    # An unrecognised value is shown as stored rather than hidden.
    value['warranty_status'] = 'Legacy free text'
    view.set_snapshot(value)
    assert view.values['Warranty route'].text() == 'Legacy free text'
