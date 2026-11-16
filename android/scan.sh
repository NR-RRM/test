#!/data/data/com.termux/files/usr/bin/bash
# 폴더 안의 영상 중 아직 자막(.en.srt)이 없는 것만 차례로 처리. 자막은 영상 옆에 생긴다.
# 사용: scan.sh [폴더 ...]   (생략하면 내장 저장소의 Movies, Download)
. "$(dirname "$(readlink -f "$0")")/common.sh"
dirs=("$@")
[ ${#dirs[@]} -gt 0 ] || dirs=("$SHARED/Movies" "$SHARED/Download")
todo=()
for d in "${dirs[@]}"; do
    [ -d "$d" ] || continue
    while IFS= read -r -d '' f; do
        [ -e "${f%.*}.en.srt" ] || todo+=("$f")
    done < <(find "$d" -path '*/.*' -prune -o -type f \( -iname '*.mp4' -o -iname '*.mkv' -o -iname '*.mov' \
        -o -iname '*.avi' -o -iname '*.webm' -o -iname '*.m4v' -o -iname '*.ts' \) ! -name '*.bench*' -print0 | sort -z)
done
if [ ${#todo[@]} -eq 0 ]; then
    echo "자막이 필요한 영상이 없습니다: ${dirs[*]}"
    exit 0
fi
echo "처리할 영상 ${#todo[@]}개:"
printf '  %s\n' "${todo[@]}"
exec bash "$AUTOSUB_DIR/android/run.sh" "${todo[@]}"
