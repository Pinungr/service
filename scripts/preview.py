"""Developer-only visual preview using the separately created synthetic demo."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication
from repairshop.persistence import Database
from repairshop.services import Service
from repairshop.ui import MainWindow
from repairshop.ui_widgets import STYLE
app=QApplication([])
app.setStyle('Fusion')
app.setStyleSheet(STYLE)
s=Service(Database(Path(__file__).resolve().parents[1]/'demo-data'))
s.login('demo','DemoShop2026!')
w=MainWindow(s,demo=True)
w.show()
raise SystemExit(app.exec())
