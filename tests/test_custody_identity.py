"""The logged-in person receives the product; assignment and custody stay separate.

There is no front office and no office-storage default custodian. Whoever is signed in
when the customer hands a product over becomes its receiver and first custodian, and the
product only moves to someone else when a real handover is recorded.
"""
import uuid
import pytest
from PyQt6.QtGui import QImage, QColor
from repairshop.customer_records import CustomerRecords
from repairshop.domain import RuleError, in_shop, staff_custody
from repairshop.lifecycle import Lifecycle

ADDRESS = dict(address_line1='12 Station Road', address_line2='', pincode='411001',
               district='Pune', state='Maharashtra')


def staff(service, username, role='counter'):
    service.save_staff(username, username.title(), role, 'TestPassword123')
    return service.db.one('SELECT id FROM users WHERE username=?', (username,))['id']


def customer_of(service, name='Walk-in Owner', phone='9990007001'):
    ident = service.save_customer(name, phone, **ADDRESS)
    image = QImage(32, 32, QImage.Format.Format_RGB32)
    image.fill(QColor('#68a398'))
    CustomerRecords(service).save_photo(image, ident)
    return ident


def device_item(service, job):
    return service.db.one("SELECT id FROM items WHERE job_id=? AND type='device'", (job,))['id']


def where(service, job):
    return service.db.one("""SELECT h.location FROM holdings h JOIN items i ON i.id=h.item_id
        WHERE i.job_id=? AND i.type='device' AND h.quantity>0""", (job,))['location']


# ---- 1/2/3. the signed-in person receives and holds the product --------------

def test_intake_records_the_signed_in_user_as_receiver_and_first_custodian(service):
    customer = customer_of(service)
    job = service.intake(customer, 'Dell Laptop', 'No power', operation_id=uuid.uuid4().hex)
    me = service.user['id']
    assert service.job(job)['actor'] == me, 'received by the person who did the intake'
    assert where(service, job) == staff_custody(me), 'and they hold it'


def test_a_different_signed_in_user_becomes_that_intake_receiver(service):
    customer = customer_of(service)
    rahul = staff(service, 'rahul')
    service.login('rahul', 'TestPassword123')
    job = service.intake(customer, 'Samsung Mobile', 'No display', operation_id=uuid.uuid4().hex)
    assert service.job(job)['actor'] == rahul
    assert where(service, job) == staff_custody(rahul)


def test_the_intake_movement_runs_from_the_customer_to_that_person(service):
    customer = customer_of(service)
    job = service.intake(customer, 'Dell Laptop', 'No power', operation_id=uuid.uuid4().hex)
    move = service.db.one("""SELECT m.* FROM movements m JOIN items i ON i.id=m.item_id
        WHERE i.job_id=? AND i.type='device' ORDER BY m.id LIMIT 1""", (job,))
    assert move['from_location'] == 'customer'
    assert move['to_location'] == staff_custody(service.user['id'])
    assert move['actor'] == service.user['id']
    assert not service.db.rows("SELECT 1 FROM movements WHERE to_location LIKE 'shop:%'"), \
        'no artificial customer to office-storage movement is created'


def test_intake_never_asks_who_received_the_product(service):
    """The receiver is not an input: passing someone else is refused."""
    customer = customer_of(service)
    other = staff(service, 'rahul')
    with pytest.raises(RuleError, match='cannot be recorded as someone else'):
        service.intake(customer, 'Dell Laptop', 'No power', storage=staff_custody(other),
                       operation_id=uuid.uuid4().hex)


def test_a_shop_storage_place_can_no_longer_be_made_the_custodian(service):
    """There is no office storage: a product is always held by a person."""
    customer = customer_of(service)
    with pytest.raises(RuleError, match='storage place'):
        service.intake(customer, 'Dell Laptop', 'No power', storage='shop:Service shelf',
                       operation_id=uuid.uuid4().hex)
    assert not service.db.rows('SELECT id FROM jobs')


def test_no_storage_places_are_seeded_for_a_new_shop(service):
    assert service.db.rows("SELECT id FROM masters WHERE kind='storage'") == []


# ---- 5/6. assignment is not custody ------------------------------------------

def routed(service, customer, technician_user):
    job = service.intake(customer, 'Dell Laptop', 'No power', guided=True,
                         accessories=[dict(type='accessory', description='Charger', quantity=1)])
    life = Lifecycle(service)
    life.execute(job, 'inspect')
    life.execute(job, 'inspection_done', {'notes': 'Power fault'})
    life.execute(job, 'verify_warranty', {'warranty_status': 'out_of_warranty', 'notes': 'No cover'})
    life.execute(job, 'select_route', {'route': 'in_house', 'confirmed': True,
                                       'technician_id': technician_user})
    return job, life


def test_assigning_a_repair_does_not_move_the_product(service):
    customer = customer_of(service)
    receiver = service.user['id']
    amit = staff(service, 'amit', 'technician')
    job, life = routed(service, customer, amit)
    assert service.db.one('SELECT technician_id FROM assignments WHERE id=?',
                          (service.job(job)['assignment_id'],))['technician_id'] == amit
    assert where(service, job) == staff_custody(receiver), 'still with the person who received it'
    assert not service.db.rows("SELECT 1 FROM movements WHERE to_location LIKE 'technician:%'")


def test_custody_moves_only_when_the_handover_is_recorded(service):
    customer = customer_of(service)
    amit = staff(service, 'amit', 'technician')
    job, life = routed(service, customer, amit)
    life.execute(job, 'hand_technician', dict(bench='Bench 2', condition='Intact',
                                              acknowledgment='Technician signed'))
    assert where(service, job) == 'technician:' + str(amit)
    # The earlier custody is still in the ledger, not overwritten.
    history = [r['to_location'] for r in service.db.rows("""SELECT m.to_location FROM movements m
        JOIN items i ON i.id=m.item_id WHERE i.job_id=? AND i.type='device' ORDER BY m.id""", (job,))]
    assert history == [staff_custody(service.user['id']), 'technician:' + str(amit)]


# ---- 7/8/9. internal handover between authorized people ----------------------

def test_a_product_can_be_handed_to_another_member_of_staff(service):
    customer = customer_of(service)
    sneha = staff(service, 'sneha', 'counter')
    job = service.intake(customer, 'Dell Laptop', 'No power', guided=True)
    life = Lifecycle(service)
    assert 'hand_over' in life.snapshot(job)['actions']
    life.execute(job, 'hand_over', dict(to_user_id=sneha, condition='Intact',
                                        acknowledgment='Handed at the counter',
                                        notes='Going off shift'))
    assert where(service, job) == staff_custody(sneha)
    snapshot = life.snapshot(job)
    assert snapshot['current_custodian'] == 'Sneha'
    assert snapshot['custodian_role'] == 'Counter'


def test_the_previous_custodian_stays_in_the_ledger(service):
    customer = customer_of(service)
    me = service.user['id']
    sneha = staff(service, 'sneha', 'counter')
    job = service.intake(customer, 'Dell Laptop', 'No power', guided=True)
    Lifecycle(service).execute(job, 'hand_over', dict(to_user_id=sneha, condition='Intact',
                                                      acknowledgment='Handed over'))
    history = [(r['from_location'], r['to_location']) for r in service.db.rows("""SELECT m.from_location,
        m.to_location FROM movements m JOIN items i ON i.id=m.item_id
        WHERE i.job_id=? AND i.type='device' ORDER BY m.id""", (job,))]
    assert history == [('customer', staff_custody(me)), (staff_custody(me), staff_custody(sneha))]


def test_a_handover_records_who_performed_it_and_who_received_it(service):
    customer = customer_of(service)
    sneha = staff(service, 'sneha', 'counter')
    job = service.intake(customer, 'Dell Laptop', 'No power', guided=True)
    Lifecycle(service).execute(job, 'hand_over', dict(to_user_id=sneha, condition='Intact',
                                                      acknowledgment='Handed over'))
    import json
    event = json.loads(service.db.one("""SELECT payload FROM audit WHERE entity='job' AND entity_id=?
        AND action='custody_handed_over' ORDER BY id DESC""", (job,))['payload'])
    assert event['to'] == 'Sneha' and event['to_user_id'] == sneha
    assert event['by'] == 'Owner', 'the operator is taken from the session'


def test_an_inactive_user_cannot_be_handed_the_product(service):
    customer = customer_of(service)
    gone = staff(service, 'gone', 'counter')
    service.save_staff('gone', 'Gone', 'counter', ident=gone, active=False)
    job = service.intake(customer, 'Dell Laptop', 'No power', guided=True)
    with pytest.raises(RuleError, match='active member of staff'):
        Lifecycle(service).execute(job, 'hand_over', dict(to_user_id=gone, condition='Intact',
                                                          acknowledgment='Handed over'))


def test_the_receiver_may_keep_the_product_and_the_repair(service):
    """Self-assignment: nothing forces the product away from the person who took it in."""
    customer = customer_of(service)
    me = service.user['id']
    job, life = routed(service, customer, me)
    assert where(service, job) == staff_custody(me)
    assert life.snapshot(job)['assigned_technician'] == 'Owner'


# ---- 13. third-party return comes back to the person who receives it ---------

def test_a_third_party_return_goes_to_the_person_who_receives_it(service):
    customer = customer_of(service)
    job = service.intake(customer, 'Dell Laptop', 'No power', guided=True,
                         accessories=[dict(type='accessory', description='Charger', quantity=1)])
    life = Lifecycle(service)
    life.execute(job, 'inspect')
    life.execute(job, 'inspection_done', {'notes': 'Board fault'})
    life.execute(job, 'verify_warranty', {'warranty_status': 'out_of_warranty', 'notes': 'No cover'})
    vendor = service.save_master('vendor', 'ABC Repair', contact='9998887771', **ADDRESS)
    life.execute(job, 'select_route', {'route': 'third_party', 'confirmed': True, 'contact_id': vendor})
    life.execute(job, 'prepare_dispatch', dict(items=[r['id'] for r in life.holdings(job)], consent=True,
                                               condition='Intact', expected_return='2099-01-01'))
    life.execute(job, 'dispatch', dict(counterparty='Courier', condition='Intact', acknowledgment='D1'))
    life.execute(job, 'diagnose', dict(notes='Board fault', repairable=True))
    quote = service.issue_quote(job, 'Board repair',
                                [{'description': 'Board', 'amount': 500000, 'kind': 'part'}])
    service.decide_quote(quote, 'approved', 'Device owner', 'in_person')
    life.execute(job, 'start_repair')
    life.execute(job, 'complete_repair', dict(notes='Repaired', parts='Board'))
    # A different member of staff is on the counter when the vendor returns it.
    rahul = staff(service, 'rahul', 'counter')
    service.login('rahul', 'TestPassword123')
    life = Lifecycle(service)
    held = {h['id']: h['quantity'] for h in life.holdings(job)}
    life.execute(job, 'receive', dict(counterparty='Rahul', condition='Intact', acknowledgment='R1',
                                      repair_result='REPAIRED', items=list(held),
                                      quantities={str(k): v for k, v in held.items()},
                                      discrepancies=[], operation_id=uuid.uuid4().hex,
                                      received_by='Rahul'))
    assert where(service, job) == staff_custody(rahul), 'the receiving person becomes the custodian'
    assert not service.db.rows("SELECT 1 FROM movements WHERE to_location LIKE 'shop:%'")


# ---- 14. the lifecycle says who currently has it -----------------------------

def test_the_lifecycle_names_the_person_currently_holding_the_product(service):
    customer = customer_of(service)
    job = service.intake(customer, 'Dell Laptop', 'No power', guided=True)
    snapshot = Lifecycle(service).snapshot(job)
    assert snapshot['current_custodian'] == 'Owner'
    assert snapshot['custodian_role'] == 'Owner'
    assert snapshot['custodian_since']
    assert 'IN SHOP' in snapshot['current_location'] and 'Owner' in snapshot['current_location']
    assert snapshot['received_by']['name'] == 'Owner'


def test_external_and_customer_custody_still_read_correctly(service):
    assert service.custodian('vendor:ABC Laptop Services') == dict(
        name='ABC Laptop Services', kind='vendor', role='Third Party')
    assert service.custodian('centre:HP Care')['role'] == 'Authorized Service Center'
    assert service.custodian('customer')['name'] == 'Customer'


def test_a_storage_place_is_not_a_custody_value(service):
    """There is no office storage, so `shop:` is refused by the movement service itself."""
    from repairshop.domain import in_shop, sql_in_shop
    assert not in_shop('shop:Front desk')
    assert 'shop:' not in sql_in_shop('h.location')
    customer = customer_of(service)
    job = service.intake(customer, 'Dell Laptop', 'No power', operation_id=uuid.uuid4().hex)
    item = device_item(service, job)
    for destination in ('shop:Front Desk', 'shop:Service Shelf', 'shop:Office Storage'):
        with pytest.raises(RuleError, match='Invalid custody destination'):
            service.move(item, 1, where(service, job), destination, 'Someone', uuid.uuid4().hex)
    assert not service.db.rows("SELECT 1 FROM movements WHERE to_location LIKE 'shop:%'")
    assert not service.db.rows("SELECT 1 FROM holdings WHERE location LIKE 'shop:%'")


# ---- 18. identity comes from the session, never from the caller --------------

def test_an_operator_cannot_record_a_colleague_as_the_receiver(service):
    other = staff(service, 'rahul')
    with pytest.raises(RuleError, match='cannot be recorded as someone else'):
        service.receiving_custody(staff_custody(other))
    assert service.receiving_custody() == staff_custody(service.user['id'])
    assert service.receiving_custody(staff_custody(service.user['id'])) == staff_custody(service.user['id'])


def test_a_custody_destination_outside_the_shop_is_refused_for_a_receipt(service):
    for destination in ('vendor:Somebody', 'shop:Front desk', 'customer'):
        with pytest.raises(RuleError, match='cannot be recorded as someone else'):
            service.receiving_custody(destination)

# ---- 15. dashboard and filters follow custody, not a storage bucket ----------

def test_the_dashboard_counts_products_held_by_people_as_at_shop(service):
    from repairshop.queries import Queries
    customer = customer_of(service)
    job = service.intake(customer, 'Dell Laptop', 'No power', operation_id=uuid.uuid4().hex)
    counts = {(r['location'], r['type']): r['units'] for r in Queries(service).dashboard()['locations']}
    assert counts[('staff', 'device')] == 1, 'custody is recorded against the person'
    assert sum(counts.get((k, 'device'), 0) for k in ('shop', 'staff', 'technician')) == 1
    # The "at shop" filter finds it even though no storage place is involved.
    assert [r['id'] for r in Queries(service).jobs(location='shop:')] == [job]


def test_the_at_shop_filter_excludes_a_product_that_is_away(service):
    from repairshop.queries import Queries
    customer = customer_of(service)
    job = service.intake(customer, 'Dell Laptop', 'No power', assessment_consent=True,
                         operation_id=uuid.uuid4().hex)
    item = device_item(service, job)
    service.move(item, 1, where(service, job), 'vendor:ABC', 'ABC', uuid.uuid4().hex)
    assert Queries(service).jobs(location='shop:') == []
    assert [r['id'] for r in Queries(service).jobs(location='vendor:')] == [job]


# ---- 19. the audit trail reads as a sequence of real events ------------------

def test_the_audit_trail_shows_each_identity_separately(service):
    """Received by, assigned by, assigned to, handed over by and delivered by."""
    import json
    customer = customer_of(service)
    rahul = staff(service, 'rahul', 'counter')
    amit = staff(service, 'amit', 'technician')
    sneha = staff(service, 'sneha', 'counter')

    service.login('rahul', 'TestPassword123')
    job, life = routed(service, customer, amit)
    assert service.job(job)['actor'] == rahul, 'received by Rahul'
    assignment = service.db.one('SELECT * FROM assignments WHERE id=?',
                                (service.job(job)['assignment_id'],))
    assert assignment['actor'] == rahul, 'assigned by Rahul'
    assert assignment['technician_id'] == amit, 'assigned to Amit'
    assert where(service, job) == staff_custody(rahul), 'but Rahul still has it'

    life.execute(job, 'hand_technician', dict(bench='Bench 2', condition='Intact',
                                              acknowledgment='Amit signed'))
    handed = service.db.one("""SELECT m.* FROM movements m JOIN items i ON i.id=m.item_id
        WHERE i.job_id=? AND i.type='device' ORDER BY m.id DESC LIMIT 1""", (job,))
    assert handed['from_location'] == staff_custody(rahul)
    assert handed['to_location'] == 'technician:' + str(amit)
    assert handed['actor'] == rahul, 'recorded by Rahul, who physically passed it over'

    # Sneha takes over the counter and ends up delivering it.
    service.login('sneha', 'TestPassword123')
    life = Lifecycle(service)
    life.execute(job, 'return_technician', dict(condition='Intact', acknowledgment='Back at counter'))
    assert where(service, job) == staff_custody(sneha), 'the person taking it back now holds it'
    event = json.loads(service.db.one("""SELECT payload FROM audit WHERE entity='job' AND entity_id=?
        AND action='custody_moved' ORDER BY id DESC""", (job,))['payload'])
    assert event

    story = [(r['action'], r['actor']) for r in service.db.rows("""SELECT a.action,u.name AS actor
        FROM audit a LEFT JOIN users u ON u.id=a.actor
        WHERE a.entity='job' AND a.entity_id=? ORDER BY a.id""", (job,))]
    assert ('received', 'Rahul') in story
    assert any(action == 'custody_moved' and actor == 'Sneha' for action, actor in story)
