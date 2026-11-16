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


def test_speech_regions_roundtrip():
    import numpy as np
    from autosub.audio import SR
    from autosub.speech_regions import condense, map_time, regions_from_words, remap_words

    ws = [Word("a", 10.0, 10.3), Word("b", 10.5, 10.9), Word("c", 12.0, 12.4),   # 한 구간
          Word("d", 40.0, 40.5), Word("e", 41.0, 41.2)]                           # 다른 구간
    regs = regions_from_words(ws, total=60.0, pad=0.8, merge_gap=2.5)
    assert len(regs) == 2
    assert regs[0][0] == 10.0 - 0.8 and abs(regs[0][1] - 13.2) < 1e-6
    audio = np.arange(60 * SR, dtype=np.float32)
    cond, segmap = condense(audio, regs, sep=0.4)
    assert abs(len(cond) / SR - ((13.2 - 9.2) + 0.4 + (42.0 - 39.2))) < 0.01
    # 압축 오디오의 표본이 원본의 같은 표본인지
    for orig_t in (10.0, 12.2, 40.25, 41.1):
        i = next(k for k, (c0, o0, ln) in enumerate(segmap) if o0 <= orig_t <= o0 + ln)
        c0, o0, _ = segmap[i]
        ct = c0 + (orig_t - o0)
        assert abs(map_time(ct, segmap) - orig_t) < 1e-6
        assert cond[int(round(ct * SR))] == audio[int(round(orig_t * SR))]
    # 구간 사이 무음에 떨어진 시간은 가까운 구간 끝으로
    gap_t = segmap[0][2] + 0.05
    assert abs(map_time(gap_t, segmap) - 13.2) < 1e-6
    assert abs(map_time(segmap[1][0] - 0.05, segmap) - 39.2) < 1e-6
    out = remap_words([Word("x", segmap[1][0] + 1.0, segmap[1][0] + 1.5)], segmap)
    assert abs(out[0].start - 40.2) < 1e-6 and abs(out[0].end - 40.7) < 1e-6


def test_speech_regions_edges():
    from autosub.speech_regions import map_time, regions_from_words
    assert regions_from_words([], 10.0) == []
    regs = regions_from_words([Word("a", 0.1, 0.4), Word("b", 9.8, 9.95)], total=10.0)
    assert regs[0][0] == 0.0 and regs[-1][1] == 10.0
    assert map_time(5.0, []) == 5.0
