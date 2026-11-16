from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from .model import Word
from .util import CREATE_NO_WINDOW, CancelToken, run_logged

_caps_cache: dict[str, str] = {}


def help_text(cli: Path) -> str:
    """whisper-cli -h 출력. 버전마다 지원 옵션이 달라서(기존에 설치된 빌드 재사용 시) 확인 후 사용한다."""
    key = str(cli)
    if key not in _caps_cache:
        try:
            r = subprocess.run([key, "-h"], capture_output=True, timeout=20, creationflags=CREATE_NO_WINDOW)
            _caps_cache[key] = (r.stdout + r.stderr).decode("utf-8", "replace")
        except (OSError, subprocess.TimeoutExpired):
            _caps_cache[key] = ""
    return _caps_cache[key]


def supports(cli: Path, flag: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(flag)}\b", help_text(cli)) is not None

_PROGRESS = re.compile(r"progress\s*=\s*(\d+)%")
_SPECIAL = re.compile(r"^\[_.*\]$")
# [BLANK_AUDIO], (music), ♪ ... 같은 비대사 세그먼트
_NONSPEECH = re.compile(r"^[\s\[\(\*♪♫].*[\]\)\*♪♫]\s*$|^[\s♪♫.]*$")
_INTERESTING = ("vulkan", "opencl", "adreno", "error", "fail", "gpu", "device", "system_info", "backend", "warn")


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
    cpu_cli = cli
    if getattr(cfg, "whisper_cli_cpu", ""):
        from .config import Config
        c = Config.path(cfg.whisper_cli_cpu)
        if c.exists():
            cpu_cli = c
    if not model.exists():
        raise RuntimeError(f"Whisper 모델이 없습니다: {model}\nsetup.bat을 먼저 실행하세요.")

    if not supports(cli, "-ojf"):
        raise RuntimeError(f"이 whisper-cli는 너무 오래된 버전입니다 (-ojf 미지원): {cli}")
    base = ["-m", str(model), "-f", str(wav), "-l", cfg.language,
            "-t", str(cfg.whisper_threads), "-bs", str(cfg.whisper_beam_size),
            "-ojf", "-of", str(out_base)]
    for flag in ("-pp", "-sns"):
        if supports(cli, flag):
            base.append(flag)
        else:
            log(f"[Whisper] 이 빌드는 {flag} 옵션을 지원하지 않아 생략합니다")
    if cfg.whisper_max_context >= 0:
        base += ["-mc", str(cfg.whisper_max_context)]
    base += [str(a) for a in (getattr(cfg, "whisper_extra_args", None) or [])]

    gpu_label = "GPU(Vulkan)" if os.name == "nt" else "GPU"
    gpu, cpu = (gpu_label, cli, []), ("CPU", cpu_cli, ["-ng"])
    attempts = {"gpu": [gpu], "cpu": [cpu]}.get(cfg.whisper_backend, [gpu, cpu])

    out_json = Path(str(out_base) + ".json")
    last_err = ""
    for label, exe, extra in attempts:
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

        rc = run_logged([str(exe)] + base + extra, log, cancel, on_line=on_line)
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
