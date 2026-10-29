"""Exercise asynchronous SSH ownership and Ctrl+C without running board hardware."""

from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from wolfeye.qt import QApplication, QProcess
from wolfeye.services.emwolf_process import EmWolfProcess
from wolfeye.widgets.emwolf_page import EmWolfPage


class EmWolfProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.controller = EmWolfProcess()
        self.logs = []
        self.controller.log.connect(self.logs.append)
        self.addCleanup(self.controller.shutdown)

    def wait_until(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertTrue(predicate(), self.logs)

    def run_fake_ssh(self, script):
        # Keep QProcess and its real asynchronous I/O; substitute only the server.
        original_start = self.controller.process.start

        def launch(_executable, _arguments):
            original_start(sys.executable, ["-u", "-c", script])

        with patch("wolfeye.services.emwolf_process.shutil.which", return_value=sys.executable), \
                patch.object(self.controller.process, "start", side_effect=launch) as start:
            self.controller.start("192.168.137.1")
        return start

    def test_launch_stop_and_restart_use_ssh_pty_and_actual_ctrl_c_byte(self):
        server = (
            "import sys, time\n"
            "sys.stdout.buffer.write(b'\\x1eDEVOLF_EM'); sys.stdout.buffer.flush()\n"
            "time.sleep(0.05)\n"
            "sys.stdout.buffer.write(b'WOLF_START\\x1f\\r\\n'); sys.stdout.buffer.flush()\n"
            "received = sys.stdin.buffer.read(1)\n"
            "sys.exit(130 if received == b'\\x03' else 4)\n"
        )
        for _ in range(2):
            start = self.run_fake_ssh(server)
            self.assertEqual(self.controller.state, "starting")
            args = start.call_args.args[1]
            self.assertIn("-tt", args)
            self.assertIn("root@192.168.137.1", args)
            self.assertIn("cd /home/FC22", args[-1])
            self.assertIn("exec ./EmWolf", args[-1])
            self.wait_until(lambda: self.controller.state == "running")
            with patch.object(self.controller.process, "start") as duplicate:
                self.controller.start("another-board")
                duplicate.assert_not_called()
            self.controller.stop()
            self.assertEqual(self.controller.state, "stopping")
            self.wait_until(lambda: self.controller.state == "stopped")
        self.assertEqual(self.logs.count("EmWolf SSH: EmWolf stopped."), 2)

    def test_authentication_failure_reports_error_and_allows_retry(self):
        self.run_fake_ssh("import sys; print('Permission denied (publickey).'); sys.exit(255)")
        self.wait_until(lambda: self.controller.state == "stopped")
        self.assertTrue(any("Permission denied" in line for line in self.logs))
        self.assertTrue(any("state is unknown" in line for line in self.logs))
        self.assertNotIn("EmWolf SSH: EmWolf stopped.", self.logs)

    def test_missing_client_failed_start_and_invalid_host_recover(self):
        with patch("wolfeye.services.emwolf_process.shutil.which", return_value=None):
            self.controller.start("192.168.137.1")
        self.assertEqual(self.controller.state, "stopped")
        with patch.object(self.controller.process, "start") as start:
            self.controller.start("host; shutdown")
            start.assert_not_called()
        with patch("wolfeye.services.emwolf_process.shutil.which", return_value="missing-devolf-ssh"):
            self.controller.start("192.168.137.1")
        self.wait_until(lambda: self.controller.state == "stopped")
        self.assertTrue(any("SSH error" in line for line in self.logs))

    def test_shutdown_releases_client_without_ctrl_c(self):
        self.run_fake_ssh(
            "import sys; print('\\x1eDEVOLF_EMWOLF_START\\x1f', flush=True); "
            "sys.stdin.buffer.read(1)"
        )
        self.wait_until(lambda: self.controller.state == "running")
        with patch.object(self.controller.process, "write") as write:
            self.controller.shutdown()
            write.assert_not_called()
        self.assertEqual(self.controller.process.state(), QProcess.ProcessState.NotRunning)

    def test_stop_timeout_does_not_claim_exit(self):
        self.run_fake_ssh(
            "import sys, time; print('\\x1eDEVOLF_EMWOLF_START\\x1f', flush=True); time.sleep(30)"
        )
        self.wait_until(lambda: self.controller.state == "running")
        self.controller.stop()
        self.controller._stop_timer.stop()
        self.controller._stop_timeout()
        self.assertEqual(self.controller.state, "running")
        self.assertNotIn("EmWolf SSH: EmWolf stopped.", self.logs)

    def test_buttons_control_process_and_test_independently(self):
        page = EmWolfPage()
        self.addCleanup(page.shutdown)
        page.host.setText("192.168.137.42")
        with patch.object(page.emwolf_process, "start") as start:
            page.start_emwolf_button.click()
            start.assert_called_once_with("192.168.137.42")
        page.emwolf_process._set_state("running")
        with patch.object(page.emwolf_process.process, "write", return_value=1) as write, \
                patch.object(page.connection, "stop_outputs") as stop_test:
            page.stop_emwolf_button.click()
            write.assert_called_once_with(b"\x03")
            stop_test.assert_not_called()
            page.stop_button.setEnabled(True)
            page.stop_button.click()
            stop_test.assert_called_once_with()
            self.assertEqual(write.call_count, 1)


if __name__ == "__main__":
    unittest.main()
