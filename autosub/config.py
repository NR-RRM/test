from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    # 경로 (ROOT 기준 상대경로 허용)
    ffmpeg: str = "tools/ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    whisper_cli: str = "engines/whisper/whisper-cli.exe" if os.name == "nt" else "engines/whisper/whisper-cli"
    whisper_model: str = "models/ggml-large-v3-turbo-q8_0.bin"
    parakeet_dir: str = "models/parakeet-tdt-0.6b-v2-int8"

    # 엔진 설정
    whisper_backend: str = "auto"       # auto(GPU 시도 후 CPU) | gpu | cpu
    whisper_threads: int = 8
    whisper_beam_size: int = 5
    whisper_max_context: int = -1       # 반복 환각이 심하면 0
    language: str = "en"
    use_parakeet: bool = True           # 교차검증
    parakeet_threads: int = 4

    # 자막 규칙
    max_line_chars: int = 42
    max_lines: int = 2
    max_cps: float = 20.0
    min_duration: float = 1.0
    max_duration: float = 7.0
    min_gap: float = 0.084              # 약 2프레임
    end_padding: float = 0.25
    sentence_gap: float = 0.7           # 이 이상 쉬면 자막 분리

    # 출력
    keep_temp: bool = False

    @staticmethod
    def path(p: str) -> Path:
        """상대경로는 프로그램 폴더 기준. 'ffmpeg'처럼 이름만 있으면 PATH에서 찾는다."""
        q = Path(p)
        if q.is_absolute():
            return q
        if (ROOT / q).exists() or "/" in p or "\\" in p:
            return ROOT / q
        found = shutil.which(p)
        return Path(found) if found else q


CONFIG_FILE = ROOT / "config.json"


def load_config() -> Config:
    cfg = Config()
    if CONFIG_FILE.exists():
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        names = {f.name for f in fields(Config)}
        for k, v in data.items():
            if k in names:
                setattr(cfg, k, v)
    return cfg


def save_config(cfg: Config) -> None:
    CONFIG_FILE.write_text(json.dumps(asdict(cfg), indent=2, ensure_ascii=False), encoding="utf-8")
