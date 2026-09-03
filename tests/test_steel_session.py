import unittest
from unittest.mock import patch

import steel_session


class SteelSessionRecoveryTests(unittest.TestCase):
    @patch.object(steel_session, 'recover_container_profile_locks')
    @patch.object(steel_session, 'status', return_value={'running': True})
    @patch.object(steel_session, 'container_running', return_value=True)
    def test_healthy_browser_is_never_restarted(self, _container, _status, recover):
        result = steel_session.ensure()

        self.assertTrue(result['running'])
        recover.assert_not_called()

    @patch.object(steel_session.time, 'sleep')
    @patch.object(steel_session, 'recover_container_profile_locks')
    @patch.object(steel_session, 'container_running', return_value=True)
    def test_stale_container_is_recovered_after_cdp_grace_period(
        self, _container, recover, _sleep
    ):
        unavailable = {'running': False}
        healthy = {'running': True, 'browser': 'Chrome/test'}
        with patch.object(
            steel_session, 'status', side_effect=[unavailable] * 21 + [healthy]
        ):
            result = steel_session.ensure()

        self.assertEqual(result, healthy)
        recover.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
