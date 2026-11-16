#!/data/data/com.termux/files/usr/bin/bash
# 진행 중인 자막 작업 취소 (알림의 '취소' 버튼이 실행)
. "$(dirname "$(readlink -f "$0")")/common.sh"
pid=$(cat "$STATE/job.pid" 2>/dev/null) || { echo "진행 중인 작업이 없습니다"; exit 0; }
touch "$STATE/cancelled"
pgid=$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ')
pgid=${pgid:-$pid}
kill -TERM -- "-$pgid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
for _ in 1 2 3 4 5; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
done
kill -KILL -- "-$pgid" 2>/dev/null
echo "취소했습니다"
