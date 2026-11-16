from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Word:
    text: str          # 화면에 표시될 원문 (구두점 포함, 앞 공백 없음)
    start: float       # 초
    end: float         # 초
    prob: float = 1.0
    source: str = "whisper"   # whisper | parakeet | both
    seg: int = -1             # whisper 세그먼트 번호 (환각 판정용)


@dataclass
class Cue:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass
class ReviewItem:
    time: float
    kind: str      # 누락의심 / 불일치 / 환각제거 / 환각의심 / 읽기속도
    detail: str


def fmt_ts(t: float) -> str:
    if t < 0:
        t = 0.0
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
