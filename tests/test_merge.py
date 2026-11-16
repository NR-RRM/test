from autosub.config import Config
from autosub.merge import merge
from autosub.model import Word
from autosub.postprocess import build_cues, wrap


def W(text, t, src="whisper", seg=0, p=0.9):
    return Word(text, t, t + 0.3, prob=p, source=src, seg=seg)


def seq(text, t0, src, seg=0, step=0.4, p=0.9):
    return [W(x, t0 + i * step, src, seg, p) for i, x in enumerate(text.split())]


def test_missing_whisper_line_is_inserted():
    wh = seq("Hello there.", 0, "whisper", 0) + seq("See you tomorrow.", 10, "whisper", 1)
    pk = seq("Hello there.", 0, "parakeet") + seq("I can hear you whispering.", 5, "parakeet") + seq("See you tomorrow.", 10, "parakeet")
    review = []
    out = merge(wh, pk, review)
    assert " ".join(w.text for w in out) == "Hello there. I can hear you whispering. See you tomorrow."
    assert [r.kind for r in review] == ["누락의심"]


def test_hallucination_in_silence_removed():
    wh = seq("Good night.", 0, "whisper", 0) + seq("Thank you for watching.", 30, "whisper", 1)
    pk = seq("Good night.", 0, "parakeet")
    review = []
    out = merge(wh, pk, review)
    assert " ".join(w.text for w in out) == "Good night."
    assert review[0].kind == "환각제거"


def test_repeated_loop_collapsed():
    wh = seq("Go.", 0, "whisper", 0)
    for i in range(1, 6):
        wh += seq("I am here.", 2 + i * 2, "whisper", i)
    pk = seq("Go.", 0, "parakeet") + seq("I am here.", 4, "parakeet")
    review = []
    out = merge(wh, pk, review)
    assert " ".join(w.text for w in out) == "Go. I am here."
    assert any(r.kind == "환각제거" for r in review)


def test_parakeet_timing_used_for_matched_words():
    wh = [W("Hello", 1.0), W("world.", 1.0)]
    pk = [W("Hello", 1.2, "parakeet"), W("world.", 1.7, "parakeet")]
    out = merge(wh, pk, [])
    assert [w.start for w in out] == [1.2, 1.7]


def test_cue_rules():
    cfg = Config()
    words = seq("This is a fairly long sentence that should definitely be wrapped onto two lines for reading.", 0, "both", step=0.25)
    cues = build_cues(words, cfg, [])
    for c in cues:
        lines = c.text.split("\n")
        assert len(lines) <= 2 and all(len(l) <= 42 for l in lines)
        assert c.end - c.start >= cfg.min_duration
    for a, b in zip(cues, cues[1:]):
        assert a.end <= b.start


def test_wrap_balanced():
    assert wrap("short", 42) == "short"
    l1, l2 = wrap("what your country can do for you, ask what you can do for your country.", 42).split("\n")
    assert l1.endswith(",")
