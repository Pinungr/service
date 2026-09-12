I have an existing and working **RepairShop Manager** Windows desktop application built with **Python, PyQt6, SQLite/SQLAlchemy**, with existing customer management, device intake, customer/device photos, stable device IDs, quotations, billing, payments, repair history, drafts, customer folders, and consolidated customer repair overview.

I do **NOT** want to rebuild the application from scratch.

I want you to inspect the existing project first and then **modify the current UI and workflow so that the repair lifecycle is extremely clear to shop staff**.

The current problem is that the application contains the required information, but it is confusing for the operator to understand:

* Where the customer's device physically is right now.
* Whether it is under warranty.
* Whether it is being repaired in-house.
* Whether it was sent to an authorized service center.
* Whether it was sent to a third-party technician.
* Whether diagnosis is pending.
* Whether customer approval is pending.
* Whether parts are pending.
* Whether repair is completed.
* Whether final QC is pending.
* Whether payment is pending.
* Whether the device is ready for delivery.
* Whether the device has already been delivered.

The redesigned UI must make these things immediately obvious.

Do not remove, rewrite, or break existing working functionality unless required for this lifecycle implementation.

---

# 1. TARGET REPAIR FLOW

The application must visually follow this business flow:

Customer Arrives
→ Customer Search / Registration
→ Device Intake
→ Device Photos
→ Generate Device ID and Repair Job ID
→ Receiving Receipt / Job Card
→ Initial Inspection
→ Warranty Check

From the warranty check there are three possible repair routes.

## Route A – Authorized Service Center

If the device is under valid manufacturer/OEM warranty:

Initial Inspection
→ Warranty Verification
→ Select Authorized Service Center
→ Create Dispatch Record
→ Send Device to Service Center
→ Record Service Center Reference Number
→ At Service Center
→ Service Center Diagnosis
→ Warranty Repair / Replacement OR Paid Estimate
→ If paid estimate, obtain customer approval
→ Service Center Repair
→ Receive Device Back at Shop
→ Record result and charges
→ Final Shop QC
→ Billing if applicable
→ Ready for Delivery
→ Customer Handover
→ Close Job

---

## Route B – In-House Repair

If the device is not under warranty and will be repaired by our shop:

Initial Inspection
→ In-House Diagnosis
→ Check Repairability
→ Identify Parts / Labour
→ Check Parts Availability
→ Order Parts if required
→ Prepare Customer Estimate
→ Customer Approval
→ Advance Payment if required
→ Repair in Shop
→ Technician Testing
→ Final QC
→ Billing
→ Ready for Delivery
→ Customer Handover
→ Close Job

---

## Route C – Third-Party Technician

If the device is not under warranty and needs an external technician:

Initial Inspection
→ Select Third-Party Technician / Vendor
→ Create Vendor Dispatch Record
→ Send Device to Vendor
→ Third-Party Diagnosis
→ Vendor Estimate
→ Calculate Customer Price / Shop Margin
→ Customer Approval
→ Authorize Vendor Repair
→ Vendor Repairs Device
→ Receive Device Back at Shop
→ Record Vendor Cost / Payment
→ Final Shop QC
→ Billing
→ Ready for Delivery
→ Customer Handover
→ Close Job

---

# 2. MOST IMPORTANT UI REQUIREMENT

For every active repair job, the user must be able to see immediately:

**CURRENT STATUS**

**CURRENT PHYSICAL LOCATION**

**REPAIR ROUTE**

**CURRENT RESPONSIBLE PARTY**

**NEXT REQUIRED ACTION**

For example:

Customer:
Rahul Sharma

Device:
Dell Inspiron 15

Job:
JOB-2026-00128

Repair Route:
THIRD PARTY

Current Status:
WITH THIRD-PARTY TECHNICIAN

Current Location:
ABC Laptop Service

Responsible Party:
Rajesh Technician

Pending Since:
12 Sep 2026, 11:30 AM

Next Action:
WAIT FOR VENDOR DIAGNOSIS

This information should be prominently visible without opening multiple screens.

---

# 3. REPAIR JOB HEADER

Redesign the repair/job detail screen.

At the top create a highly visible **Repair Status Header**.

Suggested structure:

---

JOB-2026-00128

Dell Inspiron 15
Serial: XXXXXXXX

[ THIRD PARTY REPAIR ]

CURRENT STATUS
WITH THIRD-PARTY TECHNICIAN

CURRENT LOCATION
ABC Laptop Service

RESPONSIBLE
Rajesh Technician

PENDING SINCE
12 Sep 2026

NEXT ACTION
Wait for Vendor Diagnosis

---

Use visual badges/chips for status.

Examples:

RECEIVED
INITIAL INSPECTION
WARRANTY CHECK
IN-HOUSE
SERVICE CENTER
THIRD PARTY
WAITING FOR CUSTOMER
WAITING FOR PARTS
REPAIR IN PROGRESS
FINAL QC
READY FOR DELIVERY
DELIVERED
CLOSED

Do not depend only on color.

Every badge must also have readable text.

---

# 4. ADD A REPAIR LIFECYCLE TRACKER

Below the job header add a clear horizontal or vertical lifecycle tracker.

Example:

Received
✓

Initial Inspection
✓

Warranty Check
✓

Third-Party Dispatch
✓

Vendor Diagnosis
● CURRENT

Customer Approval
○

Repair
○

Device Returned
○

Final QC
○

Ready for Delivery
○

Delivered
○

Completed states:
✓

Current state:
●

Future states:
○

The tracker must dynamically change depending on the selected repair route.

Do not show irrelevant steps.

For example, an in-house repair should not display "Service Center Dispatch".

A warranty repair should not display "Third-Party Vendor".

---

# 5. DISPLAY PHYSICAL DEVICE LOCATION

This is extremely important.

Every active device must have a clear physical location.

Support locations such as:

IN SHOP

AUTHORIZED SERVICE CENTER

THIRD-PARTY TECHNICIAN

WITH CUSTOMER

IN TRANSIT

DELIVERED

If external, also show the actual party.

Example:

Current Location:
AUTHORIZED SERVICE CENTER

Location Name:
Samsung Authorized Service Center Pune

or

Current Location:
THIRD-PARTY TECHNICIAN

Technician:
Rakesh Mobile Repair

The location must automatically update when lifecycle transitions occur.

Example:

Send to service center
→ location becomes AUTHORIZED SERVICE CENTER.

Receive back from service center
→ location becomes IN SHOP.

Send to third party
→ location becomes THIRD-PARTY TECHNICIAN.

Receive from third party
→ location becomes IN SHOP.

Deliver to customer
→ location becomes WITH CUSTOMER / DELIVERED.

---

# 6. ROUTE SELECTION AFTER INITIAL INSPECTION

After Initial Inspection, present a dedicated decision screen.

Show:

Warranty Status

Options:

Under Warranty

Out of Warranty

Unknown / Requires Verification

If warranty is valid:

Primary action:

SEND TO AUTHORIZED SERVICE CENTER

If out of warranty:

Ask:

HOW WILL THIS DEVICE BE REPAIRED?

Provide large UI cards/buttons:

[ REPAIR IN OUR SHOP ]

[ SEND TO THIRD-PARTY TECHNICIAN ]

The route selection should be visually very clear.

Require confirmation before changing the route.

---

# 7. SERVICE CENTER UI

When Authorized Service Center is selected, show a dedicated panel containing:

Service Center Name

Address

Contact Person

Phone

Dispatch Date

Expected Return Date

Service Center Job Number

Warranty Claim Number

Courier / Transport information if applicable

Device condition during dispatch

Accessories sent

Dispatch notes

Current status

Possible actions:

Create Dispatch

Mark Device Sent

Update Service Center Reference

Record Diagnosis

Record Service Center Estimate

Record Customer Approval

Record Repair Completed

Record Replacement

Mark Not Repairable

Receive Device Back

When "Receive Device Back" is completed:

Location automatically changes to IN SHOP.

Next action automatically becomes FINAL QC.

---

# 8. IN-HOUSE REPAIR UI

When In-House Repair is selected, show:

Assigned Technician

Diagnosis

Reported Fault

Confirmed Fault

Required Parts

Parts Availability

Estimated Parts Cost

Estimated Labour Cost

Customer Estimate

Approval Status

Advance Payment

Repair Start Date

Technician Notes

Parts Used

Repair Completion Date

Test Result

Possible actions:

Assign Technician

Start Diagnosis

Create Estimate

Send Estimate

Record Customer Approval

Order Parts

Mark Parts Received

Start Repair

Record Parts Used

Complete Repair

Start Testing

Mark Test Passed

Mark Test Failed

Send to Final QC

---

# 9. THIRD-PARTY TECHNICIAN UI

When Third-Party Repair is selected, show:

Vendor / Technician Name

Company

Phone

Specialization

Dispatch Date

Expected Return

Device Condition

Accessories Sent

Vendor Diagnosis

Vendor Estimate

Parts Cost

Labour Cost

Transport Cost

Other Cost

Customer Price

Shop Margin

Customer Approval

Vendor Repair Status

Vendor Payment Status

Possible actions:

Select Vendor

Create Dispatch

Mark Device Sent

Record Vendor Diagnosis

Record Vendor Estimate

Prepare Customer Quote

Record Customer Approval

Authorize Repair

Record Vendor Repair Complete

Receive Device Back

Record Vendor Invoice

Record Vendor Payment

Send to Final QC

---

# 10. FINAL QC SCREEN

All successful repair routes must eventually reach a common Final QC stage.

Final QC screen must show:

Original Customer Complaint

Diagnosis

Repair Performed

Parts Replaced

Repair Route

Who Performed Repair

Device Photos Before Repair

Optional Device Photos After Repair

QC Checklist

Functional Test

Power Test

Charging Test if relevant

Display Test if relevant

Connectivity Test if relevant

Customer Complaint Verification

Technician Notes

QC Result

Buttons:

PASS QC

FAIL QC

If QC fails, route back to the appropriate repair path.

If QC passes:

Capture final device photo if required.

Record repair warranty.

Proceed to billing.

---

# 11. READY FOR DELIVERY SCREEN

Once QC and billing requirements are satisfied, status becomes:

READY FOR DELIVERY

Show prominently:

Customer Name

Phone

Device

Job ID

Repair Performed

Final Amount

Advance Paid

Balance Due

Repair Warranty

Completion Date

Buttons:

Notify Customer

Print Invoice

Record Payment

Start Device Handover

---

# 12. DEVICE HANDOVER FLOW

When customer collects the device:

Open a dedicated handover screen.

Show:

Customer

Customer photo if available

Device

Device photos

Job number

Accessories received originally

Accessories being returned

Repair summary

Repair warranty

Invoice total

Amount paid

Balance

Require operator to confirm:

Device demonstrated to customer

Customer accepted device

Accessories returned

Payment completed or approved as credit where existing application supports it

Record:

Delivery date/time

Delivered by

Received by

Final notes

Then allow:

COMPLETE HANDOVER

After completion:

Status = DELIVERED

Location = WITH CUSTOMER

Then finalize:

Status = CLOSED

---

# 13. REPAIR HISTORY TIMELINE

Each job must have a complete chronological timeline.

Example:

12 Sep 09:30
Device Received
By: Counter Staff

12 Sep 09:45
Initial Inspection Completed
By: Amit

12 Sep 10:00
Device Marked Out of Warranty

12 Sep 10:05
Third-Party Repair Selected

12 Sep 11:30
Device Sent to ABC Laptop Service

13 Sep 14:00
Vendor Diagnosis Received

13 Sep 14:15
Estimate ₹4,500

13 Sep 15:20
Customer Approved Estimate

14 Sep 17:10
Vendor Repair Completed

15 Sep 10:00
Device Received Back at Shop

15 Sep 10:30
Final QC Passed

15 Sep 11:00
Customer Notified

15 Sep 18:00
Device Delivered

Do not allow lifecycle history records to silently disappear.

Keep audit history for important transitions.

---

# 14. DASHBOARD REDESIGN

Modify the existing dashboard so staff can quickly see where every active device is.

Create summary cards such as:

RECEIVED
12

UNDER DIAGNOSIS
5

AT SERVICE CENTER
8

WITH THIRD PARTY
6

WAITING FOR CUSTOMER APPROVAL
4

WAITING FOR PARTS
3

REPAIR IN PROGRESS
9

FINAL QC
2

READY FOR DELIVERY
7

OVERDUE
4

Clicking a card should filter the repair/job list.

---

# 15. ACTIVE REPAIR TABLE

Create or improve the active repair/job table.

Recommended columns:

Job ID

Customer

Device

Brand / Model

Repair Route

Current Status

Current Location

Assigned To

Pending Since

Expected Date

Balance

Next Action

Use clear text badges.

Examples:

Repair Route:
IN-HOUSE
WARRANTY
THIRD PARTY

Location:
IN SHOP
SERVICE CENTER
THIRD PARTY

Status:
WAITING FOR PARTS
REPAIR IN PROGRESS
WAITING FOR APPROVAL
READY FOR DELIVERY

---

# 16. OVERDUE / ATTENTION SYSTEM

Add visual identification for repairs requiring attention.

Examples:

Service center expected return date exceeded.

Vendor expected return date exceeded.

Customer approval pending too long.

Parts pending too long.

Device repaired but customer has not collected it.

QC pending.

Payment pending.

Do not hide these situations.

Provide an "Attention Required" dashboard section.

---

# 17. NEXT ACTION ENGINE

Each job must expose one clear **NEXT ACTION**.

Examples:

Perform Initial Inspection

Verify Warranty

Select Service Center

Dispatch Device

Wait for Service Center Diagnosis

Contact Customer for Approval

Order Parts

Wait for Parts

Start Repair

Receive Device From Vendor

Perform Final QC

Notify Customer

Collect Payment

Hand Over Device

Close Job

The operator should never need to guess what to do next.

Where practical, provide one prominent primary action button corresponding to the next action.

Example:

NEXT ACTION:
Receive Device From Third-Party Technician

[ RECEIVE DEVICE ]

---

# 18. STATE TRANSITION RULES

Do not allow arbitrary state changes from a simple free-text dropdown.

Lifecycle transitions must follow valid business rules.

Examples:

RECEIVED
→ INITIAL INSPECTION

INITIAL INSPECTION
→ WARRANTY CHECK

WARRANTY CHECK
→ SERVICE CENTER

or

WARRANTY CHECK
→ IN-HOUSE

or

WARRANTY CHECK
→ THIRD PARTY

SERVICE CENTER
→ RECEIVED BACK
→ FINAL QC

THIRD PARTY
→ RECEIVED BACK
→ FINAL QC

IN-HOUSE
→ FINAL QC

FINAL QC
→ READY FOR DELIVERY

READY FOR DELIVERY
→ DELIVERED

DELIVERED
→ CLOSED

Handle exceptional states such as:

Customer Declined Repair

Not Repairable

Repair Failed

Warranty Rejected

Waiting for Customer

Waiting for Parts

Cancelled

without corrupting the normal lifecycle.

---

# 19. PRESERVE EXISTING DATA

This is critical.

Inspect the existing database models and migrations before making changes.

Do NOT delete or recreate the production database.

Existing customers, jobs, photos, quotations, financial records, device histories and attachments must remain accessible.

If new fields or tables are required, create a proper versioned database migration.

Possible new information may include:

repair_route

current_location

location_name

current_status

pending_since

next_action

assigned_technician_id

vendor_id

service_center_id

dispatch_date

expected_return_date

returned_date

external_reference

repair_warranty_until

But first inspect whether equivalent fields already exist.

Reuse existing models and fields wherever possible.

Do not create duplicate concepts.

---

# 20. LEGACY STATUS MAPPING

Inspect existing job statuses.

If the existing application already contains statuses, create a safe mapping from the old status model to the new lifecycle.

Do not blindly replace the old values.

For example:

Existing "Open"
may map to RECEIVED or INITIAL_INSPECTION depending on available history.

Existing "In Progress"
may remain compatible but should be translated to a more precise lifecycle state where possible.

Existing "Completed"
may map to READY_FOR_DELIVERY or DELIVERED depending on billing/delivery data.

Be conservative with legacy data.

If exact conversion cannot safely be determined, preserve the old record and display an appropriate legacy status rather than making assumptions.

---

# 21. CUSTOMER OVERVIEW

Update the existing consolidated customer overview.

For each customer's device show:

Device

Device ID

Current Job

Repair Route

Current Status

Current Location

Last Update

Next Action

Previous Repairs

Example:

Rahul Sharma

Dell Inspiron 15
Device: DEV-0012
Job: JOB-00128
Route: Third Party
Status: With Third-Party Technician
Location: ABC Laptop Service
Next Action: Wait for Vendor Diagnosis

Samsung S24
Device: DEV-0041
Job: JOB-00131
Route: Warranty
Status: At Authorized Service Center
Location: Samsung Service Center Pune
Next Action: Wait for Service Center Update

HP Printer
Device: DEV-0020
Last Repair: Completed
Status: Closed

---

# 22. UI DESIGN

Keep the UI professional, simple and suitable for a repair shop counter.

Do not create an over-complicated enterprise UI.

Prioritize:

Large readable status indicators

Clear navigation

Clear primary action

Minimal clicks

Readable tables

Consistent spacing

Consistent PyQt6 widgets

Tooltips where useful

Keyboard-friendly operation

Good behavior on normal Windows desktop resolutions

Do not use color alone to represent information.

Use:

Icon + Text + Badge

where practical.

---

# 23. NAVIGATION

Suggested main navigation:

Dashboard

New Repair Intake

Active Repairs

Customers

Devices

Service Centers

Third-Party Technicians

Quotations

Billing / Payments

Ready for Delivery

Repair History

Reports

Settings

Reuse current screens where possible rather than creating unnecessary duplicate screens.

---

# 24. EXTERNAL PARTY MASTER DATA

If equivalent functionality does not already exist, create reusable master-data management for:

AUTHORIZED SERVICE CENTERS

and

THIRD-PARTY TECHNICIANS / VENDORS

Authorized Service Center fields may include:

Name

Brand / OEM

Address

Phone

Contact Person

Email

Notes

Active / Inactive

Third-Party technician fields may include:

Name

Company

Phone

Address

Specialization

Notes

Active / Inactive

Do not duplicate the same vendor every time a job is created.

---

# 25. DEVICE CUSTODY

Every time the physical device changes hands, create or reuse the existing custody tracking functionality.

Examples:

Customer → Shop

Shop → Service Center

Service Center → Shop

Shop → Third-Party Technician

Third-Party Technician → Shop

Shop → Customer

Record:

Date/time

From

To

Handled by

Device condition

Accessories

Notes

This should be visible in the repair timeline.

---

# 26. USER EXPERIENCE EXAMPLE

When an employee opens a job, the most prominent portion of the screen should look conceptually like:

JOB-2026-00128
Dell Inspiron 15

ROUTE
THIRD PARTY

STATUS
WITH THIRD-PARTY TECHNICIAN

LOCATION
ABC Laptop Service

PENDING SINCE
12 Sep 2026, 11:30 AM

EXPECTED RETURN
14 Sep 2026

NEXT ACTION
Wait for Vendor Repair

Then show:

[Repair Lifecycle]

Received ✓
Inspected ✓
Third Party Selected ✓
Dispatched ✓
Vendor Diagnosis ✓
Customer Approval ✓
Repair In Progress ●
Returned ○
Final QC ○
Ready for Delivery ○
Delivered ○

The rest of the detailed information can appear below this.

---

# 27. DATABASE AND BUSINESS LOGIC SEPARATION

Do not place all lifecycle logic directly inside UI widgets.

Keep responsibilities separated.

Use existing architecture where possible.

The preferred pattern should be:

UI
→ Repair Lifecycle Service
→ Existing repositories / SQLAlchemy models
→ SQLite

Create a lifecycle/business service if an equivalent service does not already exist.

The service should determine:

Allowed transitions

Next action

Current location

Route

Required information before transition

Timeline event creation

This will prevent different screens from implementing different status rules.

---

# 28. VALIDATION

Before allowing lifecycle transitions, validate required information.

Examples:

Cannot send to Service Center without selecting a Service Center.

Cannot send to Third Party without selecting a Vendor.

Cannot mark device returned unless it was previously dispatched.

Cannot start in-house repair without diagnosis.

Cannot start paid repair without required customer approval.

Cannot mark QC passed without recording QC result.

Cannot mark Ready for Delivery unless QC requirements are satisfied.

Cannot close job before device handover.

Show clear user-friendly validation messages.

---

# 29. TESTS

Update existing automated tests and create new tests covering at least:

Warranty → Service Center happy path.

Warranty rejected → switch to non-warranty route.

In-house repair happy path.

In-house waiting for parts.

In-house repair unsuccessful.

Third-party repair happy path.

Third-party repair unsuccessful.

Customer declines estimate.

Device returned without repair.

QC pass.

QC failure and rework.

Ready for delivery.

Payment pending.

Device delivered.

Job closed.

Physical-location transitions.

Invalid transition blocking.

Legacy job compatibility.

Existing customer/device/photo functionality continues working.

Existing quotations and financial records remain working.

---

# 30. IMPLEMENTATION APPROACH

Do the work in this order:

1. Inspect the full repository.

2. Identify the existing:

   * database models
   * job statuses
   * customer screens
   * device screens
   * repair screens
   * quotations
   * billing
   * custody logic
   * photo logic
   * dashboard
   * customer overview
   * migrations
   * tests.

3. Document internally how the current workflow works.

4. Determine which existing functionality can be reused.

5. Create the lifecycle/state model.

6. Add safe migrations only if necessary.

7. Implement lifecycle/business service.

8. Redesign the job detail UI.

9. Implement Repair Lifecycle Tracker.

10. Implement Current Location and Next Action.

11. Implement Service Center route UI.

12. Implement In-House route UI.

13. Implement Third-Party route UI.

14. Update Final QC.

15. Update Ready for Delivery / Handover.

16. Update dashboard.

17. Update customer repair overview.

18. Add attention/overdue indicators.

19. Update tests.

20. Run the complete existing test suite.

---

# 31. IMPORTANT CONSTRAINTS

Do NOT rebuild the application from scratch.

Do NOT remove working functionality.

Do NOT remove existing customer photos.

Do NOT remove device photos.

Do NOT change stable physical device IDs unnecessarily.

Do NOT lose existing repair history.

Do NOT lose quotation information.

Do NOT lose payments or financial history.

Do NOT recreate existing customers or devices.

Do NOT bypass existing schema migration architecture.

Do NOT create another parallel repair system beside the existing one.

Integrate this lifecycle into the current application.

Reuse existing classes, services, repositories and screens whenever reasonable.

Do not unnecessarily change unrelated code.

---

# 32. DEFINITION OF DONE

This change is complete only when a normal shop employee can open the application and, without needing technical knowledge, immediately understand:

1. What device came for repair?

2. Who owns it?

3. What is wrong with it?

4. Is it under warranty?

5. Which repair route is being used?

6. Where is the physical device right now?

7. Who currently has responsibility for it?

8. What has already happened?

9. What is currently pending?

10. What must the employee do next?

11. Is customer approval pending?

12. Are parts pending?

13. Has repair completed?

14. Has final QC passed?

15. Is payment pending?

16. Is the device ready for collection?

17. Has the customer collected it?

18. Is the repair job completely closed?

The primary goal of this change is **clarity of repair state and physical device location**.

Do not simply add more forms or more status fields.

Redesign the user experience around the lifecycle so that the application's workflow becomes visually self-explanatory.

After implementation, provide:

1. Summary of existing architecture discovered.
2. Files changed.
3. Database migration changes, if any.
4. New lifecycle/status model.
5. Old-to-new status mapping.
6. Screens modified.
7. New screens added.
8. Tests added or modified.
9. Test results.
10. Any assumptions made.
11. Any existing functionality intentionally left unchanged.
