"""Whisper / Parakeet 교차검증 병합.

- 두 엔진이 같은 단어  → 확정. 타이밍은 Parakeet 단어 타임스탬프(더 정확) 사용
- Parakeet에만 있는 대사 → Whisper 누락으로 보고 삽입, 검수목록에 기록
- Whisper에만 있는 대사 → Parakeet이 조용하면 환각 의심. 근거가 충분하면 제거
- 서로 다른 단어       → Whisper 채택, 검수목록에 기록
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .model import ReviewItem, Word

FILLERS = {"uh", "um", "mm", "hmm", "mhm", "erm", "ah", "huh"}
HALLUCINATION_PHRASES = [
    "thank you for watching", "thanks for watching", "subtitles by", "please subscribe",
    "like and subscribe", "translated by", "captions by", "amara.org", "see you next time",
]


def norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", t.lower())


def _text(ws: list[Word]) -> str:
    return " ".join(w.text for w in ws)


def _clean(words: list[Word]) -> list[Word]:
    """정규화하면 빈 단어(단독 구두점 등)는 앞 단어에 붙인다."""
    out: list[Word] = []
    for w in words:
        if not norm(w.text):
            if out:
                out[-1].text += w.text
            continue
        out.append(w)
    return out


def trim_runaway(words: list[Word], review: list[ReviewItem], keep: int = 3, min_run: int = 5) -> list[Word]:
    """한 문장 안에서 같은 단어/짧은 구(1~4단어)가 min_run회 이상 연달아 반복되면 keep회만 남긴다.
    ("no no no no no no no ..." 같은 Whisper 폭주 환각). 4회 이하는 실제 대사일 수 있어 유지."""
    out: list[Word] = []
    i, n = 0, len(words)
    keys = [norm(w.text) for w in words]
    while i < n:
        best = None
        for unit in range(1, 5):
            if i + unit * min_run > n:
                break
            pat = keys[i:i + unit]
            reps = 1
            while keys[i + reps * unit:i + (reps + 1) * unit] == pat:
                reps += 1
            if reps >= min_run and (best is None or reps * unit > best[0] * best[1]):
                best = (reps, unit)
        if best:
            reps, unit = best
            span = words[i:i + reps * unit]
            out.extend(span[:keep * unit])
            review.append(ReviewItem(span[0].start, "환각제거",
                                     f"\"{_text(span[:unit])}\" {reps}회 반복 → {keep}회로 줄임"))
            i += reps * unit
        else:
            out.append(words[i])
            i += 1
    return out


def collapse_repeats(words: list[Word], review: list[ReviewItem]) -> list[Word]:
    """같은 문장이 3번 이상 연달아 반복되는 Whisper 반복 환각 제거."""
    segs: dict[int, list[Word]] = {}
    order: list[int] = []
    for w in words:
        if w.seg not in segs:
            segs[w.seg] = []
            order.append(w.seg)
        segs[w.seg].append(w)
    keep: list[Word] = []
    i = 0
    while i < len(order):
        key = norm(_text(segs[order[i]]))
        j = i + 1
        while j < len(order) and norm(_text(segs[order[j]])) == key:
            j += 1
        keep.extend(segs[order[i]])
        run = j - i
        if run >= 3 and key:
            first = segs[order[i + 1]][0]
            review.append(ReviewItem(first.start, "환각제거",
                                     f"같은 문장 {run}회 반복 → 1회만 유지: \"{_text(segs[order[i]])}\""))
            i = j
        else:
            for k in range(i + 1, j):
                keep.extend(segs[order[k]])
            i = j
    return keep


def _has_words_between(ws: list[Word], t0: float, t1: float) -> bool:
    return any(w.end > t0 and w.start < t1 for w in ws)


def whisper_only(words: list[Word], review: list[ReviewItem]) -> list[Word]:
    """교차검증 없이 Whisper만 쓸 때: 반복 제거 + 의심 문구 표시만."""
    words = collapse_repeats(trim_runaway(_clean(words), review), review)
    full = norm(_text(words))
    for ph in HALLUCINATION_PHRASES:
        if norm(ph) in full:
            for w in words:
                if norm(w.text) == norm(ph.split()[0]):
                    review.append(ReviewItem(w.start, "환각의심", f"자주 생기는 환각 문구 포함: \"{ph}\""))
                    break
    return words


def merge(wh: list[Word], pk: list[Word], review: list[ReviewItem]) -> list[Word]:
    wh = collapse_repeats(trim_runaway(_clean(wh), review), review)
    pk = _clean(pk)
    a, b = [norm(w.text) for w in wh], [norm(w.text) for w in pk]
    sm = SequenceMatcher(None, a, b, autojunk=False)
    out: list[Word] = []

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        W, P = wh[i1:i2], pk[j1:j2]
        if tag == "equal":
            for w, p in zip(W, P):
                if abs(w.start - p.start) < 3.0:
                    w.start, w.end = p.start, max(p.end, p.start + 0.05)
                w.source = "both"
                out.append(w)

        elif tag == "replace":
            far = abs(W[0].start - P[0].start) > 5.0
            if far:   # 정렬 오류: 사실상 삭제 + 삽입
                out.extend(_handle_whisper_only(W, pk, review))
                out.extend(_handle_parakeet_only(P, wh, review))
                continue
            if len(W) == len(P):
                for w, p in zip(W, P):
                    w.start, w.end = p.start, max(p.end, p.start + 0.05)
            out.extend(W)
            content = [x for x in a[i1:i2] + b[j1:j2] if x not in FILLERS]
            if content:
                review.append(ReviewItem(W[0].start, "불일치",
                                         f"Whisper: \"{_text(W)}\"  /  Parakeet: \"{_text(P)}\""))

        elif tag == "delete":
            out.extend(_handle_whisper_only(W, pk, review))

        elif tag == "insert":
            out.extend(_handle_parakeet_only(P, wh, review))

    return make_monotonic(out)


def make_monotonic(words: list[Word]) -> list[Word]:
    """병합 결과는 대사 순서가 맞으므로 정렬하지 않고, 시간만 앞 단어보다 뒤로 오게 보정한다."""
    prev_start = 0.0
    for w in words:
        if w.start < prev_start:
            w.start = prev_start
        if w.end < w.start + 0.05:
            w.end = w.start + 0.05
        prev_start = w.start
    return words


def _handle_whisper_only(W: list[Word], pk: list[Word], review: list[ReviewItem]) -> list[Word]:
    t0, t1 = W[0].start, W[-1].end
    text = _text(W)
    if _has_words_between(pk, t0 - 0.5, t1 + 0.5):
        if len([w for w in W if norm(w.text) not in FILLERS]) >= 2:
            review.append(ReviewItem(t0, "불일치", f"Whisper에만 있음: \"{text}\""))
        return W
    # Parakeet은 이 구간을 조용하다고 판단
    mean_p = sum(w.prob for w in W) / len(W)
    known = any(norm(ph) in norm(text) for ph in HALLUCINATION_PHRASES)
    if known or mean_p < 0.45 or len(W) <= 3:
        why = ("자주 생기는 환각 문구" if known else
               f"낮은 신뢰도({mean_p:.2f})" if mean_p < 0.45 else "짧은 단독 문장")
        review.append(ReviewItem(t0, "환각제거", f"{why} + Parakeet 무음 → 삭제: \"{text}\""))
        return []
    review.append(ReviewItem(t0, "환각의심", f"Parakeet은 무음으로 판단 (유지함): \"{text}\""))
    return W


def _handle_parakeet_only(P: list[Word], wh: list[Word], review: list[ReviewItem]) -> list[Word]:
    content = [p for p in P if norm(p.text) not in FILLERS]
    if not content:
        return []
    t0, t1 = P[0].start, P[-1].end
    whisper_silent = not _has_words_between(wh, t0 - 1.0, t1 + 1.0)
    if len(P) >= 3 or whisper_silent:
        for p in P:
            p.seg = -2  # 삽입된 단어 표시
        review.append(ReviewItem(t0, "누락의심", f"Whisper가 놓친 대사 삽입 (Parakeet): \"{_text(P)}\""))
        return P
    return []
