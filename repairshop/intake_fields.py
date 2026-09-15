"""Name-valued master choices for the existing device brand/model text columns."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QHBoxLayout
from .ui_widgets import Form, button, combo, CHECKBOX_STYLE

# Intake dialogs set their own stylesheet, which would otherwise drop the
# application-level checkbox rules. Reuse the shared definition, never a copy.
INTAKE_STYLE = CHECKBOX_STYLE


class MasterNameField(QWidget):
    def __init__(self, service, kind, value=''):
        super().__init__()
        self.s, self.kind = service, kind
        layout=QHBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.box=combo([],editable=True);layout.addWidget(self.box,1)
        self.add_button=button('+ Add new',self.add);layout.addWidget(self.add_button)
        self.add_button.setEnabled(not service.db.readonly and service.user['role'] in ('owner','counter'))
        self.textChanged=self.box.editTextChanged
        self.setFocusProxy(self.box)
        self.reload(value)

    def reload(self, selected=''):
        self.box.clear();self.box.addItem('', '')
        for row in self.s.masters(self.kind):self.box.addItem(row['name'],row['name'])
        self.box.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.box.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.setText(selected)

    def text(self):return self.box.currentText().strip()

    def setText(self, value):self.box.setEditText(value or '')

    def clear(self):self.setText('')

    def add(self):
        form=Form('Add '+self.kind,self)
        form.text('name',self.kind.title(),self.text())
        def save(values):
            ident=self.s.save_master(self.kind,values['name'])
            row=self.s.db.one('SELECT name FROM masters WHERE id=?',(ident,))
            self.reload(row['name'])
        form.submit(save)
