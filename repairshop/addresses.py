"""Structured Indian postal addresses shared by customers and directory records.

State and district are stored as plain text so the application stays fully offline and
usable anywhere in India. The state list below is only a convenience for the dropdown;
an unlisted value the owner types is accepted and saved as entered.
"""
import re
from .domain import RuleError
from .migration12 import compose_address

FIELDS = ('address_line1', 'address_line2', 'pincode', 'district', 'state')

STATES = [
    'Andaman and Nicobar Islands', 'Andhra Pradesh', 'Arunachal Pradesh', 'Assam', 'Bihar',
    'Chandigarh', 'Chhattisgarh', 'Dadra and Nagar Haveli and Daman and Diu', 'Delhi', 'Goa',
    'Gujarat', 'Haryana', 'Himachal Pradesh', 'Jammu and Kashmir', 'Jharkhand', 'Karnataka',
    'Kerala', 'Ladakh', 'Lakshadweep', 'Madhya Pradesh', 'Maharashtra', 'Manipur', 'Meghalaya',
    'Mizoram', 'Nagaland', 'Odisha', 'Puducherry', 'Punjab', 'Rajasthan', 'Sikkim', 'Tamil Nadu',
    'Telangana', 'Tripura', 'Uttar Pradesh', 'Uttarakhand', 'West Bengal',
]


def clean(values, required=True):
    """Validate and normalize the structured address fields of one record."""
    result = {key: str(values.get(key) or '').strip() for key in FIELDS}
    if not required and not any(result.values()):
        return result
    if required:
        for key, label in (('address_line1', 'Address Line 1'), ('district', 'District'), ('state', 'State')):
            if not result[key]:
                raise RuleError('Enter ' + label + '.')
    if result['pincode'] or required:
        if not re.fullmatch(r'\d{6}', result['pincode']):
            raise RuleError('Enter a valid 6-digit PIN code.')
    return result


def readable(row):
    """One display string for documents, folders and the legacy address column."""
    row = dict(row or {})
    structured = compose_address(*(row.get(key, '') or '' for key in FIELDS))
    return structured or (row.get('address') or '')


def districts(db, state):
    """Districts already used in this shop's own records, for the offline suggestion list."""
    if not state:
        return []
    rows = db.rows('''SELECT district FROM customers WHERE state=? AND district!=''
        UNION SELECT district FROM masters WHERE state=? AND district!='' ORDER BY district''',
        (state, state))
    return [r['district'] for r in rows]
