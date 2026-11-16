from __future__ import annotations

import json
import re
from pathlib import Path

from .model import Word
from .util import CancelToken, run_logged

_PROGRESS = re.compile(r"progress\s*=\s*(\d+)%")
_SPECIAL = re.compile(r"^\[_.*\]$")
# [BLANK_AUDIO], (music), ♪ ... 같은 비대사 세그먼트
_NONSPEECH = re.compile(r"^[\s\[\(\*♪♫].*[\]\)\*♪♫]\s*$|^[\s♪♫.]*$")
_INTERESTING = ("vulkan", "error", "fail", "gpu", "device", "system_info", "backend", "warn")


def _words_from_json(data: dict) -> list[Word]:
    words: list[Word] = []
    for si, seg in enumerate(data.get("transcription", [])):
        if _NONSPEECH.match(seg.get("text", "").strip() or "."):
            continue
        cur: Word | None = None
        for tok in seg.get("tokens", []):
            t = tok.get("text", "")
            if not t or _SPECIAL.match(t.strip()):
                continue
            t0, t1 = tok["offsets"]["from"] / 1000.0, tok["offsets"]["to"] / 1000.0
            p = float(tok.get("p", 1.0))
            if t.startswith(" ") or cur is None:
                if cur is not None and cur.text:
                    words.append(cur)
                cur = Word(text=t.strip(), start=t0, end=max(t0, t1), prob=p, source="whisper", seg=si)
            else:
                cur.text += t
                cur.end = max(cur.end, t1)
                cur.prob = min(cur.prob, p)
        if cur is not None and cur.text:
            words.append(cur)
    # 대괄호 효과음 토큰이 단어로 섞여 들어온 경우 제거
    return [w for w in words if not re.fullmatch(r"[\[\(].*[\]\)]|[♪♫]+", w.text)]


def transcribe(cli: Path, model: Path, wav: Path, out_base: Path, cfg, log, cancel: CancelToken,
               progress) -> tuple[list[Word], str]:
    if not cli.exists():
        raise RuntimeError(f"whisper-cli를 찾을 수 없습니다: {cli}\nsetup.bat을 먼저 실행하세요.")
    if not model.exists():
        raise RuntimeError(f"Whisper 모델이 없습니다: {model}\nsetup.bat을 먼저 실행하세요.")

    base = [str(cli), "-m", str(model), "-f", str(wav), "-l", cfg.language,
            "-t", str(cfg.whisper_threads), "-bs", str(cfg.whisper_beam_size),
            "-ojf", "-of", str(out_base), "-pp", "-sns"]
    if cfg.whisper_max_context >= 0:
        base += ["-mc", str(cfg.whisper_max_context)]

    attempts = {"gpu": [("GPU(Vulkan)", [])], "cpu": [("CPU", ["-ng"])]}.get(
        cfg.whisper_backend, [("GPU(Vulkan)", []), ("CPU", ["-ng"])])

    out_json = Path(str(out_base) + ".json")
    last_err = ""
    for label, extra in attempts:
        cancel.check()
        if out_json.exists():
            out_json.unlink()
        log(f"[Whisper] {label} 백엔드로 실행")
        progress(0.0, f"Whisper ({label}) 시작")

        no_gpu = [False]

        def on_line(line: str, _label=label):
            if "no gpu found" in line.lower():
                no_gpu[0] = True
            m = _PROGRESS.search(line)
            if m:
                pct = int(m.group(1))
                progress(pct / 100.0, f"Whisper ({_label}) {pct}%")
            elif any(k in line.lower() for k in _INTERESTING):
                log("  " + line)
            else:
                progress(None, None)  # 하트비트

        rc = run_logged(base + extra, log, cancel, on_line=on_line)
        if rc == 0 and out_json.exists():
            data = json.loads(out_json.read_text(encoding="utf-8", errors="replace"))
            words = _words_from_json(data)
            if no_gpu[0] and not extra:
                label = "CPU (GPU 미발견)"
                log("[Whisper] 주의: GPU를 찾지 못해 CPU로 처리했습니다. Vulkan 빌드/그래픽 드라이버를 확인하세요.")
            log(f"[Whisper] 완료: 단어 {len(words)}개")
            return words, label
        last_err = f"종료코드 {rc}"
        log(f"[Whisper] {label} 실패 ({last_err})")
    raise RuntimeError(f"Whisper 실행 실패 ({last_err}). 로그를 확인하세요.")
