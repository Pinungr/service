"""What each role is allowed to do, in one place.

Services ask for a permission, never for a role, so adding or retuning a role is a change
to this table rather than an edit spread across a hundred service methods.

Granularity matters: a technician may take a product in at the counter without thereby
being able to see shop margins, other technicians' repairs, settings or the ledger.
"""

#: Every permission the application checks. Keep this list as the authority; a typo in a
#: service call is then a startup-visible error rather than a silent allow.
PERMISSIONS = (
    'intake',               # receive a product and create the repair job
    'customer_records',     # create or correct customers, devices and their photos
    'customer_export',      # open/share the complete customer-safe filesystem package
    'assign_job',           # choose the route and who is responsible for the repair
    'handover',             # record a physical custody movement
    'repair',               # diagnosis, repair progress, technician testing
    'manage_parts',         # plan, procure and install repair parts
    'manage_warranty',      # manufacturer warranty checks, claims and repair warranties
    'correct_warranty',     # override or amend a warranty record already on file
    'quality_check',        # final QC before a product is released
    'create_quote',         # issue or revise a customer quotation
    'approve_quote',        # record the customer's decision
    'billing',              # raise the customer bill
    'collect_payment',      # record money received or refunded
    'correct_finance',      # reverse a posted entry
    'release_with_balance', # hand a product over while money is still outstanding
    'financial_reports',    # dues, payments, margins and transport reporting
    'manage_inventory',     # receive, adjust and issue shop stock
    'messaging_admin',      # configure recipients and send account statements
    'cancel_records',       # cancel a visit or a prepared dispatch
    'resolve_exception',    # write an item off or otherwise resolve lost custody
    'record_replacement',   # accept a replacement unit in place of the original
    'customer_delivery',    # hand the product back to its owner
    'register_sale',        # record a product sale and see its customer price
    'view_all_jobs',        # see repairs that are not your own responsibility
    'view_internal_cost',   # purchase cost, vendor cost, margin
    'vendor_accounts',      # third-party payables
    'reports',
    'inventory',
    'directories',
    'messaging',
    'settings',
    'user_management',
    'backup_restore',
)

_COUNTER = {
    'intake', 'customer_records', 'customer_export', 'assign_job', 'handover', 'quality_check', 'repair',
    'manage_parts', 'manage_warranty',
    'create_quote', 'approve_quote', 'billing', 'collect_payment', 'customer_delivery',
    'view_all_jobs', 'reports', 'directories', 'messaging', 'register_sale',
}

#: A technician is operational staff: they take products in, decide who works on a
#: repair (including themselves), hand it over physically and do the work. Nothing
#: here exposes money, other people's repairs, or shop configuration.
_TECHNICIAN = {'intake', 'customer_records', 'assign_job', 'handover', 'repair'}

ROLES = {
    'owner': set(PERMISSIONS),
    'counter': _COUNTER,
    'technician': _TECHNICIAN,
}

assert all(p in PERMISSIONS for role in ROLES.values() for p in role), 'unknown permission in ROLES'


def allowed(role, permission):
    if permission not in PERMISSIONS:
        raise KeyError('Unknown permission: ' + str(permission))
    return permission in ROLES.get(role, ())


def granted(role):
    return set(ROLES.get(role, ()))
