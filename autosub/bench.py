"""엔진 모드 벤치마크 (안드로이드 기본 모드 결정용, PC/리눅스에서도 동작).

  python -m autosub.bench 영상.mkv [--start 600] [--seconds 300] [--out-dir 폴더] [--threads 6]

영상의 일부(기본: 10분 지점부터 5분)를 잘라
  A) Parakeet 단독   B) Whisper 단독   C) 둘 다(교차검증)
세 가지 자막을 만들고 처리 시간·속도(실시간 대비)·결과 차이를 보고서로 남긴다.
Whisper와 Parakeet은 한 번씩만 돌리고, C는 두 결과를 병합해 만든다
(C의 처리 시간 = A + B + 병합. 실제 파이프라인도 두 엔진을 순서대로 돌리므로 같다).
"""
from __future__ import annotations

import argparse
import copy
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from difflib import SequenceMatcher
from pathlib import Path

from . import merge as merge_mod
from . import parakeet_engine, whisper_engine
from .audio import SR, extract_audio, list_audio_tracks, load_wav, pick_audio_track
from .config import Config, load_config
from .model import fmt_ts
from .postprocess import build_cues
from .util import CancelToken
from .writers import write_review, write_srt


def _norm_words(words) -> list[str]:
    return [x for x in (re.sub(r"[^a-z0-9']", "", w.text.lower()) for w in words) if x]


def _agree(a, b) -> float:
    return SequenceMatcher(None, _norm_words(a), _norm_words(b), autojunk=False).ratio()


def _cpu_info() -> str:
    try:
        txt = Path("/proc/cpuinfo").read_text(errors="replace")
        feats = re.search(r"^Features\s*:\s*(.*)$", txt, re.M)
        flags = set((feats.group(1) if feats else "").split())
        have = [f for f in ("asimddp", "i8mm", "fphp", "sve", "bf16") if f in flags]
        n = len(re.findall(r"^processor\s*:", txt, re.M))
        return f"{platform.machine()}, 코어 {n}개, 기능: {' '.join(have) or '-'}"
    except OSError:
        return platform.machine()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="autosub.bench")
    ap.add_argument("video")
    ap.add_argument("--start", type=float, default=600, help="잘라낼 시작 지점(초). 영상이 짧으면 0부터")
    ap.add_argument("--seconds", type=float, default=300, help="샘플 길이(초)")
    ap.add_argument("--out-dir", help="결과 폴더 (기본: 영상 옆 영상이름.bench)")
    ap.add_argument("--config")
    ap.add_argument("--threads", type=int)
    ap.add_argument("--beam", type=int, help="Whisper beam size (1이면 greedy, 빠름)")
    ap.add_argument("--backend", choices=["auto", "gpu", "cpu"], help="Whisper 실행 장치")
    ap.add_argument("--whisper-model", help="Whisper 모델 파일 (models/ 아래 이름 또는 경로)")
    ap.add_argument("--whisper-args", default="", help='whisper-cli 추가 옵션, 예: "-nfa"')
    args = ap.parse_args(argv)

    cfg = load_config(Path(args.config) if args.config else None)
    if args.threads:
        cfg.whisper_threads = cfg.parakeet_threads = args.threads
    if args.beam:
        cfg.whisper_beam_size = args.beam
    if args.backend:
        cfg.whisper_backend = args.backend
    if args.whisper_model:
        m = args.whisper_model
        cfg.whisper_model = m if ("/" in m or "\\" in m) else f"models/{m}"
    if args.whisper_args:
        cfg.whisper_extra_args = args.whisper_args.split()
    video = Path(args.video).resolve()
    out = Path(args.out_dir) if args.out_dir else video.with_name(video.stem + ".bench")
    out.mkdir(parents=True, exist_ok=True)
    ffmpeg = Config.path(cfg.ffmpeg)
    cancel = CancelToken()
    log_lines: list[str] = []

    def log(s: str):
        log_lines.append(s)
        print("   " + s, flush=True)

    def stage_progress(name):
        last = [-1]

        def p(frac, msg):
            if frac is not None and int(frac * 100) // 5 != last[0]:
                last[0] = int(frac * 100) // 5
                print(f"  [{int(frac * 100):3d}%] {name}: {msg or ''}", flush=True)
        return p

    tmp = Path(tempfile.mkdtemp(prefix="autosub_bench_"))
    try:
        tracks = list_audio_tracks(ffmpeg, video)
        if not tracks:
            print("!! 오디오 트랙을 찾지 못했습니다")
            return 1
        track = cfg.audio_track if 0 <= cfg.audio_track < len(tracks) else pick_audio_track(tracks, cfg.language)
        full = tmp / "full.wav"
        print(f"== 오디오 추출 (트랙 {track})", flush=True)
        extract_audio(ffmpeg, video, full, log, cancel, stage_progress("추출"), track)
        total = len(load_wav(full)) / SR
        start = args.start if total >= args.start + args.seconds else max(0.0, total - args.seconds)
        wav = tmp / "sample.wav"
        subprocess.run([str(ffmpeg), "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                        "-ss", f"{start}", "-t", f"{args.seconds}", "-i", str(full), "-c", "copy", str(wav)],
                       check=True)
        audio = load_wav(wav)
        dur = len(audio) / SR
        print(f"== 샘플: {fmt_ts(start)} 부터 {dur:.0f}초", flush=True)

        print("== B) Whisper", flush=True)
        t0 = time.time()
        wh, backend = whisper_engine.transcribe(Config.path(cfg.whisper_cli), Config.path(cfg.whisper_model),
                                                wav, tmp / "whisper", cfg, log, cancel,
                                                stage_progress("Whisper"))
        t_wh = time.time() - t0

        print("== A) Parakeet", flush=True)
        t0 = time.time()
        pk = parakeet_engine.transcribe(Config.path(cfg.parakeet_dir), audio, cfg.parakeet_threads,
                                        log, cancel, stage_progress("Parakeet"))
        t_pk = time.time() - t0

        results = {}
        for key, label in (("A_parakeet", "Parakeet 단독"), ("B_whisper", "Whisper 단독"), ("C_both", "교차검증")):
            review = []
            t0 = time.time()
            if key == "A_parakeet":
                words = merge_mod.parakeet_only(copy.deepcopy(pk), review)
            elif key == "B_whisper":
                words = merge_mod.whisper_only(copy.deepcopy(wh), review)
            else:
                words = merge_mod.merge(copy.deepcopy(wh), copy.deepcopy(pk), review)
            cues = build_cues(words, cfg, review)
            t_post = time.time() - t0
            secs = {"A_parakeet": t_pk, "B_whisper": t_wh, "C_both": t_wh + t_pk}[key] + t_post
            srt = out / f"{video.stem}.{key}.en.srt"
            write_srt(cues, srt)
            write_review(review, out / f"{video.stem}.{key}.review.txt", video,
                         {"엔진": label, "샘플": f"{fmt_ts(start)} 부터 {dur:.0f}초"})
            results[key] = dict(label=label, secs=secs, words=words, cues=len(cues), review=len(review))

        base = results["C_both"]["words"]
        rep = [
            "autosub 벤치마크 보고서",
            "=" * 60,
            f"영상: {video.name}",
            f"샘플: {fmt_ts(start)} 부터 {dur:.0f}초",
            f"CPU: {_cpu_info()}",
            f"스레드: Whisper {cfg.whisper_threads}, Parakeet {cfg.parakeet_threads}",
            f"Whisper: {Path(cfg.whisper_model).name}, beam {cfg.whisper_beam_size}, {backend}"
            + (f", 옵션 {' '.join(cfg.whisper_extra_args)}" if cfg.whisper_extra_args else ""),
            "",
            f"{'모드':<16}{'처리시간':>9}{'배속':>8}{'40분 영상 예상':>14}{'자막':>6}{'검수':>6}{'C와 일치':>9}",
        ]
        for key, r in results.items():
            speed = dur / r["secs"] if r["secs"] > 0 else 0
            est = 40 * 60 / speed / 60 if speed else 0
            rep.append(f"{key + ' ' + r['label']:<16}{r['secs']:>8.0f}초{speed:>7.1f}x{est:>12.1f}분"
                       f"{r['cues']:>6}{r['review']:>6}{_agree(r['words'], base) * 100:>8.1f}%")
        rep += [
            "",
            "배속 = 샘플 길이 / 처리시간 (클수록 빠름). 40분 영상 예상은 발열로 실제보다 늘어날 수 있음.",
            "C와 일치 = 교차검증 결과와 단어가 같은 비율. 자막 파일을 열어 직접 비교해 보세요.",
            "",
            "-" * 60,
            *log_lines,
        ]
        report = out / "bench-report.txt"
        report.write_text("\n".join(rep) + "\n", encoding="utf-8")
        print("\n".join(rep[:9 + len(results)]))
        print(f"\n-> 보고서: {report}")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _main() -> int:
    try:
        return main(sys.argv[1:])
    except RuntimeError as e:
        print(f"!! 실패: {e}", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(_main())
