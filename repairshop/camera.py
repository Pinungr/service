"""Qt webcam capture with an injectable backend for offline/hardware-free tests."""
from PyQt6.QtCore import QObject, pyqtSignal, QTimer, Qt, QThreadPool
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QStackedWidget
from PyQt6.QtMultimedia import QCamera, QMediaDevices, QMediaCaptureSession, QImageCapture
from PyQt6.QtMultimediaWidgets import QVideoWidget
from .ui_widgets import button, Task
from .domain import now

NO_CAMERA = 'Please connect a webcam to capture the customer’s photo.'


class CameraBackend(QObject):
    changed = pyqtSignal()
    ready = pyqtSignal(bool)
    captured = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.media = QMediaDevices(self)
        self.media.videoInputsChanged.connect(self.changed)
        self.session = QMediaCaptureSession(self)
        self.capture_device = QImageCapture(self)
        self.session.setImageCapture(self.capture_device)
        self.capture_device.imageCaptured.connect(lambda _, image: self.captured.emit(image.copy()))
        self.capture_device.readyForCaptureChanged.connect(self.ready)
        self.capture_device.errorOccurred.connect(lambda _, error, text: self.failed.emit(text))
        self.camera = None

    def devices(self):
        return [(bytes(d.id()), d.description()) for d in QMediaDevices.videoInputs()]

    def start(self, ident, preview):
        self.stop()
        device = next((d for d in QMediaDevices.videoInputs() if bytes(d.id()) == ident), None)
        if device is None:
            self.failed.emit(NO_CAMERA)
            return
        self.camera = QCamera(device, self)
        self.camera.errorOccurred.connect(lambda error, text: self.failed.emit(text))
        self.session.setCamera(self.camera)
        self.session.setVideoOutput(preview)
        self.camera.start()

    def capture(self):
        if not self.capture_device.isReadyForCapture():
            self.failed.emit('The camera is not ready. Check the connection and choose Retry.')
        elif self.capture_device.capture() < 0:
            self.failed.emit('Photo capture failed. Choose Retry.')

    def stop(self):
        if self.camera:
            self.camera.stop()
            self.session.setCamera(None)
            self.camera.deleteLater()
            self.camera = None
        self.session.setVideoOutput(None)


class CameraDialog(QDialog):
    def __init__(self, save_photo, parent=None, label='Customer photo', backend=None):
        super().__init__(parent)
        self.setWindowTitle('Capture ' + label)
        self.resize(760, 640)
        self.backend = backend or CameraBackend(self)
        self.save_photo = save_photo
        self.image = None
        self.photo_id = None
        self.saving = False
        self.closed = False
        self.task = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(label + ' · Stored only on this computer'))
        self.selection = QComboBox()
        layout.addWidget(self.selection)
        self.stack = QStackedWidget()
        self.preview = QVideoWidget()
        self.still = QLabel()
        self.still.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.preview)
        self.stack.addWidget(self.still)
        layout.addWidget(self.stack, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        controls = QHBoxLayout()
        self.capture_button = button('Capture', self.capture)
        self.retake_button = button('Retake', self.retake)
        self.save_button = button('Save photo', self.save)
        self.retry_button = button('Retry', self.retry)
        self.cancel_button = button('Cancel', self.reject)
        for control in (self.capture_button, self.retake_button, self.save_button, self.retry_button, self.cancel_button):
            controls.addWidget(control)
        layout.addLayout(controls)
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(lambda: self.fail('The camera did not respond. Check camera permissions in Windows, close other camera apps, and choose Retry.'))
        self.selection.currentIndexChanged.connect(self.select_camera)
        self.backend.changed.connect(self.devices_changed)
        self.backend.ready.connect(self.ready)
        self.backend.captured.connect(self.captured)
        self.backend.failed.connect(self.fail)
        self.retry()

    def devices_changed(self):
        if self.closed or self.saving:
            return
        if self.image is None:
            self.retry()
        else:
            self.status.setText('Camera connection changed. You can save the captured photo, or Retry to capture again.')

    def retry(self):
        if self.saving or self.closed:
            return
        self.timeout.stop()
        self.backend.stop()
        self.image = None
        self.stack.setCurrentWidget(self.preview)
        self.capture_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.retake_button.setEnabled(False)
        selected = self.selection.currentData()
        self.selection.blockSignals(True)
        self.selection.clear()
        devices = self.backend.devices()
        for ident, name in devices:
            self.selection.addItem(name, ident)
        index = self.selection.findData(selected)
        self.selection.setCurrentIndex(max(index, 0) if devices else -1)
        self.selection.blockSignals(False)
        if not devices:
            self.status.setText(NO_CAMERA)
        else:
            self.select_camera()

    def select_camera(self, *_):
        if self.saving or self.closed or self.selection.currentIndex() < 0:
            return
        self.image = None
        self.stack.setCurrentWidget(self.preview)
        self.capture_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.retake_button.setEnabled(False)
        self.status.setText('Starting camera… If Windows asks, allow camera access to use capture.')
        self.timeout.start(12000)
        try:
            self.backend.start(self.selection.currentData(), self.preview)
        except Exception as exc:
            self.fail(str(exc))

    def ready(self, ready):
        if self.closed or self.image is not None or self.saving:
            return
        self.capture_button.setEnabled(ready)
        if ready:
            self.timeout.stop()
            self.status.setText('Position the person or product in the preview, then Capture.')

    def capture(self):
        self.capture_button.setEnabled(False)
        self.status.setText('Capturing…')
        self.timeout.start(12000)
        try:
            self.backend.capture()
        except Exception as exc:
            self.fail(str(exc))

    def captured(self, image):
        if self.closed or self.saving:
            return
        self.timeout.stop()
        if image.isNull():
            self.fail('No image was captured. Please Retry.')
            return
        self.image = image.copy()
        self.captured_at = now()
        self.backend.stop()
        self.still.setPixmap(QPixmap.fromImage(image).scaled(700, 430, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.stack.setCurrentWidget(self.still)
        self.save_button.setEnabled(True)
        self.retake_button.setEnabled(True)
        self.status.setText('Review this photo. Choose Save photo or Retake.')

    def retake(self):
        self.retry()

    def fail(self, message):
        if self.closed or self.saving:
            return
        self.timeout.stop()
        self.capture_button.setEnabled(False)
        self.backend.stop()
        self.status.setText(NO_CAMERA if message == NO_CAMERA else 'Camera unavailable or capture failed. Check the cable, Windows camera permissions, and whether another app is using it. Choose Retry.\n' + message)

    def save(self):
        if self.image is None or self.saving:
            return
        self.saving = True
        for w in (self.selection, self.save_button, self.retake_button, self.retry_button, self.cancel_button):
            w.setEnabled(False)
        self.status.setText('Saving photo locally…')
        image, captured = self.image.copy(), self.captured_at
        self.task = Task(lambda: self.save_photo(image, captured))
        self.task.signals.finished.connect(self.saved)
        self.task.signals.failed.connect(self.save_failed)
        QThreadPool.globalInstance().start(self.task)

    def saved(self, ident):
        self.saving = False
        self.photo_id = ident
        self.shutdown()
        self.accept()

    def save_failed(self, error):
        self.saving = False
        for w in (self.selection, self.save_button, self.retake_button, self.retry_button, self.cancel_button):
            w.setEnabled(True)
        self.status.setText('Photo was not saved. Your intake remains a draft. Check free disk space and the data folder, then try Save photo again.\n' + error)

    def shutdown(self):
        self.closed = True
        self.timeout.stop()
        self.backend.stop()

    def reject(self):
        if not self.saving:
            self.shutdown()
            super().reject()

    def closeEvent(self, event):
        if self.saving:
            event.ignore()
        else:
            self.shutdown()
            super().closeEvent(event)
