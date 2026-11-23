#!/usr/bin/env bash
# ~/.korail 의 로그인 정보를 읽고, 화면이 꺼져도 멈추지 않게 wake-lock 을 건 뒤 실행.
cd "$(dirname "$0")"
[ -f "$HOME/.korail" ] && source "$HOME/.korail"
command -v termux-wake-lock >/dev/null && termux-wake-lock
python -m korail_watch.watcher "$@"
status=$?
command -v termux-wake-unlock >/dev/null && termux-wake-unlock
exit $status
