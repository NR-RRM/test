# 자막 자동 생성 (영어 영상 → 영어 SRT)

> 📱 **안드로이드 폰(갤럭시)에서 PC 없이 쓰려면 [android/README.md](android/README.md)** 를 보세요.

영상을 넣고 **시작**을 누르면 `영상이름.en.srt`가 만들어집니다. 모든 처리는 로컬에서 하며 무료입니다.

```
영상 → ① 오디오 추출 (FFmpeg)
     → ② Whisper large-v3-turbo로 인식 (Intel Arc Vulkan GPU, 실패하면 CPU)
     → ③ Parakeet-TDT 0.6B로 한 번 더 인식 (교차검증)
     → ④ 두 결과 자동 대조
          · 둘 다 같은 단어       → 확정 (Parakeet 타임스탬프로 타이밍 보정)
          · Parakeet에만 있는 대사 → Whisper 누락으로 보고 삽입
          · 무음 구간의 Whisper 문장 → 환각으로 판단되면 삭제
     → ⑤ 자막 규칙 정리 (한 줄 42자, 최대 2줄, 읽기속도 20 CPS, 최소 1초, 겹침 제거)
     → 영상이름.en.srt  +  영상이름.review.txt (확인할 구간 목록)
```

## 결과물

| 파일 | 내용 |
|---|---|
| `영상이름.en.srt` | 최종 자막. 팟플레이어에서 영상과 같은 폴더에 있으면 자동으로 불러옵니다 |
| `영상이름.review.txt` | 자동 보정한 곳·의심되는 곳의 타임코드 목록. 이 구간만 들어보면 됩니다 |
| `영상이름.en.srt.bak` | 같은 이름의 자막이 이미 있었다면 백업본 |

## 설치 (한 번만)

1. 이 폴더를 원하는 위치에 둡니다 (예: `C:\autosub`).
2. **(GPU 가속용, 권장)** GitHub 저장소의 **Actions → "Build whisper.cpp (Vulkan, Windows)"** 에서 가장 최근의 성공한 실행을 열고, 아래쪽 **Artifacts → `whisper-vulkan-x64`** 를 내려받아 zip 그대로 이 폴더에 둡니다.
   - 이 파일이 없으면 공식 CPU 빌드를 자동으로 설치합니다. CPU로도 동작하지만 더 느립니다.
3. `setup.bat`을 더블클릭합니다. Python, FFmpeg, whisper.cpp와 모델 약 1.6GB를 받아 설치합니다.

## 사용

- `자막만들기.bat` 실행 → **파일 추가** 또는 **폴더 추가** → **▶ 시작**
- 영상 파일을 `자막만들기.bat` 아이콘 위로 끌어다 놓아도 목록에 들어갑니다.
- 진행률, 현재 단계, 경과·남은 시간, **마지막 응답 시각**이 표시됩니다. 3분 넘게 응답이 없으면 빨간 경고가 뜹니다.
- 처음에는 5분 정도의 짧은 영상으로 시험해 보세요.

## 기존 '자막생성툴'과 함께 쓰기

- 이 프로그램은 **자기 폴더 안에만** 설치합니다 (`.venv`, `tools`, `engines`, `models`, `logs`). PATH·레지스트리·공용 폴더는 건드리지 않습니다.
- 기존 툴이 쓰는 `C:\Users\Public\Documents\SubtitleToolRuntime`은 **읽기만** 합니다. 거기서 직접 빌드한 Vulkan `whisper-cli`나 FFmpeg를 찾으면 복사해서 씁니다. 원본은 그대로 둡니다.
- 기존에 받아둔 Whisper 모델(SubtitleToolRuntime, `%LOCALAPPDATA%\WhisperCppModels`, 팟플레이어 Model 폴더)은 GUI 모델 목록에 자동으로 나타납니다.
- 출력 이름이 다릅니다. 기존 툴은 `영상.srt`, 이 프로그램은 `영상.en.srt`라서 서로 덮어쓰지 않습니다.
- 두 프로그램을 **동시에** 돌리지는 마세요. 메모리 16GB와 GPU를 나눠 쓰게 되어 둘 다 느려지거나 실패할 수 있습니다.

## 문제가 생기면

- `진단실행.bat` 실행: 콘솔 창에 오류가 그대로 보입니다.
- 작업 로그는 `logs\` 폴더에, 시작 오류는 `logs\crash.log`에 남습니다.

## 설정 (`config.json`, 시작하면 자동 생성)

| 항목 | 기본값 | 설명 |
|---|---|---|
| `whisper_backend` | `auto` | `auto` / `gpu` / `cpu` |
| `whisper_threads` | `8` | CPU 스레드 수 |
| `whisper_max_context` | `-1` | 같은 문장 반복 환각이 많으면 `0`으로 설정 |
| `use_parakeet` | `true` | 교차검증 사용 여부 |
| `max_line_chars` / `max_lines` | `42` / `2` | 줄 길이 / 줄 수 |
| `max_cps` | `20` | 읽기 속도 상한 |
| `min_duration` | `1.0` | 자막 최소 표시 시간(초) |
| `keep_temp` | `false` | 중간 파일(오디오, Whisper JSON) 보존 |
| `audio_track` | `-1` | `-1`이면 영어 오디오 트랙 자동 선택, 숫자를 넣으면 해당 트랙 고정 |

## 명령줄 실행 (GUI 없이)

```
.venv\Scripts\python.exe -m autosub.cli 영상1.mp4 영상2.mkv
```

## 알려진 한계 / 다음 단계

- **음성 분리(배경음악 제거)** 옵션은 아직 없습니다. 다음 단계에서 추가할 예정입니다.
- NPU는 사용하지 않습니다.
- 원본 녹음에서 들리지 않는 대사는 어떤 모델로도 복원할 수 없습니다.

## 개발

```
pip install numpy sherpa-onnx pytest
python -m pytest tests
```
