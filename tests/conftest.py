import importlib.util
import pytest
from repairshop.images import solid
from repairshop.persistence import Database
from repairshop.services import Service

# Desktop-presentation tests hand QImage photos to the core; the legacy package registers
# that conversion. Core and API tests need nothing from Qt.
if importlib.util.find_spec('PyQt6') is not None:
    import legacy_desktop  # noqa: F401


@pytest.fixture
def service(tmp_path):
    s = Service(Database(tmp_path / "shop"))
    s.setup("Test Repair Shop", "owner", "CorrectHorse123!")
    return s


@pytest.fixture
def customer(service):
    from repairshop.customer_records import CustomerRecords
    ident = service.save_customer("Synthetic Customer", "9990000001", "synthetic@example.invalid", whatsapp_consent=True, email_consent=True, complete=False)
    CustomerRecords(service).save_photo(solid(), ident)
    return ident


@pytest.fixture
def job(service, customer):
    return service.intake(customer, "ThinkPad T14", "Does not start", accessories=[dict(description="Adapter", type="accessory", quantity=1), dict(description="Mouse", type="accessory", quantity=2)], assessment_consent=True)
