"""단어 목록 → 자막 큐. 줄 길이 / 줄 수 / 읽기속도 / 최소 표시시간 / 겹침 정리."""
from __future__ import annotations

from .model import Cue, ReviewItem, Word

SENT_END = (".", "?", "!", "…")
SOFT_BREAK = (",", ";", ":", "—", "-")


def _join(ws: list[Word]) -> str:
    return " ".join(w.text for w in ws).strip()


def segment(words: list[Word], cfg) -> list[list[Word]]:
    limit = cfg.max_line_chars * cfg.max_lines
    groups: list[list[Word]] = []
    cur: list[Word] = []

    def flush(upto: int | None = None):
        nonlocal cur
        if upto is None:
            if cur:
                groups.append(cur)
            cur = []
        else:
            groups.append(cur[:upto])
            cur = cur[upto:]

    for i, w in enumerate(words):
        if cur:
            gap = w.start - cur[-1].end
            if gap >= cfg.sentence_gap:
                flush()
            else:
                too_long = len(_join(cur + [w])) > limit
                too_slow = w.end - cur[0].start > cfg.max_duration
                if too_long or too_slow:
                    # 뒤쪽 절반에서 쉼표 등 자연스러운 끊김 지점 찾기
                    best = None
                    for k in range(len(cur) - 1, 0, -1):
                        if cur[k - 1].text.endswith(SENT_END + SOFT_BREAK) and len(_join(cur[:k])) >= limit * 0.35:
                            best = k
                            break
                    flush(best)
        cur.append(w)
        if w.text.endswith(SENT_END):
            nxt = words[i + 1] if i + 1 < len(words) else None
            short = len(_join(cur)) < 16
            close = nxt is not None and nxt.start - w.end < 0.35
            fits = nxt is not None and len(_join(cur + [nxt])) <= limit * 0.6
            if not (short and close and fits):   # 아주 짧은 문장("Yes.")은 다음 문장과 묶음
                flush()
    flush()
    return [g for g in groups if g]


def wrap(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    words = text.split(" ")
    best, best_score = None, None
    for k in range(1, len(words)):
        l1, l2 = " ".join(words[:k]), " ".join(words[k:])
        over = max(0, len(l1) - max_chars) + max(0, len(l2) - max_chars)
        score = over * 10 + abs(len(l1) - len(l2))
        if l1.endswith(SENT_END + SOFT_BREAK):
            score -= 8
        # 아래 줄이 더 긴 피라미드형 선호
        if len(l2) >= len(l1):
            score -= 1
        if best_score is None or score < best_score:
            best, best_score = (l1, l2), score
    return "\n".join(best) if best else text


def build_cues(words: list[Word], cfg, review: list[ReviewItem]) -> list[Cue]:
    cues = []
    for g in segment(words, cfg):
        text = _join(g)
        if text and text[0].islower() and (not cues or cues[-1].text.rstrip().endswith(SENT_END)):
            text = text[0].upper() + text[1:]
        cues.append(Cue(start=g[0].start, end=g[-1].end, text=text, words=g))

    for i, c in enumerate(cues):
        nxt_start = cues[i + 1].start if i + 1 < len(cues) else float("inf")
        room = nxt_start - cfg.min_gap
        c.end = min(c.end + cfg.end_padding, room)
        chars = len(c.text.replace("\n", ""))
        need = max(cfg.min_duration, chars / cfg.max_cps)
        if c.end - c.start < need:
            c.end = min(c.start + need, room)
        if c.end - c.start < 0.3:          # 겹침이 심한 경우 최소한의 표시시간 확보
            c.end = c.start + 0.3
            if i + 1 < len(cues) and cues[i + 1].start < c.end + cfg.min_gap:
                cues[i + 1].start = c.end + cfg.min_gap
        cps = chars / max(c.end - c.start, 0.01)
        if cps > cfg.max_cps * 1.25:
            review.append(ReviewItem(c.start, "읽기속도", f"{cps:.0f} CPS로 빠름: \"{c.text}\""))
        c.text = wrap(c.text, cfg.max_line_chars)
    return cues
