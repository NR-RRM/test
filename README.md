# korail_watch — 코레일 매진 열차 빈자리 자동 예약

매진된 열차를 주기적으로 다시 조회하다가 취소표가 나오면 바로 **예약**합니다.
예약만 해두기 때문에 **결제는 코레일톡 앱에서 직접** 해야 합니다
(앱 > 승차권 예약내역, 결제 기한이 지나면 자동 취소).

> 코레일톡 앱 화면을 직접 조작하는 방식이 아니라, 앱이 쓰는 서버 API를
> 호출하는 [`korail2`](https://github.com/carpedm20/korail2) 라이브러리를 사용합니다.

## 설치

`korail2` 0.4.0은 Python 3.12 이상에서 빌드되지 않으므로 **Python 3.11 이하**를 쓰세요.

```bash
python3.11 -m venv .venv && source .venv/bin/activate
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
