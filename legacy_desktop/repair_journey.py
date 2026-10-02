"""Horizontal repair workflow projected solely from Lifecycle.snapshot()."""
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QFrame,
                             QHBoxLayout, QLabel, QLineEdit, QScrollArea,
                             QTextEdit, QVBoxLayout, QWidget)

from repairshop.journey_model import build_journey
from repairshop.lifecycle import ACTIONS, stage_age
from .ui_widgets import STATUS_STATES, button

JOURNEY_STATES = STATUS_STATES
REPAIR_CHILDREN = ('waiting_parts', 'technician_testing')
INLINE_ACTIONS = frozenset(('inspection_done', 'verify_warranty', 'diagnose',
                            'complete_repair', 'test', 'qc', 'wait_parts', 'parts_received',
                            'rework'))


def text_label(value='', bold=False):
    label = QLabel(str(value))
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    if bold:
        font = label.font()
        font.setBold(True)
        label.setFont(font)
    return label


def clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout():
            clear(item.layout())


class WorkflowNode(QFrame):
    clicked = pyqtSignal()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()


class WorkflowConnector(QFrame):
    """A real line between stages, not a text arrow or progress indicator."""
    def __init__(self, vertical=False):
        super().__init__()
        self.setFrameShape(QFrame.Shape.VLine if vertical else QFrame.Shape.HLine)
        self.setFrameShadow(QFrame.Shadow.Plain)
        self.setStyleSheet('color:#a8b8c8;background:#a8b8c8;')
        if vertical:
            self.setFixedHeight(17)
            self.setFixedWidth(2)
        else:
            self.setFixedWidth(24)


class RepairJourney(QWidget):
    """One reusable left-to-right graph plus a contextual stage panel."""
    action_requested = pyqtSignal(str)
    inline_action_requested = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        heading = text_label('Repair workflow', True)
        heading.setStyleSheet('font-size:18px;color:#102a43;')
        layout.addWidget(heading)
        self.route = text_label()
        layout.addWidget(self.route)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(215)
        self.scroll.setMaximumHeight(280)
        self.body = QWidget()
        self.nodes_layout = QHBoxLayout(self.body)
        self.nodes_layout.setContentsMargins(6, 7, 6, 7)
        self.nodes_layout.setSpacing(0)
        self.scroll.setWidget(self.body)
        layout.addWidget(self.scroll)
        self.stage_panel = QFrame()
        self.stage_panel.setObjectName('stageActionPanel')
        self.stage_panel.setStyleSheet('QFrame#stageActionPanel {background:white;border:1px solid #dce5ee;border-radius:9px;}')
        self.stage_layout = QVBoxLayout(self.stage_panel)
        self.stage_layout.setContentsMargins(14, 10, 14, 10)
        self.stage_layout.setSpacing(5)
        layout.addWidget(self.stage_panel)
        self.primary = button('Continue', self.invoke_primary, True)
        self.primary.setAutoDefault(False)
        self.primary.hide()
        self.current_action = text_label()
        self.snapshot = {}
        self.nodes = []
        self.node_widgets = []
        self.current_node = None
        self.selected_key = None
        self.readonly = False
        self.inline_fields = {}
        self.orientation = Qt.Orientation.Horizontal
        self.focus_timer = QTimer(self)
        self.focus_timer.setSingleShot(True)
        self.focus_timer.timeout.connect(self.focus_current)

    def set_orientation(self, orientation):
        self.orientation = Qt.Orientation.Horizontal

    def set_snapshot(self, snapshot, readonly=False):
        old_stage = self.snapshot.get('stage')
        self.snapshot = snapshot
        self.readonly = readonly
        self.nodes = build_journey(snapshot)
        if old_stage != snapshot.get('stage') or not self.selected_key:
            current = next((n for n in self.nodes if n.get('is_current')), None)
            self.selected_key = current['key'] if current else None
        self.render()
        if old_stage != snapshot.get('stage'):
            self.focus_timer.start(0)

    def graph_groups(self):
        if not any(n['key'] == 'under_repair' for n in self.nodes):
            return [(n, []) for n in self.nodes]
        children = [n for n in self.nodes if n['key'] in REPAIR_CHILDREN]
        return [(n, children if n['key'] == 'under_repair' else [])
                for n in self.nodes if n['key'] not in REPAIR_CHILDREN]

    def render(self):
        clear(self.nodes_layout)
        self.node_widgets = []
        self.current_node = None
        self.route.setText('Route · ' + str(self.snapshot.get('route_label') or 'Not selected'))
        groups = self.graph_groups()
        for index, (node, children) in enumerate(groups):
            if index:
                self.nodes_layout.addWidget(WorkflowConnector())
            column = QWidget()
            column_layout = QVBoxLayout(column)
            column_layout.setContentsMargins(0, 0, 0, 0)
            column_layout.setSpacing(0)
            column_layout.addWidget(self.make_node(node), 0, Qt.AlignmentFlag.AlignTop)
            if children:
                column_layout.addWidget(WorkflowConnector(vertical=True), 0, Qt.AlignmentFlag.AlignHCenter)
                row = QHBoxLayout()
                row.setSpacing(5)
                for child in children:
                    row.addWidget(self.make_node(child, child=True))
                column_layout.addLayout(row)
            column_layout.addStretch()
            self.nodes_layout.addWidget(column)
        self.body.setMinimumWidth(12 + sum(max(170, 154 * len(children) + 5 * (len(children) - 1))
                                           for _, children in groups) + 24 * max(0, len(groups) - 1))
        self.body.setMinimumHeight(205 if any(children for _, children in groups) else 115)
        self.nodes_layout.activate()
        self.body.adjustSize()
        self.show_selected()

    def make_node(self, node, child=False):
        status = node.get('status', 'upcoming')
        icon, state, ink, surface, border = JOURNEY_STATES.get(status, JOURNEY_STATES['upcoming'])
        selected = node['key'] == self.selected_key
        card = WorkflowNode()
        card.setObjectName('workflowNode')
        card.setProperty('stage', node['key'])
        card.setProperty('visualStatus', status)
        card.setMinimumWidth(154 if child else 170)
        card.setMaximumWidth(188 if child else 205)
        card.setMinimumHeight(80 if child else 98)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setStyleSheet('QFrame#workflowNode {background:%s;border:%dpx solid %s;border-radius:8px;}'
                           % (surface, 3 if selected else 2 if node.get('is_current') else 1, border))
        card.clicked.connect(lambda n=node: self.show_history(n))
        box = QVBoxLayout(card)
        box.setContentsMargins(10, 8, 10, 8)
        box.setSpacing(3)
        title = text_label(f'{icon}  {node["title"]}', True)
        title.setStyleSheet(f'color:{ink};font-size:12px;')
        box.addWidget(title)
        status_text = 'Action required' if node.get('is_current') and status == 'current' else state
        if node.get('is_current') and status == 'waiting':
            status_text = 'Blocked / waiting'
        stamp = text_label(status_text)
        stamp.setStyleSheet(f'color:{ink};font-size:11px;')
        box.addWidget(stamp)
        if node.get('is_current'):
            box.addWidget(text_label(stage_age(self.snapshot.get('pending_raw'))))
        elif status == 'completed' and node.get('events'):
            last = node['events'][-1]
            box.addWidget(text_label(str(last.get('time') or last.get('created') or '')[:16]))
        card.setAccessibleName(node['title'] + ' · ' + status_text)
        card.setToolTip(node.get('detail') or status_text)
        self.node_widgets.append(card)
        if node.get('is_current'):
            self.current_node = card
        return card

    def show_history(self, node):
        """Select a stage in place; completed and future stages remain read only."""
        self.selected_key = node['key']
        self.render()

    def show_selected(self):
        self.stage_layout.removeWidget(self.primary)
        self.primary.setParent(self.stage_panel)
        self.primary.hide()
        clear(self.stage_layout)
        self.inline_fields = {}
        node = next((n for n in self.nodes if n['key'] == self.selected_key), None)
        if not node:
            return
        status = node['status']
        icon, state, ink, _, _ = JOURNEY_STATES.get(status, JOURNEY_STATES['upcoming'])
        title = text_label(f'{icon}  {node["title"]} · {state}', True)
        title.setStyleSheet(f'color:{ink};font-size:14px;')
        self.stage_layout.addWidget(title)
        if node.get('detail'):
            self.stage_layout.addWidget(text_label(node['detail']))
        if node.get('options'):
            self.stage_layout.addWidget(text_label('Available routes: ' + ', '.join(node['options'])))
        if node.get('is_current'):
            self.current_action = text_label(self.snapshot.get('next_action') or 'No action available', True)
            self.stage_layout.addWidget(self.current_action)
            if self.snapshot.get('attention'):
                warning = text_label('\n'.join(str(item) for item in self.snapshot['attention']))
                warning.setStyleSheet('color:#9a4b00;')
                self.stage_layout.addWidget(warning)
            action = self.snapshot.get('primary')
            if action in INLINE_ACTIONS and not self.readonly:
                self.add_inline_fields(action)
            self.stage_layout.addWidget(self.primary, 0, Qt.AlignmentFlag.AlignLeft)
            self.primary.setText(ACTIONS.get(self.snapshot.get('primary'), 'Continue'))
            self.primary.setEnabled(bool(self.snapshot.get('primary')) and not self.readonly)
            self.primary.setVisible(bool(self.snapshot.get('primary')))
        elif status == 'completed':
            events = node.get('events') or []
            for event in events[-3:]:
                self.stage_layout.addWidget(text_label(
                    f"{event.get('time') or event.get('created') or 'Time not recorded'} · "
                    f"{event.get('actor') or 'Staff not recorded'} · "
                    f"{event.get('details') or event.get('event') or event.get('action') or ''}"))
            if not events:
                self.stage_layout.addWidget(text_label('No completion evidence recorded for this stage.'))
        else:
            self.stage_layout.addWidget(text_label(
                'Follow the current stage before this step can begin.' if status == 'upcoming'
                else node.get('detail') or 'This stage is not currently actionable.'))

    def add_inline_fields(self, action):
        fields = QFormLayout()
        fields.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        def entry(key, title, kind='text', options=(), checked=False):
            if kind == 'notes':
                widget = QTextEdit()
                widget.setMaximumHeight(65)
            elif kind == 'choice':
                widget = QComboBox()
                for label, value in options:
                    widget.addItem(label, value)
            elif kind == 'check':
                widget = QCheckBox(title)
                widget.setChecked(checked)
            else:
                widget = QLineEdit()
            fields.addRow('' if kind == 'check' else title, widget)
            self.inline_fields[key] = widget

        if action == 'inspection_done':
            entry('notes', 'Inspection findings *', 'notes')
        elif action == 'verify_warranty':
            entry('warranty_status', 'Warranty status', 'choice', (
                ('Choose status', ''), ('Under manufacturer warranty', 'under_warranty'),
                ('Out of warranty', 'out_of_warranty'), ('Unknown', 'unknown')))
            entry('notes', 'Evidence / verification *', 'notes')
        elif action == 'diagnose':
            entry('notes', 'Confirmed fault *', 'notes')
            entry('repairable', 'Device is repairable', 'check', checked=True)
            entry('parts', 'Required parts')
            entry('parts_available', 'Required parts available', 'check', checked=True)
        elif action == 'complete_repair':
            entry('notes', 'Work performed *', 'notes')
            entry('parts', 'Parts used')
        elif action == 'test':
            entry('result', 'Test result', 'choice', (('Passed', 'passed'), ('Failed', 'failed')))
            entry('notes', 'Test observations *', 'notes')
        elif action == 'qc':
            if self.snapshot.get('data', {}).get('unrepaired'):
                entry('condition_checked', 'Condition checked against intake', 'check')
            else:
                entry('result', 'QC result *', 'choice', (
                    ('Choose result', ''), ('Pass QC', 'passed'), ('Fail QC', 'failed')))
                for key, title in (('functional', 'Functional test'), ('power', 'Power test'),
                                   ('charging', 'Charging test'), ('display', 'Display test'),
                                   ('connectivity', 'Connectivity test'), ('complaint', 'Reported fault resolved')):
                    choices = [('Not checked', ''), ('Passed', 'passed'), ('Failed', 'failed')]
                    if key in ('charging', 'display', 'connectivity'):
                        choices.append(('Not applicable', 'not_applicable'))
                    entry(key, title, 'choice', choices)
            entry('notes', 'QC findings / return condition *', 'notes')
            entry('repair_warranty', 'Repair warranty terms')
            entry('warranty_until', 'Warranty valid until (YYYY-MM-DD)')
        elif action in ('wait_parts', 'parts_received', 'rework'):
            entry('notes', 'Details *', 'notes')
        self.stage_layout.addLayout(fields)

    def inline_values(self):
        values = {}
        for key, widget in self.inline_fields.items():
            if isinstance(widget, QTextEdit):
                values[key] = widget.toPlainText().strip()
            elif isinstance(widget, QComboBox):
                values[key] = widget.currentData()
            elif isinstance(widget, QCheckBox):
                values[key] = widget.isChecked()
            else:
                values[key] = widget.text().strip()
        return values

    def show_error(self, message):
        error = text_label(message)
        error.setStyleSheet('color:#b42318;font-weight:600;')
        self.stage_layout.addWidget(error)

    def invoke_primary(self):
        action = self.snapshot.get('primary')
        if action and self.primary.isEnabled():
            if action in INLINE_ACTIONS and self.inline_fields:
                values = self.inline_values()
                if action == 'qc':
                    values['checks'] = {key: values.pop(key) for key in
                                        ('functional', 'power', 'charging', 'display',
                                         'connectivity', 'complaint') if key in values}
                self.inline_action_requested.emit(action, values)
            else:
                self.action_requested.emit(action)

    def focus_current(self):
        if self.current_node:
            self.scroll.ensureWidgetVisible(self.current_node, 36, 0)

    def text(self):
        return '\n'.join(node['title'] + ' · ' + node['status'] for node in self.nodes)
