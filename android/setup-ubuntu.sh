#!/bin/bash
# Ubuntu(proot) 안에서 실행되는 설치 단계. setup-android.sh 가 자동으로 부른다.
# 사용: setup-ubuntu.sh <autosub 폴더>
set -euo pipefail
AUTOSUB_DIR="$1"
VENV="${AUTOSUB_VENV:-/opt/autosub-venv}"
WHISPER_REF="${WHISPER_REF:-v1.9.5}"
WSRC=/opt/whisper.cpp
export DEBIAN_FRONTEND=noninteractive
step() { echo; echo "=== [Ubuntu] $* ==="; }

step "1/4 패키지 설치 (python, ffmpeg, 빌드 도구)"
apt-get update -q
apt-get install -y -q --no-install-recommends python3 python3-venv python3-pip ffmpeg \
    build-essential cmake git curl ca-certificates

step "2/4 Python 환경 ($VENV)"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$AUTOSUB_DIR/requirements.txt"
"$VENV/bin/python" -c "import numpy, sherpa_onnx; print('  numpy', numpy.__version__, '/ sherpa-onnx', sherpa_onnx.__version__)"

step "3/4 whisper.cpp $WHISPER_REF 빌드 (CPU, 10~20분 걸릴 수 있음)"
DST="$AUTOSUB_DIR/engines/whisper/whisper-cli"
STAMP="$AUTOSUB_DIR/engines/whisper/BUILD_INFO"
# CPU가 지원하는 명령어를 보고 컴파일 옵션 결정 (-mcpu=native는 최신 코어를 모르는 컴파일러에서 실패할 수 있음)
FEATS=$(grep -m1 '^Features' /proc/cpuinfo || true)
ARCH="armv8.2-a+fp16"
case " $FEATS " in *" asimddp "*) ARCH="$ARCH+dotprod" ;; esac
case " $FEATS " in *" i8mm "*) ARCH="$ARCH+i8mm" ;; esac
WANT="ref=$WHISPER_REF arch=$ARCH"
if [ "$(uname -m)" != "aarch64" ]; then
    echo "  주의: aarch64가 아닙니다 ($(uname -m)). 기본 옵션으로 빌드합니다."
    ARCH_OPTS=()
    WANT="ref=$WHISPER_REF arch=native-$(uname -m)"
else
    ARCH_OPTS=(-DGGML_NATIVE=OFF -DGGML_CPU_ARM_ARCH="$ARCH")
fi
if [ -x "$DST" ] && [ "$(cat "$STAMP" 2>/dev/null)" = "$WANT" ] && "$DST" -h >/dev/null 2>&1; then
    echo "  이미 빌드되어 있습니다 ($WANT)"
else
    echo "  컴파일 옵션: $WANT"
    if [ ! -d "$WSRC/.git" ]; then
        git clone -q --depth 1 --branch "$WHISPER_REF" https://github.com/ggml-org/whisper.cpp "$WSRC"
    else
        git -C "$WSRC" fetch -q --depth 1 origin tag "$WHISPER_REF" && git -C "$WSRC" checkout -q "$WHISPER_REF"
    fi
    rm -rf "$WSRC/build"
    cmake -S "$WSRC" -B "$WSRC/build" -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
        -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_SERVER=OFF -DGGML_OPENMP=ON "${ARCH_OPTS[@]}" >/dev/null
    cmake --build "$WSRC/build" -j"$(nproc)" --target whisper-cli
    mkdir -p "$(dirname "$DST")"
    cp "$WSRC/build/bin/whisper-cli" "$DST"
    echo "$WANT" >"$STAMP"
fi
"$DST" -h 2>&1 | grep -q -- "-ojf" && echo "  whisper-cli OK"

step "4/4 모델 다운로드 (약 1.5GB, 이어받기 지원)"
dl() {   # dl <url> <파일> <최소 크기(바이트)>
    local url="$1" out="$2" min="$3" size
    mkdir -p "$(dirname "$out")"
    size=$(stat -c %s "$out" 2>/dev/null || echo 0)
    if [ "$size" -ge "$min" ]; then echo "  있음: $(basename "$out")"; return; fi
    echo "  받는 중: $(basename "$out")"
    curl -fL --retry 5 --retry-delay 3 -C - -o "$out" "$url" || curl -fL --retry 5 -o "$out" "$url"
}
M="$AUTOSUB_DIR/models"
dl https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q8_0.bin \
    "$M/ggml-large-v3-turbo-q8_0.bin" 800000000
HF=https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/resolve/main
PK="$M/parakeet-tdt-0.6b-v2-int8"
dl "$HF/encoder.int8.onnx" "$PK/encoder.int8.onnx" 600000000
dl "$HF/decoder.int8.onnx" "$PK/decoder.int8.onnx" 5000000
dl "$HF/joiner.int8.onnx" "$PK/joiner.int8.onnx" 1000000
dl "$HF/tokens.txt" "$PK/tokens.txt" 5000
echo
echo "  Ubuntu 쪽 설치 완료"
