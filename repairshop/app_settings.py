"""Operational defaults the owner configures once, in one declarative place.

Staff should not answer the same questions on every intake: which paper, whether to
print, whether to message the customer. The owner sets those once here and normal
operations read them.

Customer consent is deliberately not a setting here: it can never be switched off, so it
is enforced unconditionally in code rather than offered as something an owner might turn
against the customer.

Nothing in this file decides whether a customer may actually be contacted. A global
setting only says what the shop *wants* to do; the customer's recorded contact details
and consent still decide what is allowed, and that check stays in `queue_customer_document`.
"""

PAPER_CHOICES = ('A4', 'A5')
#: Events a customer document can be sent for, in the order they occur in a repair.
NOTIFY_EVENTS = ('intake_receipt', 'job_card', 'quotation', 'completion', 'invoice')


class Setting:
    def __init__(self, default, section, label, choices=None, kind=None):
        self.default, self.section, self.label = default, section, label
        self.choices = choices
        self.kind = kind or type(default).__name__

    def clean(self, value):
        if self.kind == 'bool':
            if not isinstance(value, bool):
                raise ValueError(self.label + ' is a yes/no choice.')
            return value
        if self.choices is not None and value not in self.choices:
            raise ValueError(self.label + ' must be one of: ' + ', '.join(x or 'default' for x in self.choices))
        return value


def _paper(label):
    # An empty value means "use the shop's default paper size", so a shop that only
    # cares about one size never has to set the per-document ones.
    return Setting('', 'Documents & printing', label, choices=('',) + PAPER_CHOICES, kind='str')


SETTINGS = {
    'paper_size': Setting('A4', 'Documents & printing', 'Default paper size', choices=PAPER_CHOICES, kind='str'),
    'paper_intake_receipt': _paper('Intake receipt paper size'),
    'paper_job_card': _paper('Job card paper size'),
    'paper_invoice': _paper('Invoice paper size'),
    'include_photos': Setting(False, 'Documents & printing', 'Include photos in customer messages'),

    'auto_job_card': Setting(True, 'After intake', 'Auto Generate Customer Job Card (the shop copy is always recorded)'),
    'auto_print': Setting(False, 'After intake', 'Open documents for printing automatically'),

    # Master switches. They gate notifications the shop already sends, so they default
    # on; turning one off stops that channel everywhere, at queue time and at send time.
    'whatsapp_enabled': Setting(True, 'WhatsApp', 'Send WhatsApp messages at all'),
    'whatsapp_attach_pdf': Setting(True, 'WhatsApp', 'Attach the PDF where the template allows it'),

    'email_enabled': Setting(True, 'Email', 'Send emails at all'),
    'email_attach_pdf': Setting(True, 'Email', 'Attach the PDF'),

    'show_estimate_on_receipt': Setting(True, 'Estimates', 'Show the initial estimate on the intake receipt'),
    'show_advance_on_receipt': Setting(True, 'Estimates', 'Show the advance received on the intake receipt'),
    'show_completion_date': Setting(True, 'Estimates', 'Show the estimated completion date'),
    'require_initial_estimate': Setting(False, 'Estimates', 'Require an initial estimate at intake'),
}

for _channel, _section in (('whatsapp', 'WhatsApp'), ('email', 'Email')):
    for _event in NOTIFY_EVENTS:
        SETTINGS[f'auto_{_channel}_{_event}'] = Setting(
            False, _section, 'Automatically send the ' + _event.replace('_', ' '))

KEYS = frozenset(SETTINGS)


def value(db, key):
    """One setting, falling back to its default when the shop has never set it.

    An installation that predates a setting simply gets the default, so adding a key
    never breaks an existing database.
    """
    setting = SETTINGS[key]
    stored = db.setting(key, None)
    if stored is None:
        return setting.default
    try:
        return setting.clean(stored)
    except ValueError:
        return setting.default


def paper_for(db, document):
    """Paper size for one kind of document: its own setting, else the shop default."""
    specific = value(db, 'paper_' + document) if 'paper_' + document in SETTINGS else ''
    return specific or value(db, 'paper_size')


def channels_for(db, event):
    """Channels the shop is configured to use for this event.

    This is the shop's intention only. Whether the customer can actually be reached, and
    whether they have consented, is decided separately and is never overridden here.
    """
    if event not in NOTIFY_EVENTS:
        return []
    chosen = []
    for channel in ('whatsapp', 'email'):
        if value(db, channel + '_enabled') and value(db, f'auto_{channel}_{event}'):
            chosen.append(channel)
    return chosen


def sections():
    """Settings grouped for the settings screen, in declaration order."""
    grouped = {}
    for key, setting in SETTINGS.items():
        grouped.setdefault(setting.section, []).append((key, setting))
    return grouped
