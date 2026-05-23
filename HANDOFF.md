# PowerSignal 데이터 수집 — 인수인계 문서

> 작성일: 2026-05-23
> 작성자: seonkyuLee (Claude Code 협업)
> 대상: 본 저장소를 이어받는 개발자
>
> 함께 읽을 문서:
> - [PowerSignal_데이터수집_플랜.md](./PowerSignal_데이터수집_플랜.md) — 원본 핸드오프(도메인·데이터셋·미해결 항목)
> - [README.md](./README.md) — 셋업·실행 빠른 참조

---

## 0. 한 줄 요약

PowerSignal 데이터 수집 파이프라인의 **Phase 0~2(그룹1+2, D1~D6)** 가 구현·테스트 완료 상태다.
**실제 데이터는 아직 한 건도 수집되지 않았다** — 공공데이터포털 API 키 발급이 선행되어야 함.

---

## 1. 현재 상태 요약

| 영역 | 상태 | 비고 |
|---|---|---|
| 코드 구현 (D1~D6) | ✅ 완료 | 1,982 LOC Python |
| 단위 테스트 | ✅ 42개 통과 | 외부 API는 `respx`로 모킹 |
| DB 스키마 | ✅ 6개 테이블 생성 | SQLite, Postgres 호환 |
| 사용 문서 (README) | ✅ 완료 | |
| **실제 수집 데이터** | ❌ **0건** | **API 키 발급 필요** |
| D5/D6 DR CSV 파일 | ❌ 없음 | 수동 다운로드 필요 |
| Phase 3 (D7~D10) | ⏸ 미착수 | 기획팀 답변 5건 대기 (플랜 §7) |

---

## 2. 폴더 구조

```
powersignal-data/
├── PowerSignal_데이터수집_플랜.md   # 원본 핸드오프 (기획)
├── HANDOFF.md                        # ← 본 문서
├── README.md                         # 셋업·실행 가이드
│
├── pyproject.toml                    # 의존성 + CLI 진입점 정의
├── .env.example                      # 환경변수 템플릿 (실제 .env는 .gitignore)
├── .gitignore
│
├── config/
│   └── datasets.yaml                 # D1~D6 엔드포인트·기본 파라미터
│
├── src/
│   ├── config.py                     # .env + datasets.yaml 로더
│   ├── logging_setup.py              # structlog 설정
│   │
│   ├── clients/
│   │   ├── data_go_kr.py             # 공통 HTTP 클라이언트
│   │   │                             #  - 서비스키 주입
│   │   │                             #  - 재시도 (tenacity, 지수백오프)
│   │   │                             #  - 페이지네이션
│   │   │                             #  - raw 응답 디스크 저장
│   │   │                             #  - 포털 에러코드 분류 (retryable/quota/fatal)
│   │   └── rate_limiter.py           # 토큰버킷 (data.go.kr 트래픽 제한 대응)
│   │
│   ├── collectors/
│   │   ├── base.py                   # BaseCollector + ingestion_run 컨텍스트
│   │   ├── smp.py                    # D1 — SMP+수요예측
│   │   ├── supply.py                 # D2 — 실시간 수급
│   │   ├── weather.py                # D3 — KMA ASOS 시간자료 (KMA 키 사용)
│   │   ├── lng.py                    # D4 — 월간 연료비
│   │   └── dr_history.py             # D5/D6 — DR 거래실적 (파일 기반)
│   │
│   ├── transform/
│   │   └── time_normalize.py         # 거래시간 끝점(6=05~06), 육지/제주 매핑, KMA 시각 파싱
│   │
│   ├── storage/
│   │   ├── db.py                     # SQLAlchemy engine / session_scope
│   │   ├── models.py                 # 6개 테이블 ORM
│   │   └── upsert.py                 # SQLite/Postgres dialect-aware ON CONFLICT
│   │
│   └── cli/
│       ├── init_db.py                # ps-init-db
│       ├── run_daily.py              # ps-daily
│       ├── run_monthly.py            # ps-monthly
│       └── run_dr_ingest.py          # ps-dr-ingest
│
├── scripts/
│   └── run_daily.py                  # pip install 없이 돌리는 단축 진입점
│
├── tests/                            # 42개 단위 테스트
│   ├── conftest.py                   # per-test 격리 SQLite fixture
│   ├── test_time_normalize.py
│   ├── test_rate_limiter.py
│   ├── test_data_go_kr_client.py
│   ├── test_smp_collector.py
│   └── test_dr_history_collector.py
│
└── data/                             # 런타임 출력 (대부분 .gitignore)
    ├── raw/                          # API 원본 응답 (dataset_id/YYYYMMDD/타임스탬프_p{N}.json)
    ├── parsed/                       # 가공본 (필요 시)
    ├── static/                       # D8/D9 정적 통계 (현재 비어 있음)
    └── powersignal.db                # SQLite DB (.gitignore)
```

### DB 테이블 (6개)

| 테이블 | 데이터셋 | 키 |
|---|---|---|
| `smp_hourly` | D1 | (trade_date, trade_hour, region) |
| `supply_snapshot` | D2 | (observed_at) |
| `weather_hourly` | D3 | (station_id, observed_at) |
| `fuel_cost_monthly` | D4 | (year, month, fuel_type) |
| `dr_transaction_monthly` | D5+D6 | (year, month, dr_type, resource_name) |
| `ingestion_run` | (메타) | 매 실행 로그 — 성공/실패/행수/에러 |

---

## 3. 코드 사용법

### 셋업 (최초 1회)

```bash
# Python 3.11+ (개발은 3.14에서 검증)
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# .env 만들고 API 키 입력 (§5 참조)
cp .env.example .env
$EDITOR .env

# DB 초기화 (테이블 생성)
ps-init-db
```

### 데이터 수집 명령

```bash
# 일별 (D1 SMP + D2 supply + D3 weather)
ps-daily                            # 모두
ps-daily --no-supply --no-weather   # D1만
ps-daily --weather-date 2026-05-22  # 특정 날짜 기상

# 월별 (D4 LNG)
ps-monthly

# DR 거래실적 파일 적재 (D5/D6)
ps-dr-ingest --type economic --file data/static/dr_econ_2026_03.csv
ps-dr-ingest --type reliability --file data/static/dr_rel_2026_03.csv
ps-dr-ingest --type economic --url https://example.com/dr.csv
```

### 테스트

```bash
pytest                              # 42 passed in ~10s
```

### 운영 시 cron 예시 (참고)

```cron
# D1 SMP는 23시경 다음날 데이터 공개 → 23:30 KST
30 23 * * *  cd /opt/powersignal && .venv/bin/ps-daily

# D4 LNG는 월 1회
0  3  1 * *  cd /opt/powersignal && .venv/bin/ps-monthly
```

---

## 4. 데이터 흐름

```
.env (API 키)
config/datasets.yaml (엔드포인트)
        │
        ▼
DataGoKrClient ──▶ Collector.fetch (paginate)
        │                  │
        ▼            Collector.parse (필드 매핑)
data/raw/D*/...            │
                            ▼
                    upsert into SQLite/Postgres
                            │
                            ▼
                    ingestion_run 로그 기록
```

핵심 설계 결정:
- **raw 응답은 항상 디스크 보존** → 파싱 실패·스키마 변경에도 원본 복구 가능
- **UPSERT 기반 멱등성** → 동일 데이터 재수집해도 중복 안 됨, 변경분만 갱신
- **포털 에러코드 분류** → 일시 오류는 재시도, 쿼터 초과는 즉시 중단, 영구 오류는 fail-fast
- **거래시간(1~24) 원본 보존** → 시작점/끝점 변환은 가공 단계에서 결정

---

## 5. 🔴 인수자가 해야 할 것

### 5.1 지금 당장 — 코드 돌리려면 필수

#### (1) 공공데이터포털 API 키 4개 발급

[data.go.kr](https://www.data.go.kr) 회원가입 후 각각 **활용신청** 클릭:

| 데이터셋 | 포털 ID | 활용신청 페이지 |
|---|---|---|
| D1 SMP+수요예측 | 15131225 | [data.go.kr/data/15131225/openapi.do](https://www.data.go.kr/data/15131225/openapi.do) |
| D2 실시간수급 | 15056640 | [data.go.kr/data/15056640/openapi.do](https://www.data.go.kr/data/15056640/openapi.do) |
| D3 기상청 ASOS 시간자료 | 15057210 | [data.go.kr/data/15057210/openapi.do](https://www.data.go.kr/data/15057210/openapi.do) |
| D4 월간연료비 | 15099765 | [data.go.kr/data/15099765/openapi.do](https://www.data.go.kr/data/15099765/openapi.do) |

- 활용승인: D1·D2·D4는 보통 즉시~1일 / **D3는 자동승인 (개발·운영 모두)**
- 트래픽: D1·D2·D4는 개발계정 기본 100건/일 / **D3는 10,000건/일** (여유 있음)
- 4개가 같은 키일 수도, 다를 수도 있음 (포털 정책)
- 발급된 **인코딩된 키**를 그대로 복사

**소요시간**: 회원가입 + 신청 4건 = 약 20~30분

> 참고: D3는 "지상(종관, ASOS)" 시리즈에 시간자료/일자료/관측자료가 따로 있음.
> 우리가 필요한 건 **시간자료(15057210)**. 일자료(15059093)나 관측자료(15059218)와 혼동 주의.

#### (2) `.env` 파일 만들기

```bash
cp .env.example .env
# 발급받은 키를 DATA_GO_KR_SERVICE_KEY 와 KMA_SERVICE_KEY 에 입력
```

여기까지가 **코어 작업**. 끝나면 `ps-daily` 실행해서 첫 데이터 받아볼 수 있음.

---

### 5.2 그 다음 — D5/D6 DR 거래실적

이건 OpenAPI가 아니라 **파일 다운로드**:

1. data.go.kr에서 "수요반응자원 거래실적" 검색
2. 경제성DR / 신뢰성DR 각각 CSV 또는 Excel 다운로드
3. `data/static/` 권장 경로에 저장
4. `ps-dr-ingest --type economic --file <경로>` 실행

자동화하려면 `config/datasets.yaml`의 `D5.download_url`에 URL 박아두고 `--url` 옵션으로 정기 실행.

**소요시간**: 파일 다운로드 5분

---

### 5.3 나중에 — 기획팀과 합의 (Phase 3 진입 전)

플랜 문서 §7의 5가지. **지금 당장은 안 해도 됨**. Phase 3(D7~D10) 구현 시점에 답이 있어야 함:

1. **D7 시간별 DR 데이터** 신청 여부 — 월별 D5/D6만으로 갈지, 시간별까지 신청할지
2. **업종별 집중도 지수 산출 공식** — D8/D9 원시통계 → "지수 3.8" 변환 로직
3. **D10 업종 적합도 별점 근거** — 논문/산업자료/도메인 전문가 중 무엇으로?
4. **육지/제주 외 추가 지역 구분** 필요 여부
5. **실시간 수급 데이터 소스 단일화** — D2 하나로 충분한지 확인

D7은 전력거래소 "공공데이터 큐레이션 서비스" 신청 → 승인까지 시간 소요. 진행 결정되면 **즉시 신청** 권장.

---

## 6. 알려진 한계 (인수자가 알아두면 좋을 것)

### 6.1 응답 필드명은 모킹 기반 가정

테스트는 전부 `respx` mock으로 검증했지만, **실제 포털 응답 스키마와 1:1 검증은 못 했음**.

각 collector에는 필드명 후보를 여러 개 두는 패턴이 박혀 있음:

```python
# src/collectors/smp.py
_DATE_KEYS = ("tradeDt", "trade_dt", "tradeDate", "baseDate", ...)
_HOUR_KEYS = ("tradeHh", "trade_hh", "tradeHour", "hh", ...)
```

키 발급 후 첫 호출에서 `data/raw/D1/<오늘>/*.json` 열어보고 실제 필드명을 확인 → 안 맞으면
해당 상수에 한 줄 추가하면 됨. `_first()` 헬퍼가 후보 순회.

### 6.2 D1의 `landSmp`/`jejuSmp` 합쳐진 응답 처리

만약 D1 응답이 한 행에 land/jeju SMP를 같이 담아 돌려주면 (예: `{landSmp: 100, jejuSmp: 110}`),
현재 `parse()`는 **경고만 찍고 스킵**함. 그 형태로 오면 `SmpCollector.fetch()`에서 한 행을
두 행으로 분할하도록 수정 필요. (`src/collectors/smp.py:50` 부근 주석 참조)

### 6.3 D2 실시간 수급의 시각 필드

D2는 API 응답에 관측 시각이 명시되지 않을 수도 있음. 그 경우 `_parse_dt()` 가 **현재 시각으로
폴백**함. 정확한 관측 시각이 필요하면 응답 확인 후 키 매핑 보정 필요.

### 6.4 D3 기상 stations 기본값

`config/datasets.yaml`의 `D3.default_stations`는 주요 8개 도시(서울 108, 부산 159, …)만 들어
있음. 전국 ASOS 전체가 필요하면 KMA 지점 코드표 받아서 확장.

### 6.5 스케줄러 미포함

CLI 진입점만 제공. cron / systemd timer / Airflow / Prefect 등은 운영자가 등록.

### 6.6 마이그레이션 도구 없음

`init_db()` 가 `CREATE IF NOT EXISTS` 만 수행. 컬럼 추가/변경 시 Alembic 도입 권장
(Postgres 운영 전환 시점).

### 6.7 Python 3.14에서 검증

`requires-python = ">=3.11"` 이지만 실제 검증은 3.14에서 함. 3.11~3.13에서 동작은 거의
확실하지만 검증 안 됨.

---

## 7. 인수자 추천 진행 순서

```
[1단계 — 오늘/내일]
  □ data.go.kr 회원가입
  □ D1, D2, D3, D4 활용신청 4건 → 키 발급
  □ .env 만들고 키 입력
  □ ps-daily 한 번 실행
  □ data/raw/D1/<오늘>/*.json 열어 응답 필드명 확인
  □ 필요시 collector의 _KEYS 상수 보정
  □ DB에 행이 들어갔는지 확인 (sqlite3 data/powersignal.db)

[2단계 — 시간 날 때]
  □ D5/D6 CSV 수동 다운로드
  □ ps-dr-ingest 실행

[3단계 — 기획팀 미팅 잡힐 때]
  □ 플랜 §7의 5가지 합의
  □ D7 신청 여부 결정 → 결정되면 즉시 신청 (리드타임)
  □ Phase 3 구현 의뢰
```

---

## 8. 트러블슈팅 빠른 참조

| 증상 | 의심 원인 | 확인할 곳 |
|---|---|---|
| `DataGoKrError [30]: SERVICE_KEY_IS_NOT_REGISTERED` | 키 미발급 / 활용신청 안 함 | data.go.kr 마이페이지 → 활용 승인 여부 |
| `DataGoKrRateLimitError [22]` | 일일 트래픽 초과 | 개발계정 100건/일. 운영계정 전환 필요 |
| `httpx.ConnectError` | 네트워크 / 방화벽 | `curl https://apis.data.go.kr` 로 확인 |
| `Failed to decode CSV` (D5/D6) | 새 인코딩 | `config/datasets.yaml` 의 `encoding_candidates` 에 추가 |
| 첫 호출 후 DB가 비어 있음 | 필드명 미스매치 | `data/raw/D*/` 의 raw JSON 확인 → collector `_KEYS` 보정 |
| `ingestion_run` 에 status='error' | 파싱/upsert 실패 | 같은 행의 `error` 컬럼에 traceback |

```bash
# DB 상태 빠른 점검
sqlite3 data/powersignal.db "SELECT dataset_id, status, rows_inserted, error FROM ingestion_run ORDER BY id DESC LIMIT 10;"
```

---

## 9. 연락처 / 컨텍스트

- 본 코드 작성: Claude Code 협업으로 2026-05-23 한 세션에 작업
- 의사결정 기록 (구현 시작 시 사용자 선택):
  - 범위: Phase 0~2 (그룹1+2)
  - 스토리지: SQLite + raw 파일
  - API 키: `.env.example`만 작성 (실제 키 미보유)
  - 스케줄러: 미포함 (CLI 스크립트만)

질문/이슈 발생 시 위 의사결정 기록 참조.
