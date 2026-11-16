#!/data/data/com.termux/files/usr/bin/bash
# 그래픽 칩(Adreno GPU)으로 Whisper를 돌리기 위한 설치. setup-android.sh 가 마지막에 부르고, 따로 실행해도 됨.
#   bash ~/autosub/android/setup-gpu.sh
# Ubuntu(glibc) 안에서는 안드로이드 그래픽 드라이버를 쓸 수 없어서, whisper.cpp를 Termux 쪽에서
# OpenCL로 따로 빌드하고 Ubuntu 안의 프로그램이 그것을 호출한다. 실패하면 지금처럼 CPU로 동작한다.
set -o pipefail
. "$(dirname "$(readlink -f "$0")")/common.sh"
WHISPER_REF="${WHISPER_REF:-v1.9.5}"
SRC="$HOME/.cache/autosub/whisper.cpp-gpu"
DST="$AUTOSUB_DIR/engines/whisper-gpu"
LOG="$STATE/logs/setup-gpu.log"
MODEL="$AUTOSUB_DIR/models/ggml-large-v3-turbo-q8_0.bin"
step() { echo; echo "=== [GPU] $* ==="; }
fail() { echo; echo "!! GPU 설정 실패: $*"; echo "   CPU로는 계속 정상 동작합니다. 이 로그를 보내 주세요: $LOG"; exit 1; }
mkdir -p "$DST" "$(dirname "$SRC")"
exec > >(tee "$LOG") 2>&1

step "1/5 빌드 도구·OpenCL 패키지"
APT_OPTS=(-o Dpkg::Options::=--force-confnew -o Dpkg::Options::=--force-confdef)
pkg install -y "${APT_OPTS[@]}" clang cmake make git python ocl-icd opencl-headers clinfo </dev/null \
    || fail "패키지 설치 실패"
pkg install -y "${APT_OPTS[@]}" opencl-vendor-driver </dev/null >/dev/null 2>&1 || true

step "2/5 그래픽 드라이버(OpenCL) 찾기"
# 폰마다 드라이버를 찾는 방법이 달라서 차례로 시험한다
VLIB="$DST/vendor-lib"
mkdir -p "$VLIB"
for d in /vendor/lib64 /system/vendor/lib64; do
    for f in "$d"/libOpenCL*.so "$d"/libCB.so "$d"/libgsl.so "$d"/libadreno_utils.so; do
        [ -r "$f" ] && cp -f "$f" "$VLIB/" 2>/dev/null
    done
done
OCL_LD=""; FOUND=""
for cand in "" "/vendor/lib64:$PREFIX/lib" "/system/vendor/lib64:$PREFIX/lib" "$VLIB:$PREFIX/lib"; do
    out=$(env ${cand:+LD_LIBRARY_PATH="$cand"} timeout 60 clinfo -l 2>&1)
    echo "  시도 [${cand:-기본}]: $(echo "$out" | tr '\n' ' ' | head -c 200)"
    if echo "$out" | grep -qi "adreno"; then OCL_LD="$cand"; FOUND=1; break; fi
done
[ -n "$FOUND" ] || fail "Adreno OpenCL 드라이버를 찾지 못했습니다"
echo "  찾음: LD_LIBRARY_PATH=${OCL_LD:-(기본)}"

step "3/5 whisper.cpp $WHISPER_REF GPU(OpenCL) 빌드 (10~20분)"
FEATS=$(grep -m1 '^Features' /proc/cpuinfo || true)
ARCH="armv8.2-a+fp16"
case " $FEATS " in *" asimddp "*) ARCH="$ARCH+dotprod" ;; esac
case " $FEATS " in *" i8mm "*) ARCH="$ARCH+i8mm" ;; esac
WANT="ref=$WHISPER_REF arch=$ARCH opencl=adreno patch=init-order"
if [ -x "$DST/whisper-cli.bin" ] && [ "$(cat "$DST/BUILD_INFO" 2>/dev/null)" = "$WANT" ]; then
    echo "  이미 빌드되어 있습니다 ($WANT)"
else
    if [ ! -d "$SRC/.git" ]; then
        git clone -q --depth 1 --branch "$WHISPER_REF" https://github.com/ggml-org/whisper.cpp "$SRC" || fail "소스 다운로드 실패"
    else
        git -C "$SRC" fetch -q --depth 1 origin tag "$WHISPER_REF" && git -C "$SRC" checkout -q "$WHISPER_REF"
    fi
    # ggml OpenCL 버그 수정 (초기화 전에 정렬값을 읽다가 충돌)
    python "$AUTOSUB_DIR/android/patches/ggml_opencl_init_order.py" "$SRC" || fail "소스 패치 실패"
    # 빌드 폴더는 남겨 둔다: 바뀐 파일만 다시 컴파일
    cmake -S "$SRC" -B "$SRC/build" -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
        -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_SERVER=OFF -DWHISPER_BUILD_EXAMPLES=ON \
        -DGGML_OPENMP=OFF -DGGML_NATIVE=OFF -DGGML_CPU_ARM_ARCH="$ARCH" \
        -DGGML_OPENCL=ON -DGGML_OPENCL_USE_ADRENO_KERNELS=ON -DGGML_OPENCL_EMBED_KERNELS=ON \
        || fail "cmake 설정 실패"
    cmake --build "$SRC/build" -j"$(nproc)" --target whisper-cli || fail "컴파일 실패"
    cp "$SRC/build/bin/whisper-cli" "$DST/whisper-cli.bin"
    echo "$WANT" >"$DST/BUILD_INFO"
fi
# Ubuntu 안에서도 같은 드라이버 경로로 실행되도록 감싸는 스크립트.
# write_wrapper "<환경변수들>" "<추가 옵션>"
write_wrapper() {
    {
        echo "#!$PREFIX/bin/bash"
        echo "# autosub: Adreno GPU용 whisper-cli (setup-gpu.sh가 생성). 시험 통과 설정: ${1:-기본} ${2:-}"
        echo "export LD_LIBRARY_PATH=\"${OCL_LD:-$PREFIX/lib}\""
        echo "export GGML_OPENCL_KERNEL_CACHE_DIR=\"$DST/kernel-cache\""
        for kv in $1; do echo "export $kv"; done
        # -h(옵션 확인)에는 추가 옵션을 붙이지 않는다
        echo "[ \"\$1\" = \"-h\" ] && exec \"$DST/whisper-cli.bin\" -h"
        echo "exec \"$DST/whisper-cli.bin\" \"\$@\" $2"
    } >"$DST/whisper-cli"
    chmod +x "$DST/whisper-cli"
}
mkdir -p "$DST/kernel-cache"

step "4/5 GPU 시험 (첫 실행은 그래픽 칩용 코드를 만드느라 몇 분 걸릴 수 있음)"
[ -f "$MODEL" ] || fail "Whisper 모델이 없습니다. setup-android.sh를 먼저 실행하세요"
SAMPLE="$SRC/samples/jfk.wav"
[ -f "$SAMPLE" ] || fail "시험용 음성 파일이 없습니다: $SAMPLE"
timeout 30 env ${OCL_LD:+LD_LIBRARY_PATH="$OCL_LD"} clinfo 2>/dev/null \
    | grep -iE "^ *(Platform Version|Driver Version|Device Version|Max memory allocation|Global memory size)" \
    | head -6 | sed 's/^ */  /'
N=0
run_test() {   # run_test <이름> <명령...>
    local name="$1"; shift
    local t0 out rc
    N=$((N + 1))
    t0=$(date +%s)
    out=$("$@" -m "$MODEL" -f "$SAMPLE" -l en -t 8 -nt 2>&1); rc=$?
    printf '%s\n' "$out" >"$STATE/logs/gpu-test-$N.txt"
    if [ "$rc" -eq 0 ] && echo "$out" | grep -qi "ask not what your country" && echo "$out" | grep -qi "adreno"; then
        if echo "$out" | grep -qi "no GPU found"; then
            echo "  [$name] GPU를 쓰지 않고 CPU로 처리됨"; return 1
        fi
        echo "  [$name] 성공 ($(( $(date +%s) - t0 ))초)"
        return 0
    fi
    local why="종료코드 $rc"
    case $rc in 139) why="$why (프로그램 충돌 SIGSEGV)" ;; 134) why="$why (중단 SIGABRT)" ;;
                137) why="$why (강제 종료됨, 메모리 부족 가능)" ;; 135) why="$why (SIGBUS)" ;; esac
    echo "  [$name] 실패: $why, $(( $(date +%s) - t0 ))초 — 마지막 출력:"
    echo "$out" | grep -v "^\s*$" | tail -8 | cut -c1-150 | sed 's/^/      /'
    return 1
}
# 드라이버·버전마다 문제가 되는 기능이 달라서, 기본 설정이 실패하면 하나씩 끄면서 다시 시험한다
VARIANTS=(
    "|"
    "GGML_OPENCL_ADRENO_XMEM_GEMM=0|"
    "GGML_OPENCL_ADRENO_XMEM_GEMM=0|-nfa"
    "GGML_OPENCL_ADRENO_XMEM_GEMM=0 GGML_OPENCL_DISABLE_FUSION=1 GGML_OPENCL_KERNEL_CACHE_DIR=off|-nfa"
)
OK_VARIANT=""
for v in "${VARIANTS[@]}"; do
    envs=${v%%|*}; args=${v#*|}
    write_wrapper "$envs" "$args"
    if run_test "Termux, 설정: ${envs:-기본} ${args}" "$DST/whisper-cli"; then OK_VARIANT="$v"; break; fi
done
[ -n "$OK_VARIANT" ] || fail "모든 설정에서 GPU 실행 실패 (각 시험의 전체 출력: $STATE/logs/gpu-test-*.txt)"
run_test "Termux 2회차(캐시)" "$DST/whisper-cli" || true
# 실제 파이프라인처럼 Ubuntu 안에서 호출
run_test "Ubuntu 안에서" proot-distro login "$DISTRO" --bind "$AUTOSUB_DIR:$AUTOSUB_DIR" -- "$DST/whisper-cli" \
    || fail "Termux에서는 되지만 Ubuntu 안에서 호출하면 실패"

step "5/5 설정 변경 (GPU 우선, 실패 시 CPU 자동 대체)"
[ -f "$CONFIG_FILE" ] || cp "$AUTOSUB_DIR/android/config-android.default.json" "$CONFIG_FILE"
in_ubuntu -- -c '
import json, sys
p = sys.argv[1]
c = json.load(open(p, encoding="utf-8"))
c.update(whisper_cli="engines/whisper-gpu/whisper-cli", whisper_cli_cpu="engines/whisper/whisper-cli",
         whisper_backend="auto")
json.dump(c, open(p, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
print("  설정 저장:", p)
' "$CONFIG_FILE" || fail "설정 파일 수정 실패"
echo
echo "GPU 설정 완료! 속도 비교:  autosub-bench /sdcard/Download/test.mp4"
echo "(CPU로 되돌리기:  autosub-bench ... --backend cpu  /  설정에서 \"whisper_backend\": \"cpu\")"
