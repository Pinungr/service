from .domain import RuleError, today, sql_in_shop


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
            where.append("""(j.number LIKE ? OR j.serial LIKE ? OR c.name LIKE ? OR c.phone LIKE ? OR j.device LIKE ?
                OR j.intake_ref LIKE ? OR EXISTS(SELECT 1 FROM visits v WHERE v.id=j.visit_id AND v.number LIKE ?))""")
            args.extend(["%" + search + "%"] * 7)
        for key, value in (("j.stage", stage), ("j.route", route), ("j.customer_id", customer_id), ("j.category_id", category_id), ("a.contact_id", assignment)):
            if value:
                where.append(key + "=?")
                args.append(value)
        if location:
            # "shop" means the shop's own possession, whether that is a person or a shelf.
            held = sql_in_shop('h.location') if location.rstrip(':') == 'shop' else 'h.location LIKE ?'
            where.append("j.stage NOT IN ('collected','closed') AND EXISTS(SELECT 1 FROM items i JOIN holdings h ON i.id=h.item_id WHERE i.job_id=j.id AND i.type='device' AND h.quantity>0 AND " + held + ")")
            if location.rstrip(':') != 'shop':
                args.append(location + "%")
        if start:
            where.append("j.received>=?")
            args.append(start)
        if end:
            where.append("j.received<?")
            args.append(end + "T99")
        if overdue:
            where.append("j.stage NOT IN ('collected','closed') AND (j.repair_due<? OR j.collection_due<? OR j.return_due<?)")
            args.extend([today()] * 3)
        scope, scope_args = self.s.scope_jobs()
        where.append(scope)
        args.extend(scope_args)
        args.append(offset)
        return self.db.rows("""SELECT j.id,j.number,c.name AS customer,c.phone,j.device,j.serial,j.stage,j.route,
            COALESCE(m.name,tm.name,u.name,'Unassigned') AS responsible,j.repair_due,j.collection_due,j.return_due,
            (SELECT group_concat(h.location || ' (' || h.quantity || ')', ', ') FROM items i JOIN holdings h ON h.item_id=i.id WHERE i.job_id=j.id AND i.type='device' AND h.quantity>0) AS custody,
            (SELECT COALESCE(sum(e.amount),0) FROM entries e WHERE e.job_id=j.id AND e.account_type='customer') AS balance,
            (SELECT state FROM outbox o WHERE o.job_id=j.id ORDER BY o.id DESC LIMIT 1) AS message
            FROM jobs j JOIN customers c ON c.id=j.customer_id LEFT JOIN assignments a ON a.id=j.assignment_id LEFT JOIN masters m ON m.id=a.contact_id LEFT JOIN users u ON u.id=a.technician_id LEFT JOIN masters tm ON tm.id=a.technician_master_id WHERE """ + " AND ".join(where) + " ORDER BY j.id DESC LIMIT 50 OFFSET ?", args)

    def dashboard(self):
        """Counts for the signed-in user.

        Every job aggregate goes through the same scope as the job lists, so a technician
        is never shown a total that includes repairs they cannot open.
        """
        self.s.require()
        scope, scope_args = self.s.scope_jobs()
        # Grouped in a subquery: `GROUP BY location` would otherwise bind to the raw
        # column rather than the computed prefix, giving one row per individual holder
        # now that custody names a person rather than a single storage place.
        locations = self.db.rows("""SELECT kind AS location,type,sum(units) AS units FROM (
                SELECT CASE WHEN instr(h.location,':')>0 THEN substr(h.location,1,instr(h.location,':')-1)
                            ELSE h.location END AS kind, i.type AS type, h.quantity AS units
                FROM holdings h JOIN items i ON i.id=h.item_id JOIN jobs j ON j.id=i.job_id
                WHERE h.quantity>0 AND j.stage NOT IN ('collected','closed')
                  AND h.location!='customer' AND h.location NOT LIKE 'exception:%' AND """ + scope + """)
            GROUP BY kind,type""", tuple(scope_args))
        stages = self.db.rows("SELECT j.stage,count(*) AS jobs FROM jobs j WHERE j.stage NOT IN ('collected','closed') AND " + scope + " GROUP BY j.stage", tuple(scope_args))
        balances = self.db.rows("SELECT account_type,sum(amount) AS balance FROM entries GROUP BY account_type") if self.s.may('financial_reports') else []
        messages = self.db.rows("""SELECT state,count(*) AS messages FROM outbox o
            WHERE state NOT IN ('accepted','captured','cancelled','delivered','read')
            AND (o.job_id IS NULL OR EXISTS(SELECT 1 FROM jobs j WHERE j.id=o.job_id AND """ + scope + """))
            GROUP BY state""", tuple(scope_args))
        overdue = self.db.one("SELECT count(*) AS n FROM jobs j WHERE j.stage NOT IN ('collected','closed') AND (j.repair_due<? OR j.collection_due<? OR j.return_due<?) AND " + scope, (today(), today(), today(), *scope_args))["n"]
        return dict(locations=locations, stages=stages, balances=balances, messages=messages, overdue=overdue, sales=(self.db.one("SELECT count(*) AS n FROM sales WHERE collected=0")["n"] if self.s.may('register_sale') else None), backup=self.db.one("SELECT * FROM backups WHERE state='verified' ORDER BY id DESC LIMIT 1"))

    def holdings(self, job_id=None, movable=False):
        """Items the signed-in user may see, for the dispatch / receive screens.

        The custody screens used to read `holdings` directly, which showed a technician
        every other technician's products and custodians. They go through here now, so the
        list obeys the same job scope as everything else.
        """
        self.s.require_permission('handover')
        if job_id:
            self.s.require_job_access(job_id)
        scope, scope_args = self.s.scope_jobs()
        columns = ("i.*,h.location,h.quantity AS available,j.number" if movable
                   else "i.id,i.job_id,j.number,i.description,i.type,i.serial,h.location,h.quantity")
        where, args = ["h.quantity>0", "j.stage NOT IN ('collected','closed')"], []
        if not movable:
            where.append("h.location!='customer'")
        if job_id:
            where.append('i.job_id=?')
            args.append(job_id)
        where.append(scope)
        args.extend(scope_args)
        return self.db.rows(f"""SELECT {columns} FROM holdings h JOIN items i ON h.item_id=i.id
            JOIN jobs j ON j.id=i.job_id WHERE """ + ' AND '.join(where) + ' ORDER BY i.id DESC LIMIT 500', tuple(args))

    def sales(self, limit=200):
        """Sold products. Shop cost and supplier are internal and only shown to roles
        that may see them."""
        self.s.require_permission('register_sale')
        internal = "s.cost,s.provider," if self.s.may('view_internal_cost') else ''
        return self.db.rows(f"""SELECT s.id,s.customer_id,s.device,s.serial,s.invoice_ref,s.invoice_date,
            s.sale_date,s.amount,{internal}s.warranty_start,s.warranty_end,s.warranty_terms,
            s.collected,s.collector,s.acknowledgment,c.name AS customer
            FROM sales s JOIN customers c ON c.id=s.customer_id ORDER BY s.id DESC LIMIT ?""", (limit,))

    def customer_sales(self, customer_id):
        """Sold products visible on one customer's overview.

        The old Qt screen selected ``sales.*`` directly, which bypassed the permission
        layer and exposed shop cost/provider to anyone who could open customer records.
        Keep the projection here beside the normal Sales query so both screens obey the
        same permission rules.
        """
        self.s.require_permission('register_sale')
        internal = "s.cost,s.provider," if self.s.may('view_internal_cost') else ''
        return self.db.rows(f"""SELECT s.id,s.customer_id,s.device,s.serial,s.invoice_ref,s.invoice_date,
            s.sale_date,s.amount,{internal}s.warranty_start,s.warranty_end,s.warranty_terms,
            s.collected,s.collector,s.acknowledgment
            FROM sales s WHERE s.customer_id=? ORDER BY s.id DESC""", (customer_id,))

    def customer_quotes(self, customer_id):
        """Customer-visible quotations, restricted to jobs the current user may open."""
        self.s.require_permission('customer_records')
        scope, scope_args = self.s.scope_jobs()
        return self.db.rows("""SELECT q.id,q.job_id,j.number,q.version,q.scope,q.total,q.valid_until,
            q.state,q.created
            FROM quotes q JOIN jobs j ON j.id=q.job_id
            WHERE j.customer_id=? AND """ + scope + " ORDER BY q.id DESC",
            (customer_id, *scope_args))

    def customer_payments(self, customer_id):
        """Customer ledger rows only for roles allowed to collect/view customer money."""
        self.s.require_permission('collect_payment')
        scope, scope_args = self.s.scope_jobs()
        sql = """SELECT e.id,e.posted,e.kind,e.amount,e.method,e.reference,e.job_id,j.number
            FROM entries e LEFT JOIN jobs j ON j.id=e.job_id
            WHERE e.account_type='customer' AND e.account_id=?
              AND (e.job_id IS NULL OR (j.id IS NOT NULL AND """ + scope + ")) " + \
              "ORDER BY e.id DESC"
        return self.db.rows(sql, (customer_id, *scope_args))

    def customer_messages(self, customer_id):
        """Communication audit for users who are allowed to manage customer messaging."""
        self.s.require_permission('messaging')
        scope, scope_args = self.s.scope_jobs()
        sql = """SELECT o.event,o.channel,o.destination,o.state,o.created,o.job_id,j.number
            FROM outbox o LEFT JOIN jobs j ON j.id=o.job_id
            WHERE o.contact_id=? AND (o.job_id IS NULL OR (j.id IS NOT NULL AND """ + scope + ")) " + \
              "ORDER BY o.id DESC"
        return self.db.rows(sql, (customer_id, *scope_args))

    def ledger(self, account_type, account_id, start, end):
        self.s.require_permission('collect_payment')
        if account_type == "vendor":
            self.s.require_permission('vendor_accounts')
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
        self.s.require_permission('vendor_accounts')
        table = "customers" if account_type == "customer" else "masters"
        return self.db.rows(f"SELECT e.account_id,p.name,sum(e.amount) AS balance FROM entries e JOIN {table} p ON p.id=e.account_id WHERE e.account_type=? GROUP BY e.account_id,p.name ORDER BY p.name", (account_type,))

    def history(self, job_id):
        self.s.require_job_access(job_id)
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
        if not self.s.may('view_internal_cost'):
            from .inventory import public_values
            result=public_values(result)
        return result

    def report(self, kind, start, end, route="", customer_id=None, category_id=None, assignment=None):
        self.s.require_permission('reports')
        if kind in ("customer_dues", "vendor_dues", "payments", "margins", "transport"):
            self.s.require_permission('financial_reports')
        if kind in ("customer_dues", "vendor_dues"):
            return self.account_balances(kind.split("_")[0])
        filters, args = ["j.received>=?", "j.received<=?"], [start, end + "T99"]
        for key, val in (("j.route", route), ("j.customer_id", customer_id), ("j.category_id", category_id), ("a.contact_id", assignment)):
            if val:
                filters.append(key + "=?")
                args.append(val)
        base = " FROM jobs j JOIN customers c ON c.id=j.customer_id LEFT JOIN assignments a ON a.id=j.assignment_id WHERE " + " AND ".join(filters)
        if kind == 'repair_parts':
            self.s.require_permission('view_internal_cost')
            return self.db.rows("SELECT j.number,p.name,p.brand,p.model,p.part_number,p.serial,p.quantity,p.source,p.supplier_snapshot,p.purchase_cost,p.customer_price,(p.customer_price-p.purchase_cost)*p.quantity AS margin,p.installed_by,p.installed_at,p.status"+base.replace(' FROM jobs j',' FROM repair_parts p JOIN jobs j ON j.id=p.job_id')+' ORDER BY j.id,p.id',args)
        if kind == 'part_warranties':
            return self.db.rows("SELECT j.number,w.name,w.start_date,w.duration,w.unit,w.expiry,w.provider,w.terms,CASE WHEN EXISTS(SELECT 1 FROM warranty_claims wc WHERE wc.warranty_id=w.id AND wc.status!='CLOSED') THEN 'CLAIM IN PROGRESS' WHEN w.status='ACTIVE' AND w.expiry<? THEN 'EXPIRED' ELSE w.status END AS status"+base.replace(' FROM jobs j',' FROM part_warranties w JOIN jobs j ON j.id=w.job_id')+' ORDER BY w.expiry',[today()]+list(args))
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
            base += " AND j.stage NOT IN ('collected','closed') AND (j.repair_due<? OR j.collection_due<? OR j.return_due<?)"
            args.extend([today()] * 3)
        return self.db.rows("SELECT j.number,c.name AS customer,j.device,j.serial,j.stage,j.route,j.received,j.repair_due,j.collection_due,j.actual_completion,j.actual_collection" + base + " ORDER BY j.id DESC", args)
