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
WANT="ref=$WHISPER_REF arch=$ARCH opencl=adreno"
if [ -x "$DST/whisper-cli.bin" ] && [ "$(cat "$DST/BUILD_INFO" 2>/dev/null)" = "$WANT" ]; then
    echo "  이미 빌드되어 있습니다 ($WANT)"
else
    if [ ! -d "$SRC/.git" ]; then
        git clone -q --depth 1 --branch "$WHISPER_REF" https://github.com/ggml-org/whisper.cpp "$SRC" || fail "소스 다운로드 실패"
    else
        git -C "$SRC" fetch -q --depth 1 origin tag "$WHISPER_REF" && git -C "$SRC" checkout -q "$WHISPER_REF"
    fi
    rm -rf "$SRC/build"
    cmake -S "$SRC" -B "$SRC/build" -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
        -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_SERVER=OFF -DWHISPER_BUILD_EXAMPLES=ON \
        -DGGML_OPENMP=OFF -DGGML_NATIVE=OFF -DGGML_CPU_ARM_ARCH="$ARCH" \
        -DGGML_OPENCL=ON -DGGML_OPENCL_USE_ADRENO_KERNELS=ON -DGGML_OPENCL_EMBED_KERNELS=ON \
        || fail "cmake 설정 실패"
    cmake --build "$SRC/build" -j"$(nproc)" --target whisper-cli || fail "컴파일 실패"
    cp "$SRC/build/bin/whisper-cli" "$DST/whisper-cli.bin"
    echo "$WANT" >"$DST/BUILD_INFO"
fi
# Ubuntu 안에서도 같은 드라이버 경로로 실행되도록 감싸는 스크립트
cat >"$DST/whisper-cli" <<EOF
#!$PREFIX/bin/bash
# autosub: Adreno GPU용 whisper-cli (setup-gpu.sh가 생성)
export LD_LIBRARY_PATH="${OCL_LD:-$PREFIX/lib}"
export GGML_OPENCL_KERNEL_CACHE_DIR="$DST/kernel-cache"
exec "$DST/whisper-cli.bin" "\$@"
EOF
chmod +x "$DST/whisper-cli"
mkdir -p "$DST/kernel-cache"

step "4/5 GPU 시험 (첫 실행은 그래픽 칩용 코드를 만드느라 몇 분 걸릴 수 있음)"
[ -f "$MODEL" ] || fail "Whisper 모델이 없습니다. setup-android.sh를 먼저 실행하세요"
SAMPLE="$SRC/samples/jfk.wav"
[ -f "$SAMPLE" ] || fail "시험용 음성 파일이 없습니다: $SAMPLE"
run_test() {   # run_test <이름> <명령...>
    local name="$1"; shift
    local t0 out
    t0=$(date +%s)
    out=$("$@" -m "$MODEL" -f "$SAMPLE" -l en -t 8 -nt 2>&1)
    echo "$out" | grep -iE "opencl|adreno|gpu|device|error|fail" | head -15 | sed 's/^/    /'
    if echo "$out" | grep -qi "ask not what your country" && echo "$out" | grep -qi "adreno"; then
        echo "  [$name] 성공 ($(( $(date +%s) - t0 ))초)"
        return 0
    fi
    echo "$out" | tail -5 | sed 's/^/    /'
    echo "  [$name] 실패"
    return 1
}
run_test "Termux" "$DST/whisper-cli" || fail "GPU로 Whisper 실행 실패"
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
