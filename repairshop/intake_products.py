"""Turn one product entered at the counter into the arguments of `Service.intake`.

Shared by every presentation layer, so a product received through the desktop window
and one received through the web counter are held to the same rules.
"""
from .domain import RuleError, money, paise

AMOUNTS = ('advance', 'deposit', 'transport_agreed', 'assessment_agreed', 'initial_estimate')
#: What the counter form collects about the customer-reported warranty.
WARRANTY_FIELDS = ('warranty_status', 'warranty_expiry', 'warranty_provider', 'warranty_notes')
#: Form-only keys that are not intake arguments.
FORM_ONLY = ('identity_unknown', 'no_accessories', 'storage_id', 'photo_role', 'visit_products')


def prepare_product(payload, amounts_in_paise=False):
    """Validate one counter product and shape it for `Service.intake` / `intake_visit`.

    Amounts arrive as rupee text and leave as whole paise. Only ticked accessories are
    received (`amounts_in_paise=True` when the caller already sends whole paise). The
    customer-reported warranty becomes the intake warranty snapshot; a
    linked shop sale always uses the sale's own recorded dates instead.
    """
    p = dict(payload)
    if 'warranty_status' in p:
        p['intake_warranty'] = dict(source='shop') if p.get('sale_id') else dict(
            source='shop_unlinked' if p.get('origin') == 'shop' else 'external',
            status=p.get('warranty_status') or 'UNKNOWN',
            expiry=p.get('warranty_expiry'), provider=p.get('warranty_provider', ''), notes=p.get('warranty_notes', ''))
    for key in WARRANTY_FIELDS + FORM_ONLY:
        p.pop(key, None)
    if not p.get('customer_id'):
        raise RuleError('Select or register the customer first.')
    if not p.get('photo_id'):
        raise RuleError('This customer has no saved photo. Add one from their Customer details, then reselect them.')
    if not str(p.get('device') or '').strip() or not str(p.get('complaint') or '').strip():
        raise RuleError('Enter the device description and reported fault for this product.')
    p['product_photos'] = [i for i in (p.get('product_photos') or []) if i]
    for key in AMOUNTS:
        if amounts_in_paise:
            p[key] = paise(p.get(key) or 0)
        else:
            p[key] = money(p.get(key) or '0')
        if p[key] < 0:
            raise RuleError('Intake amounts cannot be negative.')
    p['accessories'] = [dict(type='accessory', description=a['description'], quantity=int(a.get('quantity') or 1),
                             serial=a.get('serial', ''), condition=a.get('condition') or 'Not Tested',
                             notes=a.get('notes', ''), photo_id=a.get('photo_id'))
                        for a in p.get('accessories', []) if a.get('checked', True)]
    p['guided'] = True
    return p


def prepare_visit(products, amounts_in_paise=False):
    """Validate a whole visit: one customer, each physical device at most once, at most 50 products."""
    if not products:
        raise RuleError('Add at least one product to this visit.')
    if len(products) > 50:
        raise RuleError('Receive up to 50 products in one visit.')
    prepared = [prepare_product(p, amounts_in_paise) for p in products]
    if len({p['customer_id'] for p in prepared}) > 1:
        raise RuleError('All products in this visit must belong to the same customer.')
    devices = [p['device_id'] for p in prepared if p.get('device_id')]
    if len(devices) != len(set(devices)):
        raise RuleError('This physical device is already in the visit list.')
    return prepared


RECEIPT_MESSAGE = ('Your products have been received. The attached receipt lists each product and the '
                   'advance recorded.')


def after_intake(service, job_ids):
    """Receipts and the configured customer copy, after the visit has been committed.

    Each step is attempted on its own and reported. None of them can undo the intake:
    the jobs, custody and advance were committed before this runs.
    """
    import uuid
    from .documents import Documents
    from .readmodels import ReadModels
    from .messaging import status_label
    documents, notes = [], []
    docs, read = Documents(service), ReadModels(service)
    try:
        for ident in job_ids:
            path = docs.generate('intake_receipt', ident)
            documents.append(dict(read.attachment_for(path), job_id=ident, title='Job Card ' + service.job(ident)['number']))
        path = docs.visit_receipt(job_ids)
        documents.append(dict(read.attachment_for(path), job_id=job_ids[0], title='Visit intake receipt'))
    except Exception as exc:
        notes.append('Receipts could not be created: ' + str(exc) + ' The intake is saved.')
    if documents and documents[-1]['title'] == 'Visit intake receipt':
        try:
            results = service.auto_notify('intake_receipt', documents[-1]['id'], service.job(job_ids[0])['customer_id'],
                                          RECEIPT_MESSAGE, uuid.uuid4().hex, job_id=job_ids[0])
            notes += [r['channel'].title() + ': ' + status_label(r['state']) for r in results]
            if not results:
                notes.append('No customer message is configured for intake receipts.')
        except Exception as exc:
            notes.append('Could not queue the customer message: ' + str(exc) + ' The intake is saved.')
    return dict(documents=documents, notes=notes)
