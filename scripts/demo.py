"""Reproducible synthetic demo. Refuses to overwrite any existing database."""
import argparse
from datetime import date, timedelta
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from repairshop.persistence import Database
from repairshop.services import Service
from repairshop.documents import Documents
from repairshop.customer_records import CustomerRecords
from PyQt6.QtGui import QImage, QColor


def create(root):
    root=Path(root)
    if (root/"shop.db").exists():
        raise SystemExit("Database already exists; choose a new demo directory. No data was overwritten.")
    s=Service(Database(root))
    s.setup("Circuit Care · Demo Shop","demo","DemoShop2026!","Demo Owner")
    s.settings({"address":"12 Sample Market, Demo City","hours":"Monday–Saturday, 10:00–19:00","messaging_mode":"test"})
    tech=s.save_staff("technician","Maya · Technician","technician","DemoTechnician2026!")
    s.save_staff("counter","Arun · Counter","counter","DemoCounter2026!")
    vendor=s.save_master("vendor","Precision Electronics",contact="Synthetic vendor contact")
    centre=s.save_master("centre","Authorized Care Centre",contact="Synthetic centre contact")
    s.save_master("transporter","Swift Courier",contact="Synthetic transport contact")
    s.save_master("technician","Maya")
    names=["Aditi Shah","Rohan Menon","Meera Nair","Kabir Rao","Nisha Patel","Arjun Sen","Priya Iyer","Sanjay Das","Ananya Roy","Vikram Joshi","Neha Kapoor","Ishaan Verma"]
    devices=["Lenovo ThinkPad T14","HP LaserJet Pro M404","Dell Inspiron 15","Apple MacBook Air M1","Epson EcoTank L3250","Samsung Galaxy A54"]
    faults=["No power; charging light is off","Paper jam and faded prints","Display flickers on battery","Keyboard keys not responding","Printhead cleaning requested","Battery drains rapidly"]
    categories={r["name"]:r["id"] for r in s.masters("category")}
    jobs=[]
    for i in range(24):
        n=i%len(names)
        if i<len(names):
            customer=s.save_customer(names[n],f"999000{n:04d}",f"demo{n}@example.invalid",whatsapp_consent=True,email_consent=True)
            image=QImage(160,160,QImage.Format.Format_RGB32)
            image.fill(QColor('#86b5a4'))
            CustomerRecords(s).save_photo(image,customer)  # Explicit synthetic demo image; no real person.
        else:
            customer=n+1
        idx=i%len(devices)
        cat="Printer" if idx in (1,4) else "Phone" if idx==5 else "Laptop"
        job=s.intake(customer,devices[idx],faults[idx],serial=f"DEMO-{i+1:05d}",category_id=categories[cat],assessment_consent=True,accessories=[dict(description="Adapter",type="accessory",quantity=1)] if cat=="Laptop" else [],repair_due=(date.today()+timedelta(days=i%6-2)).isoformat(),collection_due=(date.today()+timedelta(days=i%8)).isoformat(),transport_agreed=20000,policy="AGREED_TRANSPORT_ONLY")
        jobs.append(job)
        if i%6==0:
            s.assign(job,"in_house",technician_id=tech)
            s.stage(job,"diagnosis")
            s.record_work(job,"diagnosis",{"notes":"Bench inspection booked; checking power supply."})
        elif i%6==1:
            s.assign(job,"third_party",vendor,estimate=95000)
            device=s.db.one("SELECT id FROM items WHERE job_id=? AND type='device'",(job,))["id"]
            s.move(device,1,"shop:Front desk","vendor:Precision Electronics","Precision staff",f"demo-move-{i}",reference=f"PE-{i:04d}")
            s.stage(job,"awaiting_return")
            s.post("vendor",vendor,"charge",95000,f"demo-vendor-{i}",job_id=job,reference=f"PE-{i:04d}")
        elif i%6==2:
            s.assign(job,"warranty_centre",centre)
            device=s.db.one("SELECT id FROM items WHERE job_id=? AND type='device'",(job,))["id"]
            s.move(device,1,"shop:Front desk","centre:Authorized Care Centre","Service centre",f"demo-centre-{i}")
            s.record_warranty(job,"pending",rma=f"RMA-DEMO-{i}",findings="Awaiting centre inspection")
        elif i%6==3:
            quote=s.issue_quote(job,"Replace keyboard and test",[{"description":"Keyboard assembly","amount":240000},{"description":"Labour and testing","amount":60000}])
            if i%2:
                s.decide_quote(quote,"approved",names[n],"call",evidence="Synthetic approval")
                s.invoice(quote,f"demo-invoice-{i}")
                s.post("customer",customer,"receipt",100000,f"demo-advance-{i}",job_id=job,method="UPI",reference="Synthetic receipt")
                s.stage(job,"under_repair")
        elif i%6==4:
            s.stage(job,"ready_repaired",test_result="passed")
        else:
            s.assign(job,"third_party",vendor)
            device=s.db.one("SELECT id FROM items WHERE job_id=? AND type='device'",(job,))["id"]
            s.move(device,1,"shop:Front desk","transit:Swift Courier","Swift Courier",f"demo-transit-{i}",reference=f"TRACK-DEMO-{i}")
    s.save_sale(1,"Lenovo IdeaPad Slim 3",serial="SALE-DEMO-001",invoice_ref="DEMO-SALE-014",sale_date=date.today().isoformat(),amount=4500000,cost=4100000,provider="Manufacturer",warranty_start=date.today().isoformat(),warranty_end=(date.today()+timedelta(days=365)).isoformat(),warranty_terms="Demonstration only")
    Documents(s).generate("intake_receipt",jobs[0])
    print(f"Demo created at {root.resolve()}\nOwner login: demo / DemoShop2026!\nSynthetic data only. Messaging is local test capture.")


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--data-dir",default="demo-data")
    create(p.parse_args().data_dir)
