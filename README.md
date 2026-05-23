# powersignal-data

PowerSignal 데이터 수집 파이프라인. 전력시장 공공데이터(SMP, DR 거래실적, 기상, 연료비)를
수집해 SQLite/Postgres에 적재한다.

상세 배경·도메인 용어·미해결 항목은 [PowerSignal_데이터수집_플랜.md](./PowerSignal_데이터수집_플랜.md)
참조. 본 README는 코드를 돌리는 방법에만 집중한다.

---

## 구현 범위 (현재 버전)

| 데이터셋 | 설명 | 수집 방식 | 상태 |
|---|---|---|---|
| D1 | SMP + 수요예측 (하루전 발전계획용) | data.go.kr 15131225 OpenAPI | ✅ |
| D2 | 현재전력수급현황 | data.go.kr 15056640 OpenAPI | ✅ |
| D3 | 기상청 ASOS 시간자료 | data.go.kr 1360000 OpenAPI | ✅ |
| D4 | 월간 연료비용 정보 | data.go.kr 15099765 OpenAPI | ✅ |
| D5 | 수요반응자원 거래실적 (경제성DR) | CSV/XLSX 파일 다운로드 | ✅ |
| D6 | 수요반응자원 거래실적 (신뢰성DR) | CSV/XLSX 파일 다운로드 | ✅ |
| D7~D10 | 시간별 DR / 업종통계 / 적합도 | 신청·정의 필요 | ⏸ 기획팀 확인 대기 |

---

## 1. 셋업

```bash
# Python 3.11+ 필요 (개발은 3.14에서 검증)
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 환경 변수 — .env.example 복사 후 서비스키 채우기
cp .env.example .env
$EDITOR .env

# DB 초기화 (SQLite 파일 + 6개 테이블 생성)
ps-init-db
```

`.env`에 들어가는 값:

- `DATA_GO_KR_SERVICE_KEY` — 공공데이터포털 활용신청 후 발급. 인코딩된 키 그대로 사용.
- `KMA_SERVICE_KEY` — 기상청용. 공공데이터포털 키와 동일할 수도, 별도일 수도. 비워두면 위 값으로 폴백.
- `DATABASE_URL` — 기본 `sqlite:///./data/powersignal.db`. 운영 전환 시 `postgresql+psycopg://...`.

---

## 2. 실행 (CLI)

```bash
# 일별 수집 (D1 SMP, D2 supply, D3 weather)
# D1은 23시 이후 다음 날 SMP가 공개되므로 cron은 23:30 권장
ps-daily

# 특정 데이터만
ps-daily --no-supply --no-weather  # D1만
ps-daily --weather-date 2026-05-22  # 특정 날짜 기상

# 월별 수집 (D4 LNG)
ps-monthly

# DR 거래실적 파일 적재 (D5/D6)
ps-dr-ingest --type economic --file ./data/static/dr_econ_2026_03.csv
ps-dr-ingest --type reliability --url https://example.com/dr.csv
```

cron 예시 (참고용 — 본 패키지엔 포함 안 함):

```cron
30 23 * * *  cd /opt/powersignal && .venv/bin/ps-daily
0  3  1 * *  cd /opt/powersignal && .venv/bin/ps-monthly
```

---

## 3. 아키텍처

```
src/
├── config.py              # .env + datasets.yaml 로더
├── logging_setup.py       # structlog 설정
├── clients/
│   ├── data_go_kr.py      # 공통 HTTP 클라이언트 (재시도/레이트리밋/페이지네이션/raw 저장)
│   └── rate_limiter.py    # 토큰 버킷
├── collectors/
│   ├── base.py            # BaseCollector + ingestion_run 컨텍스트
│   ├── smp.py             # D1
│   ├── supply.py          # D2
│   ├── weather.py         # D3 (KMA 키 사용)
│   ├── lng.py             # D4
│   └── dr_history.py      # D5/D6 (파일 기반)
├── transform/
│   └── time_normalize.py  # 거래시간 끝점 처리, 지역 매핑, KMA 시각 파싱
├── storage/
│   ├── db.py              # engine / session_scope
│   ├── models.py          # 6개 테이블 ORM
│   └── upsert.py          # SQLite/Postgres dialect-aware ON CONFLICT
└── cli/
    ├── init_db.py         # ps-init-db
    ├── run_daily.py       # ps-daily
    ├── run_monthly.py     # ps-monthly
    └── run_dr_ingest.py   # ps-dr-ingest

data/
├── raw/                   # 원본 응답 (dataset_id/YYYYMMDD/타임스탬프_p{page}.json)
├── parsed/                # 가공본 (사용 시)
└── static/                # D8/D9 정적 통계 (현재 비어 있음)

config/
└── datasets.yaml          # 엔드포인트·기본 파라미터 정의
```

### 데이터 흐름

```
.env / datasets.yaml
        │
        ▼
DataGoKrClient ──▶ Collector.fetch (paginate)
        │                  │
        │            Collector.parse
        │                  │
        ▼                  ▼
data/raw/D*/...     upsert into SQLite/Postgres
                            │
                            ▼
                    ingestion_run 로그
```

---

## 4. 운영 시 챙겨야 할 것 (플랜 문서 §6 핵심만)

- ✅ **D1 API 신버전(15131225)** — `config/datasets.yaml`에 박혀 있음. 구버전 URL로 바꾸지 말 것.
- ✅ **거래시간 끝점 표기** — `trade_hour`는 1~24 그대로 저장. 가공 단계에서 시작점/끝점 변환 결정.
- ✅ **육지/제주 구분** — `region` 컬럼으로 분리 보존.
- ✅ **서비스키 보안** — `.env`는 `.gitignore`. 절대 커밋 금지.
- ✅ **트래픽 제한** — 토큰 버킷으로 throttle. 기본 2 req/sec. 백필 시 더 보수적으로.
- ✅ **CSV 인코딩** — `utf-8-sig` → `cp949` → `chardet` 폴백.
- ✅ **갱신 지연** — DR 거래실적 D-2월 정산 지연은 정상. CLI에서 에러 처리 없음.
- ✅ **원본 보존** — 모든 API 응답을 `data/raw/`에 일자별로 저장.
- ⏸ **D7 신청 리드타임** — 별도 진행 필요 (구현 대상 아님).
- ⏸ **D8/D9 정적 데이터** — 별도 진행 필요. 매일 스케줄에 절대 넣지 말 것.

---

## 5. 테스트

```bash
pytest
# 42 passed in ~10s
```

- 모든 외부 API는 `respx`로 모킹 — 네트워크 없이 실행.
- 각 테스트는 임시 SQLite 파일을 갖는 격리 fixture (`tests/conftest.py`).

---

## 6. 다음 단계 (Phase 3 이후)

코드 작성 전에 기획팀과 합의 필요 — 본 패키지에서는 다루지 않음:

1. D7 시간별 DR 데이터 신청 여부 결정.
2. 업종별 집중도 지수 산출 공식 (D8/D9 원시 통계 → 파생 지표).
3. D10 업종 적합도 별점 근거.
4. 모델링 계층 (SMP 예측, DR 낙찰 예측 스코어) — 별도 저장소.
5. 운영 전환 시 PostgreSQL + Alembic 마이그레이션 도입.
