"""Render the real intake/customer forms against isolated synthetic data."""
import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage, QColor
from repairshop.persistence import Database
from repairshop.services import Service
from repairshop.customer_records import CustomerRecords
from repairshop.customer_registration import CustomerRegistration
from repairshop.customer_ui import IntakeForm
from repairshop.ui import MainWindow
from repairshop.ui_widgets import STYLE


def render(output):
    output.mkdir(parents=True, exist_ok=True)
    app=QApplication.instance() or QApplication([]); app.setStyle('Fusion'); app.setStyleSheet(STYLE)
    service=Service(Database(output/'synthetic-data'))
    service.setup('Demo Repair Shop','owner','PreviewOnly123!')
    customer=service.save_customer('Demo Customer','9990001234',address='123 Demo Street')
    picture=QImage(64,64,QImage.Format.Format_RGB32);picture.fill(QColor('#97bfb4'))
    CustomerRecords(service).save_photo(picture,customer)
    category=next(r['id'] for r in service.masters('category') if r['name']=='Laptop')
    sale=service.save_sale(customer,'Dell Inspiron 15',category_id=category,serial='DEMO-123',sale_date=date.today().isoformat(),warranty_start=date.today().isoformat(),warranty_end=(date.today()+timedelta(days=365)).isoformat())
    sale=service.db.one('SELECT * FROM sales WHERE id=?',(sale,))
    CustomerRecords(service).update_device(sale['device_id'],'Dell Inspiron 15','Dell','Inspiron 15','DEMO-123')
    window=MainWindow(service);window.timer.stop()
    forms=[]
    original=IntakeForm.submit
    IntakeForm.submit=lambda form,callback: forms.append(form) or 0
    try:window.intake(sale=sale)
    finally:IntakeForm.submit=original
    form=forms[0];form.show();app.processEvents()
    form.fields['complaint'].setPlainText('Laptop shuts down after approximately 15 minutes.')
    form.fields['damage'].setPlainText('Minor scratches on the left panel.')
    next(c for c in form.visit_intake.checks if c.text()=='Adapter').setChecked(True)
    for step in range(4):
        form.wizard.go(step);app.processEvents();form.grab().save(str(output/f'intake-step-{step+1}.png'))
    registration=CustomerRegistration(service,initial={'name':'New customer'});registration.show();app.processEvents()
    registration.grab().save(str(output/'customer-registration.png'))
    registration.close();form.keep_draft=None;form.close();window.close()
    window.pool.waitForDone(10000)


if __name__=='__main__':render(Path(sys.argv[1]).resolve())
