"""Who may do what, and whose identity gets recorded when they do it.

Permissions are granular on purpose: a technician can take a product in at the counter
without that giving them shop margins, settings, invoices or anyone else's repairs.
"""
import uuid
import pytest
from PyQt6.QtGui import QImage, QColor
from repairshop.customer_records import CustomerRecords
from repairshop.domain import RuleError, staff_custody
from repairshop.permissions import PERMISSIONS, ROLES, allowed

ADDRESS = dict(address_line1='12 Station Road', address_line2='', pincode='411001',
               district='Pune', state='Maharashtra')


def staff(service, username, role):
    service.save_staff(username, username.title(), role, 'TestPassword123')
    return service.db.one('SELECT id FROM users WHERE username=?', (username,))['id']


def customer_of(service, phone='9990009001'):
    ident = service.save_customer('Permission Owner', phone, **ADDRESS)
    image = QImage(32, 32, QImage.Format.Format_RGB32)
    image.fill(QColor('#68a398'))
    CustomerRecords(service).save_photo(image, ident)
    return ident


def where(service, job):
    return service.db.one("""SELECT h.location FROM holdings h JOIN items i ON i.id=h.item_id
        WHERE i.job_id=? AND i.type='device' AND h.quantity>0""", (job,))['location']


# ---- the table itself --------------------------------------------------------

def test_every_granted_permission_is_a_real_one():
    for role, granted in ROLES.items():
        assert granted <= set(PERMISSIONS), f'{role} grants an unknown permission'


def test_an_unknown_permission_is_a_loud_error_not_a_silent_allow(service):
    with pytest.raises(KeyError):
        allowed('owner', 'no_such_permission')
    with pytest.raises(KeyError):
        service.require_permission('no_such_permission')


def test_the_owner_can_do_everything_and_a_technician_cannot(service):
    assert ROLES['owner'] == set(PERMISSIONS)
    for denied in ('billing', 'collect_payment', 'view_internal_cost', 'settings',
                   'user_management', 'backup_restore', 'view_all_jobs', 'reports',
                   'vendor_accounts', 'register_sale', 'financial_reports', 'customer_export'):
        assert not allowed('technician', denied), f'technician must not have {denied}'
    # A technician is operational staff: they receive products and decide who repairs them.
    for granted in ('intake', 'handover', 'repair', 'customer_records', 'assign_job'):
        assert allowed('technician', granted)


# ---- 27. intake permission ---------------------------------------------------

@pytest.mark.parametrize('role', ['owner', 'counter', 'technician'])
def test_every_operational_role_can_take_a_product_in(service, role):
    customer = customer_of(service)
    if role != 'owner':
        staff(service, 'user_' + role, role)
        service.login('user_' + role, 'TestPassword123')
    job = service.intake(customer, 'Dell Laptop', 'No power', operation_id=uuid.uuid4().hex)
    me = service.user['id']
    assert service.job(job)['actor'] == me, 'received by the operator'
    assert where(service, job) == staff_custody(me), 'and held by them'


def test_an_inactive_user_cannot_take_anything_in(service):
    customer = customer_of(service)
    ident = staff(service, 'gone', 'counter')
    service.login('gone', 'TestPassword123')
    service.db.engine.dispose()
    with service.db.transaction() as c:
        c.execute('UPDATE users SET active=0 WHERE id=?', (ident,))
    with pytest.raises(RuleError, match='role cannot|sign in'):
        service.intake(customer, 'Dell Laptop', 'No power', operation_id=uuid.uuid4().hex)


def test_an_unauthenticated_caller_cannot_take_anything_in(service):
    customer = customer_of(service)
    service.user = None
    with pytest.raises(RuleError, match='sign in'):
        service.intake(customer, 'Dell Laptop', 'No power', operation_id=uuid.uuid4().hex)


def test_a_technician_taking_a_product_in_gains_nothing_else(service):
    customer = customer_of(service)
    staff(service, 'amit', 'technician')
    service.login('amit', 'TestPassword123')
    job = service.intake(customer, 'Dell Laptop', 'No power', operation_id=uuid.uuid4().hex)
    # Assigning is part of their job; money, configuration and staff admin are not.
    service.assign(job, 'in_house', technician_id=service.user['id'])
    for operation, permission in (
            (lambda: service.settings({'shop_name': 'Mine'}), 'settings'),
            (lambda: service.save_staff('x', 'X', 'counter', 'TestPassword123'), 'role'),
            (lambda: service.post('customer', customer, 'receipt', 100, uuid.uuid4().hex), 'collect payment')):
        with pytest.raises(RuleError):
            operation()


# ---- 28. impersonation -------------------------------------------------------

def test_the_receiver_of_an_intake_cannot_be_forged(service):
    customer = customer_of(service)
    other = staff(service, 'rahul', 'counter')
    with pytest.raises(RuleError, match='cannot be recorded as someone else'):
        service.intake(customer, 'Dell Laptop', 'No power', storage=staff_custody(other),
                       operation_id=uuid.uuid4().hex)


def test_a_forged_actor_field_is_ignored(service):
    """`actor` is not an intake field at all, so supplying one is refused outright."""
    customer = customer_of(service)
    other = staff(service, 'rahul', 'counter')
    with pytest.raises(RuleError, match='Unknown intake field'):
        service.intake(customer, 'Dell Laptop', 'No power', actor=other,
                       operation_id=uuid.uuid4().hex)
    job = service.intake(customer, 'Dell Laptop', 'No power', operation_id=uuid.uuid4().hex)
    assert service.job(job)['actor'] == service.user['id']


def test_a_handover_cannot_claim_a_colleague_performed_it(service):
    from repairshop.lifecycle import Lifecycle
    customer = customer_of(service)
    rahul = staff(service, 'rahul', 'counter')
    sneha = staff(service, 'sneha', 'counter')
    service.login('rahul', 'TestPassword123')
    job = service.intake(customer, 'Dell Laptop', 'No power', guided=True)
    Lifecycle(service).execute(job, 'hand_over', dict(to_user_id=sneha, condition='Intact',
                                                      acknowledgment='Signed',
                                                      handover_by_user_id=999, actor=999))
    move = service.db.one("""SELECT m.actor FROM movements m JOIN items i ON i.id=m.item_id
        WHERE i.job_id=? AND i.type='device' ORDER BY m.id DESC LIMIT 1""", (job,))
    assert move['actor'] == rahul, 'the operator comes from the session, not the payload'


def test_a_delivery_records_the_operator_from_the_session(service):
    """Rahul takes the product in; Sneha is the one who hands it back."""
    customer = customer_of(service)
    staff(service, 'rahul', 'counter')
    sneha = staff(service, 'sneha', 'counter')
    service.login('rahul', 'TestPassword123')
    job = service.intake(customer, 'Dell Laptop', 'No power', operation_id=uuid.uuid4().hex)
    item = service.db.one("SELECT id FROM items WHERE job_id=? AND type='device'", (job,))['id']
    service.stage(job, 'ready_repaired', reason='Checked and ready', test_result='passed')
    service.login('sneha', 'TestPassword123')
    service.move(item, 1, where(service, job), 'customer', 'Device owner', uuid.uuid4().hex,
                 acknowledgment='Signed')
    delivery = service.db.one("""SELECT m.actor,m.from_location,m.to_location FROM movements m
        JOIN items i ON i.id=m.item_id WHERE i.job_id=? ORDER BY m.id DESC LIMIT 1""", (job,))
    assert delivery['to_location'] == 'customer'
    assert delivery['actor'] == sneha, 'delivered by whoever was signed in'
    assert service.job(job)['actor'] != sneha, 'received by is still the person who took it in'

# ---- the permission table matches what the services actually enforce ---------

def test_privileged_operations_stay_with_the_owner(service):
    """Counter runs the counter; it does not get shop stock, margins or the vendor ledger."""
    for denied in ('manage_inventory', 'financial_reports', 'view_internal_cost',
                   'vendor_accounts', 'release_with_balance', 'messaging_admin',
                   'cancel_records', 'correct_finance', 'correct_warranty',
                   'settings', 'user_management', 'backup_restore'):
        assert not allowed('counter', denied), f'counter must not have {denied}'
        assert allowed('owner', denied)


def test_counter_keeps_the_counter_workflow(service):
    for granted in ('intake', 'assign_job', 'handover', 'create_quote', 'approve_quote',
                    'billing', 'collect_payment', 'customer_delivery', 'view_all_jobs',
                    'manage_parts', 'manage_warranty'):
        assert allowed('counter', granted), f'counter needs {granted}'


def test_every_service_permission_exists_in_the_table():
    """A typo in a service call would otherwise be an allow-by-accident."""
    import re
    import pathlib
    used = set()
    for path in pathlib.Path('repairshop').glob('*.py'):
        used |= set(re.findall(r"require_permission\('(\w+)'\)", path.read_text(encoding='utf-8')))
    assert used, 'expected the services to ask for permissions'
    assert used - set(PERMISSIONS) == set(), 'services ask for permissions that do not exist'


def test_no_service_still_hardcodes_a_role_list():
    import re
    import pathlib
    offenders = []
    for path in pathlib.Path('repairshop').glob('*.py'):
        for line in path.read_text(encoding='utf-8').splitlines():
            if re.search(r"""require\(['"](?:owner|counter|technician)""", line):
                offenders.append(path.name + ': ' + line.strip()[:70])
    assert offenders == [], 'role lists remain instead of permissions: ' + str(offenders)

# ---- lifecycle steps are gated by permission, not by a hardcoded role list ----

def test_a_technician_cannot_run_counter_only_lifecycle_steps(service):
    """The old rule was a hardcoded role list; the rule is now the permission table."""
    from repairshop.lifecycle import ACTION_PERMISSIONS
    from repairshop.permissions import allowed as may
    counter_only = {a for a, p in ACTION_PERMISSIONS.items() if not may('technician', p)}
    assert {'bill', 'payment', 'handover', 'decision', 'quote'} <= counter_only
    technician_can = {a for a, p in ACTION_PERMISSIONS.items() if may('technician', p)}
    assert {'diagnose', 'start_repair', 'complete_repair', 'hand_over', 'select_route'} <= technician_can
    assert 'bill' not in technician_can and 'costing' not in technician_can


def test_every_lifecycle_action_permission_is_real():
    from repairshop.lifecycle import ACTION_PERMISSIONS
    assert set(ACTION_PERMISSIONS.values()) <= set(PERMISSIONS)
