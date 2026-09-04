import os
import unittest
from unittest.mock import patch

import run_with_keyvault


class KeyVaultRuntimeTests(unittest.TestCase):
    def test_production_loads_all_required_secrets(self):
        with patch.dict(os.environ, {"CVENT_ENV": "production"}, clear=True):
            self.assertEqual(run_with_keyvault.selected_secrets(), run_with_keyvault.SECRET_ENV_MAP)

    def test_explicit_staging_tunnel_fallback_loads_only_anthropic(self):
        environment = {
            "CVENT_ENV": "development",
            "CVENT_STAGING_TUNNEL_FALLBACK": "1",
        }
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(
                run_with_keyvault.selected_secrets(),
                {"anthropic-api-key": "ANTHROPIC_API_KEY"},
            )

    def test_development_cannot_use_keyvault_without_explicit_fallback(self):
        with patch.dict(os.environ, {"CVENT_ENV": "development"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "explicit staging tunnel fallback"):
                run_with_keyvault.selected_secrets()


if __name__ == "__main__":
    unittest.main()
