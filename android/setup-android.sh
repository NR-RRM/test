#!/data/data/com.termux/files/usr/bin/bash
# 갤럭시(안드로이드) 설치 스크립트. Termux에서 실행:  bash ~/autosub/android/setup-android.sh
# 여러 번 실행해도 안전합니다 (이미 된 단계는 건너뜀). 업데이트 후에도 다시 실행하세요.
set -eo pipefail
. "$(dirname "$(readlink -f "$0")")/common.sh"
step() { echo; echo "=== $* ==="; }

if [ -z "${PREFIX:-}" ] || [[ "$PREFIX" != *com.termux* ]]; then
    echo "Termux 앱 안에서 실행하세요 (Ubuntu proot 안이 아니라)."; exit 1
fi

step "1/6 저장소 권한"
if [ ! -d "$SHARED/Download" ] || ! ls "$SHARED/Download" >/dev/null 2>&1; then
    echo "  '파일 및 미디어' 권한 요청 창이 뜨면 [허용]을 누르세요."
    termux-setup-storage || true
    for _ in $(seq 1 30); do ls "$SHARED/Download" >/dev/null 2>&1 && break; sleep 1; done
fi
ls "$SHARED/Download" >/dev/null 2>&1 && echo "  저장소 접근 OK" \
    || echo "  ※ 저장소에 접근할 수 없습니다. 설정 → 애플리케이션 → Termux → 권한에서 '파일 및 미디어'를 허용하세요."

step "2/6 Termux 패키지"
# 설정 파일 덮어쓰기 질문(openssl.cnf 등)이 뜨지 않도록 새 버전을 자동 선택
APT_OPTS=(-o Dpkg::Options::=--force-confnew -o Dpkg::Options::=--force-confdef)
pkg update -y "${APT_OPTS[@]}" </dev/null || true
pkg upgrade -y "${APT_OPTS[@]}" </dev/null || true
pkg install -y "${APT_OPTS[@]}" proot-distro termux-api util-linux coreutils findutils procps git </dev/null

step "3/6 Termux:API 앱 확인 (알림용)"
if timeout 15 termux-battery-status >/dev/null 2>&1; then
    echo "  Termux:API OK"
else
    echo "  ※ Termux:API 앱이 응답하지 않습니다. F-Droid에서 'Termux:API' 앱을 설치하세요."
    echo "    (없어도 자막은 만들어지지만 진행률·완료 알림이 뜨지 않습니다)"
fi

step "4/6 Ubuntu 설치 (proot-distro, 약 500MB)"
# 설치 여부는 실제로 들어가 보고 판단 (proot-distro 버전마다 설치 폴더 위치가 다름)
if proot-distro login "$DISTRO" -- true </dev/null >/dev/null 2>&1; then
    echo "  이미 설치되어 있습니다"
elif ! proot-distro install "$DISTRO"; then
    # 예전에 설치하다 끊겨서 망가진 경우: 새로 설치
    echo "  기존 Ubuntu가 제대로 동작하지 않아 다시 설치합니다"
    proot-distro reset "$DISTRO"
fi
proot-distro login "$DISTRO" -- true </dev/null || { echo "!! Ubuntu 실행 실패. 이 화면을 캡처해서 보내 주세요."; exit 1; }

step "5/6 Ubuntu 안에 엔진/모델 설치"
proot-distro login "$DISTRO" --bind "$AUTOSUB_DIR:$AUTOSUB_DIR" -- \
    env AUTOSUB_VENV="$VENV" bash "$AUTOSUB_DIR/android/setup-ubuntu.sh" "$AUTOSUB_DIR"

step "6/6 공유 메뉴·명령어 연결"
[ -f "$CONFIG_FILE" ] || { cp "$AUTOSUB_DIR/android/config-android.default.json" "$CONFIG_FILE"; echo "  설정 파일 생성: $CONFIG_FILE"; }
mkdir -p "$HOME/bin"
for h in termux-file-editor termux-url-opener; do
    f="$HOME/bin/$h"
    if [ -f "$f" ] && ! grep -q "autosub" "$f"; then
        mv "$f" "$f.bak.$(date +%s)"; echo "  기존 $h 를 백업했습니다"
    fi
    printf '#!/data/data/com.termux/files/usr/bin/bash\nexec bash "%s/android/share-handler.sh" "$@"\n' "$AUTOSUB_DIR" >"$f"
    chmod +x "$f"
done
for c in run:autosub scan:autosub-scan bench:autosub-bench cancel:autosub-cancel; do
    ln -sf "$AUTOSUB_DIR/android/${c%%:*}.sh" "$PREFIX/bin/${c#*:}"
done
# Termux:Widget(선택) 홈 화면 바로가기
mkdir -p "$HOME/.shortcuts"
printf '#!/data/data/com.termux/files/usr/bin/bash\nbash "%s/android/scan.sh"\nread -r -t 60 -p "엔터를 누르면 닫힙니다 " _\n' \
    "$AUTOSUB_DIR" >"$HOME/.shortcuts/자막-폴더처리"
chmod +x "$HOME/.shortcuts/자막-폴더처리"
echo "  명령어: autosub 영상.mp4 / autosub-scan [폴더] / autosub-bench 영상 / autosub-cancel"

echo
echo "설치 완료!"
echo "  · 갤러리/내 파일에서 영상 → 공유 → Termux → '편집(Edit)'"
echo "  · 먼저 벤치마크:  autosub-bench /sdcard/Movies/영상.mkv"
