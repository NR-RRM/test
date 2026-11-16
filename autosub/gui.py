"""간단한 GUI: 파일 선택 → 시작 → 진행률/경과시간/응답 상태/로그 표시."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .config import ROOT, load_config, save_config
from .pipeline import output_paths, run
from .util import CancelToken, Cancelled

VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".ts", ".webm", ".wmv", ".flv", ".mp3", ".wav", ".m4a", ".flac"}
BACKENDS = {"자동 (GPU 시도 → 실패 시 CPU)": "auto", "GPU (Vulkan)": "gpu", "CPU": "cpu"}
STALL_WARN = 180  # 초: 이 시간 동안 아무 출력이 없으면 경고


def external_model_dirs() -> list[Path]:
    """기존에 설치된 다른 자막 도구/팟플레이어의 Whisper 모델도 재사용 (중복 다운로드 방지)."""
    env = os.environ.get
    cands = [
        Path(env("PUBLIC", r"C:\Users\Public")) / "Documents" / "SubtitleToolRuntime" / "WhisperCpp" / "Models",
        Path(env("LOCALAPPDATA", "")) / "WhisperCppModels" if env("LOCALAPPDATA") else None,
        Path(env("APPDATA", "")) / "PotPlayer64" / "Model" if env("APPDATA") else None,
        Path(env("APPDATA", "")) / "PotPlayerMini64" / "Model" if env("APPDATA") else None,
        Path(r"C:\WhisperCpp\models"),
    ]
    return [p for p in cands if p and p.is_dir()]


def find_models() -> list[str]:
    out = sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / "models").glob("ggml-*.bin"))
    for d in external_model_dirs():
        out += sorted(str(p) for p in d.glob("ggml-*.bin")
                      if "silero" not in p.name and p.stat().st_size > 50_000_000)
    return out


def _fmt(sec: float) -> str:
    sec = int(max(0, sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def open_path(p: Path) -> None:
    if os.name == "nt":
        os.startfile(str(p))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


class App:
    def __init__(self, root: Tk, files: list[str]):
        self.root = root
        self.cfg = load_config()
        self.q: queue.Queue = queue.Queue()
        self.cancel: CancelToken | None = None
        self.worker: threading.Thread | None = None
        self.files: list[Path] = []
        self.results: list[tuple[Path, Path | None, str]] = []
        self.t_file = self.t_all = self.t_beat = 0.0
        self.frac = 0.0

        root.title("자막 자동 생성 — 영어 SRT")
        root.geometry("820x640")
        root.minsize(680, 520)
        pad = {"padx": 8, "pady": 4}

        # 파일 목록
        f1 = ttk.LabelFrame(root, text="영상 파일")
        f1.pack(fill="x", **pad)
        self.listbox = ttk.Treeview(f1, columns=("status",), height=5, show="tree headings")
        self.listbox.heading("#0", text="파일")
        self.listbox.heading("status", text="상태")
        self.listbox.column("#0", width=560)
        self.listbox.column("status", width=160, anchor="center")
        self.listbox.pack(fill="x", padx=6, pady=4)
        bf = ttk.Frame(f1)
        bf.pack(fill="x", padx=6, pady=(0, 6))
        self.btn_add = ttk.Button(bf, text="파일 추가…", command=self.add_files)
        self.btn_add.pack(side="left")
        self.btn_dir = ttk.Button(bf, text="폴더 추가…", command=self.add_folder)
        self.btn_dir.pack(side="left", padx=4)
        self.btn_clear = ttk.Button(bf, text="목록 비우기", command=self.clear)
        self.btn_clear.pack(side="left")

        # 옵션
        f2 = ttk.LabelFrame(root, text="설정")
        f2.pack(fill="x", **pad)
        ttk.Label(f2, text="Whisper 모델").grid(row=0, column=0, sticky="w", padx=6, pady=3)
        self.model_var = StringVar(value=self.cfg.whisper_model)
        models = find_models()
        if self.cfg.whisper_model not in models:
            models.insert(0, self.cfg.whisper_model)
        ttk.Combobox(f2, textvariable=self.model_var, values=models, width=48).grid(row=0, column=1, sticky="w")
        ttk.Label(f2, text="실행 장치").grid(row=1, column=0, sticky="w", padx=6, pady=3)
        inv = {v: k for k, v in BACKENDS.items()}
        self.backend_var = StringVar(value=inv.get(self.cfg.whisper_backend, next(iter(BACKENDS))))
        ttk.Combobox(f2, textvariable=self.backend_var, values=list(BACKENDS), state="readonly",
                     width=32).grid(row=1, column=1, sticky="w")
        self.pk_var = BooleanVar(value=self.cfg.use_parakeet)
        ttk.Checkbutton(f2, text="Parakeet 교차검증 (누락·환각 자동 보정, 권장)",
                        variable=self.pk_var).grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=3)

        # 실행 버튼
        f3 = ttk.Frame(root)
        f3.pack(fill="x", **pad)
        self.btn_start = ttk.Button(f3, text="▶  시작", command=self.start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(f3, text="■  중지", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        self.btn_open = ttk.Button(f3, text="결과 폴더 열기", command=self.open_out, state="disabled")
        self.btn_open.pack(side="right")

        # 진행 상황
        f4 = ttk.LabelFrame(root, text="진행 상황")
        f4.pack(fill="x", **pad)
        self.file_lbl = ttk.Label(f4, text="대기 중")
        self.file_lbl.pack(anchor="w", padx=6, pady=(4, 0))
        self.stage_lbl = ttk.Label(f4, text="")
        self.stage_lbl.pack(anchor="w", padx=6)
        self.bar = ttk.Progressbar(f4, maximum=1000)
        self.bar.pack(fill="x", padx=6, pady=4)
        self.time_lbl = ttk.Label(f4, text="")
        self.time_lbl.pack(anchor="w", padx=6)
        self.beat_lbl = ttk.Label(f4, text="")
        self.beat_lbl.pack(anchor="w", padx=6, pady=(0, 4))

        # 로그
        f5 = ttk.LabelFrame(root, text="로그")
        f5.pack(fill="both", expand=True, **pad)
        self.log_box = ScrolledText(f5, height=10, state="disabled", font=("Consolas", 9))
        self.log_box.pack(fill="both", expand=True, padx=4, pady=4)

        for f in files:
            self._add(Path(f))
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self.poll)

    # ---------- 파일 목록 ----------
    def _add(self, p: Path):
        if p.is_dir():
            for c in sorted(p.iterdir()):
                if c.suffix.lower() in VIDEO_EXT:
                    self._add(c)
            return
        if p.suffix.lower() in VIDEO_EXT and p not in self.files:
            self.files.append(p)
            done = output_paths(p)[0].exists()
            self.listbox.insert("", "end", iid=str(len(self.files) - 1), text=p.name,
                                values=("이미 자막 있음 (덮어씀)" if done else "대기",))

    def add_files(self):
        exts = " ".join(f"*{e}" for e in sorted(VIDEO_EXT))
        for f in filedialog.askopenfilenames(title="영상 선택", filetypes=[("영상/오디오", exts), ("모든 파일", "*.*")]):
            self._add(Path(f))

    def add_folder(self):
        d = filedialog.askdirectory(title="영상 폴더 선택")
        if d:
            self._add(Path(d))

    def clear(self):
        self.files.clear()
        self.listbox.delete(*self.listbox.get_children())

    def set_status(self, idx: int, text: str):
        if self.listbox.exists(str(idx)):
            self.listbox.set(str(idx), "status", text)

    # ---------- 실행 ----------
    def log(self, msg: str):
        self.q.put(("log", msg))

    def start(self):
        if not self.files:
            messagebox.showinfo("자막 자동 생성", "먼저 영상 파일을 추가하세요.")
            return
        self.cfg.whisper_model = self.model_var.get()
        self.cfg.whisper_backend = BACKENDS[self.backend_var.get()]
        self.cfg.use_parakeet = self.pk_var.get()
        try:
            save_config(self.cfg)
        except OSError:
            pass
        self.cancel = CancelToken()
        self.results.clear()
        for b in (self.btn_start, self.btn_add, self.btn_dir, self.btn_clear):
            b.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.t_all = self.t_beat = time.time()
        self.worker = threading.Thread(target=self.work, args=(list(self.files), self.cancel), daemon=True)
        self.worker.start()

    def work(self, files: list[Path], cancel: CancelToken):
        for i, f in enumerate(files):
            if cancel.cancelled:
                break
            self.q.put(("file", (i, len(files), f)))
            try:
                srt, rev = run(f, self.cfg, self.log, lambda fr, m: self.q.put(("prog", (fr, m))), cancel)
                self.q.put(("done_file", (i, f, srt, rev)))
            except Cancelled:
                self.q.put(("fail_file", (i, f, "중지됨")))
                break
            except Exception as e:  # noqa: BLE001
                self.log(traceback.format_exc())
                self.q.put(("fail_file", (i, f, str(e))))
        self.q.put(("all_done", None))

    def stop(self):
        if self.cancel:
            self.log("중지 요청…")
            self.cancel.cancel()

    def poll(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                self.t_beat = time.time()
                if kind == "log":
                    self._append_log(data)
                elif kind == "file":
                    i, n, f = data
                    self.t_file = time.time()
                    self.frac = 0.0
                    self.bar["value"] = 0
                    self.file_lbl.config(text=f"[{i + 1}/{n}]  {f.name}")
                    self.set_status(i, "처리 중…")
                    self._append_log(f"===== {f.name} =====")
                elif kind == "prog":
                    fr, msg = data
                    if fr is not None:
                        self.frac = fr
                        self.bar["value"] = int(fr * 1000)
                    if msg:
                        self.stage_lbl.config(text=msg)
                elif kind == "done_file":
                    i, f, srt, rev = data
                    self.set_status(i, "완료 ✔")
                    self.results.append((srt, rev, "ok"))
                elif kind == "fail_file":
                    i, f, err = data
                    self.set_status(i, "중지" if err == "중지됨" else "실패 ✖")
                    self.results.append((f, None, err))
                    if err != "중지됨":
                        self._append_log(f"!! 실패: {err}")
                elif kind == "all_done":
                    self.finish()
        except queue.Empty:
            pass
        self.tick()
        self.root.after(150, self.poll)

    def tick(self):
        if not (self.worker and self.worker.is_alive()):
            return
        now = time.time()
        el = now - self.t_file if self.t_file else 0
        eta = ""
        if self.frac > 0.08:
            eta = f"   ·   남은 예상 {_fmt(el / self.frac - el)}"
        self.time_lbl.config(text=f"현재 파일 경과 {_fmt(el)}{eta}   ·   전체 경과 {_fmt(now - self.t_all)}")
        quiet = now - self.t_beat
        if quiet > STALL_WARN:
            self.beat_lbl.config(text=f"⚠ {int(quiet)}초째 엔진 응답 없음 — 긴 구간 처리 중이거나 멈췄을 수 있습니다",
                                 foreground="#c0392b")
        else:
            dots = "●" if int(now * 2) % 2 else "○"
            self.beat_lbl.config(text=f"{dots} 작동 중 (마지막 응답 {int(quiet)}초 전)", foreground="#2e7d32")

    def finish(self):
        for b in (self.btn_start, self.btn_add, self.btn_dir, self.btn_clear):
            b.config(state="normal")
        self.btn_stop.config(state="disabled")
        ok = [r for r in self.results if r[2] == "ok"]
        self.beat_lbl.config(text="")
        self.stage_lbl.config(text="")
        self.time_lbl.config(text="")
        self.file_lbl.config(text=f"끝: 성공 {len(ok)} / {len(self.results)}  ·  총 {_fmt(time.time() - self.t_all)}")
        if ok:
            self.btn_open.config(state="normal")
            if len(ok) == 1 and messagebox.askyesno(
                    "완료", f"자막이 만들어졌습니다.\n\n{ok[0][0].name}\n\n검수 목록({ok[0][1].name})을 열까요?"):
                open_path(ok[0][1])

    def open_out(self):
        ok = [r for r in self.results if r[2] == "ok"]
        if ok:
            open_path(ok[-1][0].parent)

    def _append_log(self, msg: str):
        self.log_box.config(state="normal")
        self.log_box.insert("end", msg + "\n")
        if int(self.log_box.index("end-1c").split(".")[0]) > 3000:
            self.log_box.delete("1.0", "500.0")
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    def on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("종료", "작업 중입니다. 중지하고 종료할까요?"):
                return
            self.stop()
        self.root.destroy()


def _fatal(exc_text: str):
    """pythonw로 실행하면 오류가 화면에 안 보이므로 파일로 남기고 알림창을 띄운다."""
    path = ROOT / "logs" / "crash.log"
    try:
        path.parent.mkdir(exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S]\n") + exc_text + "\n")
    except OSError:
        pass
    msg = f"프로그램 오류가 발생했습니다.\n\n{exc_text[-800:]}\n\n기록: {path}"
    try:
        messagebox.showerror("자막 자동 생성 — 오류", msg)
    except Exception:  # noqa: BLE001
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, "자막 자동 생성 — 오류", 0x10)


def main():
    try:
        _main()
    except Exception:  # noqa: BLE001
        _fatal(traceback.format_exc())


def _main():
    root = Tk()
    root.report_callback_exception = lambda *a: _fatal("".join(traceback.format_exception(*a)))
    try:
        ttk.Style().theme_use("vista" if os.name == "nt" else "clam")
    except Exception:  # noqa: BLE001
        pass
    App(root, sys.argv[1:])
    root.mainloop()


if __name__ == "__main__":
    main()
