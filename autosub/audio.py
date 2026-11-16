from __future__ import annotations

import re
import subprocess
import wave
from pathlib import Path

import numpy as np

from .util import CREATE_NO_WINDOW, run_logged

_AUDIO_STREAM = re.compile(r"Stream #\d+:\d+(?:\[[^\]]*\])?(?:\((?P<lang>[^)]*)\))?: Audio: (?P<desc>.*)")


def list_audio_tracks(ffmpeg: Path, video: Path) -> list[tuple[str, str]]:
    """[(언어, 설명), ...] — ffmpeg -i 출력 파싱 (ffprobe 없이)."""
    try:
        r = subprocess.run([str(ffmpeg), "-hide_banner", "-nostdin", "-i", str(video)],
                           capture_output=True, timeout=60, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return []
    text = r.stderr.decode("utf-8", "replace")
    return [(m.group("lang") or "", m.group("desc").strip()) for m in _AUDIO_STREAM.finditer(text)]


def pick_audio_track(tracks: list[tuple[str, str]], wanted: str = "en") -> int:
    """영어 트랙(eng/en)이 있으면 그 번호, 없으면 0. 해설(commentary) 트랙은 피한다."""
    codes = {"en": ("eng", "en"), "ja": ("jpn", "ja"), "ko": ("kor", "ko")}.get(wanted, (wanted,))
    for i, (lang, desc) in enumerate(tracks):
        if lang.lower() in codes and "comment" not in desc.lower():
            return i
    return 0

SR = 16000


def extract_audio(ffmpeg: Path, video: Path, out_wav: Path, log, cancel, progress, track: int = 0) -> None:
    """영상의 오디오 트랙(track번째) → 16kHz mono PCM wav."""
    cmd = [str(ffmpeg), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-stats", "-i", str(video),
           "-map", f"0:a:{track}", "-vn", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(out_wav)]
    def on_line(line: str):
        if line.startswith("size=") or " time=" in line:
            progress(None, None)  # 하트비트
        else:
            log("  " + line)

    rc = run_logged(cmd, log, cancel, on_line=on_line)
    if rc != 0 or not out_wav.exists():
        raise RuntimeError(f"ffmpeg 오디오 추출 실패 (종료코드 {rc}). 영상에 오디오 트랙이 있는지 확인하세요.")


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == SR and w.getnchannels() == 1 and w.getsampwidth() == 2
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def split_points(audio: np.ndarray, max_len: float = 20.0, search: float = 6.0) -> list[tuple[int, int]]:
    """max_len 이하 청크로 자르되, 끝 search초 구간에서 가장 조용한 지점에서 자른다.
    VAD를 쓰지 않으므로 속삭임 구간이 버려지지 않는다."""
    n = len(audio)
    hop = SR // 50  # 20ms
    chunks = []
    pos = 0
    max_n, search_n = int(max_len * SR), int(search * SR)
    while pos < n:
        if n - pos <= max_n:
            chunks.append((pos, n))
            break
        lo, hi = pos + max_n - search_n, pos + max_n
        seg = audio[lo:hi]
        frames = len(seg) // hop
        energy = np.sqrt(np.mean(seg[: frames * hop].reshape(frames, hop) ** 2, axis=1) + 1e-12)
        # 주변 100ms 평균으로 부드럽게
        k = 15  # 300ms 평균: 단어 사이가 아니라 실제 쉼을 고르도록
        smooth = np.convolve(energy, np.ones(k) / k, mode="same")
        cut = lo + int(np.argmin(smooth)) * hop + hop // 2
        chunks.append((pos, cut))
        pos = cut
    return chunks
