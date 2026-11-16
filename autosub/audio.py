from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from .util import run_logged

SR = 16000


def extract_audio(ffmpeg: Path, video: Path, out_wav: Path, log, cancel, progress) -> None:
    """영상 첫 번째 오디오 트랙 → 16kHz mono PCM wav."""
    cmd = [str(ffmpeg), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-stats", "-i", str(video),
           "-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(out_wav)]
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
