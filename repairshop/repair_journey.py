"""Connected, read-only lifecycle presentation; actions remain in JobWorkspace.

Every node, colour and word here is derived from one ``Lifecycle.snapshot``.
The widget owns no workflow state of its own, so it can never disagree with the
state machine: if the backend says WARRANTY CHECK, that is the only stage this
screen can draw as current.
"""
from PyQt6.QtCore import Qt, QTimer, QSize, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QFrame,
                             QScrollArea, QDialog, QSizePolicy)
from .ui_widgets import button, FlowLayout, STATUS_STATES
from .lifecycle import ACTIONS
from .journey_model import build_journey

# Shared semantics for every lifecycle node, connector, legend and status badge.
# Defined once in the design system so no screen invents its own palette.
JOURNEY_STATES = STATUS_STATES

# Width below which the stacked card column is replaced by a wrapping rail.
RAIL_WIDTH = 520


def text_label(text='', bold=False):
    label = QLabel(str(text))
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    if bold:
        font = label.font()
        font.setBold(True)
        label.setFont(font)
    return label


def clear(layout):
    """Drop every child of a layout without leaving stale widgets visible."""
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout():
            clear(item.layout())
            item.layout().deleteLater()


class Rail(QWidget):
    """A wrapping row of chips that reports the height its width really needs.

    ``FlowLayout`` wraps correctly but its size hint is one row tall, so inside a
    scroll area the later rows were laid out below the clip and disappeared. This
    wrapper answers ``heightForWidth`` for the layout above it, which is what a
    box layout and a resizable scroll area both ask before allocating space.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.flow = FlowLayout(self)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.flow.heightForWidth(width)

    def sizeHint(self):
        width = self.width() or 600
        return QSize(width, self.flow.heightForWidth(width))

    def minimumSizeHint(self):
        return self.sizeHint()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setMinimumHeight(self.flow.heightForWidth(event.size().width()))
        self.updateGeometry()


class JourneyNode(QFrame):
    """One lifecycle stage. Clicking it only ever opens its recorded history."""
    clicked = pyqtSignal()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()


class RepairJourney(QWidget):
    action_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        heading = text_label('Repair journey', True)
        heading.setStyleSheet('font-size:18px;')
        layout.addWidget(heading)
        self.route = text_label()
        layout.addWidget(self.route)
        self.legend = FlowLayout()
        self.legend_labels = {}
        for status, (icon, title, ink, _, _) in JOURNEY_STATES.items():
            item = text_label(f'{icon} {title}')
            item.setStyleSheet(f'color:{ink};font-size:11px;')
            self.legend_labels[status] = item
            self.legend.addWidget(item)
        layout.addLayout(self.legend)
        # The overview strip stays pinned above the scrolling detail, so the
        # whole journey is still visible once the view scrolls to the current
        # stage. It is only populated in rail mode.
        self.rail_holder = QWidget()
        self.rail_layout = QVBoxLayout(self.rail_holder)
        self.rail_layout.setContentsMargins(0, 0, 0, 0)
        self.rail_holder.hide()
        layout.addWidget(self.rail_holder)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.nodes_layout = QVBoxLayout(self.body)
        self.nodes_layout.setContentsMargins(2, 4, 12, 4)
        self.nodes_layout.setSpacing(0)
        self.scroll.setWidget(self.body)
        layout.addWidget(self.scroll, 1)
        self.notice = text_label()
        self.notice.setObjectName('subtitle')
        layout.addWidget(self.notice)
        self.primary = button('Continue', self.invoke_primary, True)
        self.primary.setAutoDefault(False)
        self.primary.hide()
        self.snapshot = {}
        self.nodes = []
        self.node_widgets = []
        self.current_node = None
        self.current_action = text_label()
        self.readonly = False
        self.orientation = Qt.Orientation.Vertical
        self.focus_timer = QTimer(self)
        self.focus_timer.setSingleShot(True)
        self.focus_timer.timeout.connect(self.focus_current)
        self.setMinimumWidth(280)

    # ---------------------------------------------------------------- input

    def invoke_primary(self):
        """Dispatch the snapshot's own primary action; no local rule decides it."""
        action = self.snapshot.get('primary')
        if action and self.primary.isEnabled():
            self.action_requested.emit(action)

    def set_orientation(self, orientation):
        """Stacked cards in a side column, a wrapping rail when placed on top."""
        if orientation == self.orientation:
            return
        self.orientation = orientation
        if self.snapshot:
            self.render()

    def set_snapshot(self, snapshot, readonly=False):
        previous_stage = self.snapshot.get('stage')
        self.snapshot = snapshot
        self.readonly = readonly
        self.nodes = build_journey(snapshot)
        self.render()
        if previous_stage != snapshot['stage']:
            self.focus_timer.start(0)

    # --------------------------------------------------------------- render

    def render(self):
        snapshot = self.snapshot
        # The legend only explains the states actually drawn for this repair.
        shown = {node['status'] for node in self.nodes} | {'completed', 'current', 'upcoming'}
        for status, item in self.legend_labels.items():
            item.setVisible(status in shown)
        self.route.setText('Route · ' + snapshot['route_label'])
        self.primary.setParent(self)
        self.primary.hide()
        self.primary.setText(ACTIONS.get(snapshot.get('primary'), 'No action available'))
        self.primary.setEnabled(bool(snapshot.get('primary')) and not self.readonly)
        clear(self.nodes_layout)
        clear(self.rail_layout)
        self.rail_holder.setVisible(self.orientation == Qt.Orientation.Horizontal)
        self.current_node = None
        self.node_widgets = []
        if self.orientation == Qt.Orientation.Horizontal:
            self.render_rail()
        else:
            self.render_column()
        self.nodes_layout.addStretch(1)
        legacy = not snapshot.get('lifecycle_version') or (snapshot.get('data') or {}).get('legacy_review')
        undecided = str(snapshot.get('route_label') or '').startswith('NOT SELECTED')
        self.notice.setText(
            'Legacy history is shown only where evidence was recorded.' if legacy else
            'The stages after route selection appear once the route is chosen.' if undecided else
            'Upcoming stages follow the recorded route. Decisions may change the path.')

    def render_column(self):
        """Full connected cards, one per stage, for the tall side column."""
        for index, node in enumerate(self.nodes):
            if index:
                self.nodes_layout.addWidget(self.connector('│\n↓'))
            card = self.make_node(node)
            self.nodes_layout.addWidget(card)
            self.node_widgets.append(card)
            if node.get('is_current'):
                self.current_node = card

    def render_rail(self):
        """A pinned chip rail, with the current stage expanded beneath it.

        The whole journey stays readable in one short strip when the component
        sits above the tabs, where a column of full cards would push every later
        stage off the screen. The strip lives outside the scroll area, so
        scrolling to the current stage never hides the overview it belongs to.
        """
        strip = Rail()
        for index, node in enumerate(self.nodes):
            if index:
                strip.flow.addWidget(self.connector('→'))
            chip = self.make_node(node, compact=True)
            strip.flow.addWidget(chip)
            self.node_widgets.append(chip)
        self.rail_layout.addWidget(strip)
        current = next((node for node in self.nodes if node.get('is_current')), None)
        if current:
            card = self.make_node(current)
            self.nodes_layout.addWidget(card)
            self.node_widgets.append(card)
            self.current_node = card

    def connector(self, glyph):
        line = text_label(glyph)
        line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        line.setStyleSheet('color:' + JOURNEY_STATES['upcoming'][2] + ';font-size:14px;')
        return line

    def describe(self, node, state):
        """Tooltip text: everything a node knows without crowding the card."""
        icon, _, _, _, _ = JOURNEY_STATES.get(node['status'], JOURNEY_STATES['upcoming'])
        lines = [f"{icon}  {node['title']} · {state}"]
        if node.get('detail'):
            lines.append(node['detail'])
        events = node.get('events') or []
        if events:
            last = events[-1]
            lines.append('Recorded ' + str(last.get('time') or last.get('created') or 'time not recorded')
                         + ' by ' + str(last.get('actor') or 'staff not recorded'))
        if node.get('is_current'):
            lines.append('Location · ' + str(self.snapshot.get('current_location') or 'Not recorded'))
            lines.append('Responsible · ' + str(self.snapshot.get('responsible') or 'Not assigned'))
            lines.append('Route · ' + str(self.snapshot.get('route_label') or 'Not selected'))
        lines.append('Click for recorded history.')
        return '\n'.join(lines)

    def make_node(self, node, compact=False):
        status = node.get('status', 'upcoming')
        icon, state, ink, surface, border = JOURNEY_STATES.get(status, JOURNEY_STATES['upcoming'])
        current = bool(node.get('is_current'))
        if current and status != 'current':
            state = 'Current · ' + state
        card = JourneyNode()
        card.setObjectName('journeyNode')
        card.setProperty('stage', node['key'])
        card.setProperty('visualStatus', status)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.clicked.connect(lambda n=node: self.show_history(n))
        card.setStyleSheet('QFrame#journeyNode {background:%s;border:%dpx solid %s;border-radius:10px;}'
                           % (surface, 2 if current else 1, border))
        layout = QVBoxLayout(card)
        margin = 11 if compact else 13
        layout.setContentsMargins(margin, margin - 3, margin, margin - 3)
        layout.setSpacing(4 if compact else 7)
        title = text_label(f'{icon}  {node["title"]}', True)
        title.setStyleSheet(f'color:{ink};font-size:{13 if compact else 14}px;')
        layout.addWidget(title)
        badge = text_label(state)
        badge.setStyleSheet(f'color:{ink};font-size:{11 if compact else 12}px;')
        layout.addWidget(badge)
        card.setAccessibleName(node['title'] + ' · ' + state)
        card.setToolTip(self.describe(node, state))
        if compact:
            # Chips size to their own stage name so the rail wraps on whole
            # stages instead of breaking a title across two lines.
            title.setWordWrap(False)
            badge.setWordWrap(False)
            return card
        if node.get('detail'):
            layout.addWidget(text_label(node['detail']))
        events = node.get('events', [])
        if status == 'completed' and events:
            last = events[-1]
            stamp = text_label(str(last.get('time') or last.get('created') or '')
                               + ' · ' + str(last.get('actor') or 'Staff not recorded'))
            stamp.setObjectName('subtitle')
            layout.addWidget(stamp)
        for line in self.branch_lines(node):
            layout.addWidget(line)
        if current:
            self.fill_current(node, layout)
        if events or current:
            details = button('View stage history', lambda checked=False, n=node: self.show_history(n))
            details.setAutoDefault(False)
            details.setAccessibleName('View history: ' + node['title'])
            layout.addWidget(details)
        return card

    def branch_lines(self, node):
        """Name the routes still open, without promising any route's stages."""
        options = node.get('options')
        if not options:
            return []
        heading = text_label('Possible routes from here', True)
        heading.setStyleSheet('font-size:12px;')
        branch = text_label('\n'.join('├─ ' + option for option in options[:-1]) + '\n└─ ' + options[-1])
        branch.setStyleSheet('color:' + JOURNEY_STATES['upcoming'][2] + ';')
        return [heading, branch]

    def fill_current(self, node, layout):
        """What is happening, why it waits, what to do and what follows."""
        self.current_action = text_label(self.snapshot['next_action'], True)
        layout.addWidget(self.current_action)
        layout.addWidget(text_label('Location · ' + str(self.snapshot.get('current_location') or 'Not recorded')
                                    + '\nResponsible · ' + str(self.snapshot.get('responsible') or 'Not assigned')))
        if self.snapshot.get('attention'):
            warning = text_label('\n'.join('! ' + str(item) for item in self.snapshot['attention']))
            warning.setStyleSheet('color:' + JOURNEY_STATES['waiting'][2] + ';')
            layout.addWidget(warning)
        layout.addWidget(self.primary)
        self.primary.setVisible(bool(self.snapshot.get('primary')))
        if self.readonly:
            layout.addWidget(text_label('Read-only archive · actions disabled'))
        following = self.nodes[self.nodes.index(node) + 1:]
        upcoming = next((n for n in following if n.get('status') == 'upcoming'), None)
        if upcoming:
            layout.addWidget(text_label('Expected next · ' + upcoming['title']))

    # ------------------------------------------------------------ behaviour

    def focus_current(self):
        if self.current_node:
            self.nodes_layout.activate()
            self.scroll.ensureWidgetVisible(self.current_node, 0, 18)

    def show_history(self, node):
        dialog = QDialog(self)
        dialog.setWindowTitle(node['title'] + ' · Recorded history')
        dialog.resize(650, 480)
        layout = QVBoxLayout(dialog)
        layout.addWidget(text_label(node['title'], True))
        layout.addWidget(text_label(self.describe(node, JOURNEY_STATES.get(
            node['status'], JOURNEY_STATES['upcoming'])[1]).rsplit('\n', 1)[0]))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        rows = QVBoxLayout(body)
        events = node.get('events', [])
        if not events:
            rows.addWidget(text_label('No historical completion evidence is recorded for this stage.'))
        for event in events:
            rows.addWidget(text_label(f"{event.get('time') or event.get('created') or 'Time not recorded'}"
                                      f" · {event.get('actor') or 'Staff not recorded'}", True))
            rows.addWidget(text_label(event.get('event') or event.get('action', '')))
            rows.addWidget(text_label(event.get('details') or 'No additional details recorded.'))
        rows.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        layout.addWidget(button('Close', dialog.accept))
        dialog.exec()

    def text(self):
        """Accessible text equivalent retained for old view integrations."""
        return '\n'.join(node['title'] + ' · ' + node['status'] for node in self.nodes)
