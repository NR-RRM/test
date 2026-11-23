"""매진된 코레일 열차를 주기적으로 조회하다가 좌석이 나오면 예약(결제 전 '예약' 상태)까지 해주는 도구.

개인이 본인 승차권을 구하는 용도로만 사용하세요. 너무 짧은 간격의 조회는 서버에 부담을 주고
계정 제재를 받을 수 있어 최소 조회 간격을 강제합니다.
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Iterable, Optional

log = logging.getLogger("korail_watch")

MIN_INTERVAL_SEC = 5.0

SEAT_OPTIONS = ("GENERAL_FIRST", "GENERAL_ONLY", "SPECIAL_FIRST", "SPECIAL_ONLY")
TRAIN_TYPES = {
    "ALL": "109", "KTX": "100", "SAEMAEUL": "101", "MUGUNGHWA": "102",
    "ITX-CHEONGCHUN": "104", "AIRPORT": "105",
}


@dataclass
class WatchConfig:
    dep: str
    arr: str
    date: str                      # yyyyMMdd
    start_time: str = "000000"     # hhmmss, 이 시각 이후 출발
    end_time: str = "235959"       # hhmmss, 이 시각 이전 출발
    train_nos: set[str] = field(default_factory=set)  # 비어 있으면 시간대 내 전체
    train_type: str = "ALL"
    adults: int = 1
    children: int = 0
    seniors: int = 0
    seat_option: str = "GENERAL_FIRST"
    try_waiting: bool = False      # 예약대기도 신청할지
    interval: float = 10.0
    max_attempts: Optional[int] = None


def train_matches(train, cfg: WatchConfig) -> bool:
    if not (cfg.start_time <= train.dep_time <= cfg.end_time):
        return False
    if cfg.train_nos and train.train_no.lstrip("0") not in {n.lstrip("0") for n in cfg.train_nos}:
        return False
    return True


def seat_available(train, cfg: WatchConfig) -> bool:
    opt = cfg.seat_option
    if opt == "GENERAL_ONLY":
        ok = train.has_general_seat()
    elif opt == "SPECIAL_ONLY":
        ok = train.has_special_seat()
    else:
        ok = train.has_seat()
    if not ok and cfg.try_waiting:
        ok = train.has_waiting_list()
    return ok


def build_passengers(cfg: WatchConfig):
    from korail2 import AdultPassenger, ChildPassenger, SeniorPassenger
    ps = []
    if cfg.adults:
        ps.append(AdultPassenger(cfg.adults))
    if cfg.children:
        ps.append(ChildPassenger(cfg.children))
    if cfg.seniors:
        ps.append(SeniorPassenger(cfg.seniors))
    return ps


class Watcher:
    def __init__(self, client, cfg: WatchConfig,
                 notify: Callable[[str], None] = print,
                 sleep: Callable[[float], None] = time.sleep,
                 passengers=None):
        if cfg.interval < MIN_INTERVAL_SEC:
            raise ValueError(f"조회 간격은 최소 {MIN_INTERVAL_SEC}초 이상이어야 합니다.")
        self.client = client
        self.cfg = cfg
        self.notify = notify
        self.sleep = sleep
        self.passengers = passengers

    def _search(self) -> list:
        from korail2 import NoResultsError
        try:
            return self.client.search_train(
                self.cfg.dep, self.cfg.arr, self.cfg.date, self.cfg.start_time,
                train_type=TRAIN_TYPES.get(self.cfg.train_type, self.cfg.train_type),
                passengers=self.passengers, include_no_seats=True,
                include_waiting_list=self.cfg.try_waiting,
            )
        except NoResultsError:
            return []

    def _candidates(self, trains: Iterable) -> list:
        return [t for t in trains if train_matches(t, self.cfg) and seat_available(t, self.cfg)]

    def try_once(self):
        """한 번 조회해서 예약에 성공하면 Reservation 객체, 아니면 None."""
        from korail2 import KorailError, NeedToLoginError, SoldOutError
        for train in self._candidates(self._search()):
            log.info("좌석 발견: %s → 예약 시도", train)
            try:
                rsv = self.client.reserve(
                    train, passengers=self.passengers,
                    option=self.cfg.seat_option, try_waiting=self.cfg.try_waiting,
                )
            except SoldOutError:
                log.info("예약 직전에 다시 매진됨: %s", train.train_no)
                continue
            except NeedToLoginError:
                log.warning("세션 만료, 재로그인")
                self.client.login()
                continue
            except KorailError as e:
                log.warning("예약 실패 (%s): %s", train.train_no, e)
                continue
            return rsv
        return None

    def run(self):
        attempt = 0
        while self.cfg.max_attempts is None or attempt < self.cfg.max_attempts:
            attempt += 1
            try:
                rsv = self.try_once()
            except Exception as e:  # 네트워크 오류 등은 로그만 남기고 계속
                log.warning("조회 중 오류: %s", e)
                rsv = None
            if rsv is not None:
                self.notify(
                    "\a[예약 성공] %s\n코레일톡 앱 > 승차권 예약내역에서 결제 기한 안에 결제하세요. "
                    "(기한 내 미결제 시 자동 취소)" % rsv
                )
                return rsv
            log.info("[%d회] %s 좌석 없음, %.0f초 후 재조회",
                     attempt, datetime.now().strftime("%H:%M:%S"), self.cfg.interval)
            self.sleep(self.cfg.interval)
        log.info("최대 시도 횟수 도달, 종료")
        return None


def _hhmm(s: str) -> str:
    s = s.replace(":", "")
    if len(s) == 4:
        s += "00"
    if len(s) != 6 or not s.isdigit():
        raise argparse.ArgumentTypeError("시간은 HH:MM 또는 HHMM 형식")
    return s


def parse_args(argv=None) -> WatchConfig:
    p = argparse.ArgumentParser(description="코레일 매진 열차 빈자리 자동 예약")
    p.add_argument("dep", help="출발역 (예: 서울)")
    p.add_argument("arr", help="도착역 (예: 부산)")
    p.add_argument("date", help="출발일 YYYYMMDD")
    p.add_argument("--from", dest="start", type=_hhmm, default="000000", help="출발 시각 하한 HH:MM")
    p.add_argument("--to", dest="end", type=_hhmm, default="235959", help="출발 시각 상한 HH:MM")
    p.add_argument("--train", action="append", default=[], help="특정 열차번호만 (여러 번 지정 가능)")
    p.add_argument("--type", default="KTX", choices=list(TRAIN_TYPES))
    p.add_argument("--adults", type=int, default=1)
    p.add_argument("--children", type=int, default=0)
    p.add_argument("--seniors", type=int, default=0)
    p.add_argument("--seat", default="GENERAL_FIRST", choices=SEAT_OPTIONS)
    p.add_argument("--waiting", action="store_true", help="좌석 없으면 예약대기도 신청")
    p.add_argument("--interval", type=float, default=10.0, help=f"조회 간격(초), 최소 {MIN_INTERVAL_SEC}")
    p.add_argument("--max-attempts", type=int, default=None)
    a = p.parse_args(argv)
    if a.interval < MIN_INTERVAL_SEC:
        p.error(f"--interval 은 {MIN_INTERVAL_SEC}초 이상이어야 합니다.")
    if a.adults + a.children + a.seniors < 1:
        p.error("승객이 최소 1명 필요합니다.")
    return WatchConfig(
        dep=a.dep, arr=a.arr, date=a.date, start_time=a.start, end_time=a.end,
        train_nos=set(a.train), train_type=a.type, adults=a.adults, children=a.children,
        seniors=a.seniors, seat_option=a.seat, try_waiting=a.waiting,
        interval=a.interval, max_attempts=a.max_attempts,
    )


def default_notify(msg: str) -> None:
    """터미널 출력 + (Android Termux 에서 termux-api 가 있으면) 폰 알림/진동."""
    print(msg, flush=True)
    if shutil.which("termux-notification"):
        try:
            subprocess.run(["termux-notification", "--title", "코레일 예약 성공",
                            "--content", "결제 기한 안에 코레일톡 앱에서 결제하세요",
                            "--priority", "high", "--sound", "--vibrate", "500,300,500"],
                           timeout=10, check=False)
        except Exception as e:  # 알림 실패해도 예약은 이미 된 상태
            log.warning("알림 실패: %s", e)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    cfg = parse_args(argv)
    korail_id = os.environ.get("KORAIL_ID")
    korail_pw = os.environ.get("KORAIL_PW")
    if not korail_id or not korail_pw:
        sys.exit("환경변수 KORAIL_ID (회원번호/이메일/전화번호), KORAIL_PW 를 설정하세요.")
    from korail2 import Korail
    client = Korail(korail_id, korail_pw)
    if not client.logined:
        sys.exit("로그인 실패: 아이디/비밀번호를 확인하세요.")
    rsv = Watcher(client, cfg, notify=default_notify, passengers=build_passengers(cfg)).run()
    sys.exit(0 if rsv else 1)


if __name__ == "__main__":
    main()
