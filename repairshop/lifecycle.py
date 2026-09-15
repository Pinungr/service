"""Guided repair lifecycle over the existing jobs, work, custody and accounts.

Physical location is always read from holdings. Workflow evidence augments a job;
it never replaces movements, issued quotes, payments or the immutable audit log.
"""
from contextvars import ContextVar
from datetime import datetime, timezone, date
from zoneinfo import ZoneInfo
import json
import uuid
from .domain import RuleError, now, day, rupees, today, in_shop, sql_in_shop

_command = ContextVar('repair_lifecycle_command', default=False)
ROUTE_LABELS = {'in_house': 'IN-HOUSE REPAIR', 'warranty_centre': 'AUTHORIZED SERVICE CENTER', 'third_party': 'THIRD-PARTY REPAIR'}
LABELS = dict(received='RECEIVED', inspection='INITIAL INSPECTION', warranty_check='WARRANTY CHECK',
    route_selection='SELECT REPAIR ROUTE', diagnosis='DIAGNOSIS', external_diagnosis='EXTERNAL DIAGNOSIS',
    awaiting_estimate='PREPARE ESTIMATE', awaiting_approval='WAITING FOR CUSTOMER APPROVAL', approved='APPROVED',
    ready_dispatch='DISPATCH PENDING', under_repair='REPAIR IN PROGRESS', waiting_parts='WAITING FOR PARTS',
    awaiting_return='AWAITING RETURN TO SHOP', technician_testing='TECHNICIAN TESTING', testing='FINAL QC',
    final_qc='FINAL QC', billing='BILLING', ready_repaired='READY FOR DELIVERY',
    return_unrepaired='RETURN WITHOUT REPAIR', ready_unrepaired='READY FOR DELIVERY · UNREPAIRED',
    collected='DELIVERED', closed='CLOSED')
ACTIONS = {
    'hand_technician':'Hand device to technician','return_technician':'Return device from technician to QC',
    'hand_over':'Hand product to another staff member',
    'return_dispatch':'Hand returning device to courier','parts':'Check shop inventory / manage required parts',
    'costing':'Review internal repair costs','manual_warranty':'Manual warranty check',
    'inspect': 'Perform initial inspection', 'inspection_done': 'Complete initial inspection',
    'verify_warranty': 'Verify warranty', 'select_route': 'Select repair route', 'change_route': 'Change repair route',
    'prepare_dispatch': 'Create dispatch record', 'dispatch': 'Send device', 'arrive': 'Confirm arrival at repairer',
    'diagnose': 'Record diagnosis', 'quote': 'Prepare customer estimate', 'decision': 'Record customer decision',
    'warranty_result': 'Record service center warranty decision', 'wait_parts': 'Order / wait for parts',
    'parts_received': 'Mark parts received', 'start_repair': 'Start / authorize repair',
    'complete_repair': 'Record repair completed', 'replacement': 'Record replacement result',
    'repair_failed': 'Record unsuccessful repair', 'test': 'Record technician test', 'receive': 'Receive device back at shop',
    'qc': 'Perform final QC / return check', 'bill': 'Review billing and mark ready',
    'notify': 'Notify customer', 'payment': 'Record customer payment / refund', 'handover': 'Start device handover',
    'close': 'Close job', 'decline': 'Declined / not repairable / cancelled', 'rework': 'Record concern and reopen diagnosis',
    'adopt': 'Review legacy job and enable guided actions', 'details': 'Update route details',
    'resolve_item': 'Record item custody exception',
    'claim': 'Resolve warranty claim',
}


from .domain import local_time  # noqa: F401  (kept importable from here for existing callers)


def intake_warranty(data):
    """Was this product under warranty when the shop collected it?

    Answered only from the snapshot recorded at intake, so a warranty that expires while
    the device is in the shop or at a service centre is still treated as valid cover.
    """
    snapshot = data.get('intake_warranty') or {}
    status = (snapshot.get('status') or '').upper()
    if not snapshot:
        # Legacy jobs have no snapshot; keep the existing manual warranty check.
        return dict(eligible=True, status='UNRECORDED', expiry=None,
                    reason='No warranty status was recorded at intake; verify it manually.')
    reasons = {'EXPIRED': 'Warranty had already expired when the product was collected.',
               'NONE': 'The customer reported no warranty at collection.',
               'NOT_STARTED': 'The recorded warranty had not started at collection.',
               'UNKNOWN': 'Warranty was not confirmed as valid when the product was collected.'}
    # The guided Warranty Check stage exists only for a product that was explicitly
    # recorded as covered at intake. Unknown is preserved as unknown, but it no longer
    # forces staff through a warranty-verification stage that the shop did not choose.
    return dict(eligible=status == 'VALID', status=status or 'UNKNOWN',
                expiry=snapshot.get('expiry') or snapshot.get('expiry_date'),
                checked_on=snapshot.get('checked_on'),
                reason=reasons.get(status, 'Warranty was not confirmed as valid when the product was collected.'))


#: The permission each guided lifecycle step needs. Steps with no entry are open to any
#: signed-in user who can already reach the job.
ACTION_PERMISSIONS = {
    'inspect': 'repair', 'inspection_done': 'repair', 'diagnose': 'repair',
    'start_repair': 'repair', 'complete_repair': 'repair', 'repair_failed': 'repair',
    'test': 'repair', 'wait_parts': 'repair', 'parts_received': 'repair',
    'qc': 'quality_check',
    'verify_warranty': 'manage_warranty', 'warranty_result': 'manage_warranty',
    'manual_warranty': 'manage_warranty', 'claim': 'manage_warranty',
    'select_route': 'assign_job', 'change_route': 'assign_job', 'adopt': 'assign_job',
    'hand_technician': 'handover', 'return_technician': 'handover', 'hand_over': 'handover',
    'prepare_dispatch': 'handover', 'dispatch': 'handover', 'arrive': 'handover',
    'receive': 'handover', 'return_dispatch': 'handover',
    'quote': 'create_quote', 'decision': 'approve_quote',
    'bill': 'billing', 'payment': 'collect_payment',
    'handover': 'customer_delivery', 'close': 'customer_delivery',
    'notify': 'messaging', 'parts': 'manage_parts', 'costing': 'view_internal_cost',
    'resolve_item': 'resolve_exception', 'replacement': 'record_replacement',
    'decline': 'assign_job', 'rework': 'repair',
}


def guard(j, operation):
    if j['lifecycle_version'] and not _command.get():
        raise RuleError('Use the guided job action to ' + operation + '. Open the job to see the next required step.')


def quote_guard(c, j):
    if not j['lifecycle_version']:
        return
    if j['stage'] not in ('awaiting_estimate', 'awaiting_approval', 'approved'):
        raise RuleError('Record diagnosis and reach Prepare Estimate before issuing or revising a quotation.')


class Lifecycle:
    def __init__(self, service):
        self.s, self.db = service, service.db

    def holdings(self, ident):
        self.s.require_job_access(ident)
        return self.db.rows('''SELECT i.id,i.description,i.type,i.serial,h.location,h.quantity
            FROM items i JOIN holdings h ON h.item_id=i.id WHERE i.job_id=? AND h.quantity>0''', (ident,))

    def timeline(self, ident):
        self.s.require_job_access(ident)
        rows = self.db.rows("SELECT a.id,a.created,u.name AS actor,a.action,a.payload FROM audit a LEFT JOIN users u ON u.id=a.actor WHERE a.entity='job' AND a.entity_id=? ORDER BY a.created,a.id", (ident,))
        for r in rows:
            r['time'] = local_time(r['created'])
            payload = json.loads(r['payload'])
            if not self.s.may('view_internal_cost'):
                from .inventory import public_values
                payload=public_values(payload);r['payload']=json.dumps(payload)
            r['event'] = ACTIONS.get(payload.get('action'), r['action'].replace('_', ' ').title())
            # Financial detail visibility remains owner-only; business events stay readable.
            if not self.s.may('view_internal_cost') and r['action'] in ('expense_allocated', 'finance_posted') and payload.get('account_type') != 'customer':
                r['details'] = 'Account record updated'
            else:
                def readable(obj):
                    parts=[]
                    for key,value in obj.items():
                        if key in ('action','before','after','version','actor'):
                            continue
                        if not self.s.may('view_internal_cost') and key in ('vendor_parts','vendor_labour','transport_cost','other_cost','customer_price','purchase_cost','cost','estimate'):
                            continue
                        if isinstance(value,dict):
                            parts.append(readable(value))
                        elif isinstance(value,list):
                            parts.append(key.replace('_',' ').title()+': '+', '.join(readable(x) if isinstance(x,dict) else str(x) for x in value))
                        elif value not in (None,''):
                            shown=rupees(value) if key in ('amount','total','cost','estimate','vendor_parts','vendor_labour','transport_cost','other_cost','customer_price') and isinstance(value,int) else ('Yes' if value is True else 'No' if value is False else str(value).replace('_',' '))
                            parts.append(key.replace('_',' ').title()+': '+shown)
                    return ' · '.join(parts)
                r['details'] = readable(payload) or r['event']
        return rows

    def snapshot(self, ident):
        with self.db.read_snapshot():
            value=self._snapshot(ident)
            if not self.s.may('view_internal_cost'):
                from .inventory import public_values
                value=public_values(value)
            return value

    def _snapshot(self, ident):
        j = self.s.job(ident)
        data = json.loads(j['lifecycle_data'])
        holdings = self.holdings(ident)
        devices = [h for h in holdings if h['type'] == 'device' and not h['location'].startswith('exception:')]
        names = {'shop': 'IN SHOP', 'staff': 'IN SHOP', 'technician': 'IN SHOP · TECHNICIAN',
                 'vendor': 'THIRD-PARTY TECHNICIAN', 'centre': 'AUTHORIZED SERVICE CENTER',
                 'transit': 'IN TRANSIT', 'customer': 'WITH CUSTOMER'}
        locations = sorted({h['location'] for h in devices})
        data['in_transit']=any(h['location'].startswith('transit:') for h in devices)
        # A person holding an item reads as their name, not as the raw identity token.
        def place(value):
            kind=value.split(':')[0]
            label=names.get(kind,value)
            if kind in ('staff','technician'):
                return label+' · '+self.s.custodian(value)['name']
            return label+(': '+value.split(':',1)[1] if ':' in value else '')
        location = ' / '.join(place(v) for v in locations) or 'LOCATION NEEDS REVIEW'
        assignment = self.db.one('''SELECT a.*,m.name AS party,m.contact,m.details,COALESCE(tm.name,u.name) AS technician FROM assignments a
            LEFT JOIN masters m ON m.id=a.contact_id LEFT JOIN users u ON u.id=a.technician_id LEFT JOIN masters tm ON tm.id=a.technician_master_id WHERE a.id=?''', (j['assignment_id'],)) or {}
        try:
            profile=json.loads(assignment.get('details') or '{}')
        except ValueError:
            profile={}
        if isinstance(profile,dict) and profile:
            assignment['details']=' · '.join(k.replace('_',' ').title()+': '+str(val) for k,val in profile.items() if val)
        away = any(not in_shop(v) and v != 'customer' for v in locations)
        at_shop = bool(devices) and all(in_shop(h['location']) for h in devices)
        responsible = (j['customer'] if locations == ['customer'] else
            assignment.get('party') if j['route']!='in_house' else assignment.get('technician')) or 'Shop counter · assignment needed'
        if away and data.get('route_details',{}).get('contact_person') and not any(v.startswith('transit:') for v in locations):
            responsible=data['route_details']['contact_person']+' · '+(assignment.get('party') or 'External repairer')
        elif away and isinstance(profile,dict) and profile.get('contact_person') and not any(v.startswith('transit:') for v in locations):
            responsible=profile['contact_person']+' · '+(assignment.get('party') or 'External repairer')
        quotes = self.db.one('SELECT * FROM quotes WHERE job_id=? ORDER BY version DESC LIMIT 1', (ident,)) or {}
        warranty = self.db.one('SELECT * FROM warranty WHERE job_id=? ORDER BY id DESC LIMIT 1', (ident,)) or {}
        finances = self.db.one("SELECT COALESCE(sum(amount),0) balance,COALESCE(sum(CASE WHEN kind='invoice' THEN amount ELSE 0 END),0) billed FROM entries WHERE account_type='customer' AND job_id=?", (ident,))
        receipts = self.db.one("""SELECT -COALESCE(sum(e.amount),0) paid FROM entries e LEFT JOIN entries o ON o.id=e.reverses_id
            WHERE e.account_type='customer' AND e.job_id=? AND (e.kind IN ('receipt','refund') OR (e.kind='reversal' AND o.kind IN ('receipt','refund')))""", (ident,))['paid']
        events = self.timeline(ident)
        changes = [e for e in events if e['action'] in ('received','lifecycle','stage_changed','quote_issued','quote_decision','custody_moved')]
        pending = changes[-1]['created'] if changes else j['received']
        for e in reversed(changes):
            p = json.loads(e['payload'])
            if e['action'] != 'lifecycle' or p.get('before') != p.get('after'):
                pending = e['created']
                break
        stage = j['stage']
        actions = self.allowed(j, data, away, quotes)
        if j['lifecycle_version'] and stage in ('final_qc','billing','ready_repaired','ready_unrepaired') and any(h['location'].startswith(('centre:','vendor:','transit:')) for h in holdings) and 'receive' not in actions:
            actions.append('receive')
        primary = actions[0] if actions else ''
        status = LABELS.get(stage, 'LEGACY STATUS: ' + stage)
        if stage == 'external_diagnosis':
            status = 'AT SERVICE CENTER · DIAGNOSIS' if j['route'] == 'warranty_centre' else 'WITH THIRD-PARTY TECHNICIAN · DIAGNOSIS'
        transit=any(v.startswith('transit:') for v in locations)
        technician_holds=any(v.startswith('technician:') for v in locations)
        def technician_name(location):
            token=location.split(':',1)[1]
            if token.startswith('master-'):
                row=self.db.one("SELECT name FROM masters WHERE id=? AND kind='technician'",(token[7:],))
            else:
                row=self.db.one('SELECT name FROM users WHERE id=?',(token,))
            return (row or {}).get('name',location)
        # "Currently with" names the responsible person, not a storage place.
        holders=[dict(self.s.custodian(v), location=v) for v in locations]
        for holder in holders:
            if holder['kind']=='customer':holder['name']=j['customer']
        custodian=' / '.join(h['name'] for h in holders) or 'Not recorded'
        custodian_role=' / '.join(dict.fromkeys(h['role'] for h in holders))
        since=self.db.one('''SELECT max(m.happened) AS held FROM movements m JOIN items i ON i.id=m.item_id
            WHERE i.job_id=? AND m.to_location IN ('''+','.join('?' for _ in locations or [1])+')',
            (ident,*locations)) if locations else None
        custodian_since=(since or {}).get('held')
        destination=data.get('transit_destination','') if transit else ''
        if transit:
            status='RETURN DISPATCHED TO SHOP' if data.get('transit_direction')=='return' else 'DISPATCHED TO SERVICE CENTER' if j['route']=='warranty_centre' else 'DISPATCHED TO THIRD PARTY'
            location='IN TRANSIT'
        elif technician_holds:
            location='IN SHOP · '+data.get('technician_bench','Technician work area')
            if stage=='diagnosis':status='WITH IN-HOUSE TECHNICIAN · DIAGNOSIS'
        if not j['lifecycle_version']:
            status += ' · LEGACY'
        next_action = ACTIONS.get(primary, 'Review job history')
        if stage=='external_diagnosis' and not data.get('in_transit'):
            next_action='Wait for service center diagnosis' if j['route']=='warranty_centre' else 'Wait for vendor diagnosis'
        if stage=='under_repair' and j['route']!='in_house':
            next_action='Wait for service center repair result' if j['route']=='warranty_centre' else 'Wait for vendor repair result'
        if stage == 'approved' and j['deposit'] > receipts:
            next_action, primary = 'Collect required advance payment', 'payment'
        if stage in ('ready_repaired', 'ready_unrepaired'):
            primary = 'payment' if finances['balance'] else 'handover' if data.get('notified') else 'notify'
            next_action = 'Collect remaining payment' if finances['balance'] > 0 else 'Record refund due' if finances['balance'] < 0 else ACTIONS[primary]
        if j['hold_reason'] and stage not in ('closed','collected'):
            next_action, primary = 'Resolve hold: ' + j['hold_reason'], ''
        attention = []
        today_local = today()
        if stage == 'awaiting_approval' and quotes.get('valid_until') and quotes['valid_until'] < today_local:
            attention.append('Quotation expired on '+quotes['valid_until']+'; approval needs a revised estimate')
            if primary == 'decision':next_action='Record a decline or issue a revised estimate'
        if transit:
            next_action='Receive device from courier' if data.get('transit_direction')=='return' else 'Confirm service center arrival' if j['route']=='warranty_centre' else 'Confirm vendor arrival'
        if primary=='diagnose' and j['route']!='in_house':next_action='Wait for vendor diagnosis' if j['route']=='third_party' else 'Wait for service center diagnosis'
        planned=self.db.rows("SELECT name,source,stock_state,procurement_status FROM repair_parts WHERE job_id=? AND status='planned'",(ident,))
        for part in planned:
            if part['source']=='stock' and part['stock_state']!='issued':attention.append(part['name']+': '+('reserve shop stock' if part['stock_state'] in ('none','returned') else 'issue reserved stock to repairer'))
            if part['source']=='supplier' and part['procurement_status'] not in ('received','legacy'):attention.append(part['name']+': '+('order external part' if part['procurement_status']=='not_ordered' else 'receive external part'))
        if primary=='start_repair' and planned and any(p['source']=='stock' and p['stock_state']!='issued' or p['source']=='supplier' and p['procurement_status'] not in ('received','legacy') for p in planned):
            primary='parts';next_action='Reserve / issue shop parts or receive external parts'
        if stage not in ('closed','collected'):
            for field, label, relevant in [('return_due','External return overdue',away),('repair_due','Repair overdue',stage not in ('ready_repaired','ready_unrepaired')),('collection_due','Collection overdue',True)]:
                if relevant and j[field] and j[field] < today_local:
                    attention.append(label)
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(pending)).days
            except ValueError:
                age = 0
            if stage in ('awaiting_approval','waiting_parts') and age >= int(self.db.setting('lifecycle_attention_days', 3)):
                attention.append('Customer approval pending too long' if stage == 'awaiting_approval' else 'Parts pending too long')
            if stage in ('final_qc','testing'):
                attention.append('QC pending')
            if finances['balance'] > 0:
                attention.append('Payment pending: ' + rupees(finances['balance']))
            if finances['balance'] < 0 and stage in ('billing','ready_unrepaired','ready_repaired'):
                attention.append('Advance / refund to review: ' + rupees(-finances['balance']))
            if j['hold_reason']:
                attention.append('On hold: ' + j['hold_reason'])
            if not devices:
                attention.append('Physical device location needs review')
            if at_shop and any(h['type'] != 'device' and not in_shop(h['location']) and not h['location'].startswith('exception:') and h['location'] != 'customer' for h in holdings):
                attention.append('Accessories remain with an external holder')
        route_label=ROUTE_LABELS.get(j['route'],j['route'])
        if j['lifecycle_version'] and stage in ('received','inspection','warranty_check','route_selection'):
            route_label='NOT SELECTED · AFTER WARRANTY CHECK'
        card=self.db.one('SELECT sequence,kind FROM job_cards WHERE job_id=? ORDER BY sequence DESC LIMIT 1',(ident,))
        from .warranties import Warranties
        part_warranties=Warranties(self.s).rows(j['device_id'])
        active=sum(r['effective_status']=='ACTIVE' for r in part_warranties)
        claims=self.db.one("SELECT count(*) n FROM warranty_claims WHERE new_job_id=? AND status!='CLOSED'",(ident,))['n']
        if claims and stage=='collected':
            primary,next_action='claim','Resolve and close the warranty claim'
            actions.insert(0,'claim')
        from .dispatch import Dispatches
        dispatch=Dispatches(self.s).current(ident)
        visit=self.db.one('SELECT number FROM visits WHERE id=?',(j['visit_id'],)) if j['visit_id'] else None
        return dict(j, data=data, route_label=route_label, current_status=status,
            dispatch=dispatch, visit_number=(visit or {}).get('number',j['intake_ref']),
            current_card=f"CARD-{card['sequence']:02d} · {card['kind'].replace('_',' ')}" if card else 'LEGACY · no issued card',
            warranty_indicator=f"{active} active warranties · {sum(r['effective_status']=='CLAIM IN PROGRESS' for r in part_warranties)} claims in progress · {claims} unclosed claims",open_claims=claims,
            current_custodian=custodian,custodian_role=custodian_role,custodian_since=custodian_since,
            custodians=holders,received_by=self.db.one('SELECT name FROM users WHERE id=?',(j['actor'],) ) or {},
            final_destination=destination,assigned_technician=(assignment.get('technician') or 'Not assigned') if j['route']=='in_house' else 'Not applicable',
            current_location=location, responsible=responsible, pending_since=local_time(pending), pending_raw=pending,
            next_action=next_action, primary=primary, actions=actions, attention=attention, at_shop=at_shop, away=away,
            assignment=assignment, quote=quotes, warranty=warranty, warranty_status=data.get('warranty_status','Unknown / requires verification'),
            balance=finances['balance'], paid=receipts, holdings=holdings, timeline=events,
            tracker=self.tracker(j, data, events))

    def allowed(self, j, data, away, quote):
        if not j['lifecycle_version']:
            return [] if j['stage'] == 'closed' else ['adopt']
        stage = j['stage']
        by_stage = {
            'received': ['inspect'], 'inspection': ['inspection_done'], 'warranty_check': ['verify_warranty'],
            'route_selection': ['select_route'], 'ready_dispatch': ['dispatch' if data.get('dispatch') else 'prepare_dispatch'],
            'external_diagnosis': ['arrive' if data.get('in_transit') else 'diagnose'],
            'diagnosis': ['diagnose'], 'awaiting_estimate': ['quote'], 'awaiting_approval': ['decision','quote'],
            'approved': ['start_repair','payment'], 'waiting_parts': ['parts_received'],
            'under_repair': ['complete_repair','repair_failed'], 'technician_testing': ['test'],
            'awaiting_return': ['receive'], 'return_unrepaired': ['receive'] if away else ['qc'],
            'final_qc': ['qc'], 'testing': ['qc'], 'billing': ['bill'],
            'ready_repaired': ['handover','notify','payment','rework'], 'ready_unrepaired': ['handover','notify','payment'],
            'collected': ['close'], 'closed': []}
        actions = by_stage.get(stage, [])[:]
        if stage=='approved' and quote.get('state')!='approved' and self.db.one("SELECT 1 FROM repair_parts WHERE job_id=? AND status!='removed'",(j['id'],)):
            actions.insert(0,'quote')
        if stage in ('awaiting_estimate','approved') and j['route'] == 'in_house':
            actions.append('wait_parts')
        if j['route'] == 'warranty_centre' and stage in ('awaiting_estimate','approved'):
            if stage == 'awaiting_estimate' and not data.get('warranty_decided'):
                actions.insert(0,'warranty_result')
            else:
                actions.append('warranty_result')
        if j['route'] != 'in_house' and stage == 'under_repair':
            actions.append('replacement')
        if stage in ('diagnosis','awaiting_estimate','approved','ready_dispatch','return_unrepaired','final_qc') and not away:
            actions.append('change_route')
        if stage not in ('received','inspection','warranty_check','collected','closed','ready_repaired','ready_unrepaired','billing','final_qc','testing','return_unrepaired','awaiting_return'):
            actions.append('decline')
        if stage not in ('closed','collected'):
            actions.append('details')
            # Anyone in the shop holding the product can pass it to another authorized
            # person, whatever route the repair is on and whoever it is assigned to.
            if not away and self.db.one('''SELECT 1 FROM items i JOIN holdings h ON h.item_id=i.id
                WHERE i.job_id=? AND i.type='device' AND h.quantity>0 AND '''+sql_in_shop('h.location'),(j['id'],)):
                actions.append('hand_over')
            if self.s.may('resolve_exception'):
                actions.append('resolve_item')
            if away and stage in ('final_qc','billing','ready_repaired','ready_unrepaired'):
                actions.append('receive')
        if j['route']!='in_house' and stage in ('awaiting_return','return_unrepaired') and away:
            if not data.get('in_transit'):actions.append('return_dispatch')
        if j['route']=='in_house' and j['assignment_id']:
            technician_holds=self.db.one("SELECT 1 FROM items i JOIN holdings h ON h.item_id=i.id WHERE i.job_id=? AND i.type='device' AND h.quantity>0 AND h.location LIKE 'technician:%'",(j['id'],))
            if stage in ('diagnosis','approved','under_repair','technician_testing') and not away and not technician_holds:actions.insert(0,'hand_technician')
            if stage in ('final_qc','return_unrepaired') and technician_holds:actions.insert(0,'return_technician')
            elif stage in ('diagnosis','awaiting_estimate','approved','waiting_parts','under_repair','testing') and technician_holds:actions.append('return_technician')
        if data.get('in_transit'):
            if data.get('transit_direction')=='return':actions=['receive','details']
            elif stage=='external_diagnosis':actions=['arrive','details','decline']
        if stage not in ('closed','collected'):
            actions.append('parts');actions.append('manual_warranty')
            if self.s.may('view_internal_cost'):actions.append('costing')
        return list(dict.fromkeys(actions))

    def tracker(self, j, data, events):
        steps = [('received','Received'),('inspection','Initial inspection')]
        if not data.get('warranty_skipped'):
            steps.append(('warranty_check','Warranty check'))
        steps.append(('route_selection','Route selected'))
        intake_steps=len(steps)
        if j['route'] != 'in_house':
            steps += [('ready_dispatch','Service center dispatch' if j['route']=='warranty_centre' else 'Third-party dispatch'),('external_diagnosis','Service center diagnosis' if j['route']=='warranty_centre' else 'Vendor diagnosis')]
        else:
            steps += [('diagnosis','In-house diagnosis')]
        if j['lifecycle_version'] and j['stage'] in ('received','inspection','warranty_check','route_selection'):
            return [{'step':title,'state':'● CURRENT' if key==j['stage'] else '✓' if key in {'received','inspection','warranty_check'} and any(json.loads(e['payload']).get('before')==key and json.loads(e['payload']).get('before')!=json.loads(e['payload']).get('after') for e in events if e['action']=='lifecycle') else '○','key':key} for key,title in steps[:intake_steps]]
        if not data.get('unrepaired'):
            if not data.get('warranty_covered'):
                steps += [('awaiting_estimate','Estimate'),('awaiting_approval','Customer approval')]
            if data.get('parts_order'):
                steps += [('waiting_parts','Parts')]
            steps += [('under_repair','Repair')]
            if j['route']=='in_house':
                steps += [('technician_testing','Technician test')]
        else:
            steps += [('return_unrepaired','Return without repair')]
        if j['route'] != 'in_house':
            steps += [('awaiting_return','Device returned to shop')]
        steps += [('final_qc','Return condition check' if data.get('unrepaired') else 'Final shop QC'),('billing','Billing'),('ready_repaired','Ready for delivery'),('collected','Delivered'),('closed','Closed')]
        reached = set()
        for e in events:
            p = json.loads(e['payload'])
            if e['action'] == 'lifecycle' and p.get('action') != 'adopt' and p.get('before') != p.get('after'):
                reached.add(p.get('before'))
                if p.get('action') == 'decision':
                    reached.add('awaiting_approval')
                if p.get('action') in ('rework','change_route') or p.get('action') in ('qc','test') and p.get('after') in ('diagnosis','ready_dispatch'):
                    reached -= {'final_qc','technician_testing','billing','ready_repaired','ready_unrepaired','under_repair'}
        current = {'ready_unrepaired':'ready_repaired','testing':'final_qc'}.get(j['stage'],j['stage'])
        if 'ready_unrepaired' in reached:
            reached.add('ready_repaired')
        return [{'step': title,'state': '● CURRENT' if key==current else '✓' if key in reached else '○', 'key':key} for key,title in steps]

    def rows(self, search='', filter_key='', offset=0, limit=50):
        with self.db.read_snapshot():
            return self._rows(search,filter_key,offset,limit)

    def _rows(self, search='', filter_key='', offset=0, limit=50):
        self.s.require()
        attention_days = int(self.db.setting('lifecycle_attention_days', 3))
        external_device = "EXISTS(SELECT 1 FROM items i JOIN holdings h ON h.item_id=i.id WHERE i.job_id=j.id AND i.type='device' AND h.quantity>0 AND (h.location LIKE 'vendor:%' OR h.location LIKE 'centre:%' OR h.location LIKE 'transit:%'))"
        live_device = "EXISTS(SELECT 1 FROM items i JOIN holdings h ON h.item_id=i.id WHERE i.job_id=j.id AND i.type='device' AND h.quantity>0 AND h.location NOT LIKE 'exception:%')"
        device_outside_shop = "EXISTS(SELECT 1 FROM items i JOIN holdings h ON h.item_id=i.id WHERE i.job_id=j.id AND i.type='device' AND h.quantity>0 AND h.location NOT LIKE 'exception:%' AND NOT "+sql_in_shop('h.location')+")"
        external_accessory = "EXISTS(SELECT 1 FROM items i JOIN holdings h ON h.item_id=i.id WHERE i.job_id=j.id AND i.type!='device' AND h.quantity>0 AND (h.location LIKE 'vendor:%' OR h.location LIKE 'centre:%' OR h.location LIKE 'transit:%'))"
        customer_balance = "COALESCE((SELECT sum(e.amount) FROM entries e WHERE e.job_id=j.id AND e.account_type='customer'),0)"
        pending_since = "COALESCE((SELECT a.created FROM audit a WHERE a.entity='job' AND a.entity_id=j.id AND a.action IN ('received','lifecycle','stage_changed','quote_issued','quote_decision','custody_moved') AND (a.action!='lifecycle' OR json_extract(a.payload,'$.before') IS NOT json_extract(a.payload,'$.after')) ORDER BY a.created DESC,a.id DESC LIMIT 1),j.received)"
        # Comparisons use the date where the shop actually is, not the server's UTC date.
        local = repr(today())
        overdue = f"(j.collection_due<{local} OR (j.repair_due<{local} AND j.stage NOT IN ('ready_repaired','ready_unrepaired')) OR (j.return_due<{local} AND {external_device}))"
        attention = f"""(
            {overdue}
            OR j.stage IN ('final_qc','testing')
            OR (j.stage IN ('awaiting_approval','waiting_parts') AND julianday('now')-julianday({pending_since})>=?)
            OR (j.stage='awaiting_approval' AND (SELECT q.valid_until FROM quotes q WHERE q.job_id=j.id ORDER BY q.version DESC LIMIT 1)<{local})
            OR {customer_balance}>0
            OR (j.stage IN ('billing','ready_unrepaired','ready_repaired') AND {customer_balance}<0)
            OR j.hold_reason!=''
            OR NOT {live_device}
            OR ({live_device} AND NOT {device_outside_shop} AND {external_accessory})
            OR EXISTS(SELECT 1 FROM repair_parts p WHERE p.job_id=j.id AND p.status='planned' AND ((p.source='stock' AND p.stock_state!='issued') OR (p.source='supplier' AND p.procurement_status NOT IN ('received','legacy'))))
        )"""
        filters={
            'external_centre':"EXISTS(SELECT 1 FROM items i JOIN holdings h ON h.item_id=i.id WHERE i.job_id=j.id AND i.type='device' AND h.quantity>0 AND h.location LIKE 'centre:%')",
            'external_vendor':"EXISTS(SELECT 1 FROM items i JOIN holdings h ON h.item_id=i.id WHERE i.job_id=j.id AND i.type='device' AND h.quantity>0 AND h.location LIKE 'vendor:%')",
            'diagnosis':"j.stage IN ('diagnosis','inspection','external_diagnosis')",
            'ready':"j.stage IN ('ready_repaired','ready_unrepaired')",
            'in_house':"j.route='in_house' AND j.stage NOT IN ('received','inspection','warranty_check','route_selection')",
            'warranty_claims':"EXISTS(SELECT 1 FROM warranty_claims wc WHERE wc.new_job_id=j.id AND wc.status!='CLOSED')",
            'attention':attention,
            'overdue':overdue,
            'collected':"j.stage IN ('collected','closed')",
            'history':'1=1',
        }
        condition=filters.get(filter_key,'j.stage=?' if filter_key in LABELS else '1=1')
        condition_args=[]
        if filter_key=='attention':
            condition_args.append(attention_days)
        elif filter_key in LABELS and filter_key not in filters:
            condition_args.append(filter_key)
        # Every supported filter is now expressed in SQL. Apply LIMIT/OFFSET before
        # building expensive per-job snapshots so a 50-row screen does not project
        # every matching job in the database first.
        scope,scope_args=self.s.scope_jobs()
        params=list(('%'+search+'%',)*7)+( [filter_key] )+condition_args+scope_args
        sql="""SELECT j.id FROM jobs j JOIN customers c ON c.id=j.customer_id LEFT JOIN visits vi ON vi.id=j.visit_id
            WHERE (j.number LIKE ? OR c.name LIKE ? OR c.phone LIKE ? OR j.device LIKE ? OR j.serial LIKE ? OR j.intake_ref LIKE ? OR vi.number LIKE ?)
            AND (? IN ('history','collected','warranty_claims') OR j.stage NOT IN ('closed','collected')) AND """+condition+" AND "+scope+" ORDER BY j.id DESC"
        if limit:
            sql += " LIMIT ? OFFSET ?"
            params.extend((limit,offset))
        ids=self.db.rows(sql,tuple(params))
        result=[]
        for row in ids:
            v=self.snapshot(row['id'])
            result.append(dict(id=v['id'], number=v['number'],visit=v['visit_number'],customer=v['customer'],device=v['device'],device_id=v['device_id'],
                route=v['route_label'],status=v['current_status'],location=v['current_location'],responsible=v['responsible'],
                current_custodian=v['current_custodian'],final_destination=v['final_destination'],
                pending_since=v['pending_since'],expected_date=v['return_due'] if v['away'] else v['collection_due'] or v['repair_due'],
                balance=v['balance'],estimate=v['quote'].get('total',0),current_card=v['current_card'],warranty_indicator=v['warranty_indicator'],open_claims=v['open_claims'],next_action=v['next_action'],attention='; '.join(v['attention'])))
        return result

    def dashboard_counts(self):
        """Aggregate the full ledger in SQL; only project visible job rows in detail."""
        self.s.require()
        # The same job scope as the lists, so the headline numbers and the rows agree.
        scope,scope_args=self.s.scope_jobs()
        counts={r['stage']:r['n'] for r in self.db.rows(
            'SELECT j.stage,count(*) n FROM jobs j WHERE '+scope+' GROUP BY j.stage',tuple(scope_args))}
        result=dict(counts)
        result['diagnosis']=sum(counts.get(k,0) for k in ('diagnosis','inspection','external_diagnosis'))
        result['ready']=sum(counts.get(k,0) for k in ('ready_repaired','ready_unrepaired'))
        result['collected']=sum(counts.get(k,0) for k in ('collected','closed'))
        for key,prefix in [('external_centre','centre:%'),('external_vendor','vendor:%')]:
            result[key]=self.db.one("SELECT count(DISTINCT j.id) n FROM jobs j JOIN items i ON i.job_id=j.id JOIN holdings h ON h.item_id=i.id WHERE j.stage NOT IN ('collected','closed') AND i.type='device' AND h.quantity>0 AND h.location LIKE ? AND "+scope,(prefix,*scope_args))['n']
        result['warranty_claims']=self.db.one("SELECT count(DISTINCT wc.new_job_id) n FROM warranty_claims wc JOIN jobs j ON j.id=wc.new_job_id WHERE wc.status!='CLOSED' AND "+scope,tuple(scope_args))['n']
        result['in_house']=self.db.one("SELECT count(*) n FROM jobs j WHERE j.route='in_house' AND j.stage NOT IN ('received','inspection','warranty_check','route_selection','collected','closed') AND "+scope,tuple(scope_args))['n']
        today_local=today()
        result['overdue']=self.db.one("""SELECT count(*) n FROM jobs j WHERE stage NOT IN ('collected','closed') AND
            (collection_due<? OR (repair_due<? AND stage NOT IN ('ready_repaired','ready_unrepaired')) OR (return_due<? AND EXISTS(SELECT 1 FROM items i JOIN holdings h ON h.item_id=i.id WHERE i.job_id=j.id AND i.type='device' AND h.quantity>0 AND (h.location LIKE 'vendor:%' OR h.location LIKE 'centre:%' OR h.location LIKE 'transit:%')))) AND """+scope,(today_local,today_local,today_local,*scope_args))['n']
        return result

    def _set(self, c, j, data, stage, action, evidence):
        c.execute('UPDATE jobs SET stage=?,lifecycle_data=?,version=version+1 WHERE id=?', (stage,json.dumps(data),j['id']))
        self.s.audit(c,'job',j['id'],'lifecycle',dict(action=action,before=j['stage'],after=stage,evidence=evidence))

    def execute(self, ident, action, payload=None, version=None):
        p = payload or {}
        self.s.require()
        token = _command.set(True)
        try:
            with self.db.transaction() as c:
                j = dict(self.s._job(c,ident,version))
                v = self.snapshot(ident)
                data = json.loads(j['lifecycle_data'])
                data['in_transit']=v['data'].get('in_transit',False)
                if action not in v['actions']:
                    raise RuleError('That action is not available now. Refresh the job and follow the next required step.')
                # What each lifecycle step needs is stated once, in ACTION_PERMISSIONS,
                # rather than as a role name listed here.
                needed=ACTION_PERMISSIONS.get(action)
                if needed:self.s.require_permission(needed)
                if j['hold_reason'] and action not in ('details','decline','resolve_item'):
                    raise RuleError('Resolve the recorded job hold before continuing.')
                stage = j['stage']
                notes = str(p.get('notes','')).strip()
                if action == 'adopt':
                    self.s.require_permission('assign_job')
                    if not p.get('confirmed') or not notes:
                        raise RuleError('Review the existing history and record why this legacy status is appropriate.')
                    if stage not in LABELS:
                        raise RuleError('Unknown legacy status: owner must review the record before conversion.')
                    c.execute('UPDATE jobs SET lifecycle_version=1 WHERE id=?',(ident,))
                    data['legacy_stage'] = stage
                    data['legacy_review'] = notes
                    # Preserve the stage and do not invent completed inspection/QC/approval evidence.
                    if stage in ('return_unrepaired','ready_unrepaired'):
                        data['unrepaired'] = j['outcome'] or notes
                    if stage in ('ready_repaired','ready_unrepaired'):
                        # Preserve the recorded legacy stage as evidence, then recheck readiness.
                        stage='final_qc'
                    if stage=='collected' and all(h['location']=='customer' or h['location'].startswith('exception:') for h in v['holdings']):
                        data['legacy_handover_verified']=notes
                elif action == 'inspect':
                    stage='inspection'
                elif action == 'inspection_done':
                    self._notes(notes)
                    self.s.record_work(ident,'inspection',p)
                    data['inspection']=notes
                    # A warranty assessment stage is only meaningful when the product
                    # actually had cover when it was collected. The decision uses the
                    # snapshot captured at intake, never today's date.
                    snapshot=intake_warranty(data)
                    if snapshot['eligible']:
                        stage='warranty_check'
                    else:
                        # Keep an unknown customer-reported status distinct from an
                        # explicitly expired/absent warranty while still skipping the
                        # Warranty Check stage as required by intake policy.
                        data['warranty_status']='unknown' if snapshot['status']=='UNKNOWN' else 'out_of_warranty'
                        data['warranty_skipped']=snapshot['reason']
                        self.s.audit(c,'job',ident,'warranty_stage_skipped',snapshot)
                        stage='route_selection'
                elif action == 'verify_warranty':
                    status=p.get('warranty_status')
                    if status not in ('under_warranty','out_of_warranty','unknown'):
                        raise RuleError('Select the warranty status.')
                    self._notes(notes)
                    data['warranty_status']=status
                    self.s.record_work(ident,'warranty_verification',p)
                    stage='warranty_check' if status=='unknown' else 'route_selection'
                elif action in ('select_route','change_route'):
                    # Choosing a route for the first time needs no extra confirmation:
                    # saving the form is the decision. Replacing an existing assignment
                    # still does, because it discards the current responsible party.
                    if action=='change_route' and not p.get('confirmed'):
                        raise RuleError('Confirm the replacement of the current repair assignment before changing the route.')
                    if not v['at_shop']:
                        raise RuleError('Receive the physical device at the shop before assigning this repair route.'
                            if action=='select_route' else 'Receive the physical device at the shop before changing its repair route.')
                    route=p.get('route')
                    status=data.get('warranty_status')
                    if status not in ('under_warranty','out_of_warranty','shop_warranty','unknown'):
                        raise RuleError('Record the intake warranty status first. Use the warranty details action for a legacy job.')
                    if status=='under_warranty' and route!='warranty_centre' and v['warranty'].get('decision') not in ('rejected','partial'):
                        raise RuleError('Valid manufacturer warranty uses an authorized service center. Record a rejection before selecting a paid route.')
                    if route=='warranty_centre' and status!='under_warranty':
                        raise RuleError('Verify manufacturer warranty before selecting its authorized service center.')
                    if route!='in_house':
                        party=c.execute('SELECT * FROM masters WHERE id=? AND active=1',(p.get('contact_id'),)).fetchone()
                        if not party or party['kind']!=('centre' if route=='warranty_centre' else 'vendor'):
                            raise RuleError('Select an active authorized service center.' if route=='warranty_centre'
                                else 'Select an active third-party repairer.')
                    technician_master=p.get('technician_master_id')
                    legacy_technician=p.get('technician_id')
                    if route=='in_house':
                        if technician_master:
                            if not c.execute("SELECT 1 FROM masters WHERE id=? AND kind='technician' AND active=1",(technician_master,)).fetchone():
                                raise RuleError('Assign an active technician from the Technician directory.')
                        elif not legacy_technician or not c.execute('SELECT 1 FROM users WHERE id=? AND active=1',(legacy_technician,)).fetchone():
                            raise RuleError('Assign an active shop technician.')
                    if any(h['location'].startswith('technician:') for h in v['holdings'] if h['type']=='device'):
                        raise RuleError('Return the device from the current technician before changing assignment.')
                    if c.execute("SELECT 1 FROM repair_parts WHERE job_id=? AND stock_state='issued'",(ident,)).fetchone():
                        raise RuleError('Return issued shop parts before changing repairer.')
                    for part in c.execute("SELECT supplier_id FROM repair_parts WHERE job_id=? AND source='technician' AND status='planned'",(ident,)):
                        if route!='third_party' or part[0]!=p.get('contact_id'):raise RuleError('Remove or revise the old repairing-vendor parts before changing vendor.')
                    self.s.assign(ident,route,p.get('contact_id') if route!='in_house' else None,legacy_technician if route=='in_house' else None,technician_master_id=technician_master if route=='in_house' else None,reference=p.get('reference',''))
                    data['custody_version']=2
                    data['in_transit']=False;data.pop('transit_direction',None);data.pop('transit_destination',None)
                    if route=='in_house' and p.get('handed_over'):
                        from .custody import DeviceCustody
                        DeviceCustody(self.s).technician(c,dict(self.s._job(c,ident)),data,p)
                    if data.pop('dispatch',None) is not None:
                        # A not-yet-sent dispatch belongs to the replaced assignment.
                        from .dispatch import Dispatches
                        Dispatches(self.s).close(c,j,'CANCELLED')
                    data.pop('dispatch_id',None)
                    data.pop('diagnosis',None)
                    data.pop('unrepaired',None)
                    data.pop('qc',None)
                    data.pop('warranty_covered',None)
                    data.pop('warranty_decided',None)
                    data.pop('parts_order',None)
                    data.pop('billing_checked',None)
                    data.pop('notified',None)
                    stage='diagnosis' if route=='in_house' else 'ready_dispatch'
                elif action == 'prepare_dispatch':
                    if not v['assignment'].get('contact_id'):
                        raise RuleError('Select an external repairer first.')
                    if not p.get('consent') or not p.get('condition'):
                        raise RuleError('Record customer dispatch consent and the device condition.')
                    selected=set(p.get('items',[]))
                    chosen=[h for h in v['holdings'] if h['id'] in selected and in_shop(h['location'])]
                    if not any(h['type']=='device' for h in chosen):
                        raise RuleError('Select the physical device and only the accessories being sent.')
                    data['dispatch']=dict(p,items=sorted(selected))
                    c.execute('UPDATE jobs SET assessment_consent=1,return_due=? WHERE id=?',(day(p.get('expected_return')),ident))
                    from .dispatch import Dispatches
                    data['dispatch_id']=Dispatches(self.s).prepare(c,j,dict(
                        contact_id=v['assignment']['contact_id'],reference=p.get('reference',''),
                        transport_mode=p.get('transport_mode') or ('COURIER' if p.get('carrier','').strip() else 'BY_HAND'),
                        transport=p.get('transport') or ({'courier_name':p['carrier'].strip()} if p.get('carrier','').strip() else {}),
                        amount=p.get('amount',0),paid_by=p.get('paid_by','shop'),expected_return=day(p.get('expected_return')),
                        condition=p.get('condition',''),notes=p.get('notes',''),
                        manifest=sorted(selected),consent=True))
                elif action in ('dispatch','arrive','receive','return_dispatch'):
                    stage=self._custody(c,j,data,v,action,p)
                elif action in ('hand_technician','return_technician'):
                    from .custody import DeviceCustody
                    DeviceCustody(self.s).technician(c,j,data,p,returning=action=='return_technician')
                elif action=='hand_over':
                    from .custody import DeviceCustody
                    DeviceCustody(self.s).handover(c,j,data,p)
                elif action == 'diagnose':
                    self._notes(notes)
                    if not v['at_shop'] and j['route']=='in_house':
                        raise RuleError('The device must be in the shop for in-house diagnosis.')
                    self.s.record_work(ident,'diagnosis',p)
                    data['diagnosis']=notes
                    data['parts_required']=p.get('parts','')
                    data['parts_available']=p.get('parts_available',True)
                    if p.get('repairable',True):
                        stage='awaiting_estimate'
                    else:
                        data['unrepaired']='Not repairable: '+notes
                        stage='return_unrepaired'
                elif action == 'warranty_result':
                    self.s.record_warranty(ident,p.get('decision'),p.get('rma',''),notes,p.get('covered',''),p.get('excluded',''),p.get('terms',''))
                    data['warranty_covered']=p.get('decision')=='accepted'
                    data['warranty_decided']=p.get('decision') in ('accepted','rejected','partial')
                    stage='approved' if data['warranty_covered'] else 'awaiting_estimate'
                elif action == 'wait_parts':
                    self._notes(notes)
                    data['parts_order']=notes
                    data['parts_resume']=stage
                    data['parts_available']=False
                    self.s.record_work(ident,'parts_order',p)
                    stage='waiting_parts'
                elif action == 'parts_received':
                    self._notes(notes)
                    data['parts_available']=True
                    self.s.record_work(ident,'parts_received',p)
                    stage=data.get('parts_resume','awaiting_estimate')
                elif action == 'start_repair':
                    if not data.get('diagnosis') and not c.execute("SELECT 1 FROM work WHERE job_id=? AND kind='diagnosis'",(ident,)).fetchone():
                        raise RuleError('Record diagnosis before starting repair.')
                    if j['route']=='in_house' and (not v['at_shop'] or not data.get('parts_available',True)):
                        raise RuleError('Receive the device and required parts before starting in-house repair.')
                    if j['route']!='in_house' and not v['away']:
                        raise RuleError('Dispatch the device to the assigned repairer before authorizing external repair.')
                    if j['route']=='in_house' and data.get('custody_version')==2 and not any(h['type']=='device' and h['location'].startswith('technician:') for h in v['holdings']):raise RuleError('Record physical handover to the assigned technician before starting repair.')
                    self.s._authorize_repair(c,j)
                    data['repair_started']=now()
                    data.pop('qc',None)
                    c.execute("UPDATE jobs SET test_result='' WHERE id=?",(ident,))
                    stage='under_repair'
                elif action in ('complete_repair','replacement'):
                    self._notes(notes)
                    if c.execute("SELECT 1 FROM repair_parts WHERE job_id=? AND status='planned'",(ident,)).fetchone():
                        raise RuleError('Record installation of used parts, or remove unused planned parts and revise approval before completing repair.')
                    self.s.record_work(ident,'repair',p)
                    data['repair_summary']=notes
                    data['parts_used']=p.get('parts','')
                    data['repair_completed']=now()
                    data.pop('unrepaired',None)
                    if action=='replacement':
                        self.s.require_permission('record_replacement')
                        original=next((h for h in v['holdings'] if h['type']=='device' and h['location'].startswith(('centre:','vendor:'))),None)
                        if not original:
                            raise RuleError('The original device must be recorded with the external repairer.')
                        self.s.replacement(original['id'],p.get('description',''),p.get('serial',''),original['location'],p.get('terms',''),notes)
                        data['replacement']={'description':p.get('description',''),'serial':p.get('serial',''),'terms':p.get('terms','')}
                        self.s.move(original['id'],original['quantity'],original['location'],'exception:Replaced by repairer',v['assignment']['party'],uuid.uuid4().hex,notes=notes)
                    stage='technician_testing' if j['route']=='in_house' else 'awaiting_return'
                elif action in ('decline','repair_failed'):
                    self._notes(notes)
                    data['unrepaired']=p.get('reason','Repair unsuccessful' if action=='repair_failed' else 'Customer declined')+': '+notes
                    self.s.record_work(ident,'outcome',dict(p,outcome=data['unrepaired']))
                    stage='return_unrepaired'
                elif action == 'test':
                    self._notes(notes)
                    result=p.get('result')
                    if result not in ('passed','failed'):
                        raise RuleError('Record whether technician testing passed or failed.')
                    self.s.record_work(ident,'technician_test',p)
                    data['technician_test']=p
                    stage='final_qc' if result=='passed' else 'diagnosis'
                elif action == 'qc':
                    if not v['at_shop']:
                        raise RuleError('Receive the physical device back in the shop before final QC.')
                    if any(h['type']=='device' and h['location'].startswith('technician:') for h in v['holdings']):raise RuleError('Return the device from the technician to the QC area before final shop QC.')
                    self._notes(notes)
                    if data.get('unrepaired'):
                        if not p.get('condition_checked'):
                            raise RuleError('Check the device condition against intake before returning it unrepaired.')
                        result='checked_unrepaired'
                    else:
                        result=p.get('result')
                        checks=p.get('checks',{})
                        if result not in ('passed','failed'):
                            raise RuleError('Record a QC result.')
                        if result=='passed' and (any(checks.get(k)!='passed' for k in ('functional','power','complaint')) or any(checks.get(k) not in ('passed','not_applicable') for k in ('charging','display','connectivity'))):
                            raise RuleError('Pass the functional, power and original-complaint checks; record other checks as passed or not applicable.')
                    data['qc']=dict(p,result=result,created=now(),actor=self.s.user['name'])
                    data['repair_warranty']=p.get('repair_warranty','')
                    data['warranty_until']=day(p.get('warranty_until'))
                    c.execute('UPDATE jobs SET test_result=?,actual_completion=? WHERE id=?',(result,now() if result!='failed' else None,ident))
                    self.s.record_work(ident,'final_qc',data['qc'])
                    stage=('diagnosis' if j['route']=='in_house' else 'ready_dispatch') if result=='failed' else 'billing'
                    if result=='failed':
                        data.pop('dispatch',None)
                        data.pop('billing_checked',None)
                        data.pop('notified',None)
                elif action == 'bill':
                    if not data.get('qc') or data['qc']['result']=='failed':
                        raise RuleError('Complete final QC or the unrepaired return check first.')
                    self._billing(c,j,data,p)
                    data['billing_checked']=True
                    stage='ready_unrepaired' if data.get('unrepaired') else 'ready_repaired'
                    c.execute('UPDATE jobs SET outcome=? WHERE id=?',(data.get('unrepaired',data.get('repair_summary','')),ident))
                elif action == 'handover':
                    self._handover(c,j,data,v,p)
                    stage='collected'
                elif action == 'close':
                    if c.execute("SELECT 1 FROM warranty_claims WHERE new_job_id=? AND status!='CLOSED'",(ident,)).fetchone():
                        raise RuleError('Resolve and close the warranty claim in the Warranty tab before closing this job.')
                    if not data.get('handover') and not j['actual_collection'] and not data.get('legacy_handover_verified'):
                        raise RuleError('Complete and record device handover before closing the job.')
                    if any(h['location']!='customer' and not h['location'].startswith('exception:') for h in v['holdings']):
                        raise RuleError('Return or explicitly resolve all accessories before closing.')
                    stage='closed'
                elif action == 'rework':
                    self._notes(notes)
                    data.pop('qc',None)
                    data.pop('billing_checked',None)
                    data.pop('notified',None)
                    c.execute("UPDATE jobs SET test_result='' WHERE id=?",(ident,))
                    self.s.record_work(ident,'customer_concern',p)
                    stage='diagnosis'
                elif action == 'notify':
                    self.s.notify(c,ident,'ready_unrepaired' if data.get('unrepaired') else 'ready_repaired', 'Your device is ready for collection '+('without repair. ' if data.get('unrepaired') else 'after final shop QC. ')+ 'Please contact the shop to arrange collection.')
                    data['notified']=now()
                elif action == 'details':
                    if set(p)&{'vendor_parts','vendor_labour','transport_cost','other_cost','service_center_charge','in_house_cost','estimated_parts','estimated_labour'}:self.s.require_permission('view_internal_cost')
                    if any(not isinstance(p[k],int) or p[k]<0 for k in ('vendor_parts','vendor_labour','transport_cost','other_cost','customer_price') if k in p):
                        raise RuleError('Enter nonnegative estimates in whole paise.')
                    data.setdefault('route_details',{}).update(p)
                    if p.get('warranty_status') in ('under_warranty','out_of_warranty','unknown') and data.get('legacy_review'):
                        data['warranty_status']=p['warranty_status']
                    if 'expected_return' in p:
                        c.execute('UPDATE jobs SET return_due=? WHERE id=?',(day(p['expected_return']),ident))
                    self.s.record_work(ident,'route_update',p)
                elif action == 'resolve_item':
                    self.s.require_permission('resolve_exception')
                    self._notes(notes)
                    h=next((h for h in v['holdings'] if h['id']==p.get('item_id') and h['location']==p.get('source')),None)
                    if not h or h['location']=='customer' or h['location'].startswith('exception:'):
                        raise RuleError('Select an outstanding item and its actual holder.')
                    self.s.move(h['id'],p.get('quantity',h['quantity']),h['location'],'exception:Owner resolved',p.get('counterparty','Owner'),uuid.uuid4().hex,notes=notes,reference=p.get('reference',''))
                else:
                    raise RuleError('Use the quotation or payment form for this action.')
                self._set(c,j,data,stage,action,p)
        finally:
            _command.reset(token)
        # Only after the lifecycle transaction has committed: the customer is never told
        # about a repair step that failed to save.
        if action=='complete_repair':
            self.s.announce('completion', ident, data.get('repair_completed') or action,
                            'Your repair is complete. The summary of work and warranty is attached.',
                            'warranty_summary')

    @staticmethod
    def _notes(notes):
        if not notes:
            raise RuleError('Record findings or notes before continuing.')

    def _custody(self,c,j,data,v,action,p):
        from .custody import DeviceCustody
        return DeviceCustody(self.s).external(c,j,data,v,action,p)

    def _billing(self,c,j,data,p):
        self.s.require_permission('billing')
        if not p.get('confirmed'):
            raise RuleError('Review charges, advances and the balance before marking ready.')
        invoice=c.execute("SELECT * FROM entries e WHERE job_id=? AND kind='invoice' AND NOT EXISTS(SELECT 1 FROM entries r WHERE r.reverses_id=e.id)",(j['id'],)).fetchone()
        if data.get('unrepaired'):
            expected=self.s.decline_balance(j['id'])['agreed_charges']
            if invoice and invoice['amount']!=expected:
                raise RuleError('Review and reverse the prior repair invoice before issuing agreed return charges.')
            if expected and not invoice:
                # Existing decline billing expects an unrepaired status.
                c.execute("UPDATE jobs SET stage='return_unrepaired' WHERE id=?",(j['id'],))
                self.s.bill_decline(j['id'],uuid.uuid4().hex)
        else:
            from .parts import Parts
            Parts(self.s).validate_approval(c,j)
            q=c.execute('SELECT * FROM quotes WHERE job_id=? ORDER BY version DESC LIMIT 1',(j['id'],)).fetchone()
            if q:
                if q['state']!='approved':
                    raise RuleError('The current customer quote needs approval before final billing.')
                if invoice and invoice['quote_id']!=q['id']:
                    raise RuleError('Review the previous bill before billing a revised quote.')
                if q['total'] and not invoice:
                    self.s.invoice(q['id'],uuid.uuid4().hex)
            elif not data.get('warranty_covered'):
                raise RuleError('Record an approved estimate, including a zero-cost estimate, or an accepted warranty decision.')

    def _handover(self,c,j,data,v,p):
        self.s.require_permission('customer_delivery')
        if not all(p.get(k) for k in ('demonstrated','accepted','accessories_returned','payment_checked')):
            raise RuleError('Confirm demonstration, customer acceptance, accessories and payment review.')
        if not p.get('received_by') or not p.get('acknowledgment'):
            raise RuleError('Record who received the device and their acknowledgment.')
        if not data.get('qc') or data['qc']['result']=='failed' or not data.get('billing_checked'):
            raise RuleError('Complete final QC and billing review before handover.')
        if v['balance']>0:
            # Releasing a product with money still owed is an owner decision.
            self.s.require_permission('release_with_balance')
            if not p.get('credit_reason'):
                raise RuleError('Record remaining payment, or have the owner explicitly approve credit with a reason.')
        if v['balance']<0:
            raise RuleError('Resolve the customer refund / credit balance before handover.')
        rows=[h for h in v['holdings'] if h['location']!='customer' and not h['location'].startswith('exception:')]
        if not rows or any(not in_shop(h['location']) for h in rows):
            raise RuleError('Receive every device and accessory at the shop before customer handover.')
        # Recheck billing even if another screen changed the current quote or invoice.
        self._billing(c,j,data,{'confirmed':True})
        for h in rows:
            self.s.move(h['id'],h['quantity'],h['location'],'customer',p['received_by'],uuid.uuid4().hex,
                condition=p.get('condition','Checked against intake'),notes=p.get('notes',''),acknowledgment=p['acknowledgment'])
        data['handover']=dict(p,delivered_at=now(),delivered_by=self.s.user['name'])
        from .job_cards import JobCards
        JobCards(self.s).issue(j['id'],'customer_delivery','delivery:'+str(j['id']),p,rows)
        c.execute('UPDATE jobs SET actual_collection=? WHERE id=?',(data['handover']['delivered_at'],j['id']))
