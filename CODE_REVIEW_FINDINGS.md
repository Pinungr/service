# PROFESSIONAL CODE REVIEW - COMPREHENSIVE ANALYSIS

## CRITICAL ISSUES (Blocking Merge)

### 1. AUTHORIZATION GUARD BROKEN FOR DIRECTORY TECHNICIANS
**File:** `repairshop/services.py:367-370`  
**Severity:** 🔴 CRITICAL - Security/Access Control  

The `_job()` authorization guard that restricts technician-role users to their assigned work only checks `technician_id`:

```python
if self.user["role"] == "technician":
    assignment = c.execute("SELECT technician_id FROM assignments WHERE id=?", (j["assignment_id"],)).fetchone()
    if not assignment or assignment[0] != self.user["id"]:
        raise RuleError("Technicians can update only their assigned work.")
```

**The Problem:**
- When a job is assigned to a directory technician: `technician_id = NULL`, `technician_master_id = <id>`
- When technician-role user tries to access it: `assignment[0]` (technician_id) is NULL
- `NULL != self.user["id"]` is always TRUE
- **Result:** Technician-role users are permanently locked out of ANY directory-assigned job

**Impact:** Confirmed in e2e tests - technician-role login cannot even call `JobCards.rows()` on a directory-assigned job

**Fix Required:**
```python
if self.user["role"] == "technician":
    assignment = c.execute("SELECT technician_id, technician_master_id FROM assignments WHERE id=?", (j["assignment_id"],)).fetchone()
    if not assignment or (assignment[0] != self.user["id"] and assignment[1] is not None):
        raise RuleError("Technicians can update only their assigned work.")
    # OR: explicitly exclude directory-assigned jobs and allow them to pass
```

---

### 2. JOB NOTIFICATIONS BROKEN FOR DIRECTORY TECHNICIANS
**File:** `repairshop/services.py:214`  
**Severity:** 🔴 CRITICAL - Functional  

Notifications to assigned technicians are queried via:

```python
internal = c.execute("""SELECT r.* FROM recipients r JOIN users u ON u.id=r.entity_id 
    WHERE r.kind='staff' AND r.active=1 AND u.active=1 
    AND (u.role='owner' OR u.id=(SELECT technician_id FROM assignments WHERE id=?))""", (j['assignment_id'],))
```

**The Problem:**
- Subquery `(SELECT technician_id FROM assignments...)` returns NULL for directory assignments
- `NULL != any_user_id` always fails
- Directory technicians never appear in `internal` recipients list
- **Result:** Job status updates, quotes, and other events are never sent to directory technicians

**Impact:** Silent functional failure - no audit trail, no error, just silent non-delivery

**Fix Required:**
```python
# Option A: Check both columns
AND (u.role='owner' OR u.id=(SELECT technician_id FROM assignments WHERE id=?) 
     OR (SELECT technician_master_id FROM assignments WHERE id=?) IS NOT NULL)

# Option B: Join masters table separately
UNION ALL (SELECT r.* FROM recipients WHERE kind='staff' AND entity_id IN 
    (SELECT technician_master_id FROM assignments WHERE job_id=j.id AND technician_master_id IS NOT NULL))
```

---

### 3. INCOMPLETE BACKWARD COMPATIBILITY STORY
**Files:** `services.py`, `lifecycle.py`, `inventory.py`, `custody.py`  
**Severity:** 🔴 CRITICAL - Data Integrity  

The dual-mode technician assignment (legacy `technician_id` + new `technician_master_id`) creates several problems:

- **No migration path:** Existing `technician_id` values are not converted to directory records
- **No clear policy:** UI accepts both, but when should each be used?
- **Ambiguous queries:** Many queries use COALESCE(technician_master, technician_id) but authorization doesn't
- **Mixed-mode risk:** A single database could have some jobs using legacy, others using directory
- **Deprecation unclear:** Is technician-role user account support permanent or deprecated?

**Impact:** 
- Operational confusion about assignment methods
- Long-term technical debt (two parallel systems)
- Harder to eventually deprecate login-based technicians
- Missing audit trail for how jobs are assigned

**Fix Required:**
- Document explicit policy: "technician_master_id is new standard; technician_id is legacy-only"
- Add schema detection for mixed-mode databases and warn operators
- Create operator guide for migrating legacy technician_ids to directory
- Add UI deprecation notice when legacy assignments are created

---

## MAJOR ISSUES (Should Fix)

### 4. FRESH INSTALL UX DEAD-END
**File:** `repairshop/lifecycle_ui.py:289`  
**Severity:** 🟠 HIGH - UX/Usability  

On a fresh install, attempting to assign in-house work fails:

```python
# lifecycle_ui.py:289
f.select('technician_master_id','Assigned technician',
         [(r['name'],r['id']) for r in self.window.db.rows("SELECT id,name FROM masters WHERE kind='technician' AND active=1 ORDER BY name")])
```

- `masters` table starts empty (no technician entries)
- Dropdown shows zero options
- No "Unassigned" fallback (unlike `ui.py:900`)
- Form submission fails with confusing error

**User Journey:**
1. Shop owner creates first repair job
2. Tries to assign to in-house (themselves)
3. Technician dropdown is empty
4. Cannot complete - must first add yourself to Directories > technician
5. Unintuitive for new users

**Impact:** First-time in-house repair cannot complete without extra setup discovery

**Fix Required:**
```python
# Add fallback option
opts = [(r['name'],r['id']) for r in self.window.db.rows("SELECT id,name FROM masters WHERE kind='technician' AND active=1 ORDER BY name")]
if not opts:
    opts = [("Unassigned", None)]
f.select('technician_master_id','Assigned technician', opts)
```

---

### 5. `save_master` RE-ADD SILENTLY RENAMES
**File:** `repairshop/services.py:130-145`  
**Severity:** 🟡 MEDIUM - Data Quality  

When a normalized directory entry already exists, re-adding with different casing updates it:

```python
# First call
s.save_master("technician", "Amit Kumar", contact="111")  # Stored as "Amit Kumar"

# Later call with different casing
s.save_master("technician", "amit kumar", contact="222")  # Becomes "amit kumar" everywhere
```

**The Problem:**
- Line 135 in services.py unconditionally updates `name=?`
- Silently changes display name retroactively in all job cards, snapshots, audit logs
- No warning to operator
- No audit trail of name change itself

**Confirmed in e2e test:** "re-add preserves the original display name casing" = **FAIL**

**Impact:** 
- Confusing to operators (why did technician name change?)
- Retroactive name changes in historical records
- Inconsistent display in snapshots vs audit logs

**Fix Required:**
```python
# Only update optional fields on re-add, keep original name
if existing and not ident:
    ident = existing["id"]
    merged_contact = contact if contact.strip() else existing["contact"]
    merged_details = details if details.strip() else existing["details"]
    # NOTE: Do NOT update name - keep original
    c.execute("UPDATE masters SET contact=?, details=?, active=? WHERE id=?",
              (merged_contact, merged_details, int(active), ident))
```

---

### 6. SQL PARAMETERIZATION EDGE CASE
**File:** `repairshop/services.py:227`  
**Severity:** 🟢 LOW - Code Quality  

```python
table = 'users' if kind=='staff' else 'masters'
c.execute(f'SELECT id FROM {table} WHERE id=?',(entity_id,))
```

While risk is LOW (table name is constrained), this violates secure-by-default principles.

**Fix:** Use explicit conditional:
```python
if kind == 'staff':
    c.execute("SELECT id FROM users WHERE id=?", (entity_id,))
else:
    c.execute("SELECT id FROM masters WHERE id=?", (entity_id,))
```

---

## ARCHITECTURAL OBSERVATIONS

### 7. TECHNICIAN ROLE DEPRECATION UNDEFINED
The `technician` role in users table is now mostly obsolete for new systems, but:
- Role-based UI restrictions still active (see `lifecycle.py:433`, `ui.py:78`, `ui.py:850`)
- Login workflows still support it
- Test fixtures still create it
- No deprecation timeline defined

**Recommendation:** Either (a) document as permanent legacy support with clear warnings, or (b) plan deprecation with operator migration guide

### 8. MASTERS-USERS ARCHITECTURAL DISCONNECT
Directory technicians (masters table) have no link to user accounts. This creates:
- ✓ Benefit: Allows technicians without login accounts
- ✗ Cost: Authorization patterns don't work (findings #1, #2)
- ✗ Cost: Dual-mode assignment logic throughout codebase

**Design Gap:** The `_job()` guard was built assuming all technicians have user accounts. Directory technicians break that assumption.

**Recommendation:** Document this architectural choice. Consider adding optional `masters.user_id` field for systems that want to link technicians to login accounts.

---

## CODE QUALITY ASSESSMENTS

### ✅ STRENGTHS

**SQL Query Improvements (Finding: SOUND)**
- Filter expressions correctly parameterized
- LIMIT/OFFSET push-down eliminates N+1 behavior (confirmed: 5-row page now snapshots exactly 5 jobs)
- All search terms use LIKE with bound parameters
- Filter conditions selected via pre-defined SQL, not string interpolation

**Attachment Security (Finding: WELL-IMPLEMENTED)**
- Extension allowlist (PDF, JPG, JPEG, PNG only)
- Magic byte verification prevents spoofing
- File size limit (50 MB)
- Atomic transaction (file + DB insert together)
- Rollback on error (unlink partial file)

**Migration Safety (Finding: IDEMPOTENT)**
- Column existence checked before ALTER
- Index existence checked before CREATE
- All operations in transaction
- Backup written by framework before upgrade
- Audit entry recorded

### ⚠️  GAPS

**Test Coverage**
- ✗ No test of technician-role access to directory-assigned jobs (would fail)
- ✗ No test of notifications to directory technicians
- ✗ No test of mixed-mode assignments (legacy + directory)
- ✗ No test of fresh install in-house assignment
- ✗ `test_in_house_technician_is_directory_record_not_login` verifies storage but not authorization

---

## SUMMARY MATRIX

| Issue | Severity | Category | Status | Fix Time |
|-------|----------|----------|--------|----------|
| #1 Authorization guard broken | CRITICAL | Security | VERIFIED | 1-2 hrs |
| #2 Notifications broken | CRITICAL | Functional | VERIFIED | 1 hr |
| #3 Incomplete backward-compat | CRITICAL | Data Integrity | VERIFIED | 2-3 hrs |
| #4 Fresh install UX dead-end | HIGH | UX | VERIFIED | 30 mins |
| #5 Re-add renames silently | MEDIUM | Data Quality | VERIFIED | 30 mins |
| #6 SQL parameterization edge | LOW | Code Quality | VERIFIED | 15 mins |

---

## RECOMMENDATION

**🔴 DO NOT MERGE** in current state.

**Critical blockers:**
1. **Issue #1** breaks technician-role user access (security/usability)
2. **Issue #2** breaks job notifications (silent functional failure)
3. **Issue #3** creates data integrity risk (no migration path, unclear policy)

These three issues together mean the feature is not production-ready. A technician-role user cannot:
- Access their assigned work
- Receive job notifications
- Have a clear data model

**Minimum Required Fixes:**
1. Authorize both technician_id and technician_master_id in `_job()` guard
2. Fix notification query to check technician_master_id
3. Document and enforce backward-compatibility policy
4. Add fallback technician option for fresh installs
5. Fix name clobbering in re-add scenario
6. Add integration tests for technician-role + directory technician scenarios

**Estimated Fix Time:** 4-5 hours including testing

**Then:** Full re-test of e2e scenario, new tests for above gaps, then code review sign-off.

---

## CHECKLIST FOR FIXES

- [ ] Fix authorization guard (#1)
- [ ] Fix notification query (#2)
- [ ] Document backward-compat policy and add schema detection (#3)
- [ ] Add "Unassigned" fallback to route dialog (#4)
- [ ] Exclude name from re-add update logic (#5)
- [ ] Use explicit SQL instead of f-string for table name (#6)
- [ ] Add test: technician-role + directory assignment
- [ ] Add test: notifications to directory technician
- [ ] Add test: mixed-mode assignments
- [ ] Add test: fresh install in-house route
- [ ] Full e2e regression test
- [ ] Update demo seeder if needed
- [ ] Update operator documentation

