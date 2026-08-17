# PMS — 숙박 예약 시스템

[![CI](https://github.com/Diocto/pms/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Diocto/pms/actions/workflows/ci.yml)

동시성 제어, 멱등성, 상태 전이를 중심으로 설계한 숙박 예약 시스템입니다.

## 실행 방법

Docker와 Python 3.12 이상이 필요합니다.

```bash
docker compose up -d                  # MySQL 8.4, Redis 7.4

python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

.venv/bin/alembic upgrade head        # 스키마 적용
.venv/bin/uvicorn app.main:app --reload
```

앱이 떴는지는 `curl localhost:8000/health`로 확인합니다. API 문서는 http://localhost:8000/docs 입니다.

### 화면까지 띄우려면

Node 20 이상이 추가로 필요합니다. 백엔드를 띄운 채로 새 터미널에서:

```bash
cd frontend
npm install
npm run dev                           # http://localhost:3000
```

자세한 것은 [frontend/README.md](frontend/README.md)에 있습니다 — 백엔드 없이 화면만 보는 방법(가짜 응답 모드)도 거기 있습니다.

## 테스트

SQLite가 아니라 Testcontainers로 **실제 MySQL 8.4·Redis 7.4를 띄워** 검증합니다.
SQLite는 행 수준 락이 없고 CHECK 동작도 달라서, 동시성이 주제인 이 프로젝트에서는
통과해도 아무것도 증명하지 못합니다.

```bash
.venv/bin/pytest                       # 전체
.venv/bin/pytest -m "not concurrency"  # 개발 중 빠른 확인
```

## 기술 스택

Python 3.12 · FastAPI · SQLModel(SQLAlchemy) · Dependency Injector · Alembic ·
MySQL 8.4 · Redis 7.4 · Testcontainers · k6

Java/Spring에서 전환한 이유는 [ADR-0050](docs/decisions/ADR-0050-기술-스택-전환.md)에 있습니다.

## 자동화 (CI/CD)

`main`에 코드가 들어오면 GitHub Actions가 테스트를 돌리고, 통과하면 Railway에 배포합니다.

| | 무엇을 하나 |
|---|---|
| **CI** (`.github/workflows/ci.yml`) | 백엔드 `pytest` — **실제 MySQL 8.4·Redis 7.4를 Testcontainers로 띄워서** 돌립니다. 프론트엔드는 `vitest`·타입체크·빌드. 마이그레이션 사슬이 한 줄인지도 함께 봅니다 |
| **CD** (`.github/workflows/cd.yml`) | CI가 **성공으로 끝났을 때만** Railway에 배포합니다. Actions 탭에서 손으로도 돌릴 수 있습니다 |

동시성이 주제인 프로젝트라 CI에서도 SQLite로 바꿔치기하지 않습니다. 그러면 초록불이 거짓이 됩니다.

배포 설정(서비스 구성, 환경변수, 토큰)은 [docs/deploy/railway.md](docs/deploy/railway.md)에 있습니다. **`RAILWAY_TOKEN`이 없으면 배포는 실패가 아니라 건너뜁니다** — 토큰을 넣기 전 상태와 진짜 실패가 구분돼야 하기 때문입니다.

## 문서

**[docs/submission/00-과제-제출.md](docs/submission/00-과제-제출.md) 한 장부터 읽으시면 됩니다.** 이 문서 하나로 전체가 파악되도록 썼고, 나머지는 근거를 확인하고 싶을 때 들어가는 원천 자료입니다.

| 문서 | 내용 |
|---|---|
| `docs/submission/00-과제-제출.md` | **제출 문서 — 여기서 시작** |
| `docs/submission/` | 항목별 상세 (문제 정의·범위·설계·부하테스트·AI 활용) |
| `docs/spec/` | 문제 정의와 feature별 스펙 |
| `docs/decisions/` | 의사결정 이력 (ADR) |
| `docs/architecture/` | 아키텍처·코딩 규칙 |
| `docs/load-test/` | k6 부하테스트 시나리오와 결과 |
