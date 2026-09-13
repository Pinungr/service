from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication,QDialogButtonBox,QPushButton
from repairshop.ui import MainWindow
from repairshop.lifecycle_ui import JobWorkspace
from repairshop.inventory_ui import InventoryPage
from repairshop.part_editor import choose_and_plan,edit_part
from repairshop.inventory import Inventory
from repairshop.parts import Parts
from test_lifecycle import route,dispatch,diagnosis
from test_inventory_custody import stock


def test_quote_revision_preview_uses_selling_prices(qtbot,service,customer):
    from PyQt6.QtWidgets import QLabel
    job,life=route(service,customer);diagnosis(life,job)
    quote=service.issue_quote(job,'Labour',[dict(description='Repair labour',amount=150000)])
    service.decide_quote(quote,'approved','Customer','in_person','Confirmed')
    inv,ident=stock(service);Parts(service).save(job,dict(source='stock',inventory_id=ident))
    w=MainWindow(service);qtbot.addWidget(w)
    def review():
        d=QApplication.activeModalWidget()
        try:
            d.fields['lines'].setPlainText('Repair labour | 1500')
            text='\n'.join(label.text() for label in d.findChildren(QLabel))
            assert 'Previous approved amount: INR 1,500.00' in text
            assert 'Revised total: INR 4,700.00' in text and 'Change from previous approval: INR 3,200.00' in text
            assert '2,500' not in text
        finally:d.reject()
    QTimer.singleShot(30,review);w.quote_form(job)


def test_active_claim_disables_ordinary_warranty_edit(qtbot,service,customer):
    from test_parts_cards_warranty import installed
    from test_lifecycle import deliver
    from repairshop.warranties import Warranties
    old,life,_,_=installed(service,customer);deliver(service,customer,old,life,100000)
    device=service.job(old)['device_id'];warranties=Warranties(service);wid=warranties.rows(device)[0]['id']
    new=service.intake(customer,'Same device','Battery fault',device_id=device,guided=True)
    warranties.claim(new,wid,'Battery fault')
    w=MainWindow(service);qtbot.addWidget(w);ws=JobWorkspace(w,new);qtbot.addWidget(ws)
    tab=ws.record_tabs[2];tab.grid.selectRow(0);tab.show_selected()
    assert not tab.action_buttons['Edit warranty (owner)'].isEnabled()
    assert tab.action_buttons['Privileged override (owner)'].isEnabled()
    assert 'MANAGED BY ACTIVE CLAIM' in tab.detail.text()


def test_inventory_form_creates_catalog_with_markup_and_filters(qtbot,service):
    w=MainWindow(service);qtbot.addWidget(w);page=InventoryPage(w);qtbot.addWidget(page)
    def create():
        d=QApplication.activeModalWidget()
        try:
            d.fields['name'].setText('Compatible laptop fan');d.fields['sku'].setText('FAN-001')
            d.fields['compatibility'].setText('Inspiron 15');d.fields['purchase_cost'].setText('100')
            d.fields['markup'].setText('25');d.fields['calculate_price'].setChecked(True)
            d.buttons.button(QDialogButtonBox.StandardButton.Save).click()
            assert d.result()==1,d.error.text()
        except BaseException:d.reject();raise
    QTimer.singleShot(30,create);page.edit()
    row=Inventory(service).rows()[0];assert row['customer_price']==12500 and row['markup_basis_points']==2500
    page.search.setText('Inspiron');assert page.grid.rowCount()==1
    page.search.setText('not present');assert page.grid.rowCount()==0
    page.search.clear();page.filter.setCurrentIndex(page.filter.findData('out'));assert page.grid.rowCount()==1
    def receive():
        d=QApplication.activeModalWidget()
        try:
            d.fields['quantity'].setText('5');d.fields['reference'].setText('INV-1')
            d.buttons.button(QDialogButtonBox.StandardButton.Save).click()
            assert d.result()==1,d.error.text()
        except BaseException:d.reject();raise
    page.grid.selectRow(0);QTimer.singleShot(30,receive);page.adjust()
    assert Inventory(service).rows()[0]['available']==5 and page.grid.rowCount()==0


def test_required_part_picker_starts_with_inventory_and_copies_warranty(qtbot,service,customer):
    job,life=route(service,customer);diagnosis(life,job);inv,ident=stock(service)
    w=MainWindow(service);qtbot.addWidget(w);ws=JobWorkspace(w,job);qtbot.addWidget(ws);records=ws.record_tabs[1]
    def save_part():
        d=QApplication.activeModalWidget()
        try:
            assert d.fields['source'].currentData()=='stock'
            assert d.fields['name'].text()=='Dell Battery 54Wh'
            assert d.fields['warranty_duration'].text()=='6'
            assert d.fields['purchase_cost'].isReadOnly()
            d.buttons.button(QDialogButtonBox.StandardButton.Save).click()
            assert d.result()==1,d.error.text()
        except BaseException:d.reject();raise
    def choose_stock():
        d=QApplication.activeModalWidget()
        try:
            from repairshop.ui_widgets import Grid
            d.findChild(Grid).selectRow(0)
            QTimer.singleShot(40,save_part)
            next(b for b in d.findChildren(QPushButton) if b.text()=='Use shop stock').click()
        except BaseException:d.reject();raise
    QTimer.singleShot(30,choose_stock);choose_and_plan(records)
    part=Parts(service).rows(job)[0]
    assert part['inventory_id']==ident and part['warranty_duration']==6 and part['customer_price']==320000
    assert part['stock_state']=='none' and inv.rows()[0]['available']==5


def test_counter_part_form_locks_repairer_and_hides_costs(qtbot,service,customer):
    job,life=route(service,customer,'third_party');dispatch(service,job,life);diagnosis(life,job)
    assigned=life.snapshot(job)['assignment']['contact_id'];service.save_master('vendor','Other company')
    service.save_staff('counter','Counter','counter','CounterPassword123!');service.login('counter','CounterPassword123!')
    w=MainWindow(service);qtbot.addWidget(w);ws=JobWorkspace(w,job);qtbot.addWidget(ws)
    assert ws.cost_panel is None and 'Internal costing' not in [ws.tabs.tabText(i) for i in range(ws.tabs.count())]
    def save():
        d=QApplication.activeModalWidget()
        try:
            assert d.fields['source'].currentData()=='technician'
            assert d.fields['supplier_id'].currentData()==assigned and not d.fields['supplier_id'].isEnabled()
            assert 'purchase_cost' not in d.fields
            d.fields['name'].setText('Vendor charging IC');d.fields['customer_price'].setText('1800')
            d.buttons.button(QDialogButtonBox.StandardButton.Save).click()
            assert d.result()==1,d.error.text()
        except BaseException:d.reject();raise
    QTimer.singleShot(30,save);edit_part(ws.record_tabs[1])
    row=Parts(service).rows(job)[0];assert row['supplier_id']==assigned and 'purchase_cost' not in row


def test_manual_warranty_form_and_history(qtbot,service,customer):
    from test_lifecycle import fresh
    from repairshop.warranties import Warranties
    job,life=fresh(service,customer);life.execute(job,'inspect');life.execute(job,'inspection_done',dict(notes='Device checked'))
    w=MainWindow(service);qtbot.addWidget(w);ws=JobWorkspace(w,job);qtbot.addWidget(ws)
    def verify():
        d=QApplication.activeModalWidget()
        try:
            for key,value in [('result','VALID'),('coverage','shop_part'),('evidence_type','Warranty slip')]:d.fields[key].setCurrentIndex(d.fields[key].findData(value))
            for key,value in [('reference','SLIP-10'),('provider','Our shop'),('notes','Original printed evidence verified')]:
                field=d.fields[key]
                if key=='notes':field.setPlainText(value)
                else:field.setText(value)
            d.buttons.button(QDialogButtonBox.StandardButton.Save).click()
            assert d.result()==1,d.error.text()
        except BaseException:d.reject();raise
    QTimer.singleShot(30,verify);ws.record_tabs[2].manual_warranty()
    assert Warranties(service).manual_checks(job)[0]['result']=='VALID'
    assert life.snapshot(job)['warranty_status']=='shop_warranty'
