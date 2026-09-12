"""Developer-only synthetic UI render; no real camera or production data access."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from repairshop.persistence import Database
from repairshop.services import Service
from repairshop.ui import MainWindow
from repairshop.ui_widgets import STYLE
from repairshop.customer_ui import CustomerOverview
from repairshop.camera import CameraDialog

class NoCamera(QObject):
    changed = pyqtSignal()
    ready = pyqtSignal(bool)
    captured = pyqtSignal(object)
    failed = pyqtSignal(str)
    def devices(self): return []
    def stop(self): pass

root = Path(__file__).resolve().parents[1]
output = root / 'docs' / 'screenshots'
output.mkdir(exist_ok=True)
app = QApplication([])
app.setStyle('Fusion')
app.setStyleSheet(STYLE)
s = Service(Database(root / 'runtime' / 'photo-demo-v11'))
s.login('demo', 'DemoShop2026!')
w = MainWindow(s, demo=True)
d = CustomerOverview(w, 1)
d.show()
def overview():
    d.grab().save(str(output / 'customer-overview-v11.png'))
    d.reject()
    camera = CameraDialog(lambda *_: 1, w, backend=NoCamera())
    QTimer.singleShot(250, lambda: (camera.grab().save(str(output / 'camera-missing-v11.png')), camera.reject()))
    camera.exec()
    def intake():
        form = QApplication.activeModalWidget()
        form.grab().save(str(output / 'intake-photo-v11.png'))
        form.reject()
    QTimer.singleShot(250, intake)
    w.intake(customer_id=1)
    QTimer.singleShot(100, app.quit)
QTimer.singleShot(500, overview)
app.exec()
w.pool.waitForDone(30000)
print('Rendered synthetic overview, no-camera dialog and photo intake.')
