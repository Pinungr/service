from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialogButtonBox, QLineEdit
from repairshop.ui import MainWindow
from repairshop.ui_widgets import Form, CustomerSelector, MasterSelector, STYLE


def test_main_pages_query_persisted_data(qtbot,service,customer,job):
    window=MainWindow(service)
    window.timer.stop()
    window.setStyleSheet(STYLE)
    qtbot.addWidget(window)
    window.show()
    for page in window.nav:
        window.navigate(page)
        assert window.title.text()==page
        assert window.stack.currentWidget()
    window.pool.waitForDone(10000)


def test_customer_selector_search_and_form_save(qtbot,service,customer):
    selector=CustomerSelector(service)
    qtbot.addWidget(selector)
    qtbot.keyClicks(selector.search,"Synthetic")
    assert selector.box.count()==2
    selector.box.setCurrentIndex(1)
    assert selector.text()==customer
    form=Form("Create customer")
    qtbot.addWidget(form)
    name=form.text("name","Name")
    qtbot.keyClicks(name,"New UI Customer")
    saved=[]
    from PyQt6.QtCore import QTimer
    QTimer.singleShot(50,lambda: form.buttons.button(QDialogButtonBox.StandardButton.Save).click())
    assert form.submit(lambda v:saved.append(service.save_customer(v["name"])))
    assert service.db.one("SELECT name FROM customers WHERE id=?",(saved[0],))["name"]=="New UI Customer"


def test_real_intake_accessories_start_unchecked_and_persist(qtbot,service,customer,monkeypatch):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QCheckBox
    window=MainWindow(service)
    window.timer.stop()
    qtbot.addWidget(window)
    monkeypatch.setattr(window,'job_detail',lambda _:None)
    def fill_intake():
        form=QApplication.activeModalWidget()
        assert isinstance(form,Form)
        form.fields['customer_id'].box.setCurrentIndex(1)
        category=form.fields['category_id'].box
        category.setCurrentIndex(category.findText('Laptop'))
        accessory_checks=[w for w in form.findChildren(QCheckBox) if hasattr(w,'quantity_control')]
        assert accessory_checks and all(not w.isChecked() for w in accessory_checks)
        for check in accessory_checks:
            if check.text() in ('Adapter','Mouse'):
                check.setChecked(True)
        form.fields['device'].setText('UI Laptop')
        form.fields['brand'].setText('Test brand');form.fields['model'].setText('Test model')
        service_box=form.fields['service_id'].box
        service_box.setCurrentIndex(service_box.findText('Laptop repair'))
        form.fields['complaint'].setPlainText('UI fault')
        for _ in range(3):form.wizard.next_step()
        form.buttons.button(QDialogButtonBox.StandardButton.Save).click()
    QTimer.singleShot(30,fill_intake)
    window.intake()
    rows=service.db.rows('SELECT description FROM items ORDER BY id')
    assert {r['description'] for r in rows}=={'UI Laptop','Adapter','Mouse'}
    qtbot.waitUntil(lambda:not window.tasks,timeout=10000)


def test_intake_registers_customer_inline_and_enables_photo(qtbot,service,monkeypatch):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QImage,QColor
    from repairshop.customer_records import CustomerRecords
    window=MainWindow(service);qtbot.addWidget(window)
    monkeypatch.setattr(window,'job_detail',lambda _:None)
    def register():
        form=QApplication.activeModalWidget()
        try:
            assert form.fields['name'].text()=='Bibhu Test'
            form.fields['phone_number'].setText('9990007788')
            form.fields['address'].setPlainText('123 Test Street')
            form.buttons.button(QDialogButtonBox.StandardButton.Save).click()
        except BaseException:
            form.reject();raise
    def fill_intake():
        form=QApplication.activeModalWidget()
        try:
            owner=form.fields['customer_id']
            form.fields['device'].setText('Inline registration test laptop')
            form.fields['complaint'].setPlainText('Screen fault')
            owner.search.setText('Bibhu Test')
            assert owner.text() is None and not form.intake_support.capture_button.isEnabled()
            assert 'No matching customer' in owner.hint.text()
            QTimer.singleShot(10,register)
            owner.create_button.click()
            customer=service.db.one("SELECT id FROM customers WHERE name='Bibhu Test'")['id']
            assert owner.text()==customer and form.intake_support.capture_button.isEnabled()
            assert form.fields['device'].text()=='Inline registration test laptop'
            assert form.fields['complaint'].toPlainText()=='Screen fault'
            photo=QImage(64,64,QImage.Format.Format_RGB32);photo.fill(QColor('#68a398'))
            form.intake_support.photo_id=CustomerRecords(service).save_photo(photo,customer)
            form.intake_support.update_photo()
            category=form.fields['category_id'].box;category.setCurrentIndex(category.findText('Laptop'))
            svc=form.fields['service_id'].box;svc.setCurrentIndex(svc.findText('Laptop repair'))
            form.fields['brand'].setText('Test brand');form.fields['model'].setText('Test model')
            for _ in range(3):form.wizard.next_step()
            form.buttons.button(QDialogButtonBox.StandardButton.Save).click()
        except BaseException:
            form.reject();raise
    QTimer.singleShot(30,fill_intake)
    window.intake()
    saved=service.db.one('SELECT j.customer_id,j.device,j.complaint,j.photo_id,c.name FROM jobs j JOIN customers c ON c.id=j.customer_id')
    assert saved['name']=='Bibhu Test' and saved['photo_id']
    assert saved['complaint']=='Screen fault'
    qtbot.waitUntil(lambda:not window.tasks,timeout=10000)


def test_cancel_inline_customer_preserves_selection(qtbot,service,customer):
    selector=CustomerSelector(service,customer,create=lambda _:None);qtbot.addWidget(selector)
    selector.create_button.click()
    assert selector.text()==customer
    assert service.db.one('SELECT count(*) n FROM customers')['n']==1
