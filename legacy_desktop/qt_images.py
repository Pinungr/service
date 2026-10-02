"""Hand Qt images to the headless core as encoded bytes."""
from PyQt6.QtCore import QBuffer, QIODevice
from PyQt6.QtGui import QImage
from repairshop.images import register_adapter


def qimage_bytes(image):
    if not isinstance(image, QImage):
        return None
    if image.isNull():
        return b''
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    return bytes(buffer.data()) if image.save(buffer, 'PNG') else b''


register_adapter(qimage_bytes)
