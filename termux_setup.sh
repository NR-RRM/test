#!/data/data/com.termux/files/usr/bin/bash
# Termux(Android)용 최초 설치 스크립트. 프로젝트 폴더에서: bash termux_setup.sh
set -e
pkg update -y
pkg install -y python clang termux-api   # clang: pycryptodome 빌드용, termux-api: 폰 알림
pip install -r requirements.txt

if [ ! -f "$HOME/.korail" ]; then
  read -rp "코레일 아이디(회원번호/이메일/010-xxxx-xxxx): " KID
  read -rsp "비밀번호: " KPW; echo
  printf 'export KORAIL_ID=%q\nexport KORAIL_PW=%q\n' "$KID" "$KPW" > "$HOME/.korail"
  chmod 600 "$HOME/.korail"
  echo "로그인 정보를 ~/.korail 에 저장했습니다."
fi
echo "설치 완료. 예: ./korail.sh 서울 부산 20261224 --from 08:00 --to 10:30"
