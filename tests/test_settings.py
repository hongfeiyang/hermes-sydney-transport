"""Deployment settings, including the shared-cache seam."""

import unittest
from pathlib import Path

from hermes_sydney_transport.bootstrap.settings import Settings
from hermes_sydney_transport.models.errors import DomainError


class SettingsTests(unittest.TestCase):
    def test_missing_api_key_is_a_domain_error(self) -> None:
        with self.assertRaises(DomainError):
            Settings.from_environment({})

    def test_cache_defaults_to_hermes_home(self) -> None:
        """Unset override keeps the historical path, byte for byte."""
        s = Settings.from_environment(
            {"TFNSW_API_KEY": "k", "HERMES_HOME": "/opt/data"}
        )
        self.assertEqual(s.cache_directory, Path("/opt/data/cache/sydney-transport"))

    def test_cache_override_wins_over_hermes_home(self) -> None:
        """The reason this seam exists.

        Under a profile multiplexer HERMES_HOME is whichever profile the gateway
        routed the turn to, so a HERMES_HOME-relative cache gives every profile
        its own ~540 MB copy of a feed that describes the network, not the agent.
        """
        s = Settings.from_environment(
            {
                "TFNSW_API_KEY": "k",
                "HERMES_HOME": "/opt/data/profiles/frontdesk",
                "SYDNEY_TRANSPORT_CACHE_DIR": "/opt/data/cache/sydney-transport",
            }
        )
        self.assertEqual(s.cache_directory, Path("/opt/data/cache/sydney-transport"))

    def test_blank_override_is_ignored(self) -> None:
        s = Settings.from_environment(
            {
                "TFNSW_API_KEY": "k",
                "HERMES_HOME": "/opt/data",
                "SYDNEY_TRANSPORT_CACHE_DIR": "   ",
            }
        )
        self.assertEqual(s.cache_directory, Path("/opt/data/cache/sydney-transport"))

    def test_every_profile_resolves_to_one_directory_with_the_override(self) -> None:
        """The property that matters: N profiles, one cache."""
        shared = "/opt/data/cache/sydney-transport"
        homes = [
            "/opt/data",
            "/opt/data/profiles/system-admin",
            "/opt/data/profiles/work",
            "/opt/data/profiles/frontdesk",
            "/opt/data/profiles/kean-family",
        ]
        resolved = {
            Settings.from_environment(
                {
                    "TFNSW_API_KEY": "k",
                    "HERMES_HOME": home,
                    "SYDNEY_TRANSPORT_CACHE_DIR": shared,
                }
            ).cache_directory
            for home in homes
        }
        self.assertEqual(resolved, {Path(shared)})


if __name__ == "__main__":
    unittest.main()
