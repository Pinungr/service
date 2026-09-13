"""Synthetic inventory/custody scenarios and optional offscreen visual evidence.

Refuses to reuse a populated directory: no production records are read or edited.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data-dir',default='runtime/inventory-v14-demo');parser.add_argument('--verify-ui',action='store_true');args=parser.parse_args()
    root=Path(args.data_dir).resolve()
    if (root/'shop.db').exists():raise SystemExit('Use a new empty synthetic data directory.')
    if args.verify_ui:os.environ['QT_QPA_PLATFORM']='offscreen'
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QImage,QColor,QFontDatabase,QFont
    from PyQt6.QtCore import QTimer
    from repairshop.persistence import Database
    from repairshop.services import Service
    from repairshop.customer_records import CustomerRecords
    from repairshop.inventory import Inventory
    from repairshop.parts import Parts
    from repairshop.costing import JobCosts
    from repairshop.lifecycle import Lifecycle
    from repairshop.warranties import Warranties
    from repairshop.job_cards import JobCards
    from repairshop.ui import MainWindow
    from repairshop.lifecycle_ui import JobWorkspace
    from repairshop.inventory_ui import InventoryPage
    from repairshop.ui_widgets import STYLE
    app=QApplication([])
    for font in ('segoeui.ttf','segoeuib.ttf','segoeuil.ttf','seguisb.ttf'):QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+font)
    app.setFont(QFont('Segoe UI',10));app.setStyleSheet(STYLE)
    s=Service(Database(root));s.setup('Synthetic Repair Shop','demo','DemoShop2026!')
    customer=s.save_customer('Demo Customer','9990006677')
    photo=QImage(64,64,QImage.Format.Format_RGB32);photo.fill(QColor('#68a398'));CustomerRecords(s).save_photo(photo,customer)
    life=Lifecycle(s);inv=Inventory(s);parts=Parts(s);cards=JobCards(s)
    vendor=s.save_master('vendor','Demo Laptop Service');supplier=s.save_master('supplier','Demo Parts Supply')
    battery=inv.save(dict(name='Dell Battery 54Wh',sku='BAT-DELL-001',brand='Dell',compatibility='Inspiron 15 / 54Wh compatible units',purchase_cost=250000,customer_price=320000,
        supplier_id=supplier,invoice='SYN-INV-001',storage='Shelf B / Bin 2',minimum_stock=2,warranty_duration=6,warranty_unit='months',warranty_provider='Synthetic Repair Shop'))
    inv.adjust(battery,5,'SYN-INV-001')
    for name,sku,cost,price,qty in [('8GB DDR4 RAM','RAM-8G',180000,240000,2),('Laptop cooling fan','FAN-001',40000,70000,1),('USB-C connector','USB-C-001',10000,20000,0)]:
        item=inv.save(dict(name=name,sku=sku,purchase_cost=cost,customer_price=price,minimum_stock=2))
        if qty:inv.adjust(item,qty,'SYN-STOCK-001')
    window=MainWindow(s,demo=True)
    for timer in window.findChildren(QTimer):timer.stop()
    shots=Path('docs/screenshots');shots.mkdir(exist_ok=True,parents=True)
    pdfs=Path('runtime/pdf-review/inventory-v14');pdfs.mkdir(exist_ok=True,parents=True)
    def shot(job,name,tab=None):
        if not args.verify_ui:return
        dialog=JobWorkspace(window,job)
        if tab:
            for i in range(dialog.tabs.count()):
                if dialog.tabs.tabText(i)==tab:dialog.tabs.setCurrentIndex(i)
        dialog.show();app.processEvents();dialog.grab().save(str(shots/name));dialog.close()
    def start(name):
        job=s.intake(customer,name,'Power / charging problem',guided=True,damage='Light wear; casing intact')
        life.execute(job,'inspect');life.execute(job,'inspection_done',dict(notes='Original fault reproduced; condition checked'))
        return job
    def choose(job,kind):
        life.execute(job,'verify_warranty',dict(warranty_status='out_of_warranty',notes='Manufacturer warranty not applicable'))
        life.execute(job,'select_route',dict(route=kind,confirmed=True,contact_id=vendor if kind=='third_party' else None,technician_id=s.user['id']))
    def handover(job,action,**extra):life.execute(job,action,dict(counterparty='Demo receiver',condition='Intact',acknowledgment='SYN-ACK',**extra))
    job=start('Demo Inspiron laptop');choose(job,'third_party')
    life.execute(job,'prepare_dispatch',dict(items=[h['id'] for h in life.holdings(job)],consent=True,condition='Intact'))
    handover(job,'dispatch',carrier='Demo Courier');shot(job,'inventory-courier-v14.png')
    shutil.copyfile(cards.print(cards.rows(job)[-1]['id']),pdfs/'courier-handover.pdf')
    handover(job,'arrive');life.execute(job,'diagnose',dict(notes='Battery failure confirmed',repairable=True,parts='Dell Battery',parts_available=True))
    part=parts.save(job,dict(source='stock',inventory_id=battery,requested_by='Demo Laptop Service',request_notes='Vendor requested compatible battery'))
    inv.transfer(part,'reserve','SYN-RESERVE');inv.transfer(part,'issue','Vendor signed SYN-PART-1')
    shutil.copyfile(cards.print(cards.rows(job)[-1]['id']),pdfs/'part-issue.pdf')
    JobCosts(s).save(job,dict(vendor_labour=80000,transport_cost=20000,vendor_invoice='SYN-V-100'),'Vendor budget received')
    quote=s.issue_quote(job,'Replace battery and repair charging',[dict(description='Repair labour',amount=150000)])
    s.decide_quote(quote,'approved','Demo Customer','in_person','Synthetic approval')
    shot(job,'inventory-parts-v14.png','Parts');shot(job,'inventory-costing-v14.png','Internal costing')
    life.execute(job,'start_repair');parts.install(part,'Demo Laptop Service');life.execute(job,'complete_repair',dict(notes='Battery installed and charging verified'))
    handover(job,'return_dispatch',carrier='Demo Return Courier');shot(job,'inventory-return-transit-v14.png')
    handover(job,'receive',repair_result='REPAIRED',vendor_invoice='SYN-V-100')
    card=cards.rows(job)[-1]
    shutil.copyfile(cards.print(card['id']),pdfs/'third-party-return.pdf');shutil.copyfile(cards.print(card['id'],internal=True),pdfs/'third-party-return-internal.pdf')
    shot(job,'inventory-return-cards-v14.png','Job Cards')
    inhouse=start('Demo in-house laptop');choose(inhouse,'in_house');shot(inhouse,'inventory-assignment-v14.png')
    handover(inhouse,'hand_technician',bench='Bench 2');shot(inhouse,'inventory-technician-v14.png')
    manual=start('Demo historical warranty device')
    Warranties(s).manual_check(manual,'VALID','Warranty slip','SYN-OLD-SLIP','Synthetic Repair Shop','shop_part','Printed historical slip checked; no original database entry exists')
    shot(manual,'inventory-manual-warranty-v14.png','Warranty')
    if args.verify_ui:
        page=InventoryPage(window);page.resize(1320,750);page.show();app.processEvents();page.grab().save(str(shots/'inventory-dashboard-v14.png'));page.close()
    (root/'scenarios.json').write_text(json.dumps(dict(third_party=job,in_house=inhouse,manual_warranty=manual),indent=2))
    window.pool.waitForDone();window.close()
    print('Synthetic inventory scenarios created at '+str(root))


if __name__=='__main__':main()
