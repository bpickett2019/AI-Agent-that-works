import json
import unittest
from unittest.mock import patch

from steel_resources import GIB, check_capacity, validate_capacity


class ResourceAdmissionTests(unittest.TestCase):
    def test_failed_local_docker_vm_is_denied_before_browser_creation(self):
        with self.assertRaisesRegex(RuntimeError, 'resource admission denied'):
            validate_capacity({'MemTotal': 8217473024, 'NCPU': 10}, 'MemAvailable: 50000 kB')
        with patch('steel_resources.subprocess.run') as run:
            run.return_value.stdout = json.dumps({'MemTotal': 8217473024, 'NCPU': 10})
            with self.assertRaisesRegex(RuntimeError, 'undersized runtime'):
                check_capacity('pinned-image')
            self.assertEqual(run.call_count, 1)

    def test_azure_capacity_covers_all_three_worker_caps_plus_reserve(self):
        r = validate_capacity({'MemTotal': 33598742528, 'NCPU': 8}, 'MemAvailable: 30000000 kB')
        self.assertEqual(r['workerMemoryBytes'], 6 * GIB)
        self.assertEqual(r['workerShmBytes'], 2 * GIB)
        self.assertGreater(r['dockerMemoryBytes'], 3 * r['workerMemoryBytes'] + 2 * GIB)

    def test_busy_or_unobservable_docker_host_fails_closed(self):
        for meminfo in ('MemAvailable: 1000000 kB', 'MemTotal: 33000000 kB'):
            with self.assertRaisesRegex(RuntimeError, 'MemAvailable'):
                validate_capacity({'MemTotal': 32 * GIB, 'NCPU': 8}, meminfo)

    def test_shared_memory_setting_has_not_been_increased(self):
        from pathlib import Path
        text = (Path(__file__).resolve().parents[1] / 'docker-compose.yml').read_text()
        self.assertIn('shm_size: "2gb"', text)
        self.assertIn('mem_limit: "6gb"', text)
