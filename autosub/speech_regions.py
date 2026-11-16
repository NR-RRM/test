"""Parakeet이 찾은 대사 구간만 모아 Whisper에 넘기기 위한 도구.

Whisper는 음악·무음 구간도 똑같은 시간을 들여 처리한다(그리고 거기서 환각을 만든다).
Parakeet은 매우 빠르므로 먼저 돌려서 말이 있는 구간을 찾고, 그 구간만 이어 붙인
오디오를 Whisper에 넘긴 뒤 단어 시간을 원래 시간으로 되돌린다.
"""
from __future__ import annotations

import wave
from bisect import bisect_right
from pathlib import Path

import numpy as np

from .audio import SR
from .model import Word

# (압축 오디오에서의 시작, 원본에서의 시작, 길이) — 초 단위
SegMap = list[tuple[float, float, float]]


def regions_from_words(words: list[Word], total: float, pad: float = 0.8,
                       merge_gap: float = 2.5) -> list[tuple[float, float]]:
    """단어들을 merge_gap 이하 간격이면 한 구간으로 묶고, 앞뒤로 pad만큼 넓힌다."""
    out: list[list[float]] = []
    for w in sorted(words, key=lambda w: w.start):
        a, b = max(0.0, w.start - pad), min(total, max(w.end, w.start) + pad)
        if out and a - out[-1][1] <= merge_gap - 2 * pad:
            out[-1][1] = max(out[-1][1], b)
        elif out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out if b - a > 0.05]


def condense(audio: np.ndarray, regions: list[tuple[float, float]], sep: float = 0.4
             ) -> tuple[np.ndarray, SegMap]:
    """구간들을 sep초 무음을 사이에 두고 이어 붙인다."""
    parts: list[np.ndarray] = []
    segmap: SegMap = []
    pos = 0
    gap = np.zeros(int(sep * SR), dtype=audio.dtype)
    for i, (a, b) in enumerate(regions):
        ia, ib = int(a * SR), min(len(audio), int(b * SR))
        if ib <= ia:
            continue
        if parts:
            parts.append(gap)
            pos += len(gap)
        segmap.append((pos / SR, ia / SR, (ib - ia) / SR))
        parts.append(audio[ia:ib])
        pos += ib - ia
    return (np.concatenate(parts) if parts else audio[:0]), segmap


def map_time(t: float, segmap: SegMap) -> float:
    """압축 오디오의 시간 → 원본 시간. 구간 사이 무음에 떨어지면 가까운 구간 끝으로 붙인다."""
    if not segmap:
        return t
    i = bisect_right([s[0] for s in segmap], t) - 1
    if i < 0:
        return segmap[0][1]
    c0, o0, ln = segmap[i]
    off = t - c0
    if off <= ln:
        return o0 + off
    if i + 1 < len(segmap) and (segmap[i + 1][0] - t) < (off - ln):
        return segmap[i + 1][1]
    return o0 + ln


def remap_words(words: list[Word], segmap: SegMap) -> list[Word]:
    for w in words:
        s, e = map_time(w.start, segmap), map_time(w.end, segmap)
        w.start, w.end = s, max(s, e)
    return words


def write_wav(audio: np.ndarray, path: Path) -> None:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
