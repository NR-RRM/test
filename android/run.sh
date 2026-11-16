#!/data/data/com.termux/files/usr/bin/bash
# 영상 → 영어 자막. 사용: run.sh [--mode both|whisper|parakeet] 영상 [영상2 ...]
# 알림으로 진행률을 보여주고, 화면이 꺼져도 계속되도록 wake lock을 잡는다.
# 여러 개를 동시에 공유하면 차례로 처리한다 (한 번에 하나만 실행).
set -u
. "$(dirname "$(readlink -f "$0")")/common.sh"

MODE_ARGS=()
if [ "${1:-}" = "--mode" ]; then MODE_ARGS=(--mode "$2"); shift 2; fi
[ $# -gt 0 ] || { echo "사용: $(basename "$0") [--mode both|whisper|parakeet] 영상 [영상2 ...]"; exit 2; }

# ~/downloads 로 복사된 공유 파일이면, 내장 저장소에서 같은 이름·크기의 원본을 찾는다.
# 찾으면 원본 옆에 자막을 만들고 복사본은 지운다.
find_original() {
    local f="$1" name size
    case "$f" in "$HOME"/*) ;; *) return 1 ;; esac
    [ -d "$SHARED" ] || return 1
    name=$(basename "$f"); size=$(stat -c %s "$f" 2>/dev/null) || return 1
    find "$SHARED" -path "$SHARED/Android" -prune -o -type f -name "$name" -size "${size}c" -print 2>/dev/null \
        | head -n 1
}

process_one() {
    local in="$1" video out_dir="" copy="" name log rc start pid
    video=$(readlink -f "$in") || video="$in"
    [ -f "$video" ] || { echo "!! 파일이 없습니다: $in"; notify_done "자막 실패" "파일이 없습니다: $(basename "$in")"; return 1; }

    case "$video" in
        "$HOME"/*)
            local orig
            orig=$(find_original "$video")
            if [ -n "$orig" ]; then
                echo "원본을 찾았습니다: $orig (자막을 원본 옆에 만듭니다)"
                copy="$video"; video="$orig"
            else
                out_dir="$FALLBACK_OUT"; mkdir -p "$out_dir"
                echo "원본 위치를 알 수 없어 자막을 $out_dir 에 저장합니다"
            fi ;;
    esac
    name=$(basename "$video")
    log="$STATE/logs/$(date +%Y%m%d_%H%M%S)_${name%.*}.log"
    echo "로그: $log"

    local args=("${MODE_ARGS[@]}")
    [ -n "$out_dir" ] && args+=(--out-dir "$out_dir")

    local charge=""
    is_charging || charge=" · 충전기 연결 권장"
    notify "자막 준비 중" "$name$charge" --ongoing \
        --button1 "취소" --button1-action "bash $AUTOSUB_DIR/android/cancel.sh"

    start=$(date +%s)
    # 새 세션(프로세스 그룹)으로 실행해야 취소 시 whisper-cli까지 한 번에 끝낼 수 있다.
    setsid bash -c '. "$1/android/common.sh"; shift; in_ubuntu "$@"' _ "$AUTOSUB_DIR" \
        "$(dirname "$video")" ${out_dir:+"$out_dir"} -- -m autosub.cli "${args[@]}" "$video" \
        >"$log" 2>&1 </dev/null &
    pid=$!
    echo "$pid" >"$STATE/job.pid"

    local last_pct=-1 last_t=0 line pct msg now el eta
    while IFS= read -r line; do
        printf '%s\n' "$line"
        if [[ "$line" =~ ^\ *\[\ *([0-9]+)%\]\ ?(.*)$ ]]; then
            pct=${BASH_REMATCH[1]}; msg=${BASH_REMATCH[2]}
            now=$(date +%s)
            if [ "$pct" != "$last_pct" ] && [ $((now - last_t)) -ge 3 ]; then
                el=$((now - start)); eta=""
                [ "$pct" -ge 3 ] && eta=" · 남은 시간 약 $(fmt_min $((el * (100 - pct) / pct)))"
                notify "자막 생성 중 $pct%" "$name · $msg$eta" --ongoing \
                    --button1 "취소" --button1-action "bash $AUTOSUB_DIR/android/cancel.sh" &
                last_pct=$pct; last_t=$now
            fi
        fi
    done < <(tail -n +1 -F --pid="$pid" "$log" 2>/dev/null)
    wait "$pid"; rc=$?
    rm -f "$STATE/job.pid"
    wait  # 백그라운드 알림 호출 정리

    el=$(( $(date +%s) - start ))
    local srt review
    srt=$(grep -m1 '^-> .*\.en\.srt$' "$log" | cut -c4-)
    review=$(grep -m1 '^-> .*\.review\.txt$' "$log" | cut -c4-)
    if [ "$rc" -eq 0 ] && [ -n "$srt" ]; then
        [ -n "$copy" ] && rm -f "$copy"
        if [ -n "$out_dir" ] && [ "${AUTOSUB_KEEP_COPY:-0}" != "1" ] && [[ "$video" == "$HOME"/downloads/* ]]; then
            rm -f "$video"   # 원본을 못 찾은 공유 복사본: 자막만 남기고 지움
        fi
        local cnt
        cnt=$(grep -m1 -o '자막 [0-9]*개, 검수 항목 [0-9]*건' "$log")
        echo "완료 ($(fmt_min "$el")): $srt"
        notify_done "자막 완료 ($(fmt_min "$el"))" "$(basename "$srt") · $cnt" \
            ${review:+--action "termux-open --content-type text/plain '$review'"}
        return 0
    fi
    if [ -f "$STATE/cancelled" ]; then
        rm -f "$STATE/cancelled"
        echo "취소했습니다"
        notify_done "자막 취소됨" "$name"
        return 130
    fi
    local err
    err=$(grep -m1 '^!! ' "$log" | cut -c4- | head -c 200)
    echo "!! 실패 (로그: $log)"
    notify_done "자막 실패" "$name · ${err:-로그 확인: $log}"
    return 1
}

# 터미널에서 Ctrl+C로 멈추면 백그라운드 작업도 같이 끝낸다
trap 'bash "$AUTOSUB_DIR/android/cancel.sh"' INT TERM HUP

exec 9>"$STATE/lock"
rc_all=0
for f in "$@"; do
    if ! flock -n 9; then
        echo "다른 작업이 끝나기를 기다립니다..."
        notify "자막 대기 중" "$(basename "$f") · 앞 작업이 끝나면 시작" --ongoing
        flock 9
    fi
    have termux-wake-lock && termux-wake-lock
    rm -f "$STATE/cancelled"
    process_one "$f" || rc_all=$?
    # 다음 작업이 lock을 잡은 뒤 다시 wake lock을 건다. 순서가 바뀌면 다음 작업이 wake lock 없이 돌게 된다.
    have termux-wake-unlock && termux-wake-unlock
    flock -u 9
    [ "$rc_all" -eq 130 ] && break
done
exit "$rc_all"
