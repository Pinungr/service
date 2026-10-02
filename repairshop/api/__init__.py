"""HTTP adapter for the RepairShop modular monolith.

One FastAPI application in one process exposes the headless `repairshop` business core
to the browser. Route modules translate HTTP to direct Python calls on the existing
services; they hold no business rules and no SQL. Nothing here is a separate service.
"""
