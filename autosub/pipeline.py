from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

from . import merge as merge_mod
from . import parakeet_engine, speech_regions, whisper_engine
from .audio import SR, extract_audio, list_audio_tracks, load_wav, pick_audio_track
from .config import ROOT, Config
from .model import ReviewItem, fmt_ts
from .postprocess import build_cues
from .util import CancelToken
from .writers import write_review, write_srt

# progress(전체진행률 0~1 또는 None(하트비트), 단계 문구 또는 None)
ProgressFn = Callable[[Optional[float], Optional[str]], None]


def output_paths(video: Path, out_dir: Optional[Path] = None) -> tuple[Path, Path]:
    stem = (Path(out_dir) / video.stem) if out_dir else video.with_suffix("")
    return Path(f"{stem}.en.srt"), Path(f"{stem}.review.txt")


def speech_only_wav(audio, pk_words, cfg: Config, out_wav: Path, log) -> tuple[Path | None, object]:
    """Parakeet 단어 위치로 대사 구간만 모은 wav를 만든다. 반환: (wav 경로, 시간 대응표).
    줄어드는 양이 적으면(15% 미만) 그대로 두는 편이 안전하므로 (None, None)을 돌려준다."""
    total = len(audio) / SR
    regs = speech_regions.regions_from_words(pk_words, total, cfg.speech_pad, cfg.speech_merge_gap)
    cond, segmap = speech_regions.condense(audio, regs)
    kept = len(cond) / SR
    if not regs or kept > total * 0.85:
        log(f"[대사구간] 대사 구간 {kept:.0f}초 / 전체 {total:.0f}초 — 줄일 것이 적어 전체를 처리")
        return None, None
    speech_regions.write_wav(cond, out_wav)
    log(f"[대사구간] {len(regs)}개 구간, {kept:.0f}초 / 전체 {total:.0f}초 "
        f"({kept / total * 100:.0f}%)만 Whisper로 처리")
    return out_wav, segmap


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
        cancel: CancelToken, out_dir: Optional[Path] = None) -> tuple[Path, Path]:
    t_start = time.time()
    video = video.resolve()
    log = _tee_log(log, video)
    if not video.exists():
        raise RuntimeError(f"파일이 없습니다: {video}")
    if out_dir:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
    srt_path, review_path = output_paths(video, out_dir)
    mode = cfg.mode()
    use_wh, use_pk = mode in ("both", "whisper"), mode in ("both", "parakeet")

    # 단계별 가중치 (대략적인 소요 시간 비율)
    stages = [("extract", 0.04)]
    if use_wh and use_pk and cfg.whisper_speech_only:
        stages += [("parakeet", 0.20), ("whisper", 0.72)]
    else:
        if use_wh:
            stages.append(("whisper", 0.60 if use_pk else 0.92))
        if use_pk:
            stages.append(("parakeet", 0.32 if use_wh else 0.92))
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

        t_wh = t_pk = 0.0
        backend = ""
        wh_words = pk_words = None
        review: list[ReviewItem] = []
        guided = use_wh and use_pk and cfg.whisper_speech_only

        def run_parakeet():
            nonlocal pk_words, t_pk
            p = stage("parakeet")
            t0 = time.time()
            pk_words = parakeet_engine.transcribe(Config.path(cfg.parakeet_dir), audio,
                                                  cfg.parakeet_threads, log, cancel, p)
            t_pk = time.time() - t0
            cancel.check()

        # 대사 구간만 처리하는 모드에서는 Parakeet을 먼저 돌린다
        if guided:
            run_parakeet()

        # 2. Whisper
        if use_wh:
            p = stage("whisper")
            t0 = time.time()
            wh_wav, segmap = wav, None
            if guided:
                w2, segmap = speech_only_wav(audio, pk_words, cfg, tmp / "speech.wav", log)
                wh_wav = w2 or wav
            wh_words, backend = whisper_engine.transcribe(
                Config.path(cfg.whisper_cli), Config.path(cfg.whisper_model), wh_wav, tmp / "whisper",
                cfg, log, cancel, p)
            if segmap is not None:
                speech_regions.remap_words(wh_words, segmap)
            t_wh = time.time() - t0

        # 3. Parakeet
        if use_pk and not guided:
            run_parakeet()
        if wh_words is not None and pk_words is not None:
            words = merge_mod.merge(wh_words, pk_words, review)
        elif wh_words is not None:
            words = merge_mod.whisper_only(wh_words, review)
        else:
            words = merge_mod.parakeet_only(pk_words, review)

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
            "처리 시간": f"{elapsed / 60:.1f}분" + "".join(
                [f", Whisper {t_wh / 60:.1f}분 ({backend})" if use_wh else "",
                 f", Parakeet {t_pk / 60:.1f}분" if use_pk else ""]),
            "엔진": {"both": "Whisper + Parakeet 교차검증" + (" (대사 구간만 Whisper)" if guided else ""), "whisper": "Whisper 단독",
                    "parakeet": "Parakeet-TDT 0.6B 단독"}[mode],
        }
        if use_wh:
            info["Whisper 모델"] = Path(cfg.whisper_model).name
        info.update({
            "자막 개수": str(len(cues)),
        })
        write_review(review, review_path, video, info)
        p(1.0, "완료")
        log(f"완료: {srt_path.name} (자막 {len(cues)}개, 검수 항목 {len(review)}건, {elapsed / 60:.1f}분)")
        log(f"TIMING total={elapsed:.1f} whisper={t_wh:.1f} parakeet={t_pk:.1f} audio={dur:.1f} mode={mode}")
        return srt_path, review_path
    finally:
        if cfg.keep_temp:
            log(f"임시 파일 보존: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
