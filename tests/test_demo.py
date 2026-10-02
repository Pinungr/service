"""The synthetic shop used for browser acceptance must stay buildable."""
from scripts.demo import create
from repairshop.persistence import Database
from repairshop.services import Service


def test_demo_creates_a_login_and_repair_history(tmp_path):
    create(tmp_path)
    service = Service(Database(tmp_path))
    assert service.login('demo', 'DemoShop2026!')['role'] == 'owner'
    assert service.db.one('SELECT count(*) AS total FROM jobs')['total'] == 24
    assert service.db.one('SELECT count(*) AS total FROM attachments')['total'] >= 12
