"""Unit tests for atif_to_s3's pure planners (scripts/capture/atif_to_s3.py).

These pin the functional core of the `/drvr:capture-sync` uploader: the S3-key
renderer (principal / branch / codebase segments, org-hash, unsafe-session
rejection), the identity-free x-amz-meta builder, the upload planner, the
PII-scan aggregation (counts only, never snippets), and the sync ledger /
selection logic. The pure helpers are driven directly with plain dicts/kwargs --
no mocks (mocking pure logic is a boundary failure). No I/O, clock, or
randomness is exercised here; timestamps and content hashes are passed in as
arguments (the imperative shell + main() land in a later task).

The module MUST import with stdlib only (no boto3) and pull
`is_safe_path_component` from cc_to_atif_core at module top; until atif_to_s3
exists these are red.
"""

import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest import mock

from conftest import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "capture"))  # before importing the core
import atif_to_s3

FIX = PLUGIN_ROOT / "tests" / "fixtures" / "capture"


def _load(name):
    with open(FIX / name) as fh:
        return json.load(fh)


# Session ids used across fixtures (valid path components -> safe for the key).
SID_1 = "11111111-1111-4111-8111-111111111111"
SID_2 = "22222222-2222-4222-8222-222222222222"
SID_UNGROUPED = "33333333-3333-4333-8333-333333333333"

IDENTITY = {"principal_id": "auth0|user123", "principal_type": "user",
            "org_id": "org_ABC123"}


class TestRenderPrincipalSegment(unittest.TestCase):
    def test_render_principal_segment_user_verbatim(self):
        # A user/PAT principal is already "auth0|<sub>" -> passed through verbatim.
        self.assertEqual(
            atif_to_s3.render_principal_segment("auth0|abc", "user"), "auth0|abc")
        # An unknown principal type is a hard error (never silently keyed).
        with self.assertRaises(ValueError):
            atif_to_s3.render_principal_segment("auth0|abc", "pat")
        with self.assertRaises(ValueError):
            atif_to_s3.render_principal_segment("x", "")

    def test_render_principal_segment_machine_prefixed(self):
        # A machine principal (bare uuid) is namespaced with a "machine|" prefix.
        self.assertEqual(
            atif_to_s3.render_principal_segment("uuid", "machine"), "machine|uuid")


class TestBranchFromGroupKey(unittest.TestCase):
    def test_branch_from_group_key(self):
        # "branch:<x>" -> the raw <x> (owner NOT yet stripped here).
        self.assertEqual(
            atif_to_s3.branch_from_group_key("branch:eric/foo"), "eric/foo")
        self.assertEqual(atif_to_s3.branch_from_group_key("branch:main"), "main")
        # Off-git / non-branch group keys carry no branch -> None (caller skips).
        self.assertIsNone(atif_to_s3.branch_from_group_key("ungrouped"))
        self.assertIsNone(atif_to_s3.branch_from_group_key("T-123"))  # task key
        self.assertIsNone(atif_to_s3.branch_from_group_key(None))
        self.assertIsNone(atif_to_s3.branch_from_group_key(""))


class TestStripBranchOwner(unittest.TestCase):
    def test_strip_branch_owner(self):
        self.assertEqual(
            atif_to_s3.strip_branch_owner("eric/agent-session-capture"),
            "agent-session-capture")
        # Multi-segment refs flatten to a single key component with "__".
        self.assertEqual(atif_to_s3.strip_branch_owner("a/b/c"), "b__c")
        # A bare branch (no owner prefix) is kept verbatim.
        self.assertEqual(atif_to_s3.strip_branch_owner("main"), "main")
        # Empty / None / owner-only-with-trailing-slash -> sentinel, never an
        # empty segment (which would collapse the S3 key path).
        for bad in ("", None, "owner/"):
            self.assertEqual(atif_to_s3.strip_branch_owner(bad), "unknown-branch", bad)


class TestSanitizeSegment(unittest.TestCase):
    def test_sanitize_segment(self):
        # Non-ASCII stripped; slashes stripped (single key component); result ASCII.
        cleaned = atif_to_s3.sanitize_segment("café/x", fallback="fb")
        self.assertTrue(cleaned.isascii())
        self.assertNotIn("/", cleaned)
        self.assertEqual(cleaned, "cafx")
        # Whitespace is stripped so a segment never carries embedded spaces.
        self.assertEqual(atif_to_s3.sanitize_segment("dr ver ai", fallback="fb"),
                         "drverai")
        # Empty (and whitespace-only) -> the provided fallback sentinel.
        self.assertEqual(atif_to_s3.sanitize_segment("", fallback="unknown-codebase"),
                         "unknown-codebase")
        self.assertEqual(atif_to_s3.sanitize_segment(None, fallback="fb"), "fb")
        self.assertEqual(atif_to_s3.sanitize_segment("   ", fallback="fb"), "fb")


class TestRenderS3Key(unittest.TestCase):
    def test_render_s3_key_full(self):
        org_hash = hashlib.sha256("org_ABC123".encode()).hexdigest()[:63]
        key = atif_to_s3.render_s3_key(
            org_id="org_ABC123", principal_id="auth0|abc", principal_type="user",
            codebase="driver-sdlc-plugin", branch="eric/agent-session-capture",
            session_id=SID_1)
        self.assertEqual(
            key,
            f"trajectories/v1/{org_hash}/auth0|abc/driver-sdlc-plugin/"
            f"agent-session-capture/{SID_1}/trajectory.redacted.json")
        # The org segment is the 63-char sha256 prefix (no raw org id).
        self.assertIn(org_hash, key)
        self.assertEqual(len(org_hash), 63)
        self.assertNotIn("org_ABC123", key)
        # A machine principal is namespaced in the key too.
        mkey = atif_to_s3.render_s3_key(
            org_id="org_ABC123", principal_id="m-1", principal_type="machine",
            codebase="repo", branch="branchx", session_id=SID_1)
        self.assertIn("/machine|m-1/", mkey)

    def test_render_s3_key_rejects_unsafe_session_id(self):
        # A traversal / dotfile / separator-bearing session id can never key.
        for bad in ("../x", ".hidden", "a/b", ""):
            with self.assertRaises(ValueError, msg=bad):
                atif_to_s3.render_s3_key(
                    org_id="o", principal_id="auth0|a", principal_type="user",
                    codebase="cb", branch="main", session_id=bad)


class TestBuildMetadata(unittest.TestCase):
    EXPECTED_KEYS = {"session-id", "branch", "codebase", "schema-version",
                     "cost-usd", "steps", "capture-kind"}

    def test_build_metadata_has_no_identity(self):
        md = atif_to_s3.build_metadata(
            session_id=SID_1, branch="eric/agent-session-capture",
            cwd="/Users/dev/PycharmProjects/DriverAI/driver-sdlc-plugin",
            capture_kind="branch", cost_usd=0.975789, steps=4)
        # Key set is exactly the allowlist -- no principal/name/email/org keys.
        self.assertEqual(set(md.keys()), self.EXPECTED_KEYS)
        for forbidden in ("principal", "principal-id", "user", "email", "org",
                          "org-id", "name"):
            self.assertNotIn(forbidden, md)
        # Branch owner-stripped; codebase = basename(cwd).
        self.assertEqual(md["branch"], "agent-session-capture")
        self.assertEqual(md["codebase"], "driver-sdlc-plugin")
        self.assertEqual(md["schema-version"], "v1")
        self.assertEqual(md["capture-kind"], "branch")
        self.assertEqual(md["cost-usd"], "0.975789")
        self.assertEqual(md["steps"], "4")
        # Every value is an ASCII string (safe for an HTTP x-amz-meta header).
        for v in md.values():
            self.assertIsInstance(v, str)
            self.assertTrue(v.isascii(), v)

    def test_build_metadata_defaults_none_cost_and_steps_to_zero(self):
        md = atif_to_s3.build_metadata(
            session_id=SID_1, branch="branch", cwd="/x/repo", capture_kind="branch")
        self.assertEqual(md["cost-usd"], "0")
        self.assertEqual(md["steps"], "0")

    def test_build_metadata_empty_cwd_and_branch_use_sentinels(self):
        md = atif_to_s3.build_metadata(
            session_id=SID_1, branch=None, cwd="", capture_kind="branch")
        self.assertEqual(md["codebase"], "unknown-codebase")
        self.assertEqual(md["branch"], "unknown-branch")


class TestPlanUpload(unittest.TestCase):
    def test_plan_upload_from_fixture(self):
        traj = _load("s3_traj.redacted.json")
        entry = _load("s3_index.json")["branch:eric/agent-session-capture"][SID_1]
        plan = atif_to_s3.plan_upload(traj, entry, IDENTITY)
        self.assertEqual(set(plan.keys()), {"key", "metadata", "content_type"})
        self.assertEqual(plan["content_type"], "application/json")

        org_hash = hashlib.sha256("org_ABC123".encode()).hexdigest()[:63]
        self.assertEqual(
            plan["key"],
            f"trajectories/v1/{org_hash}/auth0|user123/driver-sdlc-plugin/"
            f"agent-session-capture/{SID_1}/trajectory.redacted.json")

        md = plan["metadata"]
        self.assertEqual(md["session-id"], SID_1)
        self.assertEqual(md["branch"], "agent-session-capture")
        self.assertEqual(md["codebase"], "driver-sdlc-plugin")
        self.assertEqual(md["schema-version"], "v1")
        self.assertEqual(md["capture-kind"], "branch")
        self.assertEqual(md["cost-usd"], "0.975789")
        self.assertEqual(md["steps"], "4")
        # No identity leaks into the plan (key aside, which is opaque/hashed).
        blob = json.dumps(md)
        self.assertNotIn("auth0", blob)
        self.assertNotIn("org_ABC123", blob)


class TestAggregateScan(unittest.TestCase):
    def test_aggregate_scan(self):
        findings = _load("s3_scan_findings.json")
        agg = atif_to_s3.aggregate_scan(findings)
        self.assertEqual(agg["by_type"],
                         {"Email address": 3, "High-entropy string": 1,
                          "IPv4 address": 1})
        self.assertEqual(agg["per_session"][SID_1],
                         {"Email address": 2, "High-entropy string": 1})
        self.assertEqual(agg["per_session"][SID_2],
                         {"IPv4 address": 1, "Email address": 1})
        # Counts ONLY -- no snippet / where text may leak into the aggregate.
        blob = json.dumps(agg)
        self.assertNotIn("snippet", blob)
        self.assertNotIn("where", blob)
        self.assertNotIn("〈", blob)
        self.assertNotIn("@example.com", blob)
        self.assertNotIn("10.0.0.1", blob)

    def test_aggregate_scan_empty(self):
        self.assertEqual(atif_to_s3.aggregate_scan({}),
                         {"by_type": {}, "per_session": {}})
        # A session with no findings still appears with an empty per-session map.
        agg = atif_to_s3.aggregate_scan({SID_1: []})
        self.assertEqual(agg, {"by_type": {}, "per_session": {SID_1: {}}})


class TestSyncLedger(unittest.TestCase):
    def test_is_synced_and_mark_synced(self):
        ledger = {}
        # Unseen session -> not synced.
        self.assertFalse(atif_to_s3.is_synced(ledger, SID_1, "sha-abc"))

        new_ledger = atif_to_s3.mark_synced(
            ledger, SID_1, s3_key="k/1", etag="etag-1",
            synced_at="2026-07-08T00:00:00Z", artifact_sha="sha-abc")
        # mark_synced returns a NEW ledger and does not mutate the input.
        self.assertIsNot(new_ledger, ledger)
        self.assertEqual(ledger, {})
        self.assertEqual(
            new_ledger[SID_1],
            {"s3_key": "k/1", "etag": "etag-1",
             "synced_at": "2026-07-08T00:00:00Z", "artifact_sha256": "sha-abc"})

        # Same hash -> synced (skip); a changed hash -> not synced (re-sync).
        self.assertTrue(atif_to_s3.is_synced(new_ledger, SID_1, "sha-abc"))
        self.assertFalse(atif_to_s3.is_synced(new_ledger, SID_1, "sha-CHANGED"))
        # A different, un-recorded session -> not synced.
        self.assertFalse(atif_to_s3.is_synced(new_ledger, SID_2, "sha-abc"))


class TestSelectSessions(unittest.TestCase):
    def _index(self):
        return _load("s3_index.json")

    def test_select_sessions(self):
        index = self._index()
        # SID_1 already synced (matching hash); SID_2 un-synced; SID_UNGROUPED
        # lives under the "ungrouped" group and must be skipped entirely.
        ledger = {SID_1: {"s3_key": "k", "etag": "e",
                          "synced_at": "t", "artifact_sha256": "sha-1"}}
        shas = {SID_1: "sha-1", SID_2: "sha-2", SID_UNGROUPED: "sha-3"}

        selected = atif_to_s3.select_sessions(index, ledger, shas)
        sids = [e["session_id"] for e in selected]
        # Only the un-synced branch session; synced one excluded, ungrouped skipped.
        self.assertEqual(sids, [SID_2])
        self.assertNotIn(SID_UNGROUPED, sids)

        # Each returned entry is the full index entry (retains contract fields).
        entry = selected[0]
        for field in ("session_id", "group_key", "cwd"):
            self.assertIn(field, entry)

    def test_select_sessions_changed_hash_reselects(self):
        index = self._index()
        ledger = {SID_1: {"s3_key": "k", "etag": "e",
                          "synced_at": "t", "artifact_sha256": "sha-OLD"}}
        # SID_1's local artifact changed (re-rolled) -> it must be re-selected.
        shas = {SID_1: "sha-NEW", SID_2: "sha-2"}
        sids = [e["session_id"]
                for e in atif_to_s3.select_sessions(index, ledger, shas)]
        self.assertIn(SID_1, sids)

    def test_select_sessions_session_id_filter(self):
        index = self._index()
        shas = {SID_1: "sha-1", SID_2: "sha-2"}
        # Filter to a single (un-synced) session -> just that one.
        selected = atif_to_s3.select_sessions(index, {}, shas, session_id=SID_2)
        self.assertEqual([e["session_id"] for e in selected], [SID_2])
        # Filtering to an already-synced session still excludes it (idempotent).
        ledger = {SID_1: {"artifact_sha256": "sha-1"}}
        selected = atif_to_s3.select_sessions(index, ledger, shas, session_id=SID_1)
        self.assertEqual(selected, [])
        # Filtering to an ungrouped session -> skipped (empty).
        selected = atif_to_s3.select_sessions(index, {}, shas,
                                              session_id=SID_UNGROUPED)
        self.assertEqual(selected, [])

    def test_select_sessions_empty_and_missing_index(self):
        self.assertEqual(atif_to_s3.select_sessions({}, {}, {}), [])
        self.assertEqual(atif_to_s3.select_sessions(None, {}, {}), [])


# ===========================================================================
# Annotations S3-sync planners (plan 06). Pure functions -- the annotations
# sibling key (derived FROM the trajectory ledger row, never recomputed from
# launch identity -- capture-viewer DEC-030), the mutable last-write-wins ledger
# row (capture-viewer DEC-008 does NOT apply -- a changed sha re-uploads), and
# the per-session upload decision gated on the TRAJECTORY ledger row existing
# (capture-viewer DEC-034 -- row-exists, NOT is_synced). Driven with plain dicts;
# no I/O, clock, or randomness.
# ===========================================================================

# A real-shaped trajectory key, exactly as render_s3_key composes it -- the
# annotations sibling is derived from THIS, not re-rendered from identity.
_ORG_HASH = hashlib.sha256("org_ABC123".encode()).hexdigest()[:63]
_TRAJ_KEY = (f"trajectories/v1/{_ORG_HASH}/auth0|user123/driver-sdlc-plugin/"
             f"agent-session-capture/{SID_1}/trajectory.redacted.json")


class TestRenderAnnotationsKey(unittest.TestCase):
    def test_render_annotations_key_sibling(self):
        ann_key = atif_to_s3.render_annotations_key(_TRAJ_KEY)
        # Leaf swap only: trajectory.redacted.json -> annotations.json.
        self.assertEqual(
            ann_key,
            f"trajectories/v1/{_ORG_HASH}/auth0|user123/driver-sdlc-plugin/"
            f"agent-session-capture/{SID_1}/annotations.json")
        # The sibling shares the trajectory's EXACT prefix (the whole point of
        # DEC-030 -- the object lives where the ledger says the trajectory does).
        self.assertEqual(ann_key.rsplit("/", 1)[0], _TRAJ_KEY.rsplit("/", 1)[0])
        # A key whose leaf is not the fixed trajectory leaf is rejected -- the
        # only traversal surface left (the key comes from the ledger, not input).
        for bad in (
            f"trajectories/v1/{_ORG_HASH}/auth0|user123/cb/br/{SID_1}/annotations.json",
            f"trajectories/v1/{_ORG_HASH}/auth0|user123/cb/br/{SID_1}/trajectory.json",
            "trajectory.redacted.json",   # no prefix at all
            "",
        ):
            with self.assertRaises(ValueError, msg=bad):
                atif_to_s3.render_annotations_key(bad)


class TestAnnotationsLedgerRow(unittest.TestCase):
    def test_annotations_ledger_row_shape(self):
        row = atif_to_s3.annotations_ledger_row(
            "trajectories/v1/h/p/cb/br/sid/annotations.json",
            "ann-sha-abc", "etag-1", "2026-07-09T00:00:00Z")
        # A pure constructor: EXACTLY these four keys, values passed through.
        self.assertEqual(
            row,
            {"s3_key": "trajectories/v1/h/p/cb/br/sid/annotations.json",
             "annotations_sha": "ann-sha-abc", "etag": "etag-1",
             "updated_at": "2026-07-09T00:00:00Z"})
        self.assertEqual(set(row.keys()),
                         {"s3_key", "annotations_sha", "etag", "updated_at"})


class TestPlanAnnotationsUpload(unittest.TestCase):
    # The annotations planner reads codebase/branch off the entry directly
    # (identity-free metadata, sanitized like the trajectory's -- DEC-068).
    ENTRY = {"codebase": "driver-sdlc-plugin",
             "branch": "eric/agent-session-capture"}

    def _traj_ledger(self):
        return {SID_1: {"s3_key": _TRAJ_KEY, "etag": "e", "synced_at": "t",
                        "artifact_sha256": "traj-sha"}}

    def test_plan_annotations_upload_lww(self):
        traj_ledger = self._traj_ledger()
        ann_key = atif_to_s3.render_annotations_key(_TRAJ_KEY)

        # Unchanged sha (annotations ledger already records this exact sha) -> a
        # no-op decision (no re-upload of identical bytes). This LWW/no-op logic
        # is the PLANNER's, never the row constructor's.
        ann_ledger = {SID_1: {"s3_key": ann_key, "annotations_sha": "ann-sha-1",
                              "etag": "ae", "updated_at": "t"}}
        plan = atif_to_s3.plan_annotations_upload(
            session_id=SID_1, trajectory_ledger=traj_ledger,
            annotations_ledger=ann_ledger, annotations_sha="ann-sha-1",
            entry=self.ENTRY)
        self.assertEqual(plan["action"], "noop")
        self.assertEqual(plan["s3_key"], ann_key)
        self.assertIsNone(plan["reason"])
        self.assertIsNone(plan["metadata"])

        # Changed sha -> the row must UPDATE (upload planned), NOT be rejected as
        # a DEC-008 re-sync violation (that one-shot rule is the trajectory's).
        plan = atif_to_s3.plan_annotations_upload(
            session_id=SID_1, trajectory_ledger=traj_ledger,
            annotations_ledger=ann_ledger, annotations_sha="ann-sha-2",
            entry=self.ENTRY)
        self.assertEqual(plan["action"], "upload")
        self.assertIsNone(plan["reason"])
        self.assertEqual(plan["s3_key"], ann_key)
        # Identity-free metadata, sanitized like the trajectory's (DEC-068).
        md = plan["metadata"]
        self.assertEqual(md["session-id"], SID_1)
        self.assertEqual(md["codebase"], "driver-sdlc-plugin")
        self.assertEqual(md["branch"], "agent-session-capture")  # owner stripped
        self.assertEqual(md["content-kind"], "annotations")
        self.assertEqual(md["schema-version"], "1")
        blob = json.dumps(md)
        for forbidden in ("auth0", "org_ABC123", "eric"):
            self.assertNotIn(forbidden, blob)

        # First-ever annotations upload (no annotations ledger row) -> upload too.
        plan = atif_to_s3.plan_annotations_upload(
            session_id=SID_1, trajectory_ledger=traj_ledger,
            annotations_ledger={}, annotations_sha="ann-sha-1", entry=self.ENTRY)
        self.assertEqual(plan["action"], "upload")
        self.assertEqual(plan["s3_key"], ann_key)

    def test_plan_annotations_upload_gated_on_synced(self):
        traj_ledger = self._traj_ledger()

        # No trajectory ledger row -> refused with a reason (no orphan annotation
        # object -- a row implies the trajectory object is in S3; DEC-034).
        plan = atif_to_s3.plan_annotations_upload(
            session_id=SID_2, trajectory_ledger=traj_ledger,
            annotations_ledger={}, annotations_sha="ann-sha", entry=self.ENTRY)
        self.assertEqual(plan["action"], "refuse")
        self.assertTrue(plan["reason"])
        self.assertIsNone(plan["s3_key"])
        self.assertIsNone(plan["metadata"])

        # A trajectory row present with a DRIFTED artifact sha (a re-rolled
        # session) STILL passes -- the gate is row-exists, NOT is_synced. The
        # planner takes no artifact-sha argument at all, so a drifted/absent local
        # sha can never refuse (a strict is_synced would wrongly refuse here).
        plan = atif_to_s3.plan_annotations_upload(
            session_id=SID_1, trajectory_ledger=traj_ledger,
            annotations_ledger={}, annotations_sha="ann-sha", entry=self.ENTRY)
        self.assertEqual(plan["action"], "upload")
        self.assertEqual(plan["s3_key"],
                         atif_to_s3.render_annotations_key(_TRAJ_KEY))

        # A malformed trajectory row (no s3_key) is treated as no row -> refused
        # (a row without a key can't derive a sibling; no orphan possible).
        plan = atif_to_s3.plan_annotations_upload(
            session_id=SID_1, trajectory_ledger={SID_1: {"etag": "e"}},
            annotations_ledger={}, annotations_sha="ann-sha", entry=self.ENTRY)
        self.assertEqual(plan["action"], "refuse")


class TestScanNotePii(unittest.TestCase):
    """scan_note_pii -- by-type PII COUNTS over the human-authored text in an
    annotations doc (stepLabels[].note + runLabels[].note + tags[]; capture-viewer
    DEC-031). render_trace.scan takes a TRAJECTORY dict, so scan_note_pii wraps each
    text as its OWN synthetic step -- one step per text, so scan's value@location
    dedup cannot under-count a value repeated across notes. Counts ONLY: the
    findings' snippet/where fields never leave the function (DEC-071 lineage).
    Pure -- plain dicts in, a {type: count} dict out; no I/O."""

    def test_scan_note_pii_counts_only(self):
        # dev@example.com appears in a stepLabel note AND a runLabel note (SAME
        # value, two DIFFERENT notes); ops@example.com in a tag; an IPv4 in a
        # stepLabel note. Values chosen so render_trace.scan recognizes them:
        # "Email address" + "IPv4 address" detectors (see render_trace.SCAN).
        doc = {
            "stepLabels": [
                {"decision": "correct", "anchor": {"trajId": None, "stepId": 1},
                 "note": "ping dev@example.com about this step"},
                {"decision": "unsure", "anchor": {"trajId": None, "stepId": 3},
                 "note": "the box at 10.0.0.1 was flaky here"},
            ],
            "runLabels": [
                {"decision": "incorrect", "note": "escalate to dev@example.com"},
            ],
            "tags": ["owner ops@example.com", "flaky"],
        }
        counts = atif_to_s3.scan_note_pii(doc)

        # Three emails: dev@ (stepLabel) + dev@ (runLabel) + ops@ (tag). The
        # repeated dev@example.com across two DIFFERENT notes counts TWICE -- the
        # per-text synthetic-step wrap defeats render_trace.scan's value@location
        # dedup (a single-step scan would have folded the two dev@ hits to one).
        self.assertEqual(counts, {"Email address": 3, "IPv4 address": 1})
        self.assertEqual(counts["Email address"], 3)

        # Counts ONLY -- no snippet / where key, no raw note text leaks out
        # (capture-viewer DEC-071 lineage: the findings' snippet/where fields
        # never leave scan_note_pii). Every value is an int count.
        self.assertNotIn("snippet", counts)
        self.assertNotIn("where", counts)
        for v in counts.values():
            self.assertIsInstance(v, int)
        blob = json.dumps(counts)
        self.assertNotIn("@example.com", blob)
        self.assertNotIn("dev@", blob)
        self.assertNotIn("10.0.0.1", blob)
        self.assertNotIn("〈", blob)   # the scan snippet bracket marker

    def test_scan_note_pii_empty_doc(self):
        # An empty doc -> {} (no texts -> no synthetic steps -> nothing scanned).
        self.assertEqual(atif_to_s3.scan_note_pii({}), {})
        # A doc whose labels/tags carry no note text is also {} (empty/None notes
        # and empty tags contribute no synthetic step).
        self.assertEqual(
            atif_to_s3.scan_note_pii(
                {"stepLabels": [{"decision": "correct",
                                 "anchor": {"trajId": None, "stepId": 1}}],
                 "runLabels": [{"decision": "unsure", "note": ""}],
                 "tags": []}),
            {})


# ===========================================================================
# Imperative-shell / I/O tests (Task 3).
#
# These exercise the shell edge with REAL files in tmp dirs (never a mock of the
# I/O) and the `aws` boundary via a PATH-stubbed fake executable (never a patch
# of internals) -- mirroring test_roll_capture_hook.py's fake-executable helper
# and test_capture_atif_to_opik.py's corrupt-ledger/tmp-dir pattern.
# ===========================================================================

# A fake `aws` CLI: records every invocation's argv (one JSON line) to
# $FAKE_AWS_CALLS and emits canned output driven by env vars, so the shell's
# subprocess boundary is asserted without touching real AWS. It is a real
# on-disk executable placed first on PATH (the PATH-stub technique from
# test_roll_capture_hook.py), not a monkeypatch.
_FAKE_AWS_BODY = r'''
import json, os, sys
argv = sys.argv[1:]
calls = os.environ.get("FAKE_AWS_CALLS")
if calls:
    with open(calls, "a") as f:
        f.write(json.dumps(argv) + "\n")

def _sub(*names):
    return argv[:len(names)] == list(names)

if _sub("sts", "get-caller-identity"):
    beh = os.environ.get("FAKE_AWS_STS", "ok")
    if beh == "ok":
        print(json.dumps({"Account": "123456789012",
                          "Arn": "arn:aws:sts::123456789012:assumed-role/dev-admin/s",
                          "UserId": "AIDAEXAMPLE"}))
        sys.exit(0)
    if beh == "expired":
        sys.stderr.write("Error loading SSO Token: The SSO session associated with "
                         "this profile has expired or is otherwise invalid. To refresh "
                         "this SSO session run aws sso login with the corresponding "
                         "profile.\n")
        sys.exit(255)
    if beh == "missing-profile":
        sys.stderr.write("The config profile (dev-admin) could not be found\n")
        sys.exit(255)
    sys.stderr.write("Unable to locate credentials.\n")
    sys.exit(1)

if _sub("s3api", "put-object"):
    key = argv[argv.index("--key") + 1] if "--key" in argv else ""
    fail_keys = [k for k in os.environ.get("FAKE_AWS_PUT_FAIL_KEYS", "").split(",") if k]
    if any(fk in key for fk in fail_keys):
        if os.environ.get("FAKE_AWS_PUT_FAIL_MODE") == "kms":
            sys.stderr.write("An error occurred (AccessDenied) when calling the "
                             "PutObject operation: user is not authorized to perform "
                             "kms:GenerateDataKey on the CMK\n")
        else:
            sys.stderr.write("An error occurred (InternalError) when calling the "
                             "PutObject operation: simulated transient failure\n")
        sys.exit(1)
    # Emit the QUOTED ETag form S3 returns so upload_one's .strip('"') is exercised.
    print(json.dumps({"ETag": os.environ.get("FAKE_AWS_ETAG", '"abc123"')}))
    sys.exit(0)

sys.stderr.write("fake aws: unhandled subcommand: %r\n" % (argv,))
sys.exit(2)
'''


def _install_fake_aws(bindir):
    """Write a fake `aws` executable into bindir (mirrors the fake-executable
    helper in test_roll_capture_hook.py: write script, chmod +x, front of PATH)."""
    aws = os.path.join(bindir, "aws")
    with open(aws, "w") as fh:
        fh.write(f"#!{sys.executable}\n" + _FAKE_AWS_BODY)
    os.chmod(aws, 0o755)
    return aws


def _artifact_path(base_dir, sid):
    return os.path.join(base_dir, "sessions", sid, "trajectory.redacted.json")


def _seed_session(base_dir, sid, traj, *,
                  group_key="branch:eric/agent-session-capture",
                  cwd="/Users/dev/PycharmProjects/DriverAI/driver-sdlc-plugin",
                  record_count=16, total_cost_usd=0.5):
    """Write a redacted artifact under the base-dir convention and return the
    index entry pointing at it (store_path == the base-dir convention path, so
    scan_sessions' store_path read agrees with main's base-dir resolution)."""
    art = _artifact_path(base_dir, sid)
    os.makedirs(os.path.dirname(art), exist_ok=True)
    with open(art, "w") as fh:
        json.dump(traj, fh)
    return {"session_id": sid, "group_key": group_key, "cwd": cwd,
            "store_path": art, "first_seen": "2026-07-01T00:00:00+00:00",
            "last_seen": "2026-07-01T00:00:00+00:00",
            "record_count": record_count, "total_cost_usd": total_cost_usd,
            "prev_session_id": None}


def _write_index(base_dir, entries):
    index = {}
    for e in entries:
        index.setdefault(e["group_key"], {})[e["session_id"]] = e
    os.makedirs(base_dir, exist_ok=True)
    with open(os.path.join(base_dir, "index.json"), "w") as fh:
        json.dump(index, fh)
    return index


def _mk_traj(sid, *, message="synced.", total_cost_usd=0.5, total_steps=4):
    return {"schema_version": "ATIF-v1.7", "session_id": sid,
            "agent": {"name": "claude-code"},
            "final_metrics": {"total_cost_usd": total_cost_usd,
                              "total_steps": total_steps},
            "steps": [{"step_id": 1, "source": "agent", "message": message}]}


class _ShellBase(unittest.TestCase):
    """Isolated tmp base-dir + a fake `aws` first on PATH. Restores PATH and the
    FAKE_AWS_* env in tearDown so nothing leaks between tests."""

    _FAKE_ENV = ("FAKE_AWS_CALLS", "FAKE_AWS_STS", "FAKE_AWS_ETAG",
                 "FAKE_AWS_PUT_FAIL_KEYS", "FAKE_AWS_PUT_FAIL_MODE")

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="drvr-s3-shell-")
        self.base = os.path.join(self.tmp, "capture")
        os.makedirs(self.base, exist_ok=True)
        self.bindir = os.path.join(self.tmp, "bin")
        os.makedirs(self.bindir, exist_ok=True)
        _install_fake_aws(self.bindir)
        self.calls_file = os.path.join(self.tmp, "aws-calls.jsonl")
        self._orig_path = os.environ["PATH"]
        self._orig_env = {k: os.environ.get(k) for k in self._FAKE_ENV}
        os.environ["PATH"] = self.bindir + os.pathsep + self._orig_path
        os.environ["FAKE_AWS_CALLS"] = self.calls_file

    def tearDown(self):
        os.environ["PATH"] = self._orig_path
        for k, v in self._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- fake-aws call inspection --------------------------------------------

    def _calls(self):
        if not os.path.exists(self.calls_file):
            return []
        with open(self.calls_file) as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def _put_calls(self):
        return [c for c in self._calls() if c[:2] == ["s3api", "put-object"]]

    def _sts_calls(self):
        return [c for c in self._calls() if c[:2] == ["sts", "get-caller-identity"]]

    def _remove_aws_from_path(self):
        """Point PATH at an empty dir so `aws` cannot be resolved -> the shell hits
        FileNotFoundError (the aws-not-installed case)."""
        empty = os.path.join(self.tmp, "empty-bin")
        os.makedirs(empty, exist_ok=True)
        os.environ["PATH"] = empty

    def _run_main(self, extra_args):
        """Run main() with identity + base-dir args, capturing stdout/stderr."""
        argv = ["--principal-id", "auth0|user123", "--principal-type", "user",
                "--org-id", "org_ABC123", "--base-dir", self.base] + extra_args
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = atif_to_s3.main(argv)
        return rc, out.getvalue(), err.getvalue()

    @property
    def _ledger_path(self):
        return os.path.join(self.base, "s3-sync-ledger.json")


class TestLedgerIO(_ShellBase):
    def test_ledger_load_save_atomic_and_corrupt_recovers(self):
        path = self._ledger_path
        # Missing ledger -> empty (no crash).
        self.assertEqual(atif_to_s3.load_ledger(path), {})

        # Corrupt ledger -> warn to stderr + empty (never a crash).
        with open(path, "w") as fh:
            fh.write("{ not valid json ]")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(atif_to_s3.load_ledger(path), {})
        self.assertIn("unreadable", err.getvalue().lower())

        # save_ledger round-trips and is atomic (no torn/leftover temp file).
        ledger = {SID_1: {"s3_key": "k/1", "etag": "e1",
                          "synced_at": "2026-07-08T00:00:00Z",
                          "artifact_sha256": "sha-abc"}}
        atif_to_s3.save_ledger(path, ledger)
        with open(path) as fh:
            self.assertEqual(json.load(fh), ledger)
        leftovers = [n for n in os.listdir(self.base) if ".tmp." in n]
        self.assertEqual(leftovers, [], f"temp file left behind: {leftovers}")


class TestIndexIO(_ShellBase):
    def test_load_index_corrupt_and_missing_fields(self):
        index_path = os.path.join(self.base, "index.json")
        # Missing -> empty.
        self.assertEqual(atif_to_s3.load_index(index_path), {})
        # Corrupt -> warn + empty.
        with open(index_path, "w") as fh:
            fh.write("{ nope ]")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(atif_to_s3.load_index(index_path), {})
        self.assertIn("unreadable", err.getvalue().lower())

        # An entry missing cwd / total_cost_usd / record_count must not crash the
        # pure planners the shell feeds it (sentinels + zero defaults kick in).
        sparse_entry = {"session_id": SID_1,
                        "group_key": "branch:eric/agent-session-capture"}
        plan = atif_to_s3.plan_upload({}, sparse_entry, IDENTITY)
        self.assertEqual(plan["metadata"]["codebase"], "unknown-codebase")
        self.assertEqual(plan["metadata"]["cost-usd"], "0")
        self.assertEqual(plan["metadata"]["steps"], "0")
        md = atif_to_s3.build_metadata(session_id=SID_1, branch=None, cwd=None,
                                       capture_kind="branch")
        self.assertEqual(md["codebase"], "unknown-codebase")


class TestArtifactSha256(_ShellBase):
    def test_artifact_sha256_and_missing_file(self):
        body = os.path.join(self.tmp, "trajectory.redacted.json")
        content = b'{"schema_version": "ATIF-v1.7"}'
        with open(body, "wb") as fh:
            fh.write(content)
        expected = hashlib.sha256(content).hexdigest()
        self.assertEqual(atif_to_s3.artifact_sha256(body), expected)

        # A missing artifact is skipped with a warning (returns None), the batch
        # is expected to continue -- never a raised traceback.
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertIsNone(
                atif_to_s3.artifact_sha256(os.path.join(self.tmp, "nope.json")))
        self.assertTrue(err.getvalue().strip(), "missing artifact should warn")


class TestUploadOne(_ShellBase):
    def test_upload_one_builds_argv_and_parses_etag(self):
        body = os.path.join(self.tmp, "body.json")
        with open(body, "w") as fh:
            fh.write("{}")
        # Values carrying ',' '=' and a non-ASCII char: the JSON --metadata form
        # survives them where the `k=v,k=v` shorthand would corrupt/split.
        metadata = {"session-id": SID_1, "branch": "a,b=c",
                    "codebase": "café-x", "cost-usd": "1,2=3"}
        etag = atif_to_s3.upload_one(
            "trajectories/v1/h/auth0|abc/cb/br/%s/trajectory.redacted.json" % SID_1,
            body, metadata, bucket="my-bucket", profile="dev-admin")
        # Shim emits the quoted ETag "\"abc123\"" -> strip('"') -> abc123.
        self.assertEqual(etag, "abc123")

        put = self._put_calls()
        self.assertEqual(len(put), 1)
        argv = put[0]
        self.assertEqual(argv[:2], ["s3api", "put-object"])
        # Flag/value pairs present.
        for flag, val in (("--bucket", "my-bucket"), ("--body", body),
                          ("--content-type", "application/json"),
                          ("--profile", "dev-admin")):
            self.assertIn(flag, argv)
            self.assertEqual(argv[argv.index(flag) + 1], val)
        # --metadata is a SINGLE JSON string that round-trips to the exact dict
        # (proving the ',' '=' / non-ASCII values survive the boundary).
        self.assertIn("--metadata", argv)
        meta_arg = argv[argv.index("--metadata") + 1]
        self.assertEqual(meta_arg, json.dumps(metadata))
        self.assertEqual(json.loads(meta_arg), metadata)
        # A comma-shorthand would have split the value into extra argv tokens.
        self.assertNotIn("a,b=c", argv)


class TestPreflightSso(_ShellBase):
    def test_preflight_sso_errors_clearly(self):
        # Expired SSO -> message tells the user exactly how to refresh.
        os.environ["FAKE_AWS_STS"] = "expired"
        with self.assertRaises(RuntimeError) as ctx:
            atif_to_s3.preflight_sso("dev-admin")
        expired_msg = str(ctx.exception)
        self.assertIn("aws sso login --profile dev-admin", expired_msg)

        # Profile-missing -> a DISTINCT message (not the sso-login hint).
        os.environ["FAKE_AWS_STS"] = "missing-profile"
        with self.assertRaises(RuntimeError) as ctx:
            atif_to_s3.preflight_sso("dev-admin")
        missing_msg = str(ctx.exception)
        self.assertNotEqual(expired_msg, missing_msg)
        self.assertNotIn("aws sso login", missing_msg)
        self.assertIn("profile", missing_msg.lower())

        # aws not installed -> a clean RuntimeError (no raw FileNotFoundError /
        # traceback), telling the user to install/enable aws.
        os.environ.pop("FAKE_AWS_STS", None)
        self._remove_aws_from_path()
        with self.assertRaises(RuntimeError) as ctx:
            atif_to_s3.preflight_sso("dev-admin")
        absent_msg = str(ctx.exception).lower()
        self.assertTrue("install" in absent_msg or "enable" in absent_msg)
        self.assertIn("aws", absent_msg)


class TestMainDryRun(_ShellBase):
    def test_main_dry_run_lists_real_keys_without_upload(self):
        e1 = _seed_session(self.base, SID_1, _mk_traj(SID_1))
        e2 = _seed_session(self.base, SID_2, _mk_traj(SID_2))
        _write_index(self.base, [e1, e2])

        rc, out, _ = self._run_main(["--dry-run"])
        self.assertEqual(rc, 0)
        # The real composed keys are printed (compare against the pure planner).
        for entry, sid in ((e1, SID_1), (e2, SID_2)):
            expected = atif_to_s3.plan_upload(_mk_traj(sid), entry, IDENTITY)["key"]
            self.assertIn(expected, out)
        # Dry-run egresses nothing: no upload, no preflight, no ledger.
        self.assertEqual(self._put_calls(), [])
        self.assertEqual(self._sts_calls(), [])
        self.assertFalse(os.path.exists(self._ledger_path))


class TestMainScan(_ShellBase):
    def test_main_scan_emits_by_type_json(self):
        traj = _mk_traj(SID_1, message="contact dev@example.com and ops@example.com")
        entry = _seed_session(self.base, SID_1, traj)
        _write_index(self.base, [entry])

        rc, out, _ = self._run_main(["--scan"])
        self.assertEqual(rc, 0)
        agg = json.loads(out)
        self.assertEqual(agg["by_type"], {"Email address": 2})
        self.assertEqual(agg["per_session"][SID_1], {"Email address": 2})
        # Counts only: no snippet text / bracket / raw finding leaks into stdout.
        self.assertNotIn("@example.com", out)
        self.assertNotIn("example.com", out)
        self.assertNotIn("〈", out)  # the scan snippet marker
        self.assertNotIn("snippet", out)
        # Scan egresses nothing to S3.
        self.assertEqual(self._put_calls(), [])


class TestMainEmptySelection(_ShellBase):
    def test_main_empty_selection_noop(self):
        # (a) Empty index -> nothing to sync, rc 0, no preflight, no upload.
        _write_index(self.base, [])
        rc, out, _ = self._run_main([])
        self.assertEqual(rc, 0)
        self.assertIn("nothing to sync", out.lower())
        self.assertEqual(self._put_calls(), [])
        self.assertEqual(self._sts_calls(), [])

        # (b) All-synced ledger -> also a clean no-op.
        entry = _seed_session(self.base, SID_1, _mk_traj(SID_1))
        _write_index(self.base, [entry])
        sha = atif_to_s3.artifact_sha256(_artifact_path(self.base, SID_1))
        atif_to_s3.save_ledger(self._ledger_path, {SID_1: {
            "s3_key": "k", "etag": "e", "synced_at": "t", "artifact_sha256": sha}})
        rc, out, _ = self._run_main([])
        self.assertEqual(rc, 0)
        self.assertIn("nothing to sync", out.lower())
        self.assertEqual(self._put_calls(), [])


class TestMainPartialBatch(_ShellBase):
    def test_main_partial_batch_continues(self):
        sids = [SID_1, SID_2, "44444444-4444-4444-8444-444444444444"]
        entries = [_seed_session(self.base, s, _mk_traj(s)) for s in sids]
        _write_index(self.base, entries)
        # Fail only the SECOND session's upload; the batch must still finish 1 & 3.
        os.environ["FAKE_AWS_PUT_FAIL_KEYS"] = sids[1]

        rc, out, err = self._run_main([])
        # Partial failure -> non-zero exit.
        self.assertNotEqual(rc, 0)
        # All three were attempted; SSO preflight ran once.
        self.assertEqual(len(self._put_calls()), 3)
        self.assertEqual(len(self._sts_calls()), 1)
        # The ledger records ONLY the two successes (never the failed one).
        with open(self._ledger_path) as fh:
            ledger = json.load(fh)
        self.assertEqual(set(ledger), {sids[0], sids[2]})
        self.assertNotIn(sids[1], ledger)
        self.assertIn(sids[1], err)  # the failure was reported


# ===========================================================================
# Multi-session sync seam: select_sessions' session_ids filter, hash_candidates
# (default CLI scope vs all_groups dataset scope), and sync_sessions
# (per-session results + upload-before-ledger-write ordering) -- the extracted
# surface the viewer server composes. main() stays the CLI composition of these
# and is pinned byte-for-byte by TestMainCliParity.
# ===========================================================================

SID_3 = "44444444-4444-4444-8444-444444444444"


def _sha_of(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class TestSelectSessionsSessionIdsFilter(unittest.TestCase):
    """select_sessions' keyword-only session_ids set filter (the multi-select
    the viewer's POST /api/sync drives). Pure -- plain dicts, no I/O."""

    def test_select_sessions_session_ids_filter(self):
        index = _load("s3_index.json")
        shas = {SID_1: "sha-1", SID_2: "sha-2", SID_UNGROUPED: "sha-3"}

        # The set filter selects exactly those (index order preserved).
        selected = atif_to_s3.select_sessions(index, {}, shas,
                                              session_ids={SID_1, SID_2})
        self.assertEqual([e["session_id"] for e in selected], [SID_1, SID_2])
        selected = atif_to_s3.select_sessions(index, {}, shas,
                                              session_ids={SID_2})
        self.assertEqual([e["session_id"] for e in selected], [SID_2])

        # Composes with the synced-skip: a synced member of the set drops out.
        ledger = {SID_1: {"s3_key": "k", "etag": "e",
                          "synced_at": "t", "artifact_sha256": "sha-1"}}
        selected = atif_to_s3.select_sessions(index, ledger, shas,
                                              session_ids={SID_1, SID_2})
        self.assertEqual([e["session_id"] for e in selected], [SID_2])

        # Unknown ids are silently absent (validation is the server's job).
        selected = atif_to_s3.select_sessions(
            index, {}, shas, session_ids={SID_1, "not-in-the-index"})
        self.assertEqual([e["session_id"] for e in selected], [SID_1])

        # The branch-only rule still applies: an ungrouped id never selects.
        selected = atif_to_s3.select_sessions(index, {}, shas,
                                              session_ids={SID_UNGROUPED})
        self.assertEqual(selected, [])

        # session_id and session_ids are mutually exclusive -> ValueError.
        with self.assertRaises(ValueError):
            atif_to_s3.select_sessions(index, {}, shas, SID_1,
                                       session_ids={SID_1})


class TestHashCandidates(_ShellBase):
    """hash_candidates -- the candidate-hashing loop extracted from main().
    Real tmp-store files, no mocks: the function's whole job is store-path
    resolution + hashing at the filesystem edge."""

    def test_hash_candidates_scopes_and_skips(self):
        e1 = _seed_session(self.base, SID_1, _mk_traj(SID_1))
        e2 = _seed_session(self.base, SID_2, _mk_traj(SID_2))
        e3 = _seed_session(self.base, SID_UNGROUPED, _mk_traj(SID_UNGROUPED),
                           group_key="ungrouped")
        index = _write_index(self.base, [e1, e2, e3])
        os.remove(_artifact_path(self.base, SID_2))    # SID_2 -> unreadable
        sha_1 = _sha_of(_artifact_path(self.base, SID_1))
        sha_3 = _sha_of(_artifact_path(self.base, SID_UNGROUPED))

        # Default (CLI path): branch-keyed groups only; the unreadable artifact
        # warns to stderr and is OMITTED from shas entirely.
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            shas, paths = atif_to_s3.hash_candidates(index, self.base)
        self.assertEqual(shas, {SID_1: sha_1})
        self.assertEqual(paths, {SID_1: _artifact_path(self.base, SID_1)})
        self.assertIn(SID_2, err.getvalue())           # the skip was warned

        # session_ids narrows the pool BEFORE hashing (the excluded unreadable
        # session is never attempted, so no warning is emitted).
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            shas, paths = atif_to_s3.hash_candidates(index, self.base,
                                                     session_ids={SID_1})
        self.assertEqual(shas, {SID_1: sha_1})
        self.assertEqual(err.getvalue(), "")

        # TRUTHY session_id narrowing (main()'s `if args.session_id and ...`):
        # "" narrows nothing, so --session-id "" keeps today's hash-everything
        # behavior and stderr parity.
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            shas, _ = atif_to_s3.hash_candidates(index, self.base,
                                                 session_id="")
        self.assertEqual(set(shas), {SID_1})           # same pool as no filter
        self.assertIn(SID_2, err.getvalue())           # same warning too

        # all_groups=True (dataset path): EVERY session across EVERY group is
        # PRESENT in shas with sha-or-None -- unreadable/missing -> None, never
        # omitted; paths still holds readable artifacts only.
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            shas, paths = atif_to_s3.hash_candidates(index, self.base,
                                                     all_groups=True)
        self.assertEqual(set(shas), {SID_1, SID_2, SID_UNGROUPED})
        self.assertEqual(shas[SID_1], sha_1)
        self.assertIsNone(shas[SID_2])
        self.assertEqual(shas[SID_UNGROUPED], sha_3)
        self.assertEqual(set(paths), {SID_1, SID_UNGROUPED})


class TestSyncSessions(_ShellBase):
    """sync_sessions -- the upload loop extracted from main(), tested ABOVE the
    aws-CLI boundary: `upload_one` / `preflight_sso` / `save_ledger` are stubbed
    with unittest.mock.patch on the atif_to_s3 module namespace -- a sanctioned
    deviation from this file's documented PATH-fake-`aws` discipline. The
    fake-`aws` tests above keep policing `upload_one` itself at the subprocess
    boundary; what THIS seam owes its callers (the CLI's main() and the viewer's
    POST /api/sync) is the per-session results contract and the
    upload-before-ledger-write ordering, which live entirely above that
    boundary."""

    def _seed_batch(self, sids):
        entries = [_seed_session(self.base, s, _mk_traj(s)) for s in sids]
        paths = {s: _artifact_path(self.base, s) for s in sids}
        shas = {s: _sha_of(paths[s]) for s in sids}
        return entries, paths, shas

    def _run_sync(self, entries, paths, shas, ledger_path):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            final_ledger, results = atif_to_s3.sync_sessions(
                entries, paths=paths, shas=shas, identity=IDENTITY,
                bucket="test-bucket", profile="test-profile",
                ledger={}, ledger_path=ledger_path)
        # SILENT: no CLI lines may leak (a server POST shares this stdio).
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(err.getvalue(), "")
        return final_ledger, results

    def test_sync_sessions_results_and_ledger_order(self):
        sids = [SID_1, SID_2, SID_3]
        entries, paths, shas = self._seed_batch(sids)
        keys = {s: atif_to_s3.plan_upload(_mk_traj(s), e, IDENTITY)["key"]
                for s, e in zip(sids, entries)}

        # --- All-success: per-session result dicts in order; the ledger is
        # written AFTER the upload and saved PER session (each upload sees
        # exactly the PRIOR sessions' records on disk).
        ledger_path = os.path.join(self.tmp, "ledger-ok.json")
        ledger_keys_at_upload = []

        def fake_upload(key, body_path, metadata, *, bucket, profile):
            ledger_keys_at_upload.append(set(atif_to_s3.load_ledger(ledger_path)))
            return "etag-" + metadata["session-id"]

        with mock.patch.object(atif_to_s3, "upload_one",
                               side_effect=fake_upload) as up, \
             mock.patch.object(atif_to_s3, "preflight_sso") as pre:
            final_ledger, results = self._run_sync(entries, paths, shas,
                                                   ledger_path)
        self.assertEqual(
            results,
            [{"session_id": s, "ok": True, "s3_key": keys[s],
              "etag": "etag-" + s} for s in sids])
        self.assertEqual(ledger_keys_at_upload,
                         [set(), {SID_1}, {SID_1, SID_2}])
        # The uploaded body is the hashed artifact path; config is threaded.
        self.assertEqual([c.args[1] for c in up.call_args_list],
                         [paths[s] for s in sids])
        self.assertEqual(up.call_args_list[0].kwargs,
                         {"bucket": "test-bucket", "profile": "test-profile"})
        pre.assert_not_called()        # preflight is the CALLER's job
        with open(ledger_path) as fh:
            on_disk = json.load(fh)
        self.assertEqual(final_ledger, on_disk)
        self.assertEqual(set(on_disk), set(sids))
        for s in sids:
            self.assertEqual(on_disk[s]["s3_key"], keys[s])
            self.assertEqual(on_disk[s]["artifact_sha256"], shas[s])

        # --- Upload failure mid-batch: ok False (error = str(e), which main()
        # renders verbatim); later sessions still processed; the ledger never
        # records the failed session.
        ledger_path = os.path.join(self.tmp, "ledger-fail.json")

        def fail_second(key, body_path, metadata, *, bucket, profile):
            if metadata["session-id"] == SID_2:
                raise RuntimeError("simulated upload failure")
            return "etag-x"

        with mock.patch.object(atif_to_s3, "upload_one",
                               side_effect=fail_second) as up:
            _, results = self._run_sync(entries, paths, shas, ledger_path)
        self.assertEqual(up.call_count, 3)             # batch never aborts
        self.assertEqual([r["ok"] for r in results], [True, False, True])
        self.assertEqual(results[1],
                         {"session_id": SID_2, "ok": False,
                          "error": "simulated upload failure"})
        with open(ledger_path) as fh:
            on_disk = json.load(fh)
        self.assertEqual(set(on_disk), {SID_1, SID_3})

        # --- save_ledger raising AFTER a successful upload: ok False with a
        # ledger-mentioning error; the batch continues; the failed session is
        # not durably recorded (later saves must not resurrect it).
        ledger_path = os.path.join(self.tmp, "ledger-torn.json")
        real_save = atif_to_s3.save_ledger
        state = {"calls": 0}

        def flaky_save(path, ledger):
            state["calls"] += 1
            if state["calls"] == 1:
                raise OSError("disk full")
            real_save(path, ledger)

        with mock.patch.object(atif_to_s3, "upload_one",
                               return_value="etag-x") as up, \
             mock.patch.object(atif_to_s3, "save_ledger",
                               side_effect=flaky_save):
            final_ledger, results = self._run_sync(entries, paths, shas,
                                                   ledger_path)
        self.assertEqual(up.call_count, 3)             # later sessions ran
        self.assertFalse(results[0]["ok"])
        self.assertEqual(results[0]["session_id"], SID_1)
        self.assertIn("ledger", results[0]["error"].lower())
        self.assertEqual([r["ok"] for r in results[1:]], [True, True])
        with open(ledger_path) as fh:
            on_disk = json.load(fh)
        self.assertEqual(set(on_disk), {SID_2, SID_3})
        self.assertEqual(final_ledger, on_disk)


class TestMainCliParity(_ShellBase):
    """Byte-level CLI parity pin for main() -- EXPECTED GREEN before AND after
    the seam extraction (a regression pin, not a red seam test): the exact
    stdout/stderr bytes and exit codes of --dry-run, --scan, and the upload
    modes must not change when main() becomes a composition of
    hash_candidates/select_sessions/sync_sessions. Drives the real fake-`aws`
    boundary like the other TestMain* classes (no mocks)."""

    def test_main_cli_parity(self):
        e1 = _seed_session(
            self.base, SID_1, _mk_traj(SID_1, message="contact dev@example.com"))
        e2 = _seed_session(self.base, SID_2, _mk_traj(SID_2))
        _write_index(self.base, [e1, e2])
        k1 = atif_to_s3.plan_upload({}, e1, IDENTITY)["key"]
        k2 = atif_to_s3.plan_upload({}, e2, IDENTITY)["key"]

        # --dry-run: exactly one key per line, index order, nothing else.
        rc, out, err = self._run_main(["--dry-run"])
        self.assertEqual(rc, 0)
        self.assertEqual(out, f"{k1}\n{k2}\n")
        self.assertEqual(err, "")

        # --scan: exactly the indent-2 JSON aggregate plus a newline.
        rc, out, err = self._run_main(["--scan"])
        self.assertEqual(rc, 0)
        expected = {"by_type": {"Email address": 1},
                    "per_session": {SID_1: {"Email address": 1}, SID_2: {}}}
        self.assertEqual(out, json.dumps(expected, indent=2) + "\n")
        self.assertEqual(err, "")

        # Upload mode, all-success: one OK line per session, index order.
        rc, out, err = self._run_main([])
        self.assertEqual(rc, 0)
        self.assertEqual(out, f"OK  {k1}  (etag abc123)\n"
                              f"OK  {k2}  (etag abc123)\n")
        self.assertEqual(err, "")

        # Upload mode, failure: exit 1, no OK line, the exact stderr message.
        e3 = _seed_session(self.base, SID_3, _mk_traj(SID_3))
        _write_index(self.base, [e1, e2, e3])
        k3 = atif_to_s3.plan_upload({}, e3, IDENTITY)["key"]
        os.environ["FAKE_AWS_PUT_FAIL_KEYS"] = SID_3
        rc, out, err = self._run_main([])
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")
        self.assertEqual(
            err,
            f"error: failed to sync {SID_3}: s3 put-object failed for {k3}: "
            f"An error occurred (InternalError) when calling the PutObject "
            f"operation: simulated transient failure\n")


# ===========================================================================
# Optional real-AWS integration test (Task 7). Gated so it SKIPS cleanly when no
# live SSO session is available -- it never fails/errors unauthenticated. Mirrors
# the skipUnless gating pattern in test_capture_atif_to_opik.py.
# ===========================================================================

_S3_ITEST_PROFILE = os.environ.get("DRVR_S3_ITEST_PROFILE", "dev-admin")
_S3_ITEST_BUCKET = os.environ.get("DRVR_S3_ITEST_BUCKET", "trajectory-uploads-1ddbee")


def _real_s3_available() -> bool:
    """True only when explicitly opted in (DRVR_S3_ITEST=1) AND a real `aws sts
    get-caller-identity` succeeds for the profile -- so an unauthenticated run
    SKIPS rather than erroring."""
    if os.environ.get("DRVR_S3_ITEST") != "1":
        return False
    aws = shutil.which("aws")
    if not aws:
        return False
    try:
        res = subprocess.run(
            [aws, "sts", "get-caller-identity", "--profile", _S3_ITEST_PROFILE],
            capture_output=True, text=True, timeout=30)
    except Exception:
        return False
    return res.returncode == 0


@unittest.skipUnless(
    _real_s3_available(),
    "real S3/SSO not available (set DRVR_S3_ITEST=1 after `aws sso login "
    "--profile dev-admin`)")
class TestEndToEndRealS3(unittest.TestCase):
    """A real PUT + head_object size check against the live bucket, then cleanup.
    No real identity is used (synthetic org/principal); ETag is NOT asserted equal
    to the local md5 because SSE-KMS ETags are opaque."""

    def test_end_to_end_real_s3(self):
        tmp = tempfile.mkdtemp(prefix="drvr-s3-e2e-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        body = os.path.join(tmp, "trajectory.redacted.json")
        payload = json.dumps(
            {"schema_version": "ATIF-v1.7", "session_id": "itest",
             "note": "capture-sync integration test object; safe to delete"}
        ).encode()
        with open(body, "wb") as fh:
            fh.write(payload)

        sid = "itest-" + uuid.uuid4().hex
        key = atif_to_s3.render_s3_key(
            org_id="itest-org", principal_id="auth0|itest", principal_type="user",
            codebase="itest-codebase", branch="itest-branch", session_id=sid)
        metadata = atif_to_s3.build_metadata(
            session_id=sid, branch="itest-branch", cwd="/x/itest-codebase",
            capture_kind="branch")

        etag = atif_to_s3.upload_one(key, body, metadata,
                                     bucket=_S3_ITEST_BUCKET,
                                     profile=_S3_ITEST_PROFILE)
        self.assertTrue(etag)  # opaque under SSE-KMS -- presence only, not == md5.
        try:
            head = subprocess.run(
                ["aws", "s3api", "head-object", "--bucket", _S3_ITEST_BUCKET,
                 "--key", key, "--profile", _S3_ITEST_PROFILE, "--output", "json"],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(head.returncode, 0, head.stderr)
            self.assertEqual(json.loads(head.stdout)["ContentLength"], len(payload))
        finally:
            subprocess.run(
                ["aws", "s3api", "delete-object", "--bucket", _S3_ITEST_BUCKET,
                 "--key", key, "--profile", _S3_ITEST_PROFILE],
                capture_output=True, text=True, timeout=60)


if __name__ == "__main__":
    unittest.main()
