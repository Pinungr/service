import pytest
from repairshop.persistence import Database
from repairshop.services import Service


@pytest.fixture
def service(tmp_path):
    s = Service(Database(tmp_path / "shop"))
    s.setup("Test Repair Shop", "owner", "CorrectHorse123!")
    return s


@pytest.fixture
def customer(service):
    from PyQt6.QtGui import QImage, QColor
    from repairshop.customer_records import CustomerRecords
    ident = service.save_customer("Synthetic Customer", "9990000001", "synthetic@example.invalid", whatsapp_consent=True, email_consent=True)
    image = QImage(64, 64, QImage.Format.Format_RGB32)
    image.fill(QColor('#68a398'))
    CustomerRecords(service).save_photo(image, ident)
    return ident


@pytest.fixture
def job(service, customer):
    return service.intake(customer, "ThinkPad T14", "Does not start", accessories=[dict(description="Adapter", type="accessory", quantity=1), dict(description="Mouse", type="accessory", quantity=2)], assessment_consent=True)
