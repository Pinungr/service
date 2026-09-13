"""Synthetic lifecycle scenarios for release verification; never uses shop data."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage,QColor,QFontDatabase
from repairshop.persistence import Database
from repairshop.services import Service
from repairshop.customer_records import CustomerRecords
from repairshop.lifecycle import Lifecycle
from repairshop.parts import Parts
from repairshop.warranties import Warranties
from repairshop.documents import Documents
from repairshop.ui import MainWindow
from repairshop.lifecycle_ui import JobWorkspace
from repairshop.ui_widgets import STYLE

ROOT=Path(__file__).resolve().parents[1]


def populate(s):
    if s.db.one('SELECT 1 FROM jobs'):
        return
    if not s.db.one('SELECT 1 FROM users'):
        s.setup('RepairShop · Synthetic lifecycle demo','demo','DemoShop2026!','Demo Owner')
    else:
        s.login('demo','DemoShop2026!')
    photo=QImage(100,100,QImage.Format.Format_RGB32);photo.fill(QColor('#7aa598'))
    customer=s.save_customer('Rahul Sharma · DEMO','9990001234')
    CustomerRecords(s).save_photo(photo,customer)
    vendor=s.save_master('vendor','ABC Laptop Service','9990001111','Rajesh · Board repair specialist · Pune · DEMO')
    centre=s.save_master('centre','Dell Authorized Service Center · DEMO','9990002222','Pune · Warranty desk · Synthetic address')
    life=Lifecycle(s)
    parts=Parts(s)
    stock=parts.stock_item('Power board',180000,300000,part_number='PB-DEMO-20',brand='Demo Components',model='Inspiron compatible')
    parts.adjust_stock(stock,10,'DEMO stock opening')
    states=['received','inspection','third_party','warranty','parts','approval','repair','qc','ready','closed']
    for index,target in enumerate(states):
        j=s.intake(customer,f'Dell Inspiron {index+1} · DEMO','Laptop does not power on',guided=True,damage='Light lid scratches; screen intact',accessories=[dict(type='accessory',description='Adapter',quantity=1)])
        if target=='received':continue
        life.execute(j,'inspect')
        if target=='inspection':continue
        life.execute(j,'inspection_done',dict(notes='No power confirmed; case and serial inspected'))
        life.execute(j,'verify_warranty',dict(warranty_status='under_warranty' if target=='warranty' else 'out_of_warranty',notes='Purchase date and warranty proof reviewed'))
        route='third_party' if target=='third_party' else 'warranty_centre' if target=='warranty' else 'in_house'
        life.execute(j,'select_route',dict(route=route,confirmed=True,technician_id=s.user['id'],contact_id=centre if target=='warranty' else vendor))
        if route=='in_house':life.execute(j,'hand_technician',dict(bench='Bench 1',condition='Intact',acknowledgment='Synthetic technician receipt'))
        if route!='in_house':
            life.execute(j,'prepare_dispatch',dict(items=[h['id'] for h in life.holdings(j)],condition='Intact; adapter included',consent=True,expected_return='2026-09-14'))
            life.execute(j,'dispatch',dict(counterparty='Rajesh' if target=='third_party' else 'Service desk',condition='Intact',reference='EXT-DEMO-101',acknowledgment='Synthetic dispatch receipt'))
            life.execute(j,'details',dict(contact_person='Rajesh Technician' if target=='third_party' else 'OEM warranty desk',external_reference='EXT-DEMO-101',notes='Awaiting diagnosis from repairer'))
            if target=='third_party':continue
        life.execute(j,'diagnose',dict(notes='Power circuit fault; board replacement recommended',parts='Power board',parts_available=target!='parts',repairable=True))
        part=None
        if target!='warranty':
            part=parts.save(j,dict(name='Power board',brand='Demo Components',model='Inspiron compatible',part_number='PB-DEMO-20',source='stock',inventory_id=stock,purchase_cost=180000,customer_price=300000,warranty_duration=6,warranty_unit='months',warranty_provider='RepairShop',warranty_terms='Manufacturing defects; physical damage excluded'))
        if target=='parts':
            life.execute(j,'wait_parts',dict(notes='Power board ordered · PO-DEMO-100'));continue
        if target=='warranty':
            life.execute(j,'warranty_result',dict(decision='accepted',notes='Repair covered under OEM warranty',rma='CLAIM-DEMO-24'))
            life.execute(j,'start_repair');continue
        q=s.issue_quote(j,'Replace power board',[dict(description='Labour',amount=150000)])
        if target=='approval':continue
        s.decide_quote(q,'approved','Rahul Sharma · DEMO','in_person','Synthetic customer approval')
        from repairshop.inventory import Inventory
        Inventory(s).transfer(part,'reserve','Synthetic reservation');Inventory(s).transfer(part,'issue','Synthetic issue')
        life.execute(j,'start_repair')
        if target=='repair':continue
        parts.install(part,'Demo Owner')
        life.execute(j,'complete_repair',dict(notes='Power board replaced; device powers on',parts='Power board'))
        life.execute(j,'test',dict(result='passed',notes='Startup, charging and display passed'))
        if target=='qc':continue
        life.execute(j,'return_technician',dict(condition='Intact',acknowledgment='Synthetic QC receipt'))
        life.execute(j,'qc',dict(result='passed',notes='Original complaint resolved',checks={k:'passed' for k in ('power','functional','charging','display','connectivity','complaint')},repair_warranty='90 days on supplied part'))
        life.execute(j,'bill',dict(confirmed=True))
        if target=='ready':continue
        s.post('customer',customer,'receipt',450000,'demo-payment',job_id=j)
        life.execute(j,'handover',dict(demonstrated=True,accepted=True,accessories_returned=True,payment_checked=True,received_by='Rahul Sharma · DEMO',acknowledgment='Synthetic handover receipt'))
        life.execute(j,'close')
    device=s.job(j)['device_id']
    follow=s.intake(customer,'Dell Inspiron 10 · DEMO','Power board fails again · WARRANTY DEMO',device_id=device,parent_id=j,guided=True)
    Warranties(s).claim(follow,Warranties(s).rows(device)[0]['id'],'Power failure within part warranty')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--preview',action='store_true');args=parser.parse_args()
    app=QApplication([])
    for filename in ('segoeui.ttf','segoeuib.ttf','seguisym.ttf'):
        QFontDatabase.addApplicationFont(str(Path('C:/Windows/Fonts')/filename))
    app.setStyle('Fusion');app.setStyleSheet(STYLE)
    s=Service(Database(ROOT/'runtime'/'lifecycle-v12-demo'))
    populate(s);s.login('demo','DemoShop2026!')
    start=time.perf_counter();w=MainWindow(s,demo=True)
    w.timer.stop();w.startup_worker.stop();w.startup_backup.stop();w.backup_timer.stop();w.show();app.processEvents()
    if args.preview:
        return app.exec()
    output=ROOT/'docs'/'screenshots';output.mkdir(exist_ok=True)
    w.grab().save(str(output/'lifecycle-dashboard-v12.png'))
    for job_id,name in [(3,'third-party'),(8,'final-qc'),(9,'ready-delivery'),(10,'closed')]:
        d=JobWorkspace(w,job_id);d.show();app.processEvents()
        d.grab().save(str(output/f'lifecycle-{name}-v12.png'));d.close()
    for job_id,kind in [(10,'cards'),(10,'parts'),(11,'warranty')]:
        d=JobWorkspace(w,job_id);tab=next(t for t in d.record_tabs if t.kind==kind);d.tabs.setCurrentWidget(tab.parentWidget().parentWidget());d.show();app.processEvents();d.grab().save(str(output/f'lifecycle-{kind}-v12.png'));d.close()
    documents=Documents(s)
    pdf_dir=ROOT/'runtime'/'pdf-review';pdf_dir.mkdir(exist_ok=True)
    import shutil
    for kind,ident,name in [('intake_receipt',1,'receiving'),('dispatch_manifest',3,'vendor-dispatch'),('dispatch_manifest',4,'service-center-dispatch'),('final_invoice',10,'final-invoice')]:
        shutil.copyfile(documents.generate(kind,ident),pdf_dir/(name+'.pdf'))
    w.navigate('Active Repairs');app.processEvents();w.grab().save(str(output/'lifecycle-active-v12.png'))
    w.pool.waitForDone(10000)
    app.processEvents()
    print(json.dumps({'synthetic_jobs':11,'screenshots':9,'elapsed_seconds':round(time.perf_counter()-start,3)}),flush=True)
    w.hide()


if __name__=='__main__':raise SystemExit(main())
