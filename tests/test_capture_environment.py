"""Unit tests for the pure `environment.build_environment` core (Contract C).

Pure-core tests: import `environment` ONLY. No logs2atif, no mocks, no I/O. Stdlib
`unittest` only. `build_environment` is a pure transform of the facts handed to
it, so these tests exercise it directly with plain kwargs.
"""
import sys
import unittest

from conftest import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts" / "capture"))  # before importing the core
import environment


FULL_FACTS = dict(
    codebase_url="https://github.com/driver-ai/driver",
    cwd="/Users/dev/driver",
    branch="eric/agent-session-capture",
    commit_start="aaaa1111",
    commit_end="bbbb2222",
    mcp_endpoint="https://app.driverai.com/mcp",
    mcp_version="1.7.0",
)


class TestBuildEnvironment(unittest.TestCase):
    def test_full_facts_returns_each_value_plus_mcp_env(self):
        """All 7 kwargs present -> a dict with each fact key + derived mcp_env (Contract C)."""
        env = environment.build_environment(**FULL_FACTS)
        for key, val in FULL_FACTS.items():
            self.assertIn(key, env)
            self.assertEqual(env[key], val)
        # app.driverai.com endpoint -> prod
        self.assertEqual(env["mcp_env"], "prod")

    def test_absent_facts_are_missing_keys_not_null(self):
        """None facts -> the key is ABSENT from the result, not present-with-None (L2)."""
        facts = dict(FULL_FACTS)
        facts["commit_start"] = None
        facts["mcp_version"] = None
        env = environment.build_environment(**facts)
        self.assertNotIn("commit_start", env)
        self.assertNotIn("mcp_version", env)
        # surviving facts remain present with their values
        self.assertEqual(env["branch"], FULL_FACTS["branch"])
        self.assertEqual(env["commit_end"], FULL_FACTS["commit_end"])

    def test_mcp_env_prod_for_app_driverai_endpoint(self):
        """mcp_endpoint containing app.driverai.com -> mcp_env == 'prod'."""
        facts = dict(FULL_FACTS, mcp_endpoint="https://app.driverai.com/mcp")
        env = environment.build_environment(**facts)
        self.assertEqual(env["mcp_env"], "prod")
        self.assertEqual(env["mcp_endpoint"], "https://app.driverai.com/mcp")

    def test_mcp_env_dev_for_other_non_none_endpoint(self):
        """Any other non-None mcp_endpoint -> mcp_env == 'dev'."""
        facts = dict(FULL_FACTS, mcp_endpoint="http://localhost:8080/mcp")
        env = environment.build_environment(**facts)
        self.assertEqual(env["mcp_env"], "dev")
        self.assertEqual(env["mcp_endpoint"], "http://localhost:8080/mcp")

    def test_mcp_env_absent_when_endpoint_none(self):
        """mcp_endpoint=None -> mcp_env key is ABSENT (and mcp_endpoint absent too, L2)."""
        facts = dict(FULL_FACTS, mcp_endpoint=None)
        env = environment.build_environment(**facts)
        self.assertNotIn("mcp_env", env)
        self.assertNotIn("mcp_endpoint", env)

    def test_no_facts_returns_empty_dict(self):
        """Every kwarg None -> returns {} (empty dict) (M4)."""
        env = environment.build_environment(
            codebase_url=None, cwd=None, branch=None, commit_start=None,
            commit_end=None, mcp_endpoint=None, mcp_version=None,
        )
        self.assertEqual(env, {})


if __name__ == "__main__":
    unittest.main()
