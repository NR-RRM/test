"""GUI 없이 실행: python -m autosub.cli 영상.mp4 [영상2 ...]"""
from __future__ import annotations

import sys
from pathlib import Path

from .config import load_config
from .pipeline import run
from .util import CancelToken


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cfg = load_config()
    last = [-1]

    def progress(frac, msg):
        if frac is not None and int(frac * 100) != last[0]:
            last[0] = int(frac * 100)
            print(f"  [{last[0]:3d}%] {msg or ''}", flush=True)

    rc = 0
    for f in argv:
        print(f"== {f}")
        try:
            srt, rev = run(Path(f), cfg, lambda s: print("   " + s, flush=True), progress, CancelToken())
            print(f"-> {srt}\n-> {rev}")
        except Exception as e:  # noqa: BLE001
            print(f"!! 실패: {e}")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
