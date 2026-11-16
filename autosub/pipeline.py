from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

from . import merge as merge_mod
from . import parakeet_engine, whisper_engine
from .audio import SR, extract_audio, list_audio_tracks, load_wav, pick_audio_track
from .config import ROOT, Config
from .model import ReviewItem, fmt_ts
from .postprocess import build_cues
from .util import CancelToken
from .writers import write_review, write_srt

# progress(전체진행률 0~1 또는 None(하트비트), 단계 문구 또는 None)
ProgressFn = Callable[[Optional[float], Optional[str]], None]


def output_paths(video: Path) -> tuple[Path, Path]:
    stem = video.with_suffix("")
    return Path(f"{stem}.en.srt"), Path(f"{stem}.review.txt")


def _tee_log(log: Callable[[str], None], video: Path) -> Callable[[str], None]:
    """화면 로그를 logs/ 폴더 파일에도 남긴다 (프로그램이 죽어도 원인 확인 가능)."""
    try:
        d = ROOT / "logs"
        d.mkdir(exist_ok=True)
        f = open(d / f"{time.strftime('%Y%m%d_%H%M%S')}_{video.stem[:60]}.log", "a", encoding="utf-8")
    except OSError:
        return log

    def tee(msg: str):
        log(msg)
        try:
            f.write(msg + "\n")
            f.flush()
        except (OSError, ValueError):
            pass
    return tee


def run(video: Path, cfg: Config, log: Callable[[str], None], progress: ProgressFn,
        cancel: CancelToken) -> tuple[Path, Path]:
    t_start = time.time()
    video = video.resolve()
    log = _tee_log(log, video)
    if not video.exists():
        raise RuntimeError(f"파일이 없습니다: {video}")
    srt_path, review_path = output_paths(video)

    # 단계별 가중치 (대략적인 소요 시간 비율)
    stages = [("extract", 0.04), ("whisper", 0.60 if cfg.use_parakeet else 0.92)]
    if cfg.use_parakeet:
        stages.append(("parakeet", 0.32))
    stages.append(("finish", 0.04))
    total = sum(w for _, w in stages)
    base = {}
    acc = 0.0
    for name, w in stages:
        base[name] = (acc / total, w / total)
        acc += w

    def stage(name: str):
        b, w = base[name]

        def p(frac, msg):
            progress(None if frac is None else b + w * max(0.0, min(1.0, frac)), msg)
        return p

    tmp = Path(tempfile.mkdtemp(prefix="autosub_"))
    log(f"작업 폴더: {tmp}")
    try:
        # 1. 오디오 추출
        p = stage("extract")
        p(0.0, "오디오 추출 중")
        wav = tmp / "audio.wav"
        ffmpeg = Config.path(cfg.ffmpeg)
        if not ffmpeg.exists():
            raise RuntimeError(f"FFmpeg를 찾을 수 없습니다: {ffmpeg}\nsetup.bat을 먼저 실행하세요.")
        tracks = list_audio_tracks(ffmpeg, video)
        if not tracks:
            raise RuntimeError("영상에서 오디오 트랙을 찾지 못했습니다.")
        track = cfg.audio_track if 0 <= cfg.audio_track < len(tracks) else pick_audio_track(tracks, cfg.language)
        for i, (lang, desc) in enumerate(tracks):
            log(f"  오디오 트랙 {i}: [{lang or '언어정보 없음'}] {desc[:70]}" + ("   ← 사용" if i == track else ""))
        extract_audio(ffmpeg, video, wav, log, cancel, p, track)
        audio = load_wav(wav)
        dur = len(audio) / SR
        log(f"오디오 길이: {fmt_ts(dur)}")
        p(1.0, "오디오 추출 완료")

        # 2. Whisper
        p = stage("whisper")
        wh_words, backend = whisper_engine.transcribe(
            Config.path(cfg.whisper_cli), Config.path(cfg.whisper_model), wav, tmp / "whisper",
            cfg, log, cancel, p)
        t_wh = time.time() - t_start

        # 3. Parakeet
        review: list[ReviewItem] = []
        if cfg.use_parakeet:
            p = stage("parakeet")
            pk_words = parakeet_engine.transcribe(Config.path(cfg.parakeet_dir), audio,
                                                  cfg.parakeet_threads, log, cancel, p)
            cancel.check()
            words = merge_mod.merge(wh_words, pk_words, review)
        else:
            words = merge_mod.whisper_only(wh_words, review)

        # 4. 자막 정리 및 저장
        p = stage("finish")
        p(0.0, "자막 정리 중")
        cues = build_cues(words, cfg, review)
        if srt_path.exists():
            bak = srt_path.with_suffix(".srt.bak")
            shutil.copy2(srt_path, bak)
            log(f"기존 자막을 백업했습니다: {bak.name}")
        write_srt(cues, srt_path)
        elapsed = time.time() - t_start
        info = {
            "영상 길이": fmt_ts(dur),
            "처리 시간": f"{elapsed / 60:.1f}분 (Whisper {t_wh / 60:.1f}분, {backend})",
            "Whisper 모델": Path(cfg.whisper_model).name,
            "교차검증": "Parakeet-TDT 0.6B" if cfg.use_parakeet else "사용 안 함",
            "자막 개수": str(len(cues)),
        }
        write_review(review, review_path, video, info)
        p(1.0, "완료")
        log(f"완료: {srt_path.name} (자막 {len(cues)}개, 검수 항목 {len(review)}건, {elapsed / 60:.1f}분)")
        return srt_path, review_path
    finally:
        if cfg.keep_temp:
            log(f"임시 파일 보존: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
