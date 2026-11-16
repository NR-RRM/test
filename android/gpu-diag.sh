#!/data/data/com.termux/files/usr/bin/bash
# GPU(OpenCL) whisper-cli 충돌 원인 진단. 사용: bash ~/autosub/android/gpu-diag.sh
# 결과 요약을 화면에 보여주고, 전체는 ~/.autosub/logs/gpu-diag.txt 에 저장한다.
. "$(dirname "$(readlink -f "$0")")/common.sh"
DST="$AUTOSUB_DIR/engines/whisper-gpu"
BIN="$DST/whisper-cli.bin"
MODEL="$AUTOSUB_DIR/models/ggml-large-v3-turbo-q8_0.bin"
SAMPLE="$HOME/.cache/autosub/whisper.cpp-gpu/samples/jfk.wav"
OUT="$STATE/logs/gpu-diag.txt"
[ -x "$BIN" ] || { echo "GPU 빌드가 없습니다. 먼저 setup-gpu.sh를 실행하세요."; exit 1; }
LD=$(grep -m1 '^export LD_LIBRARY_PATH=' "$DST/whisper-cli" | sed 's/^export LD_LIBRARY_PATH=//; s/"//g')
ARGS=(-m "$MODEL" -f "$SAMPLE" -l en -t 8 -nt)
: >"$OUT"

echo "=== 1/3 같은 빌드를 CPU로 실행 (-ng) ==="
out=$(env LD_LIBRARY_PATH="$LD" "$BIN" "${ARGS[@]}" -ng 2>&1); rc=$?
printf '### 1 CPU (-ng) rc=%s\n%s\n\n' "$rc" "$out" >>"$OUT"
if [ $rc -eq 0 ] && echo "$out" | grep -qi "ask not"; then
    echo "  CPU로는 정상 → 빌드는 문제없고 GPU 쪽 문제"
else
    echo "  CPU로도 실패 (종료코드 $rc) → GPU가 아니라 Termux 빌드 자체 문제"
    echo "$out" | tail -4 | sed 's/^/    /'
fi

echo
echo "=== 2/3 디버거로 충돌 위치 확인 ==="
pkg install -y gdb </dev/null >/dev/null 2>&1 || true
if have gdb; then
    bt=$(env LD_LIBRARY_PATH="$LD" GGML_OPENCL_KERNEL_CACHE_DIR=off timeout 600 gdb -q -batch \
        -ex "set startup-with-shell off" -ex "set pagination off" -ex "set confirm off" \
        -ex "handle SIGPIPE nostop noprint" -ex run -ex "bt 30" -ex "info registers pc" \
        --args "$BIN" "${ARGS[@]}" 2>&1)
    printf '### 2 gdb\n%s\n\n' "$bt" >>"$OUT"
    echo "$bt" | grep -E "^Thread .* received signal|^Program received|^#[0-9]+ " | head -20 | cut -c1-160 | sed 's/^/  /'
else
    echo "  gdb 설치 실패 — 건너뜀"
fi

echo
echo "=== 3/3 OpenCL 장치 정보 ==="
info=$(env LD_LIBRARY_PATH="$LD" timeout 30 clinfo 2>&1)
printf '### 3 clinfo\n%s\n' "$info" >>"$OUT"
echo "$info" | grep -iE "^ *(Device Name|Driver Version|Max memory allocation|Global memory size|Max work group size|Preferred work group size multiple|Max sub-groups)" \
    | head -8 | sed 's/^ */  /'
echo
echo "이 화면을 캡처해서 보내 주세요. (전체 기록: $OUT)"
