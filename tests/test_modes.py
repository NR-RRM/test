from pathlib import Path

from autosub.config import Config, load_config
from autosub.merge import parakeet_only
from autosub.model import Word
from autosub.pipeline import output_paths


def test_mode_resolution():
    c = Config()
    assert c.mode() == "both"
    c.use_parakeet = False
    assert c.mode() == "whisper"
    c.engine_mode = "parakeet"
    assert c.mode() == "parakeet"
    c.engine_mode = "garbage"
    assert c.mode() == "whisper"


def test_load_config_from_path(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"engine_mode": "parakeet", "whisper_threads": 6, "unknown": 1}', encoding="utf-8")
    c = load_config(p)
    assert c.mode() == "parakeet" and c.whisper_threads == 6


def test_output_paths_out_dir(tmp_path):
    v = Path("/x/My Show S01E01.mkv")
    assert output_paths(v)[0] == Path("/x/My Show S01E01.en.srt")
    srt, rev = output_paths(v, tmp_path)
    assert srt == tmp_path / "My Show S01E01.en.srt" and rev == tmp_path / "My Show S01E01.review.txt"


def test_parakeet_only_trims_runaway_and_keeps_order():
    ws = [Word("Hi.", 0, 0.3, source="parakeet")]
    ws += [Word("no", 1 + i * 0.2, 1.1 + i * 0.2, source="parakeet") for i in range(8)]
    ws += [Word(",", 3, 3, source="parakeet"), Word("bye", 3.5, 3.8, source="parakeet")]
    review = []
    out = parakeet_only(ws, review)
    assert [w.text for w in out] == ["Hi.", "no", "no", "no", "bye"]
    assert review and review[0].kind == "환각제거"
    assert all(b.start >= a.start for a, b in zip(out, out[1:]))
