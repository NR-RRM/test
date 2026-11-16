# shellcheck shell=bash disable=SC2034
# 안드로이드(Termux) 스크립트 공용 설정. 다른 스크립트에서 source 해서 쓴다.

AUTOSUB_DIR="${AUTOSUB_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
DISTRO="${AUTOSUB_DISTRO:-ubuntu}"
VENV="${AUTOSUB_VENV:-/opt/autosub-venv}"
STATE="${AUTOSUB_STATE:-$HOME/.autosub}"
CONFIG_FILE="${AUTOSUB_CONFIG:-$AUTOSUB_DIR/config-android.json}"
SHARED="${AUTOSUB_SHARED:-/storage/emulated/0}"
# 원본 위치를 모르는 공유 파일의 자막 저장 폴더
FALLBACK_OUT="${AUTOSUB_FALLBACK_OUT:-$SHARED/Download/AutoSub}"
NOTIFY_ID="autosub"
mkdir -p "$STATE/logs"

have() { command -v "$1" >/dev/null 2>&1; }

# Termux:API 앱이 없으면 termux-notification이 멈추므로 timeout으로 감싼다.
notify() {   # notify <제목> <내용> [추가 옵션...]
    local title="$1" content="$2"; shift 2
    have termux-notification || return 0
    timeout 10 termux-notification --id "$NOTIFY_ID" --title "$title" --content "$content" \
        --alert-once --priority low "$@" >/dev/null 2>&1 || true
}

notify_done() {   # 완료/실패 알림은 따로 남겨 둔다 (진행 알림은 지움)
    local title="$1" content="$2"; shift 2
    have termux-notification || return 0
    timeout 10 termux-notification-remove "$NOTIFY_ID" >/dev/null 2>&1 || true
    timeout 10 termux-notification --id "autosub-done-$(date +%s)" --title "$title" \
        --content "$content" --priority high "$@" >/dev/null 2>&1 || true
}

# Ubuntu(proot) 안에서 autosub 파이썬 모듈 실행: in_ubuntu <추가 bind 폴더...> -- <python 인자...>
# 경로가 Termux와 똑같이 보이도록 같은 경로로 bind 한다.
in_ubuntu() {
    local binds=(--bind "$AUTOSUB_DIR:$AUTOSUB_DIR")
    while [ $# -gt 0 ] && [ "$1" != "--" ]; do
        [ -d "$1" ] && binds+=(--bind "$1:$1")
        shift
    done
    [ "${1:-}" = "--" ] && shift
    if [ -n "${AUTOSUB_PYTHON:-}" ]; then   # 테스트용: proot 없이 직접 실행
        env PYTHONPATH="$AUTOSUB_DIR" AUTOSUB_CONFIG="$CONFIG_FILE" "$AUTOSUB_PYTHON" "$@"
        return
    fi
    proot-distro login "$DISTRO" "${binds[@]}" -- \
        env PYTHONPATH="$AUTOSUB_DIR" AUTOSUB_CONFIG="$CONFIG_FILE" PYTHONUNBUFFERED=1 \
        HOME=/root LANG=C.UTF-8 "$VENV/bin/python" "$@"
}

fmt_min() {   # 초 → "12분" / "1시간 5분"
    local s=$1
    if [ "$s" -ge 3600 ]; then echo "$((s / 3600))시간 $(((s % 3600) / 60))분"
    elif [ "$s" -ge 60 ]; then echo "$((s / 60))분"
    else echo "${s}초"; fi
}

is_charging() {
    have termux-battery-status || return 0
    timeout 10 termux-battery-status 2>/dev/null | grep -Eq '"plugged": *"(PLUGGED|AC|USB|WIRELESS)'
}
