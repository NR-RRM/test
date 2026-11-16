# 안드로이드(갤럭시)에서 영어 자막 만들기

PC 없이 폰 혼자 영어 영상 → 영어 SRT 자막을 만듭니다. 무료이고, 모든 처리는 폰 안에서 합니다.
PC 버전과 같은 프로그램(Whisper + Parakeet 교차검증)을 Termux 안의 Ubuntu에서 그대로 돌립니다.

```
갤러리/내 파일 → 영상 공유 → Termux → [편집]
  → 알림에 진행률 표시 (화면 꺼도 계속)
  → 완료 알림 → 영상 옆에 영상이름.en.srt, 영상이름.review.txt
```

> 처음 설치에 30~60분(다운로드 약 2GB + whisper.cpp 컴파일), 저장공간 약 5GB가 필요합니다.
> Wi-Fi와 충전기를 연결하고 진행하세요.

## 1. 앱 설치 (F-Droid에서)

Play 스토어의 Termux는 오래된 버전이라 동작하지 않습니다. **반드시 F-Droid에서** 받으세요.

1. 브라우저에서 <https://f-droid.org> → F-Droid 앱 설치
2. F-Droid에서 **Termux**, **Termux:API** 두 개 설치
   - Termux:Widget(선택): 홈 화면에 "폴더 전체 처리" 바로가기를 만들고 싶을 때
3. **배터리 최적화 끄기** (중요 — 삼성은 백그라운드 작업을 자주 종료합니다)
   - 설정 → 애플리케이션 → Termux → 배터리 → **제한 없음**
   - Termux:API도 같은 방법으로 **제한 없음**

## 2. 프로그램 설치

Termux를 열고 먼저 **다운로드 서버를 가까운 곳으로 바꿉니다** (기본 서버가 해외라 매우 느릴 수 있음).

```bash
termux-change-repo
```
- 첫 화면에서 **Mirror group** 선택 → 다음 화면에서 **Asia**(또는 Korea가 있으면 그것) 선택 → OK

그다음 아래를 한 줄씩 입력합니다.

```bash
pkg install -y git
git clone -b ccr-d21a25ce-vlk7nt https://github.com/nr-rrm/test ~/autosub
bash ~/autosub/android/setup-android.sh
```

- 중간에 '파일 및 미디어 접근' 권한 창이 뜨면 **허용**을 누르세요.
- 설치 중 `openssl.cnf (Y/I/N/O/D/Z)` 처럼 설정 파일을 물으면 **Y** 입력 후 엔터.
- 저장소가 비공개라서 `git clone`이 아이디/비밀번호를 물으면: 아이디는 GitHub 아이디,
  비밀번호 자리에 GitHub **Personal access token**을 넣으세요.
- 설치는 여러 번 실행해도 안전합니다. 중간에 끊기면 마지막 줄만 다시 실행하세요 (받은 파일은 이어받습니다).

설치하는 것: Ubuntu(proot-distro), Python 패키지(numpy, sherpa-onnx), FFmpeg,
whisper.cpp(폰 CPU에 맞춰 직접 컴파일), Whisper large-v3-turbo 모델, Parakeet-TDT 0.6B 모델.

## 3. 먼저 속도 측정 (한 번만)

어떤 모드를 기본으로 쓸지 정하기 위해, 실제 드라마 한 편으로 5분 분량만 시험합니다.
**충전기를 연결한 상태**에서 실행하세요.

```bash
autosub-bench "/sdcard/Movies/드라마 S01E01.mkv"
```

- 10분 지점부터 5분을 잘라 세 가지로 자막을 만듭니다.
  - **A) Parakeet 단독** — 가장 빠름
  - **B) Whisper 단독**
  - **C) 둘 다 (교차검증)** — PC와 같은 방식, 가장 정확하지만 가장 느림
- 결과: 영상 옆 `드라마 S01E01.bench/` 폴더에 모드별 자막 3개와 `bench-report.txt`
- **`bench-report.txt` 내용을 Claude에게 그대로 보내 주세요.** 그걸 보고 기본 모드를 정합니다.
- 옵션: `--threads 6` (스레드 수), `--beam 1` (Whisper를 더 빠르게, 정확도 약간 하락)

## 4. 사용

### 공유로 만들기 (기본)

1. 갤러리 또는 내 파일에서 영상을 길게 눌러 **공유 → Termux**
2. 뜨는 창에서 **편집(Edit)** 을 누릅니다 (Termux가 영상을 잠시 복사합니다)
3. 알림에 진행률과 남은 시간이 표시됩니다. 화면을 꺼도 계속됩니다.
4. 완료 알림이 오면 끝. 알림을 누르면 검수 목록(review.txt)이 열립니다.

자막이 생기는 곳:
- 내장 저장소에서 원본 영상을 찾으면 → **원본 영상 옆** (같은 이름이라 플레이어가 자동으로 불러옴)
- 원본을 못 찾으면 (클라우드 영상 등) → `내 파일 > 내장 저장공간 > Download > AutoSub`
- 어느 경우든 Termux가 만든 복사본은 자동으로 지웁니다.

여러 개를 연달아 공유하면 하나씩 차례로 처리합니다. 알림의 **취소** 버튼으로 멈출 수 있습니다.

### 명령어로 만들기

```bash
autosub "/sdcard/Movies/드라마 S01E01.mkv"          # 한 편
autosub --mode parakeet "/sdcard/Movies/a.mp4"      # 이번만 다른 모드로
autosub-scan                                         # Movies, Download 폴더에서 자막 없는 영상 전부
autosub-scan "/sdcard/Movies/드라마"                # 특정 폴더
autosub-cancel                                       # 진행 중인 작업 취소
```

## 설정 (`~/autosub/config-android.json`)

| 항목 | 기본값 | 설명 |
|---|---|---|
| `engine_mode` | `both` | `both`(교차검증) / `parakeet` / `whisper`. 속도 측정 후 정합니다 |
| `whisper_threads` / `parakeet_threads` | `8` | CPU 스레드 수 |
| `whisper_beam_size` | `5` | `1`로 줄이면 빨라짐 |
| `max_line_chars`, `max_cps` 등 | PC와 같음 | 자막 규칙 (PC 버전 README 참고) |

편집: `nano ~/autosub/config-android.json`

## 업데이트

```bash
cd ~/autosub && git pull && bash android/setup-android.sh
```

## 문제가 생기면

- **로그**: `~/.autosub/logs/` (작업별 로그), 실패 알림에도 로그 위치가 나옵니다.
  `ls -t ~/.autosub/logs | head` → `cat ~/.autosub/logs/파일이름` 내용을 Claude에게 보내 주세요.
- **도중에 `[Process completed (signal 9)]` 로 끝남**: 안드로이드가 백그라운드 프로세스를 강제 종료한 것입니다.
  1. 위의 배터리 최적화 끄기를 확인
  2. 개발자 옵션 → **하위 프로세스 제한 사용 중지** 켜기
     (개발자 옵션: 설정 → 휴대전화 정보 → 소프트웨어 정보 → 빌드번호 7번 누르기)
- **알림이 안 뜸**: Termux:API 앱이 F-Droid판인지 확인 (Termux와 같은 곳에서 받아야 함), 알림 권한 허용.
- **공유 메뉴에 Termux가 없음**: Termux 앱을 한 번 실행한 뒤 다시 시도.
- **많이 느려짐**: 발열로 CPU 속도가 떨어진 것입니다. 충전기 연결, 케이스 분리, 시원한 곳에서 실행하세요.

## 구조 (참고)

| 파일 | 역할 |
|---|---|
| `setup-android.sh` | Termux 쪽 설치 (패키지, Ubuntu, 공유 연결, 명령어) |
| `setup-ubuntu.sh` | Ubuntu 쪽 설치 (Python, FFmpeg, whisper.cpp 빌드, 모델) |
| `run.sh` | 작업 실행 + 알림 진행률 + wake lock + 대기열 |
| `share-handler.sh` | 공유 받기 (`~/bin/termux-file-editor`, `termux-url-opener`) |
| `scan.sh` / `bench.sh` / `cancel.sh` | 폴더 처리 / 속도 측정 / 취소 |

GPU(Adreno)·NPU 가속은 아직 쓰지 않습니다. CPU만으로 속도를 먼저 확인한 뒤 결정합니다.
