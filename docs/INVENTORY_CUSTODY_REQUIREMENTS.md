Modify my EXISTING RepairShop Manager application.

Do NOT rebuild the application from scratch.

The existing application already has:

* Master Repair Job IDs
* Job Cards
* Customer receiving receipts
* In-house repair
* Third-party repair
* Authorized service center flow
* Device custody
* Repair lifecycle/status
* Quotations
* Billing
* Repair parts
* Vendors/service centers
* Installed-part warranties
* Warranty claims
* Timeline/audit history
* PyQt6 UI
* SQLite/SQLAlchemy
* Versioned migrations

Preserve all existing working behavior.

The goal of this change is to:

1. Add a proper SHOP SPARE-PART INVENTORY.
2. Make shop inventory the preferred spare-part source.
3. Properly support spare parts required by third-party technicians.
4. Separate vendor labour cost from vendor spare-part cost.
5. Maintain internal cost vs customer selling price/margin.
6. Improve installed-part warranty tracking.
7. Add manual warranty verification when historical warranty is not present in the system.
8. Fix third-party/service-center return Job Cards.
9. Fix confusing IN TRANSIT statuses.
10. Correct courier custody/receiver handling.
11. Correct in-house technician physical custody.
12. Prevent unrelated vendor selection for third-party-supplied parts.
13. Prevent warranty-status conflicts while a warranty claim is active.

Inspect the existing repository carefully before changing anything.

Reuse existing models/services/UI where possible.

Do not create duplicate systems.

============================================================
A. SHOP SPARE-PART INVENTORY
============================

Add or extend a proper shop inventory module for repair spare parts.

The shop must be able to maintain stock such as:

Laptop Battery
RAM
SSD
Keyboard
Display
Charging Port
Motherboard Components
Mobile Display
Mobile Battery
Printer Parts
Cables
Adapters
Connectors
ICs
Fans
Thermal Paste
and other repair components.

Inventory items should support, where applicable:

* Inventory Item ID
* SKU
* Part Name
* Category
* Brand
* Model
* Compatible Device / Compatibility Notes
* Part Number
* Serial Number if individually serialized
* Batch Number if relevant
* Quantity Available
* Quantity Reserved
* Quantity Issued
* Unit Purchase Cost
* Default Customer Selling Price
* Default Margin / Markup if configured
* Supplier
* Supplier Invoice Number
* Purchase Date
* Storage Location / Shelf / Bin
* Minimum Stock Level
* Default Warranty Duration
* Warranty Unit
* Notes
* Active / Inactive

Do not force serial numbers for generic/non-serialized items.

Support both:

serialized parts

and

quantity-based parts.

Example:

Dell Laptop Battery
SKU: BAT-DELL-001
Stock: 5
Purchase Cost: ₹2,500
Default Selling Price: ₹3,200
Default Warranty: 6 Months

============================================================
B. INVENTORY STOCK MOVEMENT
===========================

Every inventory quantity change must create a stock movement record.

Examples:

STOCK RECEIVED

STOCK ADJUSTMENT

RESERVED FOR JOB

ISSUED TO IN-HOUSE TECHNICIAN

ISSUED TO THIRD-PARTY TECHNICIAN

INSTALLED IN DEVICE

RETURNED UNUSED

DAMAGED

SCRAPPED

WARRANTY REPLACEMENT

CUSTOMER RETURN if applicable

Each movement should store:

* Inventory Item
* Quantity
* Movement Type
* Date/Time
* Master Job ID if related
* Repair Part ID if related
* From Location
* To Location
* Technician/Vendor if relevant
* Staff User
* Reason
* Notes

Maintain a permanent audit history.

Do not silently modify inventory quantity.

============================================================
C. SPARE-PART SELECTION DURING REPAIR
=====================================

When either an in-house technician or third-party technician identifies a required spare part:

FIRST allow the operator to search SHOP INVENTORY.

Example:

Required Part:
Dell Battery 54Wh

Show:

SHOP INVENTORY

Dell Battery 54Wh
Stock: 3
Purchase Cost: ₹2,500
Customer Price: ₹3,200
Warranty: 6 Months

Provide:

USE FROM SHOP INVENTORY

If inventory has the required part, the operator can reserve it for the current repair.

If inventory does not contain the correct part, allow external sourcing.

============================================================
D. THIRD-PARTY TECHNICIAN SPARE-PART FLOW
=========================================

A third-party technician may tell our shop:

Required Repair:
Motherboard work

Technician Labour:
₹800

Required Spare Part:
Charging IC

Part Cost:
₹1,200

These values are INTERNAL information.

They must NOT automatically become the customer price.

When a third-party technician requires a spare part, support these paths:

SHOP INVENTORY

or

THIRD-PARTY TECHNICIAN SUPPLIES IT

or

EXTERNAL SUPPLIER

============================================================
E. THIRD PARTY + SHOP INVENTORY
===============================

If the required spare part exists in shop inventory:

Allow the shop to reserve the item.

Then allow:

ISSUE PART TO THIRD-PARTY TECHNICIAN

Record:

* Inventory Item
* Quantity
* Master Job
* Device
* Third-Party Vendor
* Date/Time
* Staff issuing it
* Cost
* Warranty template
* Notes

Inventory should move:

AVAILABLE
→ RESERVED
→ ISSUED
→ INSTALLED

If the technician returns the part unused:

ISSUED
→ RETURNED
→ AVAILABLE

Do not consume final stock until the correct business event occurs according to the existing inventory architecture.

Use transactional stock handling.

============================================================
F. PART TRANSFER TO THIRD PARTY
===============================

When a shop-owned spare part is physically handed to a third-party technician, create a custody/transfer record.

It should also appear in the Master Job timeline.

If appropriate to the current Job Card architecture, create a Job Card type such as:

PART ISSUE TO VENDOR

Example:

Master Job:
REP-2026-000128

Card:
CARD-03

Type:
PART ISSUE TO VENDOR

From:
ABC Repair Shop

To:
Rajesh Laptop Service

Part:
Dell Battery

Quantity:
1

Device:
Dell Inspiron 15

Issued:
13 Sep 2026 11:30

This Job Card can be optionally printable.

If a dedicated inventory-transfer document fits the current architecture better than a device Job Card, use that instead, but it must remain visible from the Master Job.

============================================================
G. THIRD-PARTY PURCHASED PART
=============================

If the third-party technician buys/provides the spare part:

Record it separately from labour.

Do NOT combine this into one vendor charge.

Store:

TECHNICIAN LABOUR COST

PART COST

TRANSPORT COST

OTHER VENDOR COST

Example:

Vendor:
Rajesh Laptop Service

Labour Cost:
₹800

Part:
Charging IC

Part Cost:
₹1,200

Transport:
₹200

Internal Vendor Total:
₹2,200

Track:

* Vendor
* Part Name
* Brand
* Model
* Part Number
* Serial if applicable
* Quantity
* Vendor Part Cost
* Vendor Labour
* Vendor Invoice
* Part Warranty
* Warranty Provider
* Date Installed
* Installed By

============================================================
H. EXTERNAL SUPPLIER PART
=========================

If the repairer does not supply the part and the shop purchases it from another supplier:

Source Type:

EXTERNAL SUPPLIER

Record:

* Supplier
* Supplier Contact
* Supplier Invoice
* Part
* Purchase Cost
* Warranty
* Purchase Date

Do not incorrectly classify the repairing third-party technician as the supplier.

============================================================
I. FIX ISSUE: THIRD-PARTY SOURCE MUST MATCH VENDOR
==================================================

Current problem:

When:

Source = THIRD-PARTY TECHNICIAN

the operator can potentially select an unrelated vendor.

Fix this.

If:

PART SOURCE = REPAIRING THIRD-PARTY TECHNICIAN

then:

supplier/vendor must automatically be the third-party technician currently assigned to the repair.

Do not allow another vendor to be selected.

Example:

Repair Vendor:
Rajesh Laptop Service

Part Source:
Repairing Third Party

Supplier:
Rajesh Laptop Service

LOCK this field.

If the part came from another company:

Part Source must instead be:

EXTERNAL SUPPLIER.

============================================================
J. INTERNAL COSTING
===================

Create or improve an INTERNAL JOB COST view.

The shop owner/authorized staff should be able to see:

PART COST

IN-HOUSE TECHNICIAN COST if applicable

THIRD-PARTY LABOUR

THIRD-PARTY PART COST

SERVICE CENTER CHARGE

TRANSPORT

OTHER INTERNAL EXPENSE

TOTAL INTERNAL COST

Example:

Third-Party Labour       ₹800
Battery Cost           ₹2,500
Transport                ₹200
-----------------------------

Internal Cost          ₹3,500

This is INTERNAL information.

Do not expose it on customer invoices.

============================================================
K. CUSTOMER SELLING PRICE AND PROFIT MARGIN
===========================================

The customer quotation should use SELLING prices rather than internal costs.

Example:

Internal:

Battery Cost:
₹2,500

Customer Selling Price:
₹3,200

Internal Labour:
₹800

Customer Repair Charge:
₹1,500

Customer Estimate:

Battery              ₹3,200
Repair Labour        ₹1,500
---------------------------

Customer Total       ₹4,700

Internal Cost:
₹3,300

Expected Margin:
₹1,400

Margin must be visible only to authorized/internal users.

Do not print purchase cost/vendor cost/margin on customer documents.

============================================================
L. CUSTOMER APPROVAL
====================

Before paid repair begins, present the complete customer quotation.

Example:

Required Repair:
Motherboard Repair

Parts:

Dell Battery
₹3,200
Warranty: 6 Months

Repair Labour:
₹1,500

Total:
₹4,700

Customer approval:

PENDING
APPROVED
DECLINED

If additional parts are discovered after approval:

Create a quotation revision.

Do not silently modify an approved quote.

Show:

Previous Approved Amount

Additional Part

Additional Charge

Revised Total

Request customer approval again where required.

============================================================
M. PART INSTALLATION
====================

Once the part is actually installed:

Record:

* Device
* Master Job
* Part
* Inventory Item if shop supplied
* Source
* Supplier
* Cost
* Customer Selling Price
* Installed By
* Installation Date
* Warranty
* Serial Number
* Notes

If supplied from shop inventory:

update stock movement to:

INSTALLED

The installed part becomes part of the permanent DEVICE REPAIR HISTORY.

============================================================
N. WARRANTY FROM SHOP INVENTORY
===============================

Inventory items may have a default warranty template.

Example:

Dell Battery

Default Warranty:
6 Months

When installed:

Do NOT simply point to the inventory warranty template.

Create an actual installed-part warranty record.

Example:

Device:
DEV-00128

Part:
Dell Battery

Installed:
12 Sep 2026

Warranty:
6 Months

Expiry:
12 Mar 2027

Original Job:
REP-2026-000128

This warranty belongs to the installed part/device history.

Changing the inventory item's default warranty later must NOT alter historical warranties already issued.

============================================================
O. EXTERNAL PART WARRANTY
=========================

If a third-party technician or external supplier supplies the part:

Allow warranty metadata to be recorded.

Example:

Supplier:
Rajesh Laptop Service

Part:
Charging IC

Warranty:
3 Months

Warranty Provider:
Rajesh Laptop Service

This should also generate an installed-part warranty in the system.

If no reliable warranty information is provided:

allow:

WARRANTY NOT RECORDED

Do not invent a warranty.

============================================================
P. MANUAL WARRANTY VERIFICATION
===============================

If a customer comes for warranty service but the warranty does NOT exist in the application:

Allow staff to perform:

MANUAL WARRANTY CHECK

Examples of evidence:

* Original shop invoice
* Printed warranty slip
* Supplier invoice
* Manufacturer warranty
* Vendor confirmation
* Other evidence

Record:

Verification Result:

VALID
INVALID
UNVERIFIED

Evidence Type

Reference Number

Checked By

Checked Date

Notes

Optional attachment/photo of evidence if existing document architecture supports it.

Do NOT create fake historical inventory entries just to make the warranty appear in the system.

If manual warranty is accepted, allow the shop to proceed according to business policy and create an auditable warranty-service record.

============================================================
Q. FIX RETURN JOB CARDS
=======================

Current issue:

Third-party/service-center RETURN Job Cards do not contain enough structured repair/result information.

Expand return Job Cards.

THIRD-PARTY RETURN JOB CARD should include:

* Master Job ID
* Job Card Number
* Vendor
* Device
* Return Date/Time
* Repair Result
* Repair Status
* Work Performed
* Diagnosis
* Parts Installed
* Part Source
* Vendor Invoice
* Vendor Labour Cost
* Vendor Part Cost
* Transport Cost
* Other Vendor Cost
* Total Vendor Cost
* Device Condition on Return
* Accessories Returned
* Warranty Information
* Vendor Notes
* Shop Receiver
* Acknowledgment

Repair Result options may include:

REPAIRED

PARTIALLY REPAIRED

NOT REPAIRABLE

REPAIR DECLINED

RETURNED WITHOUT REPAIR

REPLACED where applicable

The historical Job Card must preserve the values at the time of return.

============================================================
R. SERVICE CENTER RETURN JOB CARD
=================================

Expand service-center return Job Cards similarly.

Include:

* Service Center
* Service Center Reference
* Warranty Claim Number
* Result
* Work Performed
* Warranty Accepted/Rejected
* Chargeable Repair
* Service Center Charges
* Parts/Replacements reported
* Replacement Device Serial/IMEI if applicable
* Return Date
* Device Condition
* Accessories
* Notes
* Receiver

============================================================
S. FIX IN-TRANSIT STATUS
========================

Current problem:

The UI may effectively show contradictory information such as:

IN TRANSIT · AT SERVICE CENTER

or:

IN TRANSIT · WITH THIRD-PARTY TECHNICIAN

Fix this.

STATUS and PHYSICAL LOCATION must be separate concepts.

Example while courier has the device:

REPAIR ROUTE:
THIRD PARTY

STATUS:
DISPATCHED TO THIRD PARTY

PHYSICAL LOCATION:
IN TRANSIT

CURRENT CUSTODIAN:
DTDC

DESTINATION:
Rajesh Laptop Service

NEXT ACTION:
Confirm Arrival at Third Party

After arrival is confirmed:

STATUS:
WITH THIRD-PARTY TECHNICIAN

PHYSICAL LOCATION:
Rajesh Laptop Service

CURRENT CUSTODIAN:
Rajesh Laptop Service

NEXT ACTION:
Wait for Vendor Diagnosis

Never display that the device is physically at the vendor/service center while the current custody record says a courier has it.

============================================================
T. FIX COURIER JOB CARD / RECEIVER
==================================

Current issue:

A dispatch Job Card can show:

From:
ABC Repair Shop

To:
Samsung Service Center

while the device is actually physically handed to:

DTDC

Fix custody representation.

Separate:

CURRENT CUSTODIAN

from:

FINAL DESTINATION.

For courier dispatch:

Example:

CARD-02

Type:
COURIER HANDOVER

From:
ABC Repair Shop

To / Custodian:
DTDC

Final Destination:
Samsung Authorized Service Center

Status:
IN TRANSIT

When service center confirms receipt:

create a custody event and, if appropriate, another Job Card:

CARD-03

From:
DTDC

To:
Samsung Authorized Service Center

Type:
SERVICE CENTER RECEIPT

Then:

Location = SERVICE CENTER

Custodian = Samsung Authorized Service Center

The same pattern should work for third-party technicians.

Also support reverse transit:

Service Center/Vendor
→ Courier
→ Shop.

============================================================
U. DIRECT HANDOVER WITHOUT COURIER
==================================

If shop staff directly hand the device to the vendor/service center:

No transit intermediary is required.

Create:

Shop
→ Vendor/Service Center

and immediately set physical custody accordingly.

Do not force courier steps when no courier exists.

============================================================
V. FIX IN-HOUSE PHYSICAL CUSTODY
================================

Current issue:

Assigning an in-house technician creates an assignment card but physical device custody may still remain at:

IN SHOP / FRONT DESK.

This can confuse staff.

Separate:

WORK ASSIGNMENT

from:

PHYSICAL HANDOVER.

When assigning an in-house technician, prompt:

HAS THE DEVICE BEEN PHYSICALLY HANDED TO THIS TECHNICIAN?

If YES:

Create/complete the in-house handover Job Card.

Set:

REPAIR ROUTE:
IN-HOUSE

STATUS:
WITH IN-HOUSE TECHNICIAN

PHYSICAL LOCATION:
Technician Work Area / Bench

CURRENT CUSTODIAN:
Technician Name

Example:

Technician:
Amit Kumar

Location:
Bench 2

If NO:

Keep:

PHYSICAL LOCATION:
Front Desk / Storage Location

ASSIGNED TECHNICIAN:
Amit Kumar

CURRENT CUSTODIAN:
Shop

NEXT ACTION:
Hand Device to Technician

Then provide:

HAND DEVICE TO TECHNICIAN

Once completed, update custody.

============================================================
W. TECHNICIAN RETURN TO SHOP STORAGE
====================================

When an in-house technician finishes work and returns the device to the counter/QC area:

record another custody movement:

Technician
→ Shop QC

Update:

PHYSICAL LOCATION:
QC Area

CURRENT CUSTODIAN:
Shop

STATUS:
FINAL QC

This must appear in timeline/history.

============================================================
X. WARRANTY CLAIM STATUS LOCK
=============================

Current issue:

Warranty status can potentially be manually edited while an active warranty claim exists.

This can create contradictory states such as:

Warranty:
ACTIVE

Claim:
OPEN

Fix this.

If a warranty has an active claim in:

OPEN

ACCEPTED

IN_REPAIR

then normal manual warranty-status editing must be disabled.

Display:

WARRANTY STATUS MANAGED BY ACTIVE CLAIM

Claim:
WC-XXXX

Current Claim State:
IN_REPAIR

The claim workflow becomes authoritative.

============================================================
Y. WARRANTY CLAIM STATE TRANSITIONS
===================================

Derive warranty state from claim outcome where appropriate.

Example:

Claim OPEN
→ Warranty shows CLAIM IN PROGRESS

Claim ACCEPTED
→ CLAIM IN PROGRESS

Claim IN_REPAIR
→ CLAIM IN PROGRESS

Claim REPLACED
→ update warranty according to replacement policy

Claim COMPLETED
→ close claim and update warranty as appropriate

Claim REJECTED
→ original warranty may remain ACTIVE if still valid and rejection reason does not void it

Claim CLOSED
→ unlock normal warranty administration if applicable

Do not blindly mark every warranty CLAIMED permanently simply because a claim was opened.

============================================================
Z. WARRANTY ADMIN OVERRIDE
==========================

Allow authorized owner/admin users to override warranty data only through a dedicated action.

Require:

* Reason
* User
* Date/Time
* Previous Value
* New Value

Create audit history.

If an active claim exists, warn/block normal override.

If a special administrative override is necessary, require an explicit privileged override and reason.

============================================================
AA. INVENTORY UI
================

Add an Inventory section to the main navigation.

Suggested views:

INVENTORY DASHBOARD

ALL PARTS

LOW STOCK

OUT OF STOCK

STOCK MOVEMENTS

SUPPLIERS

PART WARRANTY DEFAULTS

Inventory table should show:

SKU

Part

Brand

Compatibility

Stock

Reserved

Available

Purchase Cost

Selling Price

Margin

Warranty

Supplier

Storage Location

Status

Allow search/filter by:

Part name

SKU

Brand

Model

Part number

Compatibility

Supplier

============================================================
AB. INVENTORY ITEM DETAIL
=========================

Inventory detail screen should display:

Part Information

Stock

Cost

Selling Price

Margin

Supplier

Warranty

Storage Location

Purchase History

Stock Movement History

Jobs where the part was installed

Warranty claims related to installations of this part

============================================================
AC. REPAIR PART SELECTION UI
============================

Inside a Repair Job → Parts tab:

Provide:

ADD REQUIRED PART

Step 1:

Search Shop Inventory

If found:

USE SHOP STOCK

If not:

SOURCE EXTERNALLY

External options:

REPAIRING THIRD PARTY

EXTERNAL SUPPLIER

OTHER

The user should clearly understand the source before proceeding.

============================================================
AD. THIRD-PARTY BUDGET UI
=========================

For third-party repair add an INTERNAL COSTING panel.

Example:

Vendor:
Rajesh Laptop Service

Vendor Diagnosis:
Charging circuit failure

Vendor Labour:
₹800

Parts Required:

Charging IC
Source:
SHOP INVENTORY

Internal Cost:
₹600

OR

Charging IC
Source:
VENDOR

Vendor Part Cost:
₹1,200

Transport:
₹200

Total Internal Vendor/Repair Cost:
₹2,200

Then separately:

CUSTOMER QUOTATION

Charging IC:
₹1,800

Repair Charge:
₹1,500

Transport/Other:
₹200

Customer Total:
₹3,500

Expected Margin:
₹1,300

Do not mix these two views.

============================================================
AE. ACCESS CONTROL
==================

Internal cost and profit information should only be visible to authorized roles such as Owner/Admin according to the existing permission architecture.

Normal counter/customer-facing screens should show selling prices only.

Never expose:

purchase cost

vendor cost

profit margin

on customer-facing Job Cards or invoices.

============================================================
AF. NEXT ACTION ENGINE
======================

Update the Next Action logic to understand these new states.

Examples:

Check Shop Inventory

Reserve Spare Part

Issue Spare Part to Technician

Issue Spare Part to Vendor

Wait for Vendor Diagnosis

Review Vendor Labour and Parts Budget

Prepare Customer Quote

Get Customer Approval

Order External Part

Receive External Part

Confirm Courier Pickup

Confirm Vendor Arrival

Confirm Service Center Arrival

Receive Device From Courier

Receive Device From Vendor

Return Device From Technician to QC

Perform Final QC

Review Warranty Claim

============================================================
AG. TIMELINE
============

Every important event must appear chronologically.

Example:

12 Sep 10:30
Customer device received.
CARD-01 created.

12 Sep 11:00
Third-party repair selected.

12 Sep 11:15
Vendor Rajesh Laptop Service assigned.

12 Sep 11:30
Vendor requested Dell Battery.

12 Sep 11:35
Shop inventory checked.
3 units available.

12 Sep 11:40
1 Dell Battery reserved for REP-2026-000128.

12 Sep 12:00
Battery issued to Rajesh Laptop Service.

12 Sep 12:00
PART ISSUE TO VENDOR recorded.

12 Sep 14:00
Device handed to DTDC.

12 Sep 14:00
Current Location: IN TRANSIT.

13 Sep 09:30
Rajesh Laptop Service confirmed device receipt.

13 Sep 09:30
Current Location: Rajesh Laptop Service.

13 Sep 15:00
Vendor Labour: ₹800.

13 Sep 15:05
Customer Quote: ₹4,700.

13 Sep 16:00
Customer approved quotation.

14 Sep 17:00
Battery installed.

14 Sep 17:00
6-month battery warranty created.

15 Sep 10:00
Device returned to shop.

15 Sep 10:00
Third-party Return Job Card created.

15 Sep 10:30
Final QC passed.

============================================================
AH. DATA CONSISTENCY
====================

The following information must never contradict each other:

Repair Route

Lifecycle Status

Physical Location

Current Custodian

Destination

Assigned Technician

Third-Party Vendor

Current Job Card

Inventory Part Status

Warranty Claim Status

Next Action

Create business-service validation rather than implementing these rules independently in individual PyQt widgets.

============================================================
AI. MIGRATIONS
==============

Inspect the existing schema first.

Reuse existing:

inventory

parts

suppliers

stock

repair parts

vendors

custody events

warranties

if equivalents already exist.

Only add new columns/tables when necessary.

Use the existing versioned migration architecture.

Never recreate the production database.

============================================================
AJ. TESTS
=========

Add/update tests for all new behavior.

Inventory:

Create inventory item.

Receive stock.

Reserve stock.

Issue stock to in-house technician.

Issue stock to third-party vendor.

Return unused part.

Install part.

Prevent negative stock.

Low-stock detection.

Serialized part handling if supported.

Third Party:

Vendor requests part.

Shop inventory has part.

Shop provides part to vendor.

Vendor supplies part.

External supplier supplies part.

Vendor labour and part cost stored separately.

Wrong vendor cannot be selected for "repairing third-party supplied" part.

Customer quotation uses selling price.

Internal cost does not appear on customer receipt.

Margin calculated correctly.

Warranty:

Inventory default warranty creates installed-part warranty.

Changing inventory default does not modify historical warranty.

External part warranty works.

Manual warranty verification works.

Active warranty claim locks manual status editing.

Rejected claim handles warranty correctly.

Admin override creates audit history.

Transit:

Shop → Courier.

Courier → Vendor.

Courier → Service Center.

Vendor → Courier → Shop.

Direct shop → vendor without courier.

Status/location/custodian always consistent.

In-House:

Assign technician without physical handover.

Hand device to technician.

Location changes to technician.

Technician returns device to QC.

Custody history correct.

Return Job Cards:

Third-party result stored.

Work performed stored.

Parts stored.

Vendor invoice stored.

Vendor labour stored.

Vendor parts cost stored.

Service-center result stored.

Replacement device details stored.

Legacy:

Existing jobs remain readable.

Existing quotations remain readable.

Existing installed parts remain readable.

Existing warranties remain readable.

Existing Job Cards remain readable.

============================================================
AK. IMPLEMENTATION ORDER
========================

Implement carefully in this order:

1. Inspect current repository.
2. Identify existing inventory/part/vendor/custody/warranty architecture.
3. Design only the missing schema additions.
4. Add safe migrations.
5. Implement inventory service.
6. Implement stock movements.
7. Integrate repair-part sourcing with inventory.
8. Integrate third-party spare-part requirement flow.
9. Separate vendor labour and vendor part cost.
10. Add internal costing/customer pricing separation.
11. Add installed-part warranty generation.
12. Add manual warranty verification.
13. Expand third-party return Job Card.
14. Expand service-center return Job Card.
15. Fix transit status/location separation.
16. Fix courier custody and final destination.
17. Fix in-house custody/handover.
18. Restrict third-party part supplier.
19. Lock warranty status during active claims.
20. Update Next Action engine.
21. Update Repair Workspace UI.
22. Add Inventory UI.
23. Update timeline.
24. Update permissions.
25. Add automated tests.
26. Run complete existing and new test suite.

============================================================
AL. DO NOT
==========

Do NOT rebuild the application.

Do NOT remove existing Master Job/Job Card architecture.

Do NOT create a second unrelated spare-parts system if one already partially exists.

Do NOT combine vendor labour and vendor part cost.

Do NOT show internal costs/margins to customers.

Do NOT deduct inventory without a stock movement.

Do NOT allow negative inventory.

Do NOT change historical installed-part warranties when inventory defaults change.

Do NOT invent historical warranties.

Do NOT allow unrelated vendors for "repairing third-party supplied" parts.

Do NOT show vendor/service center as current location while courier actually holds the device.

Do NOT treat technician assignment as physical possession unless handover is recorded.

Do NOT allow warranty state and active claim state to contradict each other.

Do NOT modify unrelated working functionality.

============================================================
AM. DEFINITION OF DONE
======================

The implementation is complete when a shop employee can open one repair job and clearly understand:

what spare parts are required,

whether the part exists in shop inventory,

how much stock is available,

whether it has been reserved,

whether it was given to an in-house technician or third-party technician,

whether the third party supplied the part themselves,

which supplier provided an external part,

the actual internal part cost,

the technician/vendor labour cost,

the customer selling price,

the expected margin,

what the customer approved,

which parts were actually installed,

the warranty for every installed part,

whether warranty data exists in the system,

whether warranty must be manually verified,

where the device physically is,

who actually has custody of it,

whether it is currently with a courier,

what the final destination is,

what happened when it returned from the vendor/service center,

what the current warranty claim state is,

and what action the employee must perform next.

Most importantly:

INVENTORY + DEVICE CUSTODY + REPAIR STATUS + JOB CARDS + PART COST + CUSTOMER PRICE + WARRANTY must form one consistent workflow.

After implementation provide:

* files modified,
* files added,
* database/migration changes,
* inventory architecture,
* stock movement architecture,
* vendor-cost changes,
* return Job Card changes,
* transit/courier changes,
* in-house custody changes,
* warranty changes,
* UI changes,
* tests added,
* full test results,
* assumptions,
* remaining limitations.
