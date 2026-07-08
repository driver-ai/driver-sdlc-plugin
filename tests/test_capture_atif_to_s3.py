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

import hashlib
import json
import sys
import unittest

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


if __name__ == "__main__":
    unittest.main()
