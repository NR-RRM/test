"""GUI 진입점. 모듈 로딩 단계에서 실패해도(패키지 누락 등) 오류를 알림창과 logs/crash.log로 남긴다."""
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

try:
    from autosub.gui import main
except Exception:  # noqa: BLE001
    text = traceback.format_exc()
    (ROOT / "logs").mkdir(exist_ok=True)
    with open(ROOT / "logs" / "crash.log", "a", encoding="utf-8") as f:
        f.write(time.strftime("[%Y-%m-%d %H:%M:%S]\n") + text + "\n")
    msg = "프로그램을 시작하지 못했습니다. setup.bat을 다시 실행해 보세요.\n\n" + text[-800:]
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, "자막 자동 생성 — 오류", 0x10)
    else:
        print(msg, file=sys.stderr)
    sys.exit(1)

main()
