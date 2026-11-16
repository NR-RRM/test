from __future__ import annotations

from collections import Counter
from pathlib import Path

from .model import Cue, ReviewItem, fmt_ts


def write_srt(cues: list[Cue], path: Path) -> None:
    lines = []
    for i, c in enumerate(cues, 1):
        lines += [str(i), f"{fmt_ts(c.start)} --> {fmt_ts(c.end)}", c.text, ""]
    path.write_text("\r\n".join(lines), encoding="utf-8-sig", newline="")


def write_review(items: list[ReviewItem], path: Path, video: Path, info: dict) -> None:
    items = sorted(items, key=lambda r: r.time)
    cnt = Counter(r.kind for r in items)
    out = [
        f"자막 검수 목록 — {video.name}",
        "=" * 60,
        *(f"{k}: {v}" for k, v in info.items()),
        "",
        "요약: " + (", ".join(f"{k} {v}건" for k, v in cnt.most_common()) if cnt else "검수할 항목 없음"),
        "",
        "  누락의심  : Whisper가 놓친 대사를 Parakeet 결과로 채워 넣음 → 실제로 들리는지 확인",
        "  불일치    : 두 엔진이 다르게 들음 → Whisper 쪽을 사용함, 맞는지 확인",
        "  환각제거  : 음악/무음 구간에서 만들어진 가짜 문장을 삭제함 → 실제 대사였는지 확인",
        "  환각의심  : 가짜 문장일 수 있지만 남겨둠",
        "  읽기속도  : 자막이 너무 빨리 지나감",
        "",
        "-" * 60,
    ]
    out += [f"{fmt_ts(r.time)}  [{r.kind}]  {r.detail}" for r in items]
    path.write_text("\r\n".join(out) + "\r\n", encoding="utf-8-sig", newline="")
