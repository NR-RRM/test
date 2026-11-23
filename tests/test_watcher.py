import pytest
from korail2 import SoldOutError

from korail_watch.watcher import Watcher, WatchConfig, parse_args


class FakeTrain:
    def __init__(self, no, dep_time, gen="13", spe="13", wait=0):
        self.train_no, self.dep_time = no, dep_time
        self.general_seat, self.special_seat, self.wait = gen, spe, wait
    def has_general_seat(self): return self.general_seat == "11"
    def has_special_seat(self): return self.special_seat == "11"
    def has_seat(self): return self.has_general_seat() or self.has_special_seat()
    def has_waiting_list(self): return self.wait == 9


class FakeClient:
    def __init__(self, rounds, sold_out_on=()):
        self.rounds, self.sold_out_on, self.reserved = list(rounds), set(sold_out_on), []
    def search_train(self, *a, **k):
        return self.rounds.pop(0) if self.rounds else []
    def reserve(self, train, **k):
        if train.train_no in self.sold_out_on:
            raise SoldOutError("ERR211161")
        self.reserved.append(train.train_no)
        return f"RSV-{train.train_no}"


def cfg(**kw):
    base = dict(dep="서울", arr="부산", date="20261224", interval=5, max_attempts=5)
    base.update(kw)
    return WatchConfig(**base)


def run(client, c):
    msgs, sleeps = [], []
    rsv = Watcher(client, c, notify=msgs.append, sleep=sleeps.append).run()
    return rsv, msgs, sleeps


def test_reserves_when_seat_appears():
    client = FakeClient([[FakeTrain("101", "080000")], [FakeTrain("101", "080000", gen="11")]])
    rsv, msgs, sleeps = run(client, cfg())
    assert rsv == "RSV-101" and len(sleeps) == 1 and "예약 성공" in msgs[0]


def test_time_window_and_train_filter():
    trains = [FakeTrain("101", "060000", gen="11"), FakeTrain("103", "090000", gen="11"),
              FakeTrain("105", "093000", gen="11")]
    rsv, _, _ = run(FakeClient([trains]), cfg(start_time="080000", end_time="100000", train_nos={"105"}))
    assert rsv == "RSV-105"


def test_general_only_ignores_special():
    rsv, _, _ = run(FakeClient([[FakeTrain("101", "080000", spe="11")]]), cfg(seat_option="GENERAL_ONLY", max_attempts=1))
    assert rsv is None


def test_sold_out_race_falls_through_to_next():
    trains = [FakeTrain("101", "080000", gen="11"), FakeTrain("103", "090000", gen="11")]
    rsv, _, _ = run(FakeClient([trains], sold_out_on={"101"}), cfg())
    assert rsv == "RSV-103"


def test_waiting_list_only_when_enabled():
    t = [FakeTrain("101", "080000", wait=9)]
    assert run(FakeClient([t]), cfg(max_attempts=1))[0] is None
    assert run(FakeClient([t]), cfg(max_attempts=1, try_waiting=True))[0] == "RSV-101"


def test_min_interval_enforced():
    with pytest.raises(ValueError):
        Watcher(FakeClient([]), cfg(interval=1), notify=print)
    with pytest.raises(SystemExit):
        parse_args(["서울", "부산", "20261224", "--interval", "1"])


def test_parse_args():
    c = parse_args(["서울", "부산", "20261224", "--from", "08:00", "--to", "1030", "--train", "101"])
    assert (c.start_time, c.end_time, c.train_nos) == ("080000", "103000", {"101"})
