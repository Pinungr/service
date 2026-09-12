from concurrent.futures import ThreadPoolExecutor
from datetime import date
import json
from pathlib import Path
import sqlite3
import zipfile
import pytest
from repairshop.domain import RuleError, money
from repairshop.persistence import Database, SCHEMA_VERSION
from repairshop.services import Service
from repairshop.queries import Queries
from repairshop.backup import Backups
from repairshop.documents import Documents, safe_cell
from repairshop.messaging import Outbox, Uncertain, Retryable


def item(s, job, name="ThinkPad T14"):
    return s.db.one("SELECT * FROM items WHERE job_id=? AND description=?", (job,name))["id"]


def test_reusable_normalized_directories_restart(service):
    a = service.save_master("service", "  Laptop   repair ")
    b = service.save_master("service", "LAPTOP repair")
    assert a == b
    cat = service.masters("category")[0]["id"]
    accessory = service.save_master("accessory", "Carry case", category_id=cat)
    vendor = service.save_master("vendor", "Vendor Test")
    again = Service(Database(service.db.root))
    again.login("owner", "CorrectHorse123!")
    assert vendor in [r["id"] for r in again.masters("vendor")]
    assert again.db.one("SELECT * FROM category_accessories WHERE accessory_id=?", (accessory,))


def test_shared_phone_does_not_merge_customers(service, customer):
    other = service.save_customer("Different Owner", "9990000001")
    assert other != customer


def test_device_only_dispatch_accessories_remain(service, job):
    ident = item(service, job)
    move = service.move(ident, 1, "shop:Front desk", "vendor:Test", "Vendor Test", "dispatch-one")
    assert service.move(ident, 1, "shop:Front desk", "vendor:Test", "Vendor Test", "dispatch-one") == move
    with pytest.raises(RuleError, match="unavailable"):
        service.move(ident, 1, "shop:Front desk", "vendor:Test", "Vendor Test", "dispatch-two")
    assert service.db.one("SELECT quantity FROM holdings WHERE item_id=? AND location='shop:Front desk'", (item(service,job,"Adapter"),))["quantity"] == 1


def test_partial_custody_conservation_and_closure(service, job):
    ident = item(service,job,"Mouse")
    service.move(ident,1,"shop:Front desk","transit:Courier","Courier","m1")
    service.move(ident,1,"transit:Courier","vendor:Test","Vendor","m2")
    with pytest.raises(RuleError):
        service.move(ident,2,"vendor:Test","shop:Front desk","Counter","m3")
    assert service.db.one("SELECT sum(quantity) n FROM holdings WHERE item_id=?",(ident,))["n"] == 2
    service.stage(job,"ready_unrepaired",reason="Checked; customer declined")
    with pytest.raises(RuleError,match="every"):
        service.stage(job,"closed")


def test_assignments_do_not_move_and_keep_vendor_charges(service, job):
    a=service.save_master("vendor","Vendor A")
    b=service.save_master("vendor","Vendor B")
    service.assign(job,"third_party",a)
    service.record_work(job,"diagnosis",{"notes":"First findings"})
    service.post("vendor",a,"charge",10000,"bill-a",job_id=job)
    service.assign(job,"third_party",b)
    service.post("vendor",b,"charge",20000,"bill-b",job_id=job)
    assert len(service.db.rows("SELECT * FROM assignments WHERE job_id=?",(job,))) == 2
    assert service.db.one("SELECT sum(amount) n FROM entries WHERE job_id=?",(job,))["n"] == 30000
    assert service.db.one("SELECT location FROM holdings WHERE item_id=? AND quantity>0",(item(service,job),))["location"].startswith("shop:")


def test_owner_submitter_dedup_and_no_cost_leak(service, customer):
    other=service.save_customer("Submitter", "9990000001","synthetic@example.invalid",whatsapp_consent=True,email_consent=True)
    job=service.intake(customer,"Laptop","Fault",submitter="Submitter",relationship="Sibling",update_contact_id=other)
    messages=service.db.rows("SELECT * FROM outbox WHERE job_id=?",(job,))
    assert len(messages)==2
    assert all("vendor" not in r["payload"].lower() for r in messages)


def test_warranty_date_pending_decision_rejection(service, customer):
    sale=service.save_sale(customer,"Laptop",serial="ABC",warranty_start="2020-01-01",warranty_end="2099-01-01")
    job=service.intake(customer,"Laptop","Fault",sale_id=sale)
    service.record_warranty(job,"pending")
    row=service.db.one("SELECT * FROM warranty WHERE job_id=?",(job,))
    assert row["eligibility"]=="in_date" and row["decision"]=="pending"
    service.record_warranty(job,"rejected",findings="Physical damage reported by centre")
    assert service.db.one("SELECT count(*) n FROM warranty WHERE job_id=?",(job,))["n"]==2


def test_accepted_warranty_retains_transport(service, customer):
    job=service.intake(customer,"Laptop","Fault",transport_agreed=45000,policy="AGREED_TRANSPORT_ONLY")
    service.record_warranty(job,"accepted",covered="Mainboard repair")
    service.stage(job,"under_repair")
    assert service.job(job)["transport_agreed"]==45000


def test_replacement_preserves_serial_and_terms(service, job):
    old=item(service,job)
    new=service.replacement(old,"Replacement ThinkPad","NEW123","shop:Front desk","Only remaining original warranty","Centre RMA #123")
    assert service.db.one("SELECT replaces_id FROM items WHERE id=?",(new,))["replaces_id"]==old
    assert "remaining original warranty" in service.db.one("SELECT payload FROM audit WHERE action='replacement_received'")["payload"]


def test_quote_version_approval_deposit_and_revision(service, customer):
    job=service.intake(customer,"Laptop","Fault",deposit=50000)
    q=service.issue_quote(job,"Repair board",[{"description":"Labour","amount":100000}])
    service.decide_quote(q,"approved","Owner","call")
    with pytest.raises(RuleError,match="deposit"):
        service.stage(job,"under_repair")
    service.post("customer",customer,"receipt",50000,"deposit",job_id=job)
    service.stage(job,"under_repair")
    q2=service.issue_quote(job,"Board plus display",[{"description":"Repair","amount":200000}])
    with pytest.raises(RuleError,match="current"):
        service.stage(job,"under_repair")
    with pytest.raises(RuleError):
        service.decide_quote(q,"approved","Owner","call")
    assert service.db.one("SELECT state FROM quotes WHERE id=?",(q2,))["state"]=="issued"


def test_no_deposit_required_and_immutable_quote(service, job):
    q=service.issue_quote(job,"Repair",[{"description":"Repair","amount":10000}])
    service.decide_quote(q,"approved","Owner","in_person")
    service.stage(job,"under_repair")
    with pytest.raises(sqlite3.IntegrityError):
        with service.db.transaction() as c:
            c.execute("UPDATE quotes SET total=20000 WHERE id=?",(q,))


@pytest.mark.parametrize("policy,expected",[("NO_CUSTOMER_CHARGE",-10000),("AGREED_TRANSPORT_ONLY",15000)])
def test_decline_policy_snapshot_and_refund_due(service, customer, policy, expected):
    job=service.intake(customer,"Laptop","Fault",policy=policy,transport_agreed=25000,advance=10000)
    service.settings({"decline_policy":"AGREED_TRANSPORT_ONLY" if policy=="NO_CUSTOMER_CHARGE" else "NO_CUSTOMER_CHARGE"})
    assert service.decline_balance(job)["balance_due"]==expected
    assert not service.db.one("SELECT * FROM entries WHERE kind='refund'")


def test_external_completion_not_collection_ready(service, job):
    ident=item(service,job)
    service.move(ident,1,"shop:Front desk","vendor:Test","Vendor","send")
    service.stage(job,"awaiting_return")
    message=service.db.one("SELECT payload FROM outbox WHERE event='awaiting_return'")
    assert "awaiting return" in message["payload"]
    with pytest.raises(RuleError,match="physically"):
        service.stage(job,"ready_repaired",test_result="passed")
    service.move(ident,1,"vendor:Test","shop:Front desk","Counter","receive")
    with pytest.raises(RuleError,match="passed"):
        service.stage(job,"ready_repaired")
    service.stage(job,"ready_repaired",test_result="passed")


def test_unrepaired_collection_without_false_test(service, job):
    service.stage(job,"ready_unrepaired",reason="Unrepairable; checked on return")
    for row in service.db.rows("SELECT * FROM items WHERE job_id=?",(job,)):
        service.move(row["id"],row["quantity"],"shop:Front desk","customer","Owner",f"collect-{row['id']}",acknowledgment="Signed")
    service.stage(job,"collected")
    service.stage(job,"closed")
    assert service.job(job)["test_result"]!="passed"


def test_financial_rounding_duplicate_and_refund(service, customer, job):
    assert money("0.105")==11 and money("12.345")==1235
    with pytest.raises(RuleError):
        money(0.1)
    a=service.post("customer",customer,"receipt",10000,"same",job_id=job)
    assert service.post("customer",customer,"receipt",10000,"same",job_id=job)==a
    with pytest.raises(RuleError):
        service.post("customer",customer,"receipt",20000,"same",job_id=job)
    service.post("customer",customer,"refund",2500,"refund",job_id=job)
    assert Queries(service).ledger("customer",customer,"2000-01-01","2099-01-01")["closing"]==-7500


def test_vendor_3553_to_3550_monthly_settlement(service, job):
    vendor=service.save_master("vendor","Settlement Vendor")
    service.post("vendor",vendor,"opening",50000,"opening",posted="2026-08-31",notes="Verified opening from signed prior statement")
    a=service.post("vendor",vendor,"charge",125000,"a",job_id=job,posted="2026-09-01")
    b=service.post("vendor",vendor,"charge",180300,"b",job_id=job,posted="2026-09-02")
    service.post("vendor",vendor,"adjustment",-300,"roundoff",posted="2026-09-03",notes="Vendor agreed INR 3 settlement reduction")
    service.post("vendor",vendor,"payment",355000,"pay",posted="2026-09-03",allocations=[(a,125000),(b,180300)])
    ledger=Queries(service).ledger("vendor",vendor,"2026-09-01","2026-09-30")
    assert ledger["opening"]==50000 and ledger["closing"]==0
    assert Queries(service).ledger("vendor",vendor,"2026-10-01","2026-10-31")["opening"]==0
    service.post("vendor",vendor,"refund",10000,"later-refund",posted="2026-10-02")
    assert Queries(service).ledger("vendor",vendor,"2026-10-01","2026-10-31")["closing"]==10000


def test_overallocation_rolls_back_entire_post(service):
    vendor=service.save_master("vendor","Vendor")
    charge=service.post("vendor",vendor,"charge",10000,"charge")
    with pytest.raises(RuleError):
        service.post("vendor",vendor,"payment",10000,"bad",allocations=[(charge,11000)])
    assert not service.db.one("SELECT * FROM entries WHERE operation_id='bad'")


def test_collection_does_not_settle_debts(service, customer, job):
    v=service.save_master("vendor","Vendor")
    service.post("vendor",v,"charge",10000,"v",job_id=job)
    q=service.issue_quote(job,"Repair",[{"description":"Repair","amount":20000}])
    service.decide_quote(q,"approved","Owner","call")
    service.invoice(q,"invoice")
    service.stage(job,"ready_unrepaired",reason="Returned without repair")
    for r in service.db.rows("SELECT * FROM items WHERE job_id=?",(job,)):
        service.move(r["id"],r["quantity"],"shop:Front desk","customer","Owner",f"c{r['id']}",acknowledgment="Signed")
    service.stage(job,"closed")
    assert Queries(service).account_balances("vendor")[0]["balance"]==10000
    assert Queries(service).account_balances("customer")[0]["balance"]==20000


def test_shared_transport_and_included_cost_not_double_counted(service,customer,job):
    other=service.intake(customer,"Printer","Paper jam")
    service.expense(10000,{job:4000,other:6000},"transport","Shop","T1",{},"transport")
    with pytest.raises(RuleError):
        service.expense(10000,{job:10000,other:10000},"transport","Shop","T2",{},"bad")
    vendor=service.save_master("vendor","Vendor")
    charge=service.post("vendor",vendor,"charge",50000,"charge",job_id=job)
    service.expense(10000,{job:10000},"part","Vendor","Part",{},"part",included_entry_id=charge)
    rows=Queries(service).report("margins","2000-01-01","2099-01-01")
    assert sum(r["costs"] for r in rows)==60000


def test_offline_outbox_survives_restart_and_consent(service,customer,job):
    service.save_customer("Synthetic Customer","9990000001","synthetic@example.invalid",ident=customer)
    other=Service(Database(service.db.root))
    other.login("owner","CorrectHorse123!")
    worker=Outbox(other)
    while worker.process_one():
        pass
    assert all(r["state"]=="blocked_consent" for r in service.db.rows("SELECT * FROM outbox"))


def test_obsolete_quote_and_pickup_are_cancelled(service,job):
    q=service.issue_quote(job,"First",[{"description":"Repair","amount":10000}])
    service.issue_quote(job,"Revised",[{"description":"Repair","amount":20000}])
    worker=Outbox(service)
    while worker.process_one():
        pass
    assert service.db.one("SELECT state FROM outbox WHERE quote_id=?",(q,))["state"]=="cancelled"


def test_workers_claim_once_and_ambiguous_outcome(service,job):
    class Adapter:
        def __init__(self): self.calls=0
        def send(self,row,payload):
            self.calls+=1
            raise Uncertain("Ambiguous response")
    adapter=Adapter()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: Outbox(service,{"email":adapter,"whatsapp":adapter}).process_one(), range(2)))
    assert adapter.calls==2
    assert all(r["state"]=="uncertain" for r in service.db.rows("SELECT * FROM outbox"))
    with pytest.raises(RuleError):
        Outbox(service).action(1,"retry")


def test_dashboard_units_not_movement_rows(service,job):
    ident=item(service,job)
    service.move(ident,1,"shop:Front desk","vendor:Test","Vendor","s")
    service.move(ident,1,"vendor:Test","shop:Front desk","Counter","r")
    data=Queries(service).dashboard()
    counts={(r["location"],r["type"]):r["units"] for r in data["locations"]}
    assert counts[("shop","device")]==1 and counts[("shop","accessory")]==3


def test_backup_restore_attachments_balances_and_readonly(service,customer,job,tmp_path):
    source=tmp_path/"proof ü.txt"
    source.write_text("Evidence",encoding="utf-8")
    Documents(service).attach(source,"Evidence",job_id=job)
    service.post("customer",customer,"receipt",10000,"advance",job_id=job)
    backup=Backups(service)
    path=backup.create("archive")
    manifest=backup.validate(path)
    assert manifest["jobs"]==1
    view=backup.open_view(path)
    with pytest.raises(RuleError):
        with view.transaction(): pass
    assert view.one("SELECT sum(amount) n FROM entries")["n"]==-10000
    service.save_customer("After backup")
    with pytest.raises(RuleError):
        backup.restore(path,"yes")
    recovery=backup.restore(path,"RESTORE")
    assert recovery.is_dir()
    restored=Database(service.db.root)
    assert restored.one("SELECT count(*) n FROM customers")["n"]==1
    assert restored.setting("notifications_paused") is True
    assert restored.one("SELECT state FROM outbox")["state"]=="review_after_restore"
    assert (restored.root / restored.one("SELECT path FROM attachments WHERE title='Evidence'")["path"]).read_text()=="Evidence"


def test_missing_external_drive_preserves_local_backup(service,tmp_path):
    service.settings({"external_backup":str(tmp_path/"absent-drive")})
    archive=Backups(service).create()
    assert archive.is_file()
    assert service.db.one("SELECT external_state FROM backups")["external_state"]=="pending_missing_drive"


@pytest.mark.parametrize("failure",["checksum","missing","traversal","new_schema"])
def test_corrupt_archive_rejected_without_touching_live(service,job,tmp_path,failure):
    source=Backups(service).create()
    bad=tmp_path/"corrupt.zip"
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(bad,"w") as dst:
        for name in src.namelist():
            data=src.read(name)
            if failure=="missing" and name=="shop.db": continue
            if failure=="checksum" and name=="shop.db": data+=b"broken"
            if failure=="new_schema" and name=="manifest.json":
                m=json.loads(data);m["schema"]=999;data=json.dumps(m)
            dst.writestr(name,data)
        if failure=="traversal": dst.writestr("../evil.txt","bad")
    with pytest.raises((RuleError,sqlite3.DatabaseError)):
        Backups.validate(bad)
    assert service.job(job)["id"]==job and source.is_file()


def test_failed_backup_preserves_last_good(service,job,tmp_path,monkeypatch):
    good=Backups(service).create()
    def fail(*args,**kwargs): raise OSError("disk full")
    monkeypatch.setattr(zipfile.ZipFile,"write",fail)
    with pytest.raises(OSError,match="disk full"):
        Backups(service).create()
    assert good.exists()
    assert service.db.one("SELECT state FROM backups ORDER BY id DESC LIMIT 1")["state"]=="failed"


def test_upgrade_preserves_history(service,customer,job,tmp_path):
    from repairshop.persistence import SCHEMA
    import shutil
    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    shutil.copytree(service.db.root / 'Customers', legacy / 'Customers')
    c = sqlite3.connect(legacy / 'shop.db')
    try:
        c.executescript(SCHEMA)
        c.execute('ATTACH DATABASE ? AS original', (str(service.db.path),))
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            columns = ','.join(r[1] for r in c.execute(f'PRAGMA table_info({table})'))
            c.execute(f'INSERT INTO main.{table}({columns}) SELECT {columns} FROM original.{table}')
        c.execute('PRAGMA user_version=1')
        c.commit()
    finally:
        c.close()
    db = Database(legacy)
    assert db.one('SELECT id FROM customers WHERE id=?', (customer,))
    assert db.one('PRAGMA user_version')['user_version'] == SCHEMA_VERSION
    assert db.one('SELECT device_id,photo_id FROM jobs WHERE id=?', (job,))['photo_id'] is None
    archives = list((db.root / 'backups').glob('*pre-upgrade-v1*.zip'))
    assert len(archives) == 1 and Backups.validate(archives[0])['schema'] == 1
    assert Database(legacy).one('SELECT count(*) n FROM devices')['n'] == 1


def test_limited_role_service_guards(service,customer,job):
    service.save_staff("tech","Technician","technician","Technician123!")
    service.login("tech","Technician123!")
    with pytest.raises(RuleError): service.post("customer",customer,"receipt",10000,"forbidden")
    with pytest.raises(RuleError): service.settings({"shop_name":"Forbidden"})
    with pytest.raises(RuleError): service.record_work(job,"repair",{"notes":"Not assigned"})
    with pytest.raises(RuleError): Backups(service).restore("nothing","RESTORE")


def test_stale_job_edit_rejected(service,job):
    version=service.job(job)["version"]
    service.record_work(job,"diagnosis",{"notes":"New findings"})
    with pytest.raises(RuleError,match="changed"):
        service.stage(job,"diagnosis",version=version)


def test_documents_exports_and_formula_injection(service,job,tmp_path):
    docs=Documents(service)
    output=docs.generate("intake_receipt",job)
    assert output.read_bytes().startswith(b"%PDF")
    rows=[{"name":"=HYPERLINK(\"x\")","notes":"@cmd","amount":12345}]
    csv=docs.export(tmp_path/"report.csv","Report",rows)
    assert "'=HYPERLINK" in csv.read_text(encoding="utf-8-sig")
    xlsx=docs.export(tmp_path/"report.xlsx","Report",rows)
    from openpyxl import load_workbook
    wb=load_workbook(xlsx)
    assert wb.active["A2"].data_type=="s"
    assert safe_cell("  =1+1").startswith("'")


def test_paid_work_records_cannot_bypass_approval(service,job):
    with pytest.raises(RuleError,match='approved current'):
        service.record_work(job,'repair',{'notes':'Attempt without approval'})


def test_reversed_deposit_no_longer_authorizes_repair(service,customer):
    job=service.intake(customer,'Laptop','Fault',deposit=10000)
    quote=service.issue_quote(job,'Repair',[{'description':'Work','amount':20000}])
    service.decide_quote(quote,'approved','Owner','call')
    receipt=service.post('customer',customer,'receipt',10000,'deposit',job_id=job)
    service.reverse(receipt,'Receipt entered against wrong account','undo')
    with pytest.raises(RuleError,match='deposit'):
        service.stage(job,'under_repair')


def test_reversed_payment_releases_allocation(service):
    vendor=service.save_master('vendor','Vendor')
    charge=service.post('vendor',vendor,'charge',10000,'charge')
    payment=service.post('vendor',vendor,'payment',10000,'pay',allocations=[(charge,10000)])
    service.reverse(payment,'Wrong bank reference; payment not made','reverse')
    service.post('vendor',vendor,'payment',10000,'actual',allocations=[(charge,10000)])
    assert Queries(service).ledger('vendor',vendor,'2000-01-01','2099-01-01')['closing']==0


def test_revised_invoice_does_not_double_bill(service,job):
    q=service.issue_quote(job,'Repair',[{'description':'Repair','amount':10000}])
    service.decide_quote(q,'approved','Owner','call')
    invoice=service.invoice(q,'bill')
    q2=service.issue_quote(job,'Revised repair',[{'description':'Repair','amount':20000}])
    service.decide_quote(q2,'approved','Owner','call')
    with pytest.raises(RuleError,match='previous bill'):
        service.invoice(q2,'bill2')
    service.reverse(invoice,'Replaced by revised quotation','reverse-bill')
    service.invoice(q2,'bill2')
    assert service.db.one("SELECT sum(amount) n FROM entries WHERE account_type='customer'")['n']==20000


def test_quote_retains_issued_customer_and_branding(service,customer,job):
    q=service.issue_quote(job,'Repair',[{'description':'Labour','amount':10000}])
    service.save_customer('Changed name',ident=customer)
    service.settings({'shop_name':'Changed branding'})
    snapshot=json.loads(service.db.one('SELECT snapshot FROM quotes WHERE id=?',(q,))['snapshot'])
    assert snapshot['customer']['name']=='Synthetic Customer'
    assert snapshot['shop']['shop_name']=='Test Repair Shop'


def test_intake_operation_duplicate_does_not_create_second_job(service,customer):
    first=service.intake(customer,'Laptop','Fault',operation_id='one-intake')
    assert service.intake(customer,'Laptop','Fault',operation_id='one-intake')==first
    assert service.db.one('SELECT count(*) n FROM jobs')['n']==1


def test_interrupted_restore_rolls_back_on_startup(service,job):
    root=service.db.root
    with service.db.read() as c: c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    recovery=root/'restore-recovery-synthetic'
    old=recovery/'previous';old.mkdir(parents=True)
    import os
    os.replace(root/'shop.db',old/'shop.db')
    os.replace(root/'managed',old/'managed')
    (root/'restore-journal.json').write_text(json.dumps({'recovery':recovery.name}))
    recovered=Database(root)
    assert recovered.one('SELECT id FROM jobs WHERE id=?',(job,))
    assert (recovery/'recovered-journal.json').exists()


def test_reminders_are_bounded_and_stop_after_collection(service,job):
    service.stage(job,'ready_unrepaired',reason='Checked and unrepaired')
    service.dates(job,None,'2020-01-01',None,'Customer postponed collection')
    service.settings({'reminder_days':1})
    worker=Outbox(service)
    worker.schedule_reminders();worker.schedule_reminders()
    assert service.db.one("SELECT count(DISTINCT event_key) n FROM outbox WHERE event='collection_reminder'")['n']==1
    for r in service.db.rows('SELECT * FROM items WHERE job_id=?',(job,)):
        service.move(r['id'],r['quantity'],'shop:Front desk','customer','Owner',f"collect-r{r['id']}",acknowledgment='Signed')
    service.stage(job,'collected')
    while worker.process_one():pass
    assert service.db.one("SELECT state FROM outbox WHERE event='collection_reminder'")['state']=='cancelled'


def test_internal_recipients_and_statement_capture(service,job):
    service.save_recipient('staff',service.user['id'],'email','owner@example.invalid',True)
    service.dates(job,'2026-09-20','2026-09-21',None,'New expected date')
    assert service.db.one("SELECT * FROM outbox WHERE destination='owner@example.invalid'")
    vendor=service.save_master('vendor','Statement Vendor')
    service.save_recipient('vendor',vendor,'email','vendor@example.invalid',True)
    Documents(service).snapshot('Test vendor statement',[('Closing balance','INR 0.00')])
    attachment=service.db.one("SELECT id FROM attachments WHERE title='Test vendor statement'")['id']
    recipient=service.db.one("SELECT id FROM recipients WHERE kind='vendor'")['id']
    service.queue_document(attachment,recipient,'Requested statement','Statement attached','statement-one')
    worker=Outbox(service)
    while worker.process_one():pass
    assert service.db.one("SELECT state FROM outbox WHERE event='statement'")['state']=='captured'


def test_message_template_rejects_unapproved_variables(service):
    with pytest.raises(RuleError,match='Unsupported template'):
        service.settings({'message_template':'{vendor_cost}'})
