"""Control the board executable through a separate, asynchronous SSH session."""

from __future__ import annotations

import re
import shutil

from wolfeye.qt import QObject, QProcess, QTimer, Signal


class EmWolfProcess(QObject):
    state_changed = Signal(str)
    log = Signal(str)

    _READY = b"\x1eDEVOLF_EMWOLF_START\x1f"
    _COMMAND = (
        "if pidof EmWolf >/dev/null 2>&1; then "
        "printf 'EmWolf is already running; stop it in its original terminal first.\\n'; "
        "exit 1; fi; "
        "cd /home/FC22 && stty intr '^C' isig -echo && "
        "printf '\\036DEVOLF_EMWOLF_START\\037\\n' && exec ./EmWolf"
    )

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.state = "stopped"
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_output)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self._output = b""
        self._stop_timer = QTimer(self)
        self._stop_timer.setSingleShot(True)
        self._stop_timer.setInterval(10000)
        self._stop_timer.timeout.connect(self._stop_timeout)

    def _set_state(self, state: str) -> None:
        self.state = state
        self.state_changed.emit(state)

    def start(self, host: str) -> None:
        if self.state != "stopped":
            return
        host = host.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.:\[\]%-]+", host):
            self.log.emit("EmWolf SSH error: enter a valid board Host.")
            return
        ssh = shutil.which("ssh")
        if ssh is None:
            self.log.emit("EmWolf SSH error: OpenSSH client (ssh.exe) is not installed.")
            return
        self._output = b""
        self._set_state("starting")
        self.log.emit(f"EmWolf SSH: starting /home/FC22/EmWolf on root@{host}.")
        self.process.start(ssh, [
            "-tt", "-e", "none",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=10",
            "-o", "ServerAliveInterval=5",
            "-o", "ServerAliveCountMax=3",
            f"root@{host}", self._COMMAND,
        ])

    def stop(self) -> None:
        if self.state != "running":
            return
        # The remote PTY interprets ETX as SIGINT, just like terminal Ctrl+C.
        if self.process.write(b"\x03") < 0:
            self.log.emit("EmWolf SSH error: could not send Ctrl+C.")
            return
        self._set_state("stopping")
        self.log.emit("EmWolf SSH: Ctrl+C sent; waiting for EmWolf to exit.")
        self._stop_timer.start()

    def _read_output(self) -> None:
        self._output += bytes(self.process.readAllStandardOutput())
        while b"\n" in self._output:
            line, self._output = self._output.split(b"\n", 1)
            self._handle_line(line)
        # Do not retain unbounded output when a program writes without newlines.
        if len(self._output) > 8192:
            self._handle_line(self._output)
            self._output = b""

    def _handle_line(self, line: bytes) -> None:
        if self._READY in line:
            line = line.replace(self._READY, b"")
            if self.state == "starting":
                self._set_state("running")
                self.log.emit("EmWolf SSH: board command launched.")
        message = line.decode("utf-8", errors="replace").strip()
        if message:
            self.log.emit(f"EmWolf SSH: {message}")

    def _finished(self, exit_code: int, _exit_status) -> None:
        self._stop_timer.stop()
        self._read_output()
        if self._output:
            self._handle_line(self._output)
            self._output = b""
        stopping = self.state == "stopping"
        self._set_state("stopped")
        # 255 means SSH itself failed; do not claim a confirmed remote stop.
        if stopping and exit_code in (0, 130):
            self.log.emit("EmWolf SSH: EmWolf stopped.")
        else:
            self.log.emit(f"EmWolf SSH: session ended (exit {exit_code}).")
        if exit_code == 255:
            self.log.emit(
                "EmWolf SSH: check board/network access and SSH key login for root. "
                "Remote process state is unknown."
            )

    def _error(self, error) -> None:
        self.log.emit(f"EmWolf SSH error: {self.process.errorString()}")
        if error == QProcess.ProcessError.FailedToStart:
            self._set_state("stopped")

    def _stop_timeout(self) -> None:
        if self.state != "stopping":
            return
        self.log.emit("EmWolf SSH: exit not confirmed; you can retry Stop EmWolf.")
        self._set_state("running")

    def shutdown(self) -> None:
        """Release local SSH resources without sending a remote stop command."""
        self._stop_timer.stop()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1000)
