#!/data/data/com.termux/files/usr/bin/bash
# Termux 공유 받기 처리기. ~/bin/termux-file-editor, ~/bin/termux-url-opener 가 이 스크립트를 부른다.
# - 파일 공유: Termux가 ~/downloads 에 복사한 뒤 그 경로를 넘겨준다
# - 텍스트 공유: 파일 경로나 file:// 주소면 그 파일을 처리
. "$(dirname "$(readlink -f "$0")")/common.sh"
arg="${1:-}"
case "$arg" in
    file://*) arg="${arg#file://}"; arg=$(printf '%b' "${arg//%/\\x}") ;;   # %20 같은 URL 인코딩 풀기
esac
if [ ! -f "$arg" ]; then
    echo "영상 파일이 아닙니다: ${1:-}"
    echo "(인터넷 주소는 지원하지 않습니다. 갤러리나 내 파일 앱에서 영상 파일을 공유하세요)"
    read -r -t 30 -p "엔터를 누르면 닫힙니다 " _ || true
    exit 1
fi
echo "=== 영어 자막 만들기 ==="
echo "이 창을 닫아도 되지만, Termux 앱 자체를 종료(알림의 Exit)하면 작업이 멈춥니다."
echo
bash "$AUTOSUB_DIR/android/run.sh" "$arg"
rc=$?
echo
read -r -t 60 -p "끝났습니다. 엔터를 누르면 닫힙니다 (60초 후 자동으로 닫힘) " _ || true
exit $rc
