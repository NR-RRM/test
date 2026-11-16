#!/data/data/com.termux/files/usr/bin/bash
# 세 가지 엔진 모드(Parakeet 단독 / Whisper 단독 / 교차검증) 속도 비교.
# 사용: bench.sh 영상 [--threads 6] [--beam 1] [--start 600] [--seconds 300]
# 결과: 영상 옆 "영상이름.bench/" 폴더에 모드별 자막과 bench-report.txt
. "$(dirname "$(readlink -f "$0")")/common.sh"
[ -f "${1:-}" ] || { echo "사용: $(basename "$0") 영상 [--threads N] [--beam N]"; exit 2; }
video=$(readlink -f "$1"); shift
is_charging || echo "※ 충전기를 연결하고 실행하는 것을 권장합니다 (발열로 느려질 수 있음)"
have termux-wake-lock && termux-wake-lock
notify "벤치마크 실행 중" "$(basename "$video") · 5분 샘플, 수 분~수십 분 걸림" --ongoing
in_ubuntu "$(dirname "$video")" -- -m autosub.bench "$video" "$@" 2>&1 | tee "$STATE/logs/bench_$(date +%Y%m%d_%H%M%S).log"
rc=${PIPESTATUS[0]}
have termux-wake-unlock && termux-wake-unlock
report="${video%.*}.bench/bench-report.txt"
if [ "$rc" -eq 0 ]; then
    notify_done "벤치마크 완료" "$report"
    echo; echo "보고서 내용을 그대로 복사해서 Claude에게 보내 주세요: $report"
else
    notify_done "벤치마크 실패" "로그: $STATE/logs"
fi
exit "$rc"
