import subprocess
import sys
import unittest
import unittest.mock
import uuid
from pathlib import Path

from desktop import app, single_instance


class SingleInstanceTests(unittest.TestCase):
    def test_lock_rejects_second_process_and_releases_on_exit(self):
        name = "Global\\QianNiuAutoListingTest-" + uuid.uuid4().hex
        script = (
            "import sys; from desktop.single_instance import acquire; "
            "lock = acquire(sys.argv[1]); "
            "print('acquired' if lock else 'duplicate'); "
            "lock.close() if lock else None"
        )

        def probe():
            result = subprocess.run(
                [sys.executable, "-c", script, name],
                cwd=Path(__file__).resolve().parent,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            return result.stdout.strip()

        lock = single_instance.acquire(name)
        self.assertIsNotNone(lock)
        try:
            self.assertEqual(probe(), "duplicate")
        finally:
            lock.close()
        self.assertEqual(probe(), "acquired")

    def test_second_start_exits_before_preflight_or_cleanup(self):
        with unittest.mock.patch.object(app, "acquire", return_value=None) as acquire, \
             unittest.mock.patch.object(app, "activate_existing_window") as activate, \
             unittest.mock.patch.object(app, "configure_environ") as configure, \
             unittest.mock.patch.object(app, "_runtime_preflight") as preflight, \
             unittest.mock.patch.object(app, "_cleanup_automation_chrome") as cleanup:
            self.assertEqual(app.main([]), 0)
        acquire.assert_called_once_with()
        activate.assert_called_once_with()
        configure.assert_not_called()
        preflight.assert_not_called()
        cleanup.assert_not_called()

    def test_self_test_does_not_take_desktop_lock(self):
        with unittest.mock.patch.object(app, "acquire") as acquire, \
             unittest.mock.patch.object(app, "configure_environ"), \
             unittest.mock.patch.object(app, "_runtime_preflight", return_value=[]) as preflight, \
             unittest.mock.patch.object(app, "_write_self_test"):
            self.assertEqual(app.main(["--self-test"]), 0)
        acquire.assert_not_called()
        preflight.assert_called_once()


if __name__ == "__main__":
    unittest.main()
