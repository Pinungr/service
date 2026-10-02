"""One router per business area of the modular monolith. All run in the same process."""
from . import system, dashboard, repairs, customers, intake, contacts, dispatch, stock, finance, documents, admin

ROUTERS = [system.router, dashboard.router, repairs.router, customers.router, intake.router, contacts.router,
           dispatch.router, stock.router, finance.router, documents.router, admin.router]
