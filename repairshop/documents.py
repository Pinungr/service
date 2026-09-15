import csv
import html
import json
import os
from pathlib import Path
import shutil
import uuid
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, A5, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from openpyxl import Workbook
from .domain import now, rupees, RuleError, timezone_name
from .persistence import insert
from .customer_records import CustomerRecords
from .local_files import managed_path, publish


def safe_cell(value):
    s = "" if value is None else str(value)
    return "'" + s if s.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else s


PAPER = {'A4': A4, 'A5': A5}

#: Every document is generated for one audience or the other, stated by the caller.
#: Nothing decides this from a filename or a document type name.
VISIBILITY = ('customer', 'internal')


def pdf(path, title, shop, sections, wide=False, paper='A4'):
    from .lifecycle import local_time
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf"
    if font_path.exists() and "ShopSans" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("ShopSans", str(font_path)))
    font = "ShopSans" if "ShopSans" in pdfmetrics.getRegisteredFontNames() else "Helvetica"
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = font
    styles["Normal"].fontSize = 9
    styles["Normal"].leading = 13
    styles['Heading3'].keepWithNext = True
    size = PAPER.get(str(paper).upper(), A4)
    page = landscape(size) if wide else size
    # A5 is half the width of A4, so the body must be re-measured rather than scaled:
    # narrower margins, smaller type and column widths derived from the real page.
    compact = page[0] < A4[0]
    margin = 24 if compact else 36
    if compact:
        styles["Normal"].fontSize = 8
        styles["Normal"].leading = 11
        styles["Title"].fontSize = 15
        styles["Title"].leading = 18
        styles["Heading2"].fontSize = 11
        styles["Heading3"].fontSize = 9.5
    width = page[0] - 2 * margin
    story = [Paragraph(html.escape(shop), styles["Title"]), Paragraph(html.escape(title), styles["Heading2"]), Paragraph("Issued " + local_time(now()) + ' ' + timezone_name(), styles["Normal"]), Spacer(1, 10 if compact else 16)]
    for heading, content in sections:
        story.append(Paragraph(html.escape(heading), styles["Heading3"]))
        if isinstance(content, list) and content:
            keys = list(content[0])
            rows = [[Paragraph(html.escape(k.replace("_", " ").title()), styles["Normal"]) for k in keys]]
            for row in content:
                rows.append([Paragraph(html.escape(str(row.get(k, "") if row.get(k) is not None else "")).replace("\n", "<br/>"), styles["Normal"]) for k in keys])
            table = Table(rows, colWidths=[width / len(keys)] * len(keys), repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dcece8")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, 0), .7, colors.HexColor("#1d695b")), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f7f7")]), ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 7)]))
            story.append(table)
        else:
            story.append(Paragraph(html.escape(str(content or "None recorded")).replace("\n", "<br/>"), styles["Normal"]))
        story.append(Spacer(1, 8 if compact else 12))
    def footer(canvas, doc):
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#647875"))
        canvas.drawString(margin, 18, ("RepairShop Manager · " + title)[:52 if compact else 78])
        canvas.drawRightString(page[0] - margin, 18, str(doc.page))
    SimpleDocTemplate(str(path), pagesize=page, rightMargin=margin, leftMargin=margin,
                      topMargin=margin, bottomMargin=margin + 8).build(story, onFirstPage=footer, onLaterPages=footer)


class Documents:
    def __init__(self, service):
        self.s, self.db = service, service.db

    def visit_receipt(self,job_ids,paper=None):
        """Combined receiving summary; individual issued cards remain available."""
        from .job_cards import JobCards
        from .lifecycle import local_time
        self.s.require_permission('handover')
        if not job_ids:raise RuleError('Select the jobs received during this visit.')
        jobs=[self.s.job(ident) for ident in job_ids]
        if len({(j['customer_id'],j['visit_id'] or j['intake_ref']) for j in jobs})!=1:
            raise RuleError('A visit receipt must contain one customer and one visit reference.')
        from . import app_settings
        show_estimate=app_settings.value(self.db,'show_estimate_on_receipt')
        show_advance=app_settings.value(self.db,'show_advance_on_receipt')
        show_completion=app_settings.value(self.db,'show_completion_date')
        visit=self.db.one('SELECT number FROM visits WHERE id=?',(jobs[0]['visit_id'],)) if jobs[0]['visit_id'] else None
        reference=(visit or {}).get('number') or jobs[0]['intake_ref']
        sections=[]
        for j in jobs:
            card=next((r for r in JobCards(self.s).rows(j['id']) if r['kind']=='customer_receiving'),None)
            if not card:raise RuleError('An original receiving card is required for every product.')
            p=json.loads(card['snapshot'])
            if not sections:
                owner=p['from'];sections.append(('Customer',owner['name']+'\n'+owner.get('phone','')+'\n'+owner.get('email','')))
                sections.append(('Visit',reference+f" · {len(jobs)} products received"))
            summary = (f"{p['device']} · DEV-{p['device_id']:06d}\n"
                f"Category: {p.get('device_type','Not specified')} · Service: {p.get('requested_service','Not specified')}\n"
                f"Serial: {p['serial'] or 'Not recorded'}\nComplaint: {p['complaint']}\nCondition: {p['condition']}\n"
                f"Received: {local_time(p['effective'])} {timezone_name()} · Staff: {p['staff']}")
            # A figure the shop chose not to show is left out of the document entirely,
            # not merely unlabelled elsewhere on the page.
            if show_estimate:
                summary += f"\nInitial estimate: {rupees(j['initial_estimate'] or 0)}"
            if show_completion and j['repair_due']:
                summary += f"\nEstimated completion: {j['repair_due']}"
            if j['customer_requirement']:
                summary += f"\nAdditional customer requirement: {j['customer_requirement']}"
            sections.append((j['number']+' / '+p['card_number'], summary))
            sections.append(('Items received',[{k:r.get(k,'') for k in ('description','quantity','serial','condition','notes')} for r in p['items']]))
        estimate=sum(j['initial_estimate'] or 0 for j in jobs)
        advance=self.db.one("""SELECT -COALESCE(sum(amount),0) n FROM entries WHERE account_type='customer'
            AND kind='receipt' AND notes='Intake advance' AND job_id IN ("""+','.join('?' for _ in jobs)+')',
            tuple(j['id'] for j in jobs))['n']
        if show_estimate:
            money = 'Total initial estimate: ' + rupees(estimate)
            if show_advance:
                money += ('\nAdvance received: ' + rupees(advance)
                          + '\nEstimated balance against this initial estimate: ' + rupees(estimate - advance))
            sections.append(('Initial estimate', money))
            sections.append(('Please note','The initial estimate above is the figure given when the products were '
                'received. It is not the final repair quotation. Any chargeable repair is quoted after diagnosis '
                'and started only after your recorded approval.'))
        elif show_advance:
            sections.append(('Advance received', rupees(advance)))
        return self.snapshot('Customer visit receiving receipt · '+reference,sections,job_id=jobs[0]['id'],
            paper=paper or self.paper(document='intake_receipt'))

    def attach(self, source, title, job_id=None, sale_id=None, kind="evidence"):
        self.s.require_permission('customer_records')
        # Authorize the repair before reading, validating or publishing the file, so a
        # refused attach writes nothing to disk and records nothing in the database.
        if job_id:
            self.s.require_job_access(job_id)
        source = Path(source)
        allowed = {'.pdf', '.jpg', '.jpeg', '.png'}
        suffix = source.suffix.lower()
        if not source.is_file() or source.stat().st_size > 50 * 1024 * 1024:
            raise RuleError("Choose a file up to 50 MB.")
        if suffix not in allowed:
            raise RuleError("Attach evidence as PDF, JPG/JPEG, or PNG.")
        content = source.read_bytes()
        signatures = {
            '.pdf': lambda b: b.startswith(b'%PDF-'),
            '.jpg': lambda b: b.startswith(b'\xff\xd8\xff'),
            '.jpeg': lambda b: b.startswith(b'\xff\xd8\xff'),
            '.png': lambda b: b.startswith(b'\x89PNG\r\n\x1a\n'),
        }
        if not signatures[suffix](content):
            raise RuleError("The selected file content does not match its PDF/JPG/PNG extension.")
        relative = CustomerRecords(self.s).document_folder(job_id, sale_id) + '/' + uuid.uuid4().hex + suffix
        with self.db.guard:
            target = managed_path(self.db.root, relative)
            publish(target, content)
            try:
                with self.db.transaction() as c:
                    ident = insert(c, "attachments", job_id=job_id, sale_id=sale_id, kind=kind, path=relative, title=title, created=now(), actor=self.s.user["id"])
                    self.s.audit(c, "job" if job_id else "sale", job_id or sale_id, "attachment_added", {"id": ident, "title": title})
                return target
            except Exception:
                target.unlink(missing_ok=True)
                raise

    def generate(self, kind, job_id, source_id=None, paper=None, visibility='customer'):
        self.s.require_permission('handover')
        if visibility not in VISIBILITY:
            raise RuleError('A document is generated either for the customer or for the shop.')
        from .job_cards import JobCards
        card_kind={'intake_receipt':'customer_receiving','collection_receipt':'customer_delivery'}
        if kind in card_kind:
            cards=[r for r in JobCards(self.s).rows(job_id) if r['kind']==card_kind[kind]]
            if cards:
                return JobCards(self.s).print(cards[-1]['id'], paper=paper or self.paper(document='job_card'),
                                             internal=visibility=='internal')
        if kind in ('dispatch_manifest','return_manifest'):
            ending='dispatch' if kind=='dispatch_manifest' else 'return'
            cards=[r for r in JobCards(self.s).rows(job_id) if r['kind'].endswith(ending)]
            if cards:
                return JobCards(self.s).print(cards[-1]['id'], paper=paper or self.paper(document='job_card'),
                                             internal=visibility=='internal')
            raise RuleError('This legacy job has no external card. Review its history and record a new actual dispatch/return before printing a card.')
        j = self.s.job(job_id)
        sections = [("Customer & device", f"{j['customer']} · {j['phone']}\n{j['device']} · Serial: {j['serial'] or 'Unknown'}\nSubmitted by: {j['submitter'] or j['customer']} ({j['relationship'] or 'owner'})" )]
        title = f"{kind.replace('_',' ').title()} · {j['number']}"
        if kind == "quotation":
            q = self.db.one("SELECT * FROM quotes WHERE id=? AND job_id=?", (source_id, job_id))
            if not q:
                raise RuleError("Select a quotation.")
            title += f" · version {q['version']}"
            snapshot = json.loads(q.get('snapshot', '{}'))
            if snapshot:
                customer, job = snapshot['customer'], snapshot['job']
                sections = [('Customer & device', f"{customer['name']} · {customer['phone']}\n{job['device']} · Serial: {job['serial'] or 'Unknown'}")]
            sections += [("Scope", q["scope"]), ("Quotation", [{"Description": x["description"], "Amount": rupees(x["amount"])} for x in json.loads(q["lines"])]), ("Total", rupees(q["total"])), ("Terms", q["terms"] + "\nValid until: " + (q["valid_until"] or "Not specified"))]
        elif kind in ("bill", "payment_receipt", "refund_acknowledgment"):
            e = self.db.one("SELECT * FROM entries WHERE id=? AND account_type='customer' AND job_id=?", (source_id, job_id))
            if not e:
                raise RuleError("Select a customer financial entry for this job.")
            sections += [("Financial entry", f"Entry #{e['id']} · {e['kind']}\nDate: {e['posted']}\nAmount: {rupees(abs(e['amount']))}\nMethod: {e['method']}\nReference: {e['reference']}\n{e['notes']}")]
            snapshot = json.loads(e["payload"])
            if snapshot.get("lines"):
                sections.append(("Billed items", [{"Description": x["description"], "Amount": rupees(x["amount"])} for x in json.loads(snapshot["lines"])]))
        elif kind == 'final_invoice':
            pass  # Financial and warranty sections below form the customer invoice.
        else:
            items = self.db.rows("SELECT type,description,quantity,serial,condition,provenance FROM items WHERE job_id=?", (job_id,))
            sections += [("Complaint / visible condition", j["complaint"] + "\n" + j["damage"]), ("Items actually received / documented replacements", items)]
            if kind in ("dispatch_manifest", "return_manifest", "collection_receipt"):
                moves = self.db.rows("SELECT i.description,m.quantity,m.from_location,m.to_location,m.happened,m.counterparty,m.reference,m.acknowledgment FROM movements m JOIN items i ON i.id=m.item_id WHERE i.job_id=? ORDER BY m.id", (job_id,))
                if kind == "collection_receipt":
                    moves = [m for m in moves if m["to_location"] == "customer"]
                sections.append(("Recorded handovers", moves))
            if kind == "warranty_summary":
                sections.append(("Centre decisions", self.db.rows("SELECT eligibility,decision,rma,findings,covered,excluded,terms FROM warranty WHERE job_id=? ORDER BY id", (job_id,))))
            sections += [("Agreed return policy", f"{j['policy']}\nAgreed transport: {rupees(j['transport_agreed'])}\nExplicit assessment/handling: {rupees(j['assessment_agreed'])}"), ("Shop", self.db.setting("address", "") + "\n" + self.db.setting("hours", ""))]
        if kind in ('bill','final_invoice','warranty_summary'):
            from .warranties import Warranties
            from .parts import Parts
            parts=[r for r in Parts(self.s).rows(job_id) if r['status']=='installed']
            sections.append(('Installed parts',[dict(part=r['name'],serial=r['serial'],quantity=r['quantity'],customer_price=rupees(r['customer_price']*r['quantity'])) for r in parts]))
            warranties=[r for r in Warranties(self.s).rows(j['device_id']) if r['job_id']==job_id]
            sections.append(('Repair and part warranties',[dict(part=r['name'],duration=f"{r['duration']} {r['unit']}",expiry=r['expiry'],provider=r['provider'],terms=r['terms'],status=r['effective_status']) for r in warranties]))
            if kind=='final_invoice':
                quote=self.db.one('SELECT * FROM quotes WHERE job_id=? ORDER BY version DESC LIMIT 1',(job_id,))
                if quote and quote['state']=='approved':
                    sections.append(('Approved charges',[{'description':r['description'],'amount':rupees(r['amount'])} for r in json.loads(quote['lines'])]))
                bill=self.db.one("SELECT COALESCE(sum(e.amount),0) balance,COALESCE(sum(CASE WHEN e.kind='invoice' OR (e.kind='reversal' AND original.kind='invoice') THEN e.amount ELSE 0 END),0) invoiced FROM entries e LEFT JOIN entries original ON original.id=e.reverses_id WHERE e.account_type='customer' AND e.job_id=?",(job_id,))
                if j['stage'] not in ('ready_repaired','ready_unrepaired','collected','closed'):
                    raise RuleError('Complete QC and final billing before generating the final invoice.')
                sections.append(('Final account',f"Invoiced: {rupees(bill['invoiced'])}\nBalance: {rupees(bill['balance'])}"))
        branding = json.loads(q.get('snapshot', '{}')).get('shop', {}).get('shop_name') if kind == 'quotation' else None
        return self.snapshot(title, sections, job_id=job_id, shop_name=branding, paper=paper,
                             internal=visibility=='internal')

    def paper(self, override=None, document=None):
        """The paper this document is printed on.

        The owner configures it once; a document kind may have its own size, otherwise
        the shop default applies. An explicit override is only for a one-off reprint, so
        staff are never asked for a size during normal work.
        """
        from . import app_settings
        choice = override or (app_settings.paper_for(self.db, document) if document
                              else app_settings.value(self.db, 'paper_size'))
        choice = str(choice or 'A4').upper()
        return choice if choice in PAPER else 'A4'

    def snapshot(self, title, sections, job_id=None, shop_name=None, paper=None, internal=False):
        """Render one document. Internal copies are kept out of the customer's folder.

        The customer folder is what gets opened, copied or handed over when someone asks
        for "the customer's file", so anything carrying purchase costs, third-party costs
        or margin is filed under the shop's own internal area instead. The record itself is
        kept either way; only where it lives, and the attachment kind, differ.
        """
        self.s.require_permission('handover')
        if internal:
            self.s.require_permission('view_internal_cost')
        folder = ('Internal/Repairs/' + str(job_id or 'general')) if internal \
            else CustomerRecords(self.s).document_folder(job_id)
        relative = folder + '/' + uuid.uuid4().hex + '.pdf'
        with self.db.guard:
            path = managed_path(self.db.root, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            pending = path.with_suffix('.partial')
            try:
                pdf(pending, title, shop_name or self.db.setting("shop_name", "RepairShop Manager"), sections, paper=self.paper(paper))
                with pending.open('r+b') as stream:
                    os.fsync(stream.fileno())
                os.rename(pending, path)
                with self.db.transaction() as c:
                    insert(c, "attachments", job_id=job_id, kind="internal_document" if internal else "issued_document", path=relative, title=title, created=now(), actor=self.s.user["id"])
                    self.s.audit(c, "job" if job_id else "document", job_id, "document_issued", {"title": title, "path": relative})
            except Exception:
                pending.unlink(missing_ok=True)
                path.unlink(missing_ok=True)
                raise
        return path

    def export(self, path, title, rows):
        self.s.require_permission('reports')
        path = Path(path)
        if not rows:
            raise RuleError("No rows match this report.")
        if path.suffix.lower() == ".pdf":
            # Large reports split into manageable logical column groups.
            keys = list(rows[0])
            sections = [(title + (f" · columns {i+1}–{min(i+7,len(keys))}" if len(keys)>7 else ""), [{k:r.get(k) for k in keys[i:i+7]} for r in rows]) for i in range(0,len(keys),7)]
            pdf(path, title, self.db.setting("shop_name", "RepairShop Manager"), sections, wide=True)
        elif path.suffix.lower() == ".xlsx":
            wb = Workbook(write_only=True)
            ws = wb.create_sheet("Report")
            ws.append(list(rows[0]))
            for row in rows:
                ws.append([v if isinstance(v, (int, float)) else safe_cell(v) for v in row.values()])
            wb.save(path)
        else:
            with path.open("w", newline="", encoding="utf-8-sig") as stream:
                writer = csv.writer(stream)
                writer.writerow(rows[0])
                writer.writerows([[safe_cell(v) for v in row.values()] for row in rows])
        return path
