"""GUI 없이 실행:
  python -m autosub.cli [--mode both|whisper|parakeet] [--out-dir 폴더] [--config 설정.json] 영상.mp4 [영상2 ...]

진행률은 "  [ 37%] 단계" 형식으로 한 줄씩 출력된다 (안드로이드 알림 스크립트가 이 형식을 읽는다).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .pipeline import run
from .util import CancelToken


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="autosub.cli", description="영어 영상 → 영어 SRT")
    ap.add_argument("videos", nargs="*")
    ap.add_argument("--mode", choices=["both", "whisper", "parakeet"],
                    help="엔진: both(교차검증) / whisper / parakeet. 생략하면 설정 파일 값")
    ap.add_argument("--out-dir", help="자막 저장 폴더 (기본: 영상과 같은 폴더)")
    ap.add_argument("--config", help="설정 파일 (기본: config.json 또는 AUTOSUB_CONFIG)")
    ap.add_argument("--threads", type=int, help="Whisper/Parakeet 스레드 수")
    args = ap.parse_args(argv)
    if not args.videos:
        print(__doc__)
        return 2
    cfg = load_config(Path(args.config) if args.config else None)
    if args.mode:
        cfg.engine_mode = args.mode
    if args.threads:
        cfg.whisper_threads = cfg.parakeet_threads = args.threads
    last = [-1]

    def progress(frac, msg):
        if frac is not None and int(frac * 100) != last[0]:
            last[0] = int(frac * 100)
            print(f"  [{last[0]:3d}%] {msg or ''}", flush=True)

    rc = 0
    for f in args.videos:
        print(f"== {f}", flush=True)
        last[0] = -1
        try:
            srt, rev = run(Path(f), cfg, lambda s: print("   " + s, flush=True), progress, CancelToken(),
                           out_dir=Path(args.out_dir) if args.out_dir else None)
            print(f"-> {srt}\n-> {rev}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"!! 실패: {e}", flush=True)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
