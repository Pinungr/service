# Photos, physical devices and customer overview — version 1.1

The Windows ZIP contains only `RepairShopManager.exe`. The source and these maintenance guides stay in the developer workspace. Shop data is stored separately and remains offline.

## Customer intake

1. Add a customer if needed, or find the existing record. Start **New repair intake**.
2. Select the **Device owner**. A returning owner's saved photo appears with its capture date.
3. Under **Physical product**, choose **New physical device** for a different unit, even if its model matches another product. Select an existing device ID for a later repair of that same unit. A device with outstanding items cannot receive a second active intake.
4. Choose **Device owner** or **Submitting person** under **Person to photograph**. For someone submitting on the owner's behalf, enter **Submitted by** and the relationship, then explicitly choose **Submitting person** before capture. The photo is labelled with that person's name; it never replaces the owner's current photo.
5. Choose **Capture customer photo**. Select the camera, review the live preview, choose **Capture**, then **Save photo**. Use **Retake** to discard the unsaved capture and try again. Previously saved photos and capture dates remain in the customer history.
6. Enter the device, fault, condition, checked accessories and quantities, shop storage, tentative dates and agreed terms. Finalize with **Save**. A saved owner or correctly labelled submitter photo is required for every new intake. An existing valid owner photo may be reused.

For several devices received together, create one job per physical product with the same **Shared visit reference**. Each receives a distinct device ID unless you deliberately select an existing physical product. A follow-up repair creates a new job under the existing device's repair folder.

If no webcam is found, the app displays: “Please connect a webcam to capture the customer’s photo.” Connect it and choose **Retry**; no restart is needed. If access is denied or the device is busy, allow camera access in Windows settings, close other camera applications and Retry. The camera is released when capture closes or a still image is ready for review.

**Cancel** returns to the intake without losing its fields. Intake is saved as a local draft before opening the camera, on field changes after a short delay, with **Save draft**, and when cancelling intake. Resume your drafts from **Jobs → Intake drafts** after restarting. Photo/file-save errors retain the captured image for retry and never falsely complete intake. If draft storage itself fails, cancellation keeps the intake window open and explains the failure.

## Product photographs and the overview

Search in **Customers**, then double-click a result or choose **Customer overview**. It shows the owner photo, stable customer ID, contact details, outstanding and historical repair tables, all physical devices, photo history, sold products, quotations, payments and communications. Double-click a repair to open its existing full details and the **Product photos** and **Intake person** tabs.

Use **Product photos → Capture product photo** for webcam capture or **Attach local product photo** for an existing JPEG, PNG, BMP or WebP image. The image is decoded and stored as a new local JPEG; the original selected file is untouched. Double-clicking a device in **All physical devices** opens its photographs, editable brand/model/serial information and a new-repair action.

The outstanding table includes product thumbnail, stable device ID, job number/intake date, repair stage, actual holders, assigned party, tentative collection date, customer balance and collection status. A partial handover remains outstanding while any required accessory or device is still held.

Counts reflect unique physical device IDs. A collected historical job does not count as a second currently received device. Location and work-progress counts overlap and must not be added. External completion alone is not pickup readiness. All remaining items must be in shop custody, without a job hold; a repaired job must have a passed shop test, and an unrepaired return needs its recorded outcome/check. Unrepaired returns are displayed distinctly. Money owed does not change physical collection counts.

## Permanent local folders

Default location: `%LOCALAPPDATA%\RepairShopManager\Customers`. With `--data-dir`, `Customers` lives under that configured data directory.

```text
Customers/
  Customer_Name_CUST-000123/
    customer-details.txt
    Customer-Photos/<unique-photo-id>.jpg
    Laptop_DEV-000456/
      product-details.txt
      Product-Photos/<unique-photo-id>.jpg
      Purchase-Documents/<unique-document-id>.pdf
      Repairs/
        REP-2026-000789/
          job-details.txt
          Documents/<unique-document-id>.pdf
```

Use **Open customer folder / Retry folders** in the overview. Correcting a customer or device name updates its summary but keeps its stored folder path. Identical names have different stable IDs and folders. Paths in the database remain relative to the data directory.

The database is authoritative. Readable summaries are generated in background batches after changes and can be rebuilt on demand. They label tentative dates and format money in INR. New job documents use the relevant repair folder; existing `managed` attachment references are preserved. Summary files list links to those older documents rather than moving or deleting them.

Do not edit generated summaries as a substitute for changing records in the app. If a summary was edited outside the app, generation stops for that customer without overwriting it. Move the edited file aside, then use **Retry folders**. Missing photo entries remain in history. **Recover missing photo** in product photos, or **Recover selected customer photo** in the customer photo-history tab, accepts the exact original from an extracted backup and checks its saved checksum. Otherwise capture a new photo; old evidence is retained. Missing legacy documents can be recovered from a verified full backup.

## Existing data, backups and restoration

Schema migration 5 adds stable devices, photo metadata, drafts and projection tracking. Before any populated older database is migrated, the same verified archive writer used for normal backups creates a `backups/repairshop-pre-upgrade-vN-...zip` containing the database and linked files. Migration does not proceed if backup fails.

Legacy customers and jobs remain accessible with photo placeholders. No photo is required to open or update old work. Existing sale links and explicit parent-repair links determine shared device identities. Unlinked old jobs are conservatively treated as separate physical devices; matching names alone never merges records. Folder generation is queued, resumable and safe to repeat. Migration does not enqueue customer notifications.

Backups include customer/product photos, readable summaries, customer/device/job directories (including empty photo folders), drafts, linked documents and the database. Restore into a different data directory preserves relative links. A pre-restore archive and previous state are retained, and restored outgoing messages are paused for review. A missing referenced file stops backup with an error rather than producing a falsely complete archive.

## Verification and hardware limits

Automated tests use fake cameras for missing devices, selection/hot-plug retry, denied/busy/disconnected/capture failures, capture/retake/save, cancellation and storage errors. Real SQLite tests cover required photos, owner/submitter separation, drafts surviving restart, duplicate customer names, separate same-category devices, repeat repairs, custody and readiness, partial collections, money independence, safe paths, summary conflicts, migration safety, photo recovery and backup/restore relocation. The existing accounting, warranty, quotation, notification and UI acceptance tests remain in the suite.

Real webcam preview/image quality, camera drivers, Windows permission prompts and unplugging during physical capture still require manual checks on the shop's hardware. Automated camera simulations do not establish that a particular webcam works. Packaged launch/restart is tested on the development Windows host; a separate clean Windows machine remains an additional deployment check.
