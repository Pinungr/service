"""Bounded synthetic scale generator and repeatable query measurements."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import platform
from pathlib import Path
import statistics
import sys
from time import perf_counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from repairshop.persistence import Database
from repairshop.services import Service
from repairshop.queries import Queries


def generate(root, customers=60000, jobs=100000):
    if (root/"shop.db").exists():
        raise SystemExit("Refusing to overwrite an existing benchmark database.")
    s=Service(Database(root))
    s.setup("Synthetic Scale Test","benchmark","BenchmarkOnly2026!")
    vendors=[s.save_master("vendor",f"Synthetic Vendor {i:02d}") for i in range(30)]
    start=perf_counter()
    with s.db.transaction() as c:
        for batch in range(0,customers,5000):
            c.executemany("INSERT INTO customers(id,name,phone,email,created) VALUES (?,?,?,?,?)",[(i+1,f"Customer {i+1:06d}",f"+9199{i:08d}",f"synthetic{i}@example.invalid","2021-01-01T00:00:00+00:00") for i in range(batch,min(batch+5000,customers))])
        stages=["diagnosis","awaiting_approval","under_repair","awaiting_return","ready_repaired","closed"]
        for batch in range(0,jobs,5000):
            job_rows=[];items=[];holdings=[];movements=[];quotes=[];entries=[];assignments=[]
            for i in range(batch,min(batch+5000,jobs)):
                ident=i+1; customer=i%customers+1
                timestamp=(datetime(2021,1,1,tzinfo=timezone.utc)+timedelta(days=i%2000)).isoformat()
                stage=stages[i%6]
                location="customer" if stage=="closed" else ["shop:Front desk","vendor:Synthetic Vendor","centre:Synthetic Centre","transit:Synthetic Courier"][i%4]
                job_rows.append((ident,f"REP-{timestamp[:4]}-{ident:06d}",f"VIS-{i//2:06d}",customer,"Laptop model "+str(i%80),f"SER-{ident:08d}","Synthetic fault",timestamp,1,stage,"third_party" if i%2 else "in_house","NO_CUSTOMER_CHARGE",ident,timestamp[:10]))
                assignments.append((ident,ident,"third_party",vendors[i%30],"Scale test",timestamp,1))
                for n in range(2):
                    item_id=i*2+n+1
                    items.append((item_id,ident,"device" if n==0 else "accessory","Laptop" if n==0 else "Adapter",1))
                    holdings.append((item_id,location if n==0 else "customer" if stage=="closed" else "shop:Front desk",1))
                    movements.append((item_id,f"scale-m-{item_id}",item_id,1,"customer",location if n==0 else "shop:Front desk",timestamp,timestamp,1,"Synthetic counterparty"))
                quotes.append((ident,ident,1,"approved","Synthetic repair",'[{"description":"Repair","amount":150000}]',150000,"Synthetic terms",timestamp,1))
                entries.append((i*2+1,f"scale-bill-{i}","vendor",vendors[i%30],ident,"charge",100000,timestamp[:10],timestamp,1))
                entries.append((i*2+2,f"scale-receipt-{i}","customer",customer,ident,"receipt",-50000,timestamp[:10],timestamp,1))
            c.executemany("INSERT INTO jobs(id,number,intake_ref,customer_id,device,serial,complaint,received,actor,stage,route,policy,assignment_id,repair_due) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",job_rows)
            c.executemany("INSERT INTO assignments(id,job_id,route,contact_id,reference,created,actor) VALUES (?,?,?,?,?,?,?)",assignments)
            c.executemany("INSERT INTO items(id,job_id,type,description,quantity) VALUES (?,?,?,?,?)",items)
            c.executemany("INSERT INTO holdings VALUES (?,?,?)",holdings)
            c.executemany("INSERT INTO movements(id,operation_id,item_id,quantity,from_location,to_location,happened,recorded,actor,counterparty) VALUES (?,?,?,?,?,?,?,?,?,?)",movements)
            c.executemany("INSERT INTO quotes(id,job_id,version,state,scope,lines,total,terms,created,actor) VALUES (?,?,?,?,?,?,?,?,?,?)",quotes)
            c.executemany("INSERT INTO entries(id,operation_id,account_type,account_id,job_id,kind,amount,posted,created,actor) VALUES (?,?,?,?,?,?,?,?,?,?)",entries)
    with s.db.read() as c:
        c.execute("ANALYZE")
    print(f"Generated {customers:,} customers, {jobs:,} jobs in {perf_counter()-start:.2f}s",flush=True)


def measure(root, output):
    startup=[]
    for _ in range(12):
        begin=perf_counter(); db=Database(root); startup.append(perf_counter()-begin); db.engine.dispose()
    s=Service(Database(root));s.login("benchmark","BenchmarkOnly2026!");q=Queries(s)
    vendor=s.masters("vendor")[0]["id"]
    tests={"database_startup":None,"first_page_jobs":lambda:q.jobs(),"customer_search":lambda:q.customers("Customer 054"),"job_search_serial":lambda:q.jobs("SER-000999"),"dashboard":q.dashboard,"vendor_monthly_ledger":lambda:q.ledger("vendor",vendor,"2025-01-01","2025-01-31")}
    timings={}
    for name,fn in tests.items():
        samples=startup[:] if fn is None else []
        if fn:
            for _ in range(12):
                begin=perf_counter();fn();samples.append(perf_counter()-begin)
        timings[name]={"p50_ms":round(statistics.median(samples)*1000,2),"p95_ms":round(sorted(samples)[int((len(samples)-1)*.95)]*1000,2),"samples":len(samples)}
    result={"generated_at":datetime.now(timezone.utc).isoformat(),"platform":platform.platform(),"python":platform.python_version(),"processor":platform.processor(),"dataset":{table:s.db.one(f"SELECT count(*) n FROM {table}")["n"] for table in ("customers","jobs","items","movements","quotes","entries")},"database_bytes":s.db.path.stat().st_size,"attachments":"None; bounded synthetic load", "timings":timings,"notes":"Repeated local SSD queries; p95 is the observed lower rank of 12 samples. DB startup excludes login hashing and Qt UI construction."}
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    Path(output).write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--data-dir",default="benchmark-data");p.add_argument("--generate",action="store_true");p.add_argument("--output",default="docs/benchmark-results.json")
    args=p.parse_args();root=Path(args.data_dir).resolve()
    if args.generate:generate(root)
    measure(root,args.output)
