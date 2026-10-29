# Dashboard default-context repair plan

## Status and approval boundary

Prepared on 30 October 2026. **No production repair has been executed.**
Production access during this investigation was read-only. Compare-only
validation of the source patch does not authorise a production deployment or
repair.

This plan is prepared for operator review, not approved for execution. Obtain
explicit approval for the final candidate list, maintenance window, deployment
and production inserts before proceeding.

## Verified findings

The reported `/ang/dashboard` traceback reaches
`Patient.default_context()` while resolving a missing fixed form-group context.
That method raises `Exception("no default context")` when the patient has no
active context attached to a group marked as the default.

Production database `angelman2`, registry `ang`, currently has:

| Patient status | Patients | Missing active default context |
| --- | ---: | ---: |
| Active | 3,039 | 1,089 |
| Inactive | 1,637 | 1,633 |

All of these patients have other active contexts. For active patients:

| Fixed group | Default | Missing active contexts | Patients with duplicate active contexts |
| --- | --- | ---: | ---: |
| PatientHistoryCFG | Yes | 1,089 | 0 |
| Admin | No | 657 | 0 |
| Archive | No | 0 | 0 |
| History | No | 0 | 0 |
| Treatment | No | 0 | 0 |

The earliest existing `PatientHistoryCFG` and `Admin` contexts were created on
22 June 2026. This is consistent with incomplete initialisation following a
definition change, but does not establish when the definition changed or why
these patients were omitted. The two notification emails do not identify
whether one or two people encountered the error. These counts describe the
structural exposure, not the number of failed requests or affected logins.

## Local code fix

Changes are in the shared RDRF repository:

- [Dashboard context selection](../rdrf/rdrf/rdrf/views/dashboard_view.py):
  when a requested fixed group has no context and the registry supports
  contexts, initialise its missing fixed contexts using the existing context
  manager, log the recovery and refresh the dashboard's context map.
- The form link and progress lookup both use the resolved context for that
  particular group, rather than borrowing a different group's default context.
- Registries without the contexts feature retain their existing fallback.
  Multiple/repeating groups are not created by this recovery path.
- [Context manager](../rdrf/rdrf/rdrf/db/contexts_api.py):
  duplicate fixed contexts are logged and preserved, rather than deleted.
  The manager still selects the lowest primary key when duplicates exist;
  the dashboard's existing latest-context selection is unchanged.
- [Regression tests](../rdrf/rdrf/rdrf/testing/unit/dashboard_tests.py):
  cover the original exception, correct group-specific links and progress,
  repeat-call idempotence, preservation of existing contexts and clinical data,
  and missing fixed groups when a different default context already exists.

**Deployment behaviour:** after deployment, accessing a dashboard form link or
progress item for a missing fixed group can create the patient's missing fixed
contexts. It does not merely suppress the exception. Deploying the patch must
therefore be included in the production-write approval and maintenance plan.
The patch does not migrate historical clinical answers.

### Local validation

- The regression tests first reproduced the exact `no default context`
  exception and the old manager's deletion of a duplicate context.
- After the patch, all 59 tests across the dashboard, patient-model and
  clinical-form suites passed against an isolated, disposable PostgreSQL 17
  instance, with separate default and clinical test databases.
- Pylance syntax checks passed for all three modified Python files.
- Ruff reported nine remaining findings, all verified against the unchanged
  source baseline. No new lint findings were introduced; touched import blocks
  were sorted. Unrelated existing lint findings were left unchanged.
- The production repair procedure has not been rehearsed or executed. Local
  application tests do not replace the required restored-staging rehearsal.

## Proposed repair scope

Start with **active patients registered in `ang` only**. The expected insertion
count at the investigation snapshot is 1,746 contexts: 1,089 Patient History
plus 657 Admin contexts. These counts overlap by patient; do not describe them
as 1,746 distinct patients.

Inactive patients are explicitly excluded from the initial backfill. Repairing
them requires a separate scope decision.

The operation must be insert-only:

- Do not delete, merge, rename, reactivate or reassign existing contexts.
- Do not create repeating contexts or change registry membership.
- Do not change consent, follow-up queues, timestamps on existing records or
  clinical answers.
- Preserve all existing context IDs and their clinical-data associations.

## Preconditions and stop conditions

1. Verify the deployed source revision and release process for both the
   Angelman application and its RDRF submodule. Pin the exact tested revisions.
2. Verify usable, coordinated backups/restore points for `angelman2` and
   `angelman2clinical`; record the restore procedure and recovery time.
3. Re-run the coverage query below. Check that `PatientHistoryCFG` is the single
   default group, is fixed, and that both proposed groups still have their
   expected forms and naming configuration.
4. Generate a restricted candidate list keyed by patient ID and group ID.
   Record its counts and review it without exporting names or clinical values.
5. Check the candidates for inactive contexts in those same groups. An inactive
   record may represent an intentional deletion: stop for review instead of
   reactivating it or blindly replacing it.
6. Reconcile historical data before approving empty contexts. Check whether
   forms now assigned to Patient History or Admin already have clinical records
   under legacy, ungrouped or inactive contexts. If so, stop and prepare a
   separately approved data-migration plan. Do not copy answers or infer that
   empty new contexts mean the participant never supplied information.
7. Test the exact insert-only procedure against a securely restored staging
   copy. Verify saved historical data and progress as well as HTTP responses.
8. Pause web/background writers during the backfill. Fixed contexts currently
   lack a database uniqueness constraint, so `get_or_create()` alone does not
   prevent concurrent inserts. If writers cannot be paused, stop and agree a
   locking/uniqueness strategy first.
9. Stop on changed configuration, unexpected candidates, duplicates, concurrent
   writes, or insertion counts differing from the approved snapshot.

## Read-only coverage query

This matches the active-context filtering used by Django. It returns counts
only, not patient identities. Run immediately before approval and again after
the repair.

```sql
WITH coverage AS (
    SELECT
        p.id AS patient_id,
        cfg.id AS group_id,
        cfg.code,
        cfg.is_default,
        COUNT(c.id) AS active_context_count
    FROM patients_patient AS p
    JOIN patients_patient_rdrf_registry AS pr ON pr.patient_id = p.id
    JOIN rdrf_registry AS r ON r.id = pr.registry_id
    JOIN rdrf_contextformgroup AS cfg ON cfg.registry_id = r.id
    CROSS JOIN django_content_type AS ct
    LEFT JOIN rdrf_rdrfcontext AS c
        ON c.object_id = p.id
        AND c.registry_id = r.id
        AND c.context_form_group_id = cfg.id
        AND c.content_type_id = ct.id
        AND c.active
    WHERE r.code = 'ang'
        AND p.active
        AND cfg.context_type = 'F'
        AND ct.app_label = 'patients'
        AND ct.model = 'patient'
    GROUP BY p.id, cfg.id, cfg.code, cfg.is_default
)
SELECT
    code,
    is_default,
    COUNT(*) FILTER (WHERE active_context_count = 0) AS missing_contexts,
    COUNT(*) FILTER (WHERE active_context_count > 1) AS duplicate_patients
FROM coverage
GROUP BY code, is_default
ORDER BY is_default DESC, code;
```

## Execution procedure, after explicit approval

This is a specification for the reviewed repair script, not a command to run
blindly. Prepare and test that script on the restored staging copy first.

1. Enter the approved maintenance window, pause writers and confirm the backup
   and candidate snapshot still match.
2. Deploy the tested patch while user traffic remains paused.
3. In a transaction on the default database, restrict patients to the approved
   active `ang` candidate IDs and recheck membership and activity.
4. For each missing patient/group pair, recheck active and inactive contexts,
   then create only the approved missing fixed context with the correct
   registry, patient content type, patient ID, group ID, active flag and
   application-generated display name. Use Django model creation so creation
   timestamps and normal save behaviour are preserved.
5. Do not call the **old, unpatched** context manager: its duplicate-handling
   branch deletes records. If using the patched fixed-context manager, first
   assert that the missing fixed groups exactly equal the approved groups for
   that patient; it initialises all missing fixed groups, not just the default.
6. Capture newly inserted IDs and per-group counts in a restricted audit log.
   Assert that existing context IDs, attributes and clinical-data associations
   are unchanged. Abort and roll back the transaction on any discrepancy.
7. Before committing, rerun coverage: the approved active cohort must have zero
   missing fixed contexts and no new duplicates. Match insertion counts to the
   approved snapshot, rather than hard-coding the investigation counts.
8. Commit only after those assertions pass. Resume traffic after the application
   checks below succeed.

No direct SQL `UPDATE`, `DELETE` or clinical-data writes are part of this plan.

## Acceptance checks

- Previously failing, authorised parent dashboards return HTTP 200.
- New Patient History and Admin links point to their own context group and
  patient, not an unrelated default.
- Existing completed forms, saved responses, consent and progress remain
  unchanged. Newly empty contexts must not be presented as historical data.
- Repeating-module counts and existing context IDs are unchanged.
- Re-running the repair dry run produces zero candidates in the approved
  cohort.
- A second dashboard load creates no further contexts.
- Monitor for `no default context`, recovery warnings and duplicate-context
  warnings after traffic resumes. Investigate remaining warnings by patient ID
  without including clinical values in logs.

## Rollback

Before commit, abort the transaction on failed assertions. After commit, do
**not** delete inserted contexts automatically: participants may have saved new
data against them. Pause affected writes, inspect the inserted-ID audit log and
obtain a separate rollback approval. Prefer rolling back the application
revision without deleting data; remember that doing so can restore the original
dashboard failure. A database restore requires a coordinated recovery decision
covering both databases and any post-backup writes.
