from __future__ import annotations

import os
import subprocess
import threading
from typing import Callable, Optional

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class Cancelled(Exception):
    pass


class CancelToken:
    def __init__(self):
        self._ev = threading.Event()
        self.proc: Optional[subprocess.Popen] = None

    def cancel(self):
        self._ev.set()
        p = self.proc
        if p and p.poll() is None:
            try:
                p.kill()
            except OSError:
                pass

    @property
    def cancelled(self) -> bool:
        return self._ev.is_set()

    def check(self):
        if self._ev.is_set():
            raise Cancelled()


def run_logged(cmd: list[str], log: Callable[[str], None], cancel: CancelToken,
               on_line: Optional[Callable[[str], None]] = None) -> int:
    """하위 프로세스를 실행하며 stdout+stderr를 한 줄씩 전달한다 (GUI 하트비트용)."""
    log("$ " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
    cancel.proc = proc
    try:
        assert proc.stdout is not None
        buf = b""
        while True:
            chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096)
            if not chunk:
                break
            buf += chunk
            # ffmpeg는 \r로 진행상황을 갱신하므로 \r도 줄 구분자로 취급
            parts = buf.replace(b"\r", b"\n").split(b"\n")
            buf = parts.pop()
            for raw in parts:
                line = raw.decode("utf-8", "replace").rstrip()
                if not line:
                    continue
                if on_line:
                    on_line(line)
                else:
                    log(line)
        if buf.strip():
            line = buf.decode("utf-8", "replace").rstrip()
            (on_line or log)(line)
        rc = proc.wait()
    finally:
        cancel.proc = None
    if cancel.cancelled:
        raise Cancelled()
    return rc
