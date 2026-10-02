"""PyQt6 desktop presentation of RepairShop Manager, kept during the move to the web UI.

Everything here is presentation over the headless `repairshop` core: no business rule is
defined in this package. It is retired once the web frontend reaches parity.
"""
from . import qt_images  # noqa: E402,F401  (lets desktop code pass QImage photos to the core)
