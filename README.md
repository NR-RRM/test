# korail_watch — 코레일 매진 열차 빈자리 자동 예약

매진된 열차를 주기적으로 다시 조회하다가 취소표가 나오면 바로 **예약**합니다.
예약만 해두기 때문에 **결제는 코레일톡 앱에서 직접** 해야 합니다
(앱 > 승차권 예약내역, 결제 기한이 지나면 자동 취소).

> 코레일톡 앱 화면을 직접 조작하는 방식이 아니라, 앱이 쓰는 서버 API를
> 호출하는 [`korail2`](https://github.com/carpedm20/korail2) 라이브러리(BSD, `korail2/` 폴더에 포함)를 사용합니다.

## 안드로이드 폰에서 쓰기 (Termux)

1. **F-Droid**(https://f-droid.org)에서 **Termux**와 **Termux:API** 앱을 설치합니다.
   Play 스토어 버전 Termux는 오래돼서 `pkg` 설치가 깨질 수 있습니다.
2. Termux를 열고 실행합니다.
   ```bash
   pkg install -y git
   git clone -b ccr-07f2b757-e2te0f https://github.com/nr-rrm/test.git korail
   cd korail
   bash termux_setup.sh      # 처음 한 번만. 끝에 코레일 아이디/비번을 물어봅니다
   ```
3. 실행합니다.
   ```bash
   cd ~/korail
   ./korail.sh 서울 부산 20261224 --from 08:00 --to 10:30 --max-attempts 1   # 먼저 1회 테스트
   ./korail.sh 서울 부산 20261224 --from 08:00 --to 10:30                    # 실제 실행
   ```
4. 예약에 성공하면 **진동과 함께 알림**이 옵니다. 바로 코레일톡 앱에서 결제하세요.

팁
- `korail.sh`가 wake-lock을 걸어 주므로 화면을 꺼도 계속 돕니다. 그래도 멈추면
  설정 > 앱 > Termux > 배터리 > **제한 없음**으로 바꾸세요.
- 다른 앱을 써도 상관없지만, 최근 앱 목록에서 Termux를 쓸어서 닫으면 멈춥니다.
- 멈추려면 Termux 화면에서 볼륨다운+C(= Ctrl+C)를 누르세요.

## PC에서 쓰기

Python 3.9 이상이면 됩니다.

```bash
python3 -m venv .venv && source .venv/bin/activate   # 윈도우: .venv\Scripts\activate
pip install -r requirements.txt
```

## 사용법

```bash
export KORAIL_ID='회원번호 또는 이메일 또는 010-xxxx-xxxx'
export KORAIL_PW='비밀번호'

# 12/24 서울→부산 KTX, 08:00~10:30 출발 열차 중 아무거나 일반실 우선
python -m korail_watch.watcher 서울 부산 20261224 --from 08:00 --to 10:30

# 특정 열차만, 성인 2명, 일반실만, 15초 간격
python -m korail_watch.watcher 서울 부산 20261224 --train 101 --train 103 \
    --adults 2 --seat GENERAL_ONLY --interval 15
```

| 옵션 | 설명 | 기본값 |
|---|---|---|
| `--from` / `--to` | 출발 시각 범위 (HH:MM) | 하루 전체 |
| `--train` | 열차번호 지정 (여러 번 가능) | 시간대 내 전체 |
| `--type` | `KTX`, `SAEMAEUL`, `MUGUNGHWA`, `ITX-CHEONGCHUN`, `ALL` 등 | `KTX` |
| `--adults` `--children` `--seniors` | 승객 수 | 성인 1 |
| `--seat` | `GENERAL_FIRST`, `GENERAL_ONLY`, `SPECIAL_FIRST`, `SPECIAL_ONLY` | `GENERAL_FIRST` |
| `--waiting` | 좌석이 없으면 예약대기도 신청 | 끔 |
| `--interval` | 조회 간격(초), **최소 5초** | 10 |
| `--max-attempts` | 최대 조회 횟수 | 무제한 |

예약에 성공하면 터미널 벨과 함께 메시지를 출력하고 종료합니다(exit 0).

## 주의

- 본인 승차권 구매용으로만 쓰세요. 매크로로 구한 표를 웃돈 받고 되파는 건
  철도사업법 위반입니다. 자동화 조회는 코레일 약관에 어긋날 수 있고 계정이 제재될 수 있습니다.
- 서버 부담과 계정 차단을 막기 위해 조회 간격을 5초 미만으로는 설정할 수 없습니다.
- `korail2`는 비공식 라이브러리입니다. 코레일이 앱 API를 바꾸거나 매크로 차단을 강화하면
  로그인/조회가 실패할 수 있고, 그 경우 라이브러리 업데이트가 필요합니다.

## 테스트

```bash
pip install pytest && python -m pytest tests
```
