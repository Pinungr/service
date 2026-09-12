You are modifying an EXISTING and WORKING Windows desktop application called RepairShop Manager.

Technology:
- Python
- PyQt6
- SQLite
- SQLAlchemy
- Existing versioned schema migrations
- Existing customer/device/job/quotation/payment/photo/history functionality

IMPORTANT:
Do NOT rebuild the application from scratch.
Do NOT remove or break existing working functionality.
Inspect the current project first and integrate the following requirements into the current architecture, models, services, database, UI, reports, and tests.

The main objective is to redesign and extend the repair lifecycle so the user can always understand:

1. What device is being repaired?
2. Who owns it?
3. What is the Master Job ID?
4. Where is the device physically located right now?
5. Who currently has custody of it?
6. Which repair route is being used?
7. What Job Cards have been created?
8. What parts were used?
9. Where did those parts come from?
10. What did those parts cost?
11. What price is being charged to the customer?
12. What warranty applies to each installed part?
13. What is the next action?
14. Is customer approval pending?
15. Is payment pending?
16. Has the device been delivered?
17. Is the complete job closed?

============================================================
1. CORE CONCEPT: MASTER JOB ID
============================================================

There must be ONE Master Repair Job ID for one customer repair case.

Example:

JOB-2026-00128

The Master Job ID must remain the SAME throughout the complete lifecycle.

Do NOT generate a different Master Job ID when:

- assigning the device internally,
- sending it to a third-party technician,
- sending it to a service center,
- receiving it back,
- handing it back to the customer.

Instead, create multiple JOB CARDS under the same Master Job ID.

Example:

Master Job:
JOB-2026-00128

Job Cards:

JOB-2026-00128 / CARD-01
JOB-2026-00128 / CARD-02
JOB-2026-00128 / CARD-03
JOB-2026-00128 / CARD-04

Conceptually:

MASTER JOB
    |
    +-- CARD-01 Customer -> Shop
    |
    +-- CARD-02 Shop -> In-house / Third Party / Service Center
    |
    +-- CARD-03 External Party -> Shop
    |
    +-- CARD-04 Shop -> Customer

Job Cards represent custody, assignment, dispatch, receipt, or handover events.

============================================================
2. CUSTOMER RECEIVING JOB CARD
============================================================

When the customer initially gives a product to the shop for repair:

Create:

1. Master Job ID
2. Customer Receiving Job Card
3. Printable customer receipt

The customer receiving Job Card MUST contain at minimum:

- Master Job ID
- Job Card Number
- Shop Name
- Customer Name
- Customer Mobile Number
- Customer Email
- Customer Address if available
- Device Type
- Brand
- Model
- Serial Number / IMEI
- Device ID
- Customer Complaint
- Device Physical Condition
- Accessories Received
- Date Received
- Time Received
- Staff Member Who Received It
- Device Photos reference
- Notes
- Customer signature/acknowledgment if existing application supports it

Example:

Master Job:
JOB-2026-00128

Job Card:
CARD-01

From:
Rahul Sharma

To:
ABC Repair Shop

Device:
Dell Inspiron 15

Complaint:
Not powering on

Received:
12 Sep 2026 10:30 AM

This Customer Receiving Job Card MUST ALWAYS be printable because the customer needs a physical receipt/slip confirming:

- the shop received the device,
- which device was received,
- date/time,
- complaint,
- accessories,
- Master Job ID.

Reuse the existing printable/PDF/report functionality wherever possible.

Do not unnecessarily create a completely separate printing framework.

============================================================
3. INTERNAL / THIRD-PARTY / SERVICE CENTER JOB CARDS
============================================================

Whenever the device is assigned, dispatched, received back, or handed over, create a new Job Card under the SAME Master Job ID.

These Job Cards may be optionally printable.

The customer personal information must NOT unnecessarily appear on third-party or service-center cards.

Use the shop as the sender/customer in external transactions.

------------------------------------------------------------
3A. IN-HOUSE ASSIGNMENT JOB CARD
------------------------------------------------------------

Example:

Master Job:
JOB-2026-00128

Job Card:
CARD-02

From:
ABC Repair Shop

Assigned To:
Amit Kumar

Type:
IN-HOUSE TECHNICIAN

Device:
Dell Inspiron 15

Purpose:
Diagnosis and motherboard repair

Assigned:
12 Sep 2026 11:30 AM

Include:

- Master Job ID
- Job Card Number
- Shop Name
- Technician Name
- Device
- Device ID
- Assignment Date/Time
- Complaint
- Work Requested
- Accessories if relevant
- Device condition
- Notes

Customer mobile/email should not be required on this card.

------------------------------------------------------------
3B. THIRD-PARTY DISPATCH JOB CARD
------------------------------------------------------------

When sending the product to a third-party technician:

Create another Job Card.

Example:

Master Job:
JOB-2026-00128

Job Card:
CARD-02

Sender:
ABC Repair Shop

Receiver:
Rajesh Laptop Service

Device:
Dell Inspiron 15

Purpose:
Motherboard repair

Dispatch Date:
12 Sep 2026 02:15 PM

The third-party Job Card should contain:

- Master Job ID
- Job Card Number
- Shop Name
- Third-Party Vendor / Technician
- Phone
- Address if available
- Device
- Device ID
- Device condition
- Accessories handed over
- Purpose of repair
- Dispatch Date
- Dispatch Time
- Expected Return Date
- Staff member who dispatched
- Notes

Do not include original customer phone/email unless explicitly required.

------------------------------------------------------------
3C. THIRD-PARTY RETURN JOB CARD
------------------------------------------------------------

When the device comes back from the third-party technician:

Create another Job Card.

Example:

CARD-03

From:
Rajesh Laptop Service

To:
ABC Repair Shop

Master Job:
JOB-2026-00128

Result:
Repair Completed

Return Date:
14 Sep 2026 04:30 PM

Record:

- Master Job ID
- Job Card Number
- Vendor
- Return date/time
- Repair result
- Work done
- Parts used
- Device condition
- Accessories returned
- Vendor charges
- Vendor invoice number
- Vendor notes
- Staff member who received it

After receipt:

Current Location = IN SHOP.

============================================================
4. AUTHORIZED SERVICE CENTER JOB CARDS
============================================================

For warranty or OEM repair:

When sending to an Authorized Service Center, create a Job Card under the same Master Job.

Example:

Master Job:
JOB-2026-00128

Job Card:
CARD-02

Sender:
ABC Repair Shop

Receiver:
Samsung Authorized Service Center

Type:
AUTHORIZED SERVICE CENTER

Create the following Job Cards as required:

1. Service Center Dispatch Job Card
2. Service Center Return Job Card

The original customer is NOT the direct customer on this external Job Card.

The SHOP is acting as the sender/customer.

Store:

- Shop Name
- Service Center Name
- Service Center Address
- Service Center Contact
- OEM / Brand
- Service Center Reference Number
- Warranty Claim Number
- Device
- Device ID
- Serial / IMEI
- Dispatch Date/Time
- Expected Return Date
- Device Condition
- Accessories
- Issue
- Notes

When the device returns:

Create Service Center Return Job Card.

Record:

- repair completed,
- replacement,
- rejected warranty,
- unable to repair,
- chargeable repair,
- replacement serial number if applicable,
- charges,
- date/time,
- notes.

After return:

Current Location = IN SHOP.

============================================================
5. CUSTOMER DELIVERY JOB CARD
============================================================

When the device is finally handed back to the customer:

Create another Job Card.

Example:

Master Job:
JOB-2026-00128

Job Card:
CARD-04

Sender:
ABC Repair Shop

Receiver:
Rahul Sharma

Type:
CUSTOMER DELIVERY

Include:

- Master Job ID
- Job Card Number
- Customer
- Device
- Device ID
- Repair Summary
- Parts Installed
- Warranty Summary
- Accessories Returned
- Final Amount
- Amount Paid
- Balance
- Delivery Date
- Delivery Time
- Delivered By
- Received By
- Customer Acceptance
- Notes

After completion:

Current Location = WITH CUSTOMER
Status = DELIVERED

Then allow final closure:

Status = CLOSED

============================================================
6. JOB CARD TIMELINE
============================================================

Inside every Master Repair Job, show a visual Job Card / Custody timeline.

Example:

JOB-2026-00128

CARD-01
Customer -> ABC Repair Shop
Received 12 Sep 10:30
Completed

        ↓

CARD-02
ABC Repair Shop -> Rajesh Laptop Service
Dispatched 12 Sep 14:15
Completed

        ↓

CARD-03
Rajesh Laptop Service -> ABC Repair Shop
Returned 14 Sep 16:30
Completed

        ↓

CARD-04
ABC Repair Shop -> Customer
Delivered 15 Sep 18:20
Completed

This must make the physical custody history obvious.

============================================================
7. CURRENT PHYSICAL LOCATION
============================================================

The Master Job screen must always show:

CURRENT LOCATION

Possible values:

- IN SHOP
- IN-HOUSE TECHNICIAN
- AUTHORIZED SERVICE CENTER
- THIRD-PARTY TECHNICIAN
- IN TRANSIT
- WITH CUSTOMER
- DELIVERED

Also show the actual responsible entity.

Example:

Current Location:
THIRD-PARTY TECHNICIAN

Location Name:
Rajesh Laptop Service

Responsible Person:
Rajesh Kumar

Pending Since:
12 Sep 2026 02:15 PM

Next Action:
Wait for Vendor Diagnosis

Update location automatically based on lifecycle/job-card transitions.

============================================================
8. PARTS / COMPONENT MANAGEMENT
============================================================

A major new requirement is tracking every additional part/component used during repair.

This mainly applies to:

- IN-HOUSE repairs
- THIRD-PARTY repairs

It is usually not required for Authorized Service Center warranty work, unless explicitly entered.

Do NOT store parts only as plain technician notes.

Create or reuse structured part records.

Each part installed into a customer's device must be traceable.

For every installed part record:

- Part Name
- Part Type
- Brand
- Model
- Part Number
- Serial Number if applicable
- Quantity
- Source Type
- Supplier
- Purchase Invoice
- Purchase Date
- Purchase Cost
- Customer Selling Price
- Tax if existing billing system supports it
- Installation Date
- Installed By
- Master Job ID
- Device ID
- Job Card if relevant
- Warranty Period
- Warranty Start Date
- Warranty Expiry Date
- Warranty Terms
- Notes

============================================================
9. PART SOURCE
============================================================

Every added repair part must identify its source.

Source options:

1. OWN SHOP INVENTORY
2. EXTERNAL SUPPLIER / VENDOR
3. THIRD-PARTY TECHNICIAN
4. OTHER

------------------------------------------------------------
9A. OWN SHOP INVENTORY
------------------------------------------------------------

If the part comes from shop stock:

- select the existing inventory item if available,
- reduce inventory quantity using existing inventory logic,
- capture cost,
- capture customer price,
- link the inventory movement to the Master Job.

Do not create duplicate stock systems if inventory already exists.

------------------------------------------------------------
9B. EXTERNAL SUPPLIER
------------------------------------------------------------

If purchased externally:

Record:

- Supplier Name
- Supplier Contact
- Supplier Address if available
- Supplier Invoice Number
- Purchase Date
- Purchase Cost
- Part Details
- Warranty Provided by Supplier
- Warranty Duration

Create reusable supplier/vendor master data rather than entering the same supplier repeatedly.

------------------------------------------------------------
9C. THIRD-PARTY TECHNICIAN PART
------------------------------------------------------------

If the third-party repairer provides the part:

Record:

- Vendor
- Part
- Vendor's part charge
- Vendor labour charge
- Customer selling price
- Warranty
- Vendor invoice/reference
- Installed by third party

============================================================
10. PART COST VS CUSTOMER PRICE
============================================================

Maintain separate amounts:

PURCHASE / VENDOR COST

and

CUSTOMER SELLING PRICE

Example:

Dell Battery

Purchase Cost:
₹2,500

Customer Price:
₹3,200

Margin:
₹700

Do not expose internal vendor cost or shop margin on customer-facing receipts unless existing business configuration specifically permits it.

Customer bill should show the CUSTOMER SELLING PRICE.

Internal job/accounting views can show:

- purchase cost,
- customer price,
- margin.

============================================================
11. CUSTOMER ESTIMATE BEFORE REPAIR
============================================================

Before starting paid repairs, prepare one complete estimate.

Estimate may contain:

- Repair Labour
- Diagnostic Charge
- Parts
- Third-Party Repair Charge
- Transport
- Service Charge
- Other Charge
- Tax where applicable
- Discount
- Total

Example:

Motherboard Repair Labour      ₹1,500
Dell Battery                   ₹3,200
Thermal Paste                    ₹300
--------------------------------------
Total                          ₹5,000

The customer must be informed of:

- repair work,
- parts that will be installed,
- total estimated amount.

Then capture:

CUSTOMER APPROVAL

Possible states:

- Pending
- Approved
- Declined

Do not start a chargeable repair requiring approval before approval is recorded.

Reuse the existing quotation/approval functionality where possible.

============================================================
12. CUSTOMER APPROVAL AND PARTS
============================================================

The approval screen must clearly list all expected parts.

Example:

Repair Estimate

Motherboard Repair             ₹1,500

Parts:

Dell Battery
₹3,200
Warranty: 6 months

Thermal Paste
₹300
Warranty: 3 months

Total:
₹5,000

Customer approves:
YES

Store the approved version of the estimate.

Do not silently alter an approved quotation.

If additional parts are later required:

- create an estimate revision,
- clearly identify newly added charges,
- get additional customer approval if business rules require it,
- retain previous approval history.

============================================================
13. PART WARRANTY MANAGEMENT
============================================================

Every installed part can have its own warranty.

Examples:

Battery:
6 Months

Charging Port:
3 Months

Display:
12 Months

Motherboard Repair Labour:
3 Months

Warranty must NOT only exist as text on an invoice.

Store structured warranty data.

For each warranty:

- Device ID
- Master Job ID
- Installed Part ID
- Part Name
- Installation Date
- Warranty Duration
- Warranty Unit
- Warranty Start Date
- Warranty Expiry Date
- Warranty Source
- Warranty Provider
- Warranty Terms
- Status
- Notes

Warranty Status:

- ACTIVE
- EXPIRED
- VOID
- CLAIMED
- REPLACED

Automatically calculate warranty expiry.

Example:

Installation:
12 Sep 2026

Warranty:
6 months

Expiry:
12 Mar 2027

============================================================
14. DEVICE WARRANTY LOOKUP
============================================================

When the SAME physical device comes back for a future repair:

Search using the stable Device ID.

Automatically check:

ACTIVE WARRANTIES

Display them prominently.

Example:

ACTIVE WARRANTY FOUND

Device:
Dell Inspiron 15

Part:
Dell Battery

Installed:
12 Sep 2026

Original Job:
JOB-2026-00128

Warranty:
6 Months

Valid Until:
12 Mar 2027

Allow the operator to review whether the new complaint relates to the warranted part.

============================================================
15. WARRANTY CLAIM
============================================================

If an active repair-part warranty applies:

Allow:

CREATE WARRANTY CLAIM

The new repair visit must still generate a NEW Master Job ID.

Example:

New Repair Job:
JOB-2026-00215

Warranty Claim Against:
JOB-2026-00128

Part:
Dell Battery

Original Installation:
12 Sep 2026

Warranty Valid Until:
12 Mar 2027

Store relationships between:

New Master Job
→ Warranty Claim
→ Original Job
→ Original Device
→ Original Installed Part
→ Original Warranty

Do not overwrite the original repair history.

============================================================
16. WARRANTY SHOULD FOLLOW DEVICE
============================================================

Part warranties should primarily be linked to:

PHYSICAL DEVICE + INSTALLED PART

not only to customer name.

This allows the system to identify an active installed-part warranty whenever the same physical device returns.

If business policy allows warranties to remain valid after device ownership changes, the system will still be able to find the warranty.

Provide an Edit Warranty option only for authorized users.

Record warranty edits in audit history.

============================================================
17. REPAIR ROUTE: IN-HOUSE
============================================================

For an in-house repair:

Initial Inspection
→ Out of Warranty
→ Select In-House
→ Create In-House Assignment Job Card
→ Assign Technician
→ Diagnosis
→ Identify Repair
→ Add Parts
→ Select Part Source
→ Calculate Estimate
→ Customer Approval
→ Issue Parts
→ Start Repair
→ Install Parts
→ Record Installed Parts
→ Technician Test
→ Final QC
→ Billing
→ Ready for Delivery
→ Customer Handover
→ Close

============================================================
18. REPAIR ROUTE: THIRD PARTY
============================================================

For third-party repair:

Initial Inspection
→ Out of Warranty
→ Select Third Party
→ Create Third-Party Dispatch Job Card
→ Send Device
→ Vendor Diagnosis
→ Vendor identifies required repair/parts
→ Record vendor estimate
→ Add Parts
→ Identify whether parts come from shop/vendor/external supplier
→ Prepare customer estimate
→ Customer Approval
→ Authorize Vendor
→ Vendor Repair
→ Receive Device Back
→ Create Return Job Card
→ Record Vendor Invoice
→ Record Parts Actually Installed
→ Final QC
→ Billing
→ Ready for Delivery
→ Handover
→ Close

============================================================
19. REPAIR ROUTE: AUTHORIZED SERVICE CENTER
============================================================

Warranty route:

Initial Inspection
→ Warranty Check
→ Valid Warranty
→ Select Service Center
→ Create Service Center Dispatch Job Card
→ Dispatch Device
→ Service Center Diagnosis
→ Warranty Repair / Replacement

or:

→ Paid Estimate
→ Customer Approval
→ Paid Repair

Then:

→ Receive Device Back
→ Create Return Job Card
→ Final Shop QC
→ Billing if applicable
→ Ready for Delivery
→ Customer Delivery Job Card
→ Close

============================================================
20. FINAL CUSTOMER BILL
============================================================

The final invoice/receipt must include customer-facing charges.

Example:

Repair Charges

Motherboard Repair Labour         ₹1,500
Dell Battery                      ₹3,200
Thermal Paste                       ₹300
Transport                            ₹200
-----------------------------------------
Subtotal                           ₹5,200
Advance                            ₹1,000
-----------------------------------------
Balance                            ₹4,200

Also show warranty information.

Example:

PART WARRANTY

Dell Battery
Warranty: 6 Months
Valid Until: 12 Mar 2027

Thermal Paste
Warranty: 3 Months
Valid Until: 12 Dec 2026

Repair Labour
Warranty: 3 Months
Valid Until: 12 Dec 2026

============================================================
21. UI REDESIGN
============================================================

The main job detail screen must show:

MASTER JOB ID

DEVICE

CUSTOMER

REPAIR ROUTE

CURRENT STATUS

CURRENT LOCATION

CURRENT RESPONSIBLE PARTY

CURRENT JOB CARD

PENDING SINCE

EXPECTED DATE

NEXT ACTION

Example:

JOB-2026-00128

Dell Inspiron 15

Route:
THIRD PARTY

Status:
WITH THIRD-PARTY TECHNICIAN

Current Location:
Rajesh Laptop Service

Current Job Card:
CARD-02

Pending Since:
12 Sep 2026 02:15 PM

Expected Return:
14 Sep 2026

Next Action:
WAIT FOR VENDOR REPAIR

============================================================
22. MAIN JOB SCREEN TABS
============================================================

Organize the repair job UI into clear sections/tabs such as:

Overview

Lifecycle

Job Cards

Diagnosis

Estimate

Parts

Warranty

Billing

Photos

Timeline

Documents

Do not overcrowd one screen.

============================================================
23. JOB CARD TAB
============================================================

Show all Job Cards chronologically.

Columns:

Card Number

Type

From

To

Date

Status

Printable

Action

Example:

CARD-01
Customer Receipt
Rahul Sharma
ABC Repair Shop
12 Sep 10:30
Completed
Print

CARD-02
Third-Party Dispatch
ABC Repair Shop
Rajesh Laptop Service
12 Sep 14:15
Completed
Print

CARD-03
Third-Party Return
Rajesh Laptop Service
ABC Repair Shop
14 Sep 16:30
Completed
Print

CARD-04
Customer Delivery
ABC Repair Shop
Rahul Sharma
15 Sep 18:20
Completed
Print

============================================================
24. PARTS TAB
============================================================

Create an easy-to-understand Parts tab.

Columns:

Part

Brand

Part Number

Qty

Source

Supplier

Purchase Cost

Customer Price

Installed By

Installed Date

Warranty

Warranty Expiry

Status

Allow actions:

Add Part

Edit Part

Remove Before Installation

Mark Installed

View Warranty

Create Warranty Claim if applicable

Do not allow removal of historically installed parts without audit tracking.

============================================================
25. WARRANTY TAB
============================================================

Show:

ACTIVE WARRANTIES

EXPIRED WARRANTIES

CLAIMED WARRANTIES

Columns:

Part

Original Job

Install Date

Warranty

Expiry

Status

Provider

Action

Use clear badges:

ACTIVE
EXPIRED
CLAIMED
VOID

============================================================
26. TIMELINE
============================================================

Every important action must be visible in chronological history.

Example:

12 Sep 10:30
Customer device received.
CARD-01 created.

12 Sep 11:00
Initial inspection completed.

12 Sep 11:10
Device marked out of warranty.

12 Sep 11:15
Third-party repair selected.

12 Sep 14:15
Device dispatched to Rajesh Laptop Service.
CARD-02 created.

13 Sep 10:30
Vendor estimate received.

13 Sep 11:00
Battery added to estimate.
Supplier: ABC Components.

13 Sep 11:15
Customer approved ₹5,000 estimate.

14 Sep 15:00
Repair completed.

14 Sep 16:30
Device received back.
CARD-03 created.

14 Sep 17:00
Final QC passed.

15 Sep 18:20
Device delivered to customer.
CARD-04 created.

Do not silently delete lifecycle history.

============================================================
27. DATABASE DESIGN
============================================================

Inspect existing models before adding new ones.

Reuse equivalent models where possible.

Possible entities may include:

RepairJob
JobCard
JobCardParty
RepairPart
PartSupplier
PartWarranty
WarrantyClaim
RepairEstimate
RepairEstimateItem
CustodyEvent

Do NOT blindly create these if equivalents already exist.

Avoid duplicate sources of truth.

Create proper versioned schema migrations for new tables/fields.

Never recreate the production database.

============================================================
28. JOB CARD MODEL
============================================================

A Job Card should conceptually support:

id

master_job_id

card_number

card_type

from_party_type

from_party_id

from_party_name_snapshot

to_party_type

to_party_id

to_party_name_snapshot

device_id

created_at

effective_at

expected_return_at

completed_at

status

condition_snapshot

accessories_snapshot

purpose

notes

created_by

printed_at

Do not rely entirely on live customer/vendor details.

Keep important party/address/details as snapshots where necessary so old Job Cards remain historically correct even if a vendor/customer changes later.

============================================================
29. PART MODEL
============================================================

Repair Part data should support:

repair_job_id

device_id

estimate_id

part_name

part_type

brand

model

part_number

serial_number

quantity

source_type

inventory_item_id

supplier_id

supplier_name_snapshot

supplier_invoice

purchase_date

purchase_cost

customer_price

installed_by_type

installed_by_id

installed_at

warranty_duration

warranty_unit

warranty_start

warranty_expiry

status

notes

============================================================
30. WARRANTY CLAIM MODEL
============================================================

Warranty Claim should support:

new_job_id

original_job_id

device_id

original_repair_part_id

original_warranty_id

claim_date

complaint

claim_status

resolution

replacement_part_id

notes

created_by

Possible claim statuses:

OPEN
ACCEPTED
REJECTED
IN_REPAIR
REPLACED
COMPLETED
CLOSED

============================================================
31. VALIDATIONS
============================================================

Implement strong business validation.

Examples:

Cannot create Customer Delivery before device has returned to shop.

Cannot dispatch to third party without selecting a vendor.

Cannot dispatch to service center without selecting a service center.

Cannot mark device received back unless an outbound Job Card exists.

Cannot install an external part without identifying its source.

Cannot install a shop inventory part when stock is unavailable.

Cannot start chargeable repair requiring approval if customer approval is pending.

Cannot close job while device is still with third party/service center.

Cannot close job before customer delivery.

Cannot create warranty claim against expired warranty unless authorized override exists.

Cannot delete installed repair parts without audit history.

============================================================
32. CUSTOMER PRIVACY
============================================================

Customer personal information must appear on customer-facing documents where required.

However:

Do not unnecessarily expose:

- Customer phone
- Email
- Address
- Customer photo

to:

- third-party technician Job Cards,
- service center dispatch cards,
- vendor-facing documents.

Use the SHOP as the external party's customer/sender.

============================================================
33. PRINTING
============================================================

Customer Receiving Receipt:
MANDATORY printable.

Customer Final Invoice:
MANDATORY printable.

Customer Delivery Receipt:
Printable.

Third-Party Job Card:
Printable optionally.

Service Center Job Card:
Printable optionally.

In-House Assignment Card:
Printable optionally.

Reuse existing PDF/printing architecture.

Use clean A4/A5/thermal-friendly layouts depending on current application support.

============================================================
34. DASHBOARD
============================================================

Update dashboard so shop staff can quickly identify:

Received

Initial Inspection

In-House

At Service Center

With Third Party

Waiting for Customer Approval

Waiting for Parts

Repair In Progress

Final QC

Ready for Delivery

Warranty Claims

Overdue

Delivered

Clicking a summary should filter jobs.

============================================================
35. ACTIVE JOB TABLE
============================================================

Recommended columns:

Master Job ID

Customer

Device

Repair Route

Current Job Card

Current Status

Current Location

Assigned To

Pending Since

Expected Date

Next Action

Estimate

Balance

Warranty Indicator

============================================================
36. NEXT ACTION ENGINE
============================================================

Every job must display one clear next action.

Examples:

Print Customer Receipt

Perform Initial Inspection

Verify Warranty

Create Service Center Dispatch Card

Select In-House Technician

Create Third-Party Dispatch Card

Wait for Vendor Diagnosis

Add Required Parts

Prepare Customer Estimate

Get Customer Approval

Order Part

Start Repair

Receive Device Back

Perform Final QC

Create Invoice

Notify Customer

Collect Balance

Create Delivery Job Card

Hand Over Device

Close Job

Use one prominent primary button where practical.

============================================================
37. STATE + LOCATION + CUSTODY MUST STAY CONSISTENT
============================================================

Do not allow inconsistent data such as:

Status:
WITH THIRD PARTY

Location:
IN SHOP

Current Card:
SERVICE CENTER

The lifecycle service must enforce consistency between:

- status,
- physical location,
- repair route,
- current Job Card,
- responsible party,
- next action.

============================================================
38. BUSINESS LOGIC ARCHITECTURE
============================================================

Do not place all lifecycle logic directly into PyQt6 widgets.

Prefer:

UI
→ Repair Lifecycle Service
→ Job Card / Warranty / Part Services
→ Repository / SQLAlchemy
→ SQLite

The business layer should determine:

- valid transitions,
- Job Card creation,
- current location,
- current responsible party,
- next action,
- required approvals,
- parts validation,
- warranty calculation,
- warranty eligibility,
- timeline events.

============================================================
39. EXISTING DATA
============================================================

Preserve:

- Customers
- Devices
- Stable Device IDs
- Customer Photos
- Device Photos
- Existing Repair Jobs
- Quotations
- Payments
- Invoices
- Attachments
- Repair History
- Existing Customer Folders
- Existing backups

Do not lose or recreate them.

============================================================
40. LEGACY COMPATIBILITY
============================================================

Inspect existing repair status data.

Create safe compatibility/mapping logic.

Do not blindly convert old records.

For legacy jobs where custody history cannot be reconstructed:

Do not invent historical Job Cards.

Allow them to display:

LEGACY RECORD

or equivalent historical state.

New Job Card logic should apply cleanly going forward.

============================================================
41. TESTING
============================================================

Add automated tests for at least:

CUSTOMER RECEIPT

- Master Job created
- CARD-01 created
- Printable receipt generated
- Date/time recorded
- Customer/device correct

IN-HOUSE

- Assignment card generated
- Technician assignment
- Part from inventory
- External part
- Estimate
- Customer approval
- Repair completion
- Part warranty
- Delivery

THIRD PARTY

- Dispatch card
- Customer info hidden from vendor-facing card
- Vendor diagnosis
- Vendor parts
- External supplier part
- Customer approval
- Vendor return card
- Vendor cost
- Final customer price
- QC
- Delivery

SERVICE CENTER

- Dispatch card
- Service-center reference
- Return card
- Warranty repair
- Warranty rejection
- Paid repair
- Replacement device

PARTS

- Inventory part
- External supplier
- Third-party supplied part
- purchase cost
- customer selling price
- margin calculation
- installation
- removal validation

WARRANTY

- 3-month warranty
- 6-month warranty
- expiry calculation
- active warranty lookup
- expired warranty
- future repair detects warranty
- warranty claim creation
- warranty claim references original job/part/device
- warranty editing permissions

JOB CARDS

- same Master Job across all cards
- sequential Job Card numbers
- customer receipt
- dispatch
- return
- delivery
- custody consistency

VALIDATION

- invalid dispatch blocked
- invalid receipt blocked
- unauthorized close blocked
- repair without required approval blocked
- inconsistent location/status blocked

LEGACY

- existing records remain readable
- existing invoices work
- existing payments work
- existing photos work
- existing customer/device history works

============================================================
42. IMPLEMENTATION ORDER
============================================================

Please implement in this order:

1. Inspect full current repository.

2. Understand current:
   - database schema,
   - migrations,
   - customer model,
   - device model,
   - job model,
   - custody model,
   - quotation model,
   - billing,
   - inventory,
   - vendor logic,
   - service center logic,
   - warranty support,
   - printing,
   - PDF generation,
   - UI navigation,
   - dashboard,
   - tests.

3. Identify reusable functionality.

4. Define Master Job + Job Card architecture.

5. Define status/location/custody lifecycle.

6. Add database migrations only where needed.

7. Add/extend business services.

8. Implement Job Card creation.

9. Implement customer receiving receipt.

10. Implement in-house assignment cards.

11. Implement third-party dispatch/return cards.

12. Implement service center dispatch/return cards.

13. Implement customer delivery card.

14. Implement structured repair parts.

15. Integrate shop inventory.

16. Implement supplier/source tracking.

17. Implement estimate integration.

18. Implement part warranty.

19. Implement warranty lookup.

20. Implement warranty claims.

21. Redesign main job detail screen.

22. Add Job Cards tab.

23. Add Parts tab.

24. Add Warranty tab.

25. Update lifecycle/timeline.

26. Update dashboard.

27. Update customer overview.

28. Update printing/PDFs.

29. Add validation.

30. Update automated tests.

31. Run complete existing and new test suite.

============================================================
43. DO NOT
============================================================

Do NOT rebuild the application from scratch.

Do NOT generate multiple unrelated repair Job IDs for one repair lifecycle.

Do NOT expose customer private information unnecessarily to vendors.

Do NOT store repair parts only as free-text notes.

Do NOT store warranties only inside PDF invoices.

Do NOT overwrite previous repair history during warranty claims.

Do NOT directly edit historical approved estimates without keeping revision history.

Do NOT duplicate existing inventory/vendor/quotation/payment functionality.

Do NOT delete production data.

Do NOT bypass migrations.

Do NOT silently modify unrelated working functionality.

============================================================
44. DEFINITION OF DONE
============================================================

The implementation is complete only when:

A staff member can open one Master Job and immediately understand:

- who the customer is,
- what device was received,
- when it was received,
- the original customer receiving card,
- every movement/job card,
- where the device physically is,
- who currently has it,
- which technician/service center/vendor is responsible,
- which parts are required,
- where every part came from,
- internal cost,
- customer price,
- customer-approved total,
- parts actually installed,
- warranty for each installed part,
- whether an old warranty is active,
- warranty claim history,
- customer balance,
- next action,
- whether the device has returned,
- whether QC passed,
- whether it is ready for delivery,
- whether it has been handed to the customer,
- whether the complete job is closed.

The UI should make the lifecycle visually obvious and require minimal guessing from the operator.

============================================================
45. FINAL RESPONSE AFTER IMPLEMENTATION
============================================================

After completing the changes, provide a clear implementation report containing:

1. Existing architecture discovered.
2. Files modified.
3. Files added.
4. Database changes.
5. Migration details.
6. Master Job / Job Card model.
7. Lifecycle statuses.
8. Physical-location model.
9. Parts model.
10. Supplier/source model.
11. Warranty model.
12. Warranty-claim model.
13. UI changes.
14. Printing changes.
15. Existing functionality preserved.
16. Tests added.
17. Test results.
18. Any assumptions.
19. Any remaining limitations or risks.

Most importantly, preserve the existing working application and integrate these requirements cleanly rather than creating a second parallel repair-management system.