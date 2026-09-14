from datetime import date
from .domain import RuleError


class Queries:
    def __init__(self, service):
        self.s = service
        self.db = service.db

    def customers(self, search="", offset=0):
        self.s.require()
        return self.db.rows("SELECT id,name,phone,email,address FROM customers WHERE name LIKE ? OR phone LIKE ? OR alternate LIKE ? ORDER BY name LIMIT 50 OFFSET ?", ("%" + search + "%", "%" + search + "%", "%" + search + "%", offset))

    def jobs(self, search="", stage="", route="", location="", offset=0, customer_id=None, category_id=None, assignment=None, start=None, end=None, overdue=False):
        self.s.require()
        where, args = ["1=1"], []
        if search:
            where.append("(j.number LIKE ? OR j.serial LIKE ? OR c.name LIKE ? OR c.phone LIKE ? OR j.device LIKE ?)")
            args.extend(["%" + search + "%"] * 5)
        for key, value in (("j.stage", stage), ("j.route", route), ("j.customer_id", customer_id), ("j.category_id", category_id), ("a.contact_id", assignment)):
            if value:
                where.append(key + "=?")
                args.append(value)
        if location:
            where.append("j.stage NOT IN ('collected','closed') AND EXISTS(SELECT 1 FROM items i JOIN holdings h ON i.id=h.item_id WHERE i.job_id=j.id AND i.type='device' AND h.quantity>0 AND h.location LIKE ?)")
            args.append(location + "%")
        if start:
            where.append("j.received>=?")
            args.append(start)
        if end:
            where.append("j.received<?")
            args.append(end + "T99")
        if overdue:
            where.append("j.stage NOT IN ('collected','closed') AND (j.repair_due<? OR j.collection_due<? OR j.return_due<?)")
            args.extend([date.today().isoformat()] * 3)
        args.append(offset)
        return self.db.rows("""SELECT j.id,j.number,c.name AS customer,c.phone,j.device,j.serial,j.stage,j.route,
            COALESCE(m.name,u.name,'Unassigned') AS responsible,j.repair_due,j.collection_due,j.return_due,
            (SELECT group_concat(h.location || ' (' || h.quantity || ')', ', ') FROM items i JOIN holdings h ON h.item_id=i.id WHERE i.job_id=j.id AND i.type='device' AND h.quantity>0) AS custody,
            (SELECT COALESCE(sum(e.amount),0) FROM entries e WHERE e.job_id=j.id AND e.account_type='customer') AS balance,
            (SELECT state FROM outbox o WHERE o.job_id=j.id ORDER BY o.id DESC LIMIT 1) AS message
            FROM jobs j JOIN customers c ON c.id=j.customer_id LEFT JOIN assignments a ON a.id=j.assignment_id LEFT JOIN masters m ON m.id=a.contact_id LEFT JOIN users u ON u.id=a.technician_id WHERE """ + " AND ".join(where) + " ORDER BY j.id DESC LIMIT 50 OFFSET ?", args)

    def dashboard(self):
        self.s.require()
        locations = self.db.rows("""SELECT CASE WHEN instr(h.location,':')>0 THEN substr(h.location,1,instr(h.location,':')-1) ELSE h.location END AS location,i.type,sum(h.quantity) AS units FROM holdings h JOIN items i ON i.id=h.item_id JOIN jobs j ON j.id=i.job_id WHERE h.quantity>0 AND j.stage NOT IN ('collected','closed') AND h.location!='customer' AND h.location NOT LIKE 'exception:%' GROUP BY location,i.type""")
        stages = self.db.rows("SELECT stage,count(*) AS jobs FROM jobs WHERE stage NOT IN ('collected','closed') GROUP BY stage")
        balances = self.db.rows("SELECT account_type,sum(amount) AS balance FROM entries GROUP BY account_type") if self.s.user["role"] == "owner" else []
        messages = self.db.rows("SELECT state,count(*) AS messages FROM outbox WHERE state NOT IN ('accepted','captured','cancelled','delivered','read') GROUP BY state")
        overdue = self.db.one("SELECT count(*) AS n FROM jobs WHERE stage NOT IN ('collected','closed') AND (repair_due<? OR collection_due<? OR return_due<?)", (date.today().isoformat(),) * 3)["n"]
        return dict(locations=locations, stages=stages, balances=balances, messages=messages, overdue=overdue, sales=self.db.one("SELECT count(*) AS n FROM sales WHERE collected=0")["n"], backup=self.db.one("SELECT * FROM backups WHERE state='verified' ORDER BY id DESC LIMIT 1"))

    def ledger(self, account_type, account_id, start, end):
        self.s.require("owner", "counter")
        if account_type == "vendor":
            self.s.require("owner")
        opening = self.db.one("SELECT COALESCE(sum(amount),0) AS n FROM entries WHERE account_type=? AND account_id=? AND posted<?", (account_type, account_id, start))["n"]
        rows = self.db.rows("""SELECT e.id,e.posted,e.kind,e.amount,e.method,e.reference,e.notes,e.job_id,j.number,j.device,j.received AS job_received,
            (SELECT group_concat(json_extract(w.payload,'$.notes'),'; ') FROM work w WHERE w.job_id=j.id AND w.kind='repair') AS work,
            CASE WHEN EXISTS(SELECT 1 FROM entries rev WHERE rev.reverses_id=e.id) THEN 0 ELSE abs(e.amount)-COALESCE((SELECT sum(a.amount) FROM allocations a WHERE a.payment_id=e.id AND NOT EXISTS(SELECT 1 FROM allocation_reversals ar WHERE ar.allocation_id=a.id)),0) END AS unapplied
            FROM entries e LEFT JOIN jobs j ON j.id=e.job_id WHERE e.account_type=? AND e.account_id=? AND e.posted>=? AND e.posted<=? ORDER BY e.posted,e.id""", (account_type, account_id, start, end))
        balance = opening
        for row in rows:
            balance += row["amount"]
            row["running_balance"] = balance
            if row["kind"] not in ("receipt", "payment"):
                row["unapplied"] = None
        return dict(opening=opening, closing=balance, rows=rows)

    def account_balances(self, account_type):
        self.s.require("owner")
        table = "customers" if account_type == "customer" else "masters"
        return self.db.rows(f"SELECT e.account_id,p.name,sum(e.amount) AS balance FROM entries e JOIN {table} p ON p.id=e.account_id WHERE e.account_type=? GROUP BY e.account_id,p.name ORDER BY p.name", (account_type,))

    def history(self, job_id):
        self.s.require()
        result = {}
        for table in ("items", "assignments", "work", "warranty", "quotes", "attachments", "outbox"):
            result[table] = self.db.rows(f"SELECT * FROM {table} WHERE job_id=? ORDER BY id DESC", (job_id,))
        if self.s.user["role"] == "owner":
            result["entries"] = self.db.rows("SELECT * FROM entries WHERE job_id=? ORDER BY id DESC", (job_id,))
            result["expenses"] = self.db.rows("SELECT e.*,a.amount AS allocated FROM expenses e JOIN expense_allocations a ON a.expense_id=e.id WHERE a.job_id=?", (job_id,))
        else:
            for assignment in result["assignments"]:
                assignment.pop("estimate", None)
        result["holdings"] = self.db.rows("SELECT i.id,i.type,i.description,i.serial,h.location,h.quantity FROM items i JOIN holdings h ON i.id=h.item_id WHERE i.job_id=? AND h.quantity>0", (job_id,))
        result["movements"] = self.db.rows("SELECT m.* FROM movements m JOIN items i ON i.id=m.item_id WHERE i.job_id=? ORDER BY m.id DESC", (job_id,))
        result["audit"] = self.db.rows("SELECT a.created,u.name AS actor,a.action,a.payload FROM audit a LEFT JOIN users u ON a.actor=u.id WHERE a.entity='job' AND a.entity_id=? ORDER BY a.id DESC LIMIT 300", (job_id,)) if self.s.user["role"] == "owner" else []
        if self.s.user['role']!='owner':
            from .inventory import public_values
            result=public_values(result)
        return result

    def report(self, kind, start, end, route="", customer_id=None, category_id=None, assignment=None):
        self.s.require("owner", "counter")
        if kind in ("customer_dues", "vendor_dues", "payments", "margins", "transport"):
            self.s.require("owner")
        if kind in ("customer_dues", "vendor_dues"):
            return self.account_balances(kind.split("_")[0])
        filters, args = ["j.received>=?", "j.received<=?"], [start, end + "T99"]
        for key, val in (("j.route", route), ("j.customer_id", customer_id), ("j.category_id", category_id), ("a.contact_id", assignment)):
            if val:
                filters.append(key + "=?")
                args.append(val)
        base = " FROM jobs j JOIN customers c ON c.id=j.customer_id LEFT JOIN assignments a ON a.id=j.assignment_id WHERE " + " AND ".join(filters)
        if kind == 'repair_parts':
            self.s.require('owner')
            return self.db.rows("SELECT j.number,p.name,p.brand,p.model,p.part_number,p.serial,p.quantity,p.source,p.supplier_snapshot,p.purchase_cost,p.customer_price,(p.customer_price-p.purchase_cost)*p.quantity AS margin,p.installed_by,p.installed_at,p.status"+base.replace(' FROM jobs j',' FROM repair_parts p JOIN jobs j ON j.id=p.job_id')+' ORDER BY j.id,p.id',args)
        if kind == 'part_warranties':
            return self.db.rows("SELECT j.number,w.name,w.start_date,w.duration,w.unit,w.expiry,w.provider,w.terms,CASE WHEN EXISTS(SELECT 1 FROM warranty_claims wc WHERE wc.warranty_id=w.id AND wc.status IN ('OPEN','ACCEPTED','IN_REPAIR')) THEN 'CLAIM IN PROGRESS' WHEN w.status='ACTIVE' AND w.expiry<date('now','+330 minutes') THEN 'EXPIRED' ELSE w.status END AS status"+base.replace(' FROM jobs j',' FROM part_warranties w JOIN jobs j ON j.id=w.job_id')+' ORDER BY w.expiry',args)
        if kind == 'warranty_claims':
            return self.db.rows('SELECT j.number,wc.original_job_id,wc.device_id,wc.part_id,wc.complaint,wc.status,wc.resolution,wc.replacement_part_id'+base.replace(' FROM jobs j',' FROM warranty_claims wc JOIN jobs j ON j.id=wc.new_job_id')+' ORDER BY wc.id',args)
        if kind == 'job_cards':
            return self.db.rows('SELECT j.number,jc.sequence,jc.kind,jc.from_name,jc.to_name,jc.effective'+base.replace(' FROM jobs j',' FROM job_cards jc JOIN jobs j ON j.id=jc.job_id')+' ORDER BY j.id,jc.sequence',args)
        if kind == "custody":
            return self.db.rows("SELECT j.number,c.name AS customer,i.description,i.type,i.serial,h.location,h.quantity FROM holdings h JOIN items i ON i.id=h.item_id JOIN jobs j ON j.id=i.job_id JOIN customers c ON c.id=j.customer_id LEFT JOIN assignments a ON a.id=j.assignment_id WHERE h.quantity>0 AND j.stage NOT IN ('collected','closed') AND " + " AND ".join(filters), args)
        if kind == "warranty":
            return self.db.rows("SELECT j.number,c.name AS customer,j.device,w.* FROM warranty w JOIN jobs j ON j.id=w.job_id JOIN customers c ON c.id=j.customer_id LEFT JOIN assignments a ON a.id=j.assignment_id WHERE w.id=(SELECT max(w2.id) FROM warranty w2 WHERE w2.job_id=j.id) AND " + " AND ".join(filters), args)
        if kind == "payments":
            return self.db.rows("SELECT e.*,j.number FROM entries e LEFT JOIN jobs j ON j.id=e.job_id WHERE e.posted>=? AND e.posted<=? AND e.kind IN ('receipt','payment','refund') ORDER BY e.posted", (start, end))
        if kind == "transport":
            return self.db.rows("SELECT e.id,e.created,e.kind,e.amount AS total_expense,e.payer,e.reference,e.included_entry_id,j.number,a.amount AS allocated,e.payload FROM expenses e JOIN expense_allocations a ON a.expense_id=e.id JOIN jobs j ON j.id=a.job_id WHERE e.created>=? AND e.created<=? ORDER BY e.id", (start, end + "T99"))
        if kind == "margins":
            rows = self.db.rows("""SELECT j.id,j.number,j.device,
                (SELECT COALESCE(sum(e.amount),0) FROM entries e LEFT JOIN entries original ON original.id=e.reverses_id WHERE e.job_id=j.id AND e.account_type='customer' AND e.kind NOT IN ('receipt','refund','opening') AND (e.kind!='reversal' OR original.kind NOT IN ('receipt','refund','opening'))) AS revenue,
                (SELECT COALESCE(sum(e.amount),0) FROM entries e LEFT JOIN entries original ON original.id=e.reverses_id WHERE e.job_id=j.id AND e.account_type='vendor' AND e.kind NOT IN ('payment','refund','opening') AND (e.kind!='reversal' OR original.kind NOT IN ('payment','refund','opening'))) +
                (SELECT COALESCE(sum(ea.amount),0) FROM expense_allocations ea JOIN expenses e ON e.id=ea.expense_id WHERE ea.job_id=j.id AND e.included_entry_id IS NULL AND (e.kind!='additional_vendor_charge' OR json_extract(e.payload,'$.acceptance')='accepted')) AS costs""" + base, args)
            for row in rows:
                row["margin_before_overheads"] = row["revenue"] - row["costs"]
            return rows
        if kind == "overdue":
            base += " AND j.stage NOT IN ('collected','closed') AND (j.repair_due<date('now') OR j.collection_due<date('now') OR j.return_due<date('now'))"
        return self.db.rows("SELECT j.number,c.name AS customer,j.device,j.serial,j.stage,j.route,j.received,j.repair_due,j.collection_due,j.actual_completion,j.actual_collection" + base + " ORDER BY j.id DESC", args)
