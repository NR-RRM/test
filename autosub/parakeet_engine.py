from __future__ import annotations

from pathlib import Path

import numpy as np

from .audio import SR, split_points
from .model import Word
from .util import CancelToken


def transcribe(model_dir: Path, audio: np.ndarray, threads: int, log, cancel: CancelToken,
               progress) -> list[Word]:
    try:
        import sherpa_onnx
    except ImportError as e:
        raise RuntimeError("sherpa-onnx가 설치되지 않았습니다. setup.bat을 다시 실행하세요.") from e

    files = {k: model_dir / f"{k}.int8.onnx" for k in ("encoder", "decoder", "joiner")}
    tokens = model_dir / "tokens.txt"
    missing = [str(p) for p in [*files.values(), tokens] if not p.exists()]
    if missing:
        raise RuntimeError("Parakeet 모델 파일이 없습니다:\n" + "\n".join(missing))

    progress(0.0, "Parakeet 모델 로딩")
    rec = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(files["encoder"]), decoder=str(files["decoder"]), joiner=str(files["joiner"]),
        tokens=str(tokens), model_type="nemo_transducer", num_threads=threads)

    chunks = split_points(audio)
    log(f"[Parakeet] {len(chunks)}개 구간으로 분할하여 인식")
    words: list[Word] = []
    for i, (a, b) in enumerate(chunks):
        cancel.check()
        offset = a / SR
        st = rec.create_stream()
        st.accept_waveform(SR, audio[a:b])
        rec.decode_stream(st)
        r = st.result
        durs = list(getattr(r, "durations", []) or [])
        cur: Word | None = None
        for j, (tok, ts) in enumerate(zip(r.tokens, r.timestamps)):
            t0 = offset + float(ts)
            t1 = t0 + (float(durs[j]) if j < len(durs) and durs[j] > 0 else 0.08)
            if tok.startswith(" ") or cur is None:
                if cur is not None and cur.text:
                    words.append(cur)
                cur = Word(text=tok.strip(), start=t0, end=t1, source="parakeet")
            else:
                cur.text += tok
                cur.end = max(cur.end, t1)
        if cur is not None and cur.text:
            words.append(cur)
        progress((i + 1) / len(chunks), f"Parakeet {i + 1}/{len(chunks)} 구간")
    log(f"[Parakeet] 완료: 단어 {len(words)}개")
    return words
