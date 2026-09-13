"""Render the existing Qt screens using isolated synthetic data, without installation."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QImage, QColor, QPainter, QFontDatabase, QFont
from PyQt6.QtWidgets import QApplication, QDialog, QScrollArea
from repairshop.persistence import Database
from repairshop.services import Service
from repairshop.customer_records import CustomerRecords
from repairshop.customer_ui import CustomerOverview
from repairshop.lifecycle_ui import JobWorkspace
from repairshop.ui import MainWindow
from repairshop.ui_widgets import STYLE

app = QApplication([])
for name in ('segoeui.ttf', 'segoeuib.ttf', 'seguisb.ttf'):
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + name)
app.setFont(QFont('Segoe UI', 10))
app.setStyle('Fusion')
app.setStyleSheet(STYLE)
output = Path('runtime/ui-review') / ('scale-' + os.environ.get('QT_SCALE_FACTOR', '1'))
output.mkdir(parents=True, exist_ok=True)
shots = []

def capture(widget, name, overview=False):
    for _ in range(6):
        app.processEvents()
    pixmap = widget.grab()
    pixmap.save(str(output / (name + '.png')))
    if overview:
        shots.append((name, pixmap))

with tempfile.TemporaryDirectory(prefix='ui-review-', dir='runtime') as data:
    service = Service(Database(Path(data)))
    service.setup('Preview Repair Shop', 'owner', 'PreviewOnly2026!')
    window = MainWindow(service, demo=True)
    for timer in window.findChildren(QTimer):
        timer.stop()
    window.show()
    for size in [(1920, 1000), (1366, 700), (1024, 650)]:
        window.resize(*size)
        capture(window, f'dashboard-empty-{size[0]}', True)
    customer = service.save_customer('Preview Customer', '9990000012')
    photo = QImage(64, 64, QImage.Format.Format_RGB32)
    photo.fill(QColor('#68a398'))
    CustomerRecords(service).save_photo(photo, customer)
    job = service.intake(customer, 'Preview laptop', 'Does not power on', assessment_consent=True)
    window.resize(1366, 760)
    for page in window.nav:
        window.navigate(page)
        capture(window, page.replace('&', 'and').replace(' ', '-'), True)
        window.resize(1024, 650)
        capture(window, 'small-' + page.replace('&', 'and').replace(' ', '-'))
        if window.stack.currentWidget().horizontalScrollBar().maximum():
            print('Page overflow at 1024:', page, window.stack.currentWidget().horizontalScrollBar().maximum())
        window.resize(1366, 760)
    workspace = JobWorkspace(window, job)
    workspace.resize(1100, 700)
    workspace.show()
    for index in range(workspace.tabs.count()):
        workspace.tabs.setCurrentIndex(index)
        capture(workspace, 'job-' + str(index), True)
    workspace.close()
    overview = CustomerOverview(window, customer)
    overview.resize(1100, 700)
    overview.show()
    for index in range(overview.tabs.count()):
        overview.tabs.setCurrentIndex(index)
        capture(overview, 'customer-' + str(index), index == 0)
    overview.close()
    def inspect_form():
        form = app.activeModalWidget()
        capture(form, 'intake', True)
        for scroll in form.findChildren(QScrollArea):
            scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        capture(form, 'intake-bottom', True)
        form.reject()
    QTimer.singleShot(100, inspect_form)
    window.intake(customer_id=customer)
    while window.tasks:
        app.processEvents()
    window.close()
    app.processEvents()
    service.db.engine.dispose()

for start in range(0, len(shots), 9):
    batch = shots[start:start + 9]
    sheet = QImage(1500, ((len(batch) + 2) // 3) * 330, QImage.Format.Format_RGB32)
    sheet.fill(QColor('white'))
    painter = QPainter(sheet)
    for index, (name, pixmap) in enumerate(batch):
        x, y = index % 3 * 500, index // 3 * 330
        painter.setPen(QColor('#102a43'))
        painter.drawText(x + 10, y + 18, name)
        scaled = pixmap.toImage().scaled(490, 300, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        painter.drawImage(x + 5, y + 26, scaled)
    painter.end()
    sheet.save(str(output / f'overview-{start // 9}.png'))
print(f'Rendered {len(list(output.glob("*.png")))} screen images in {output}')
