# PMS — 숙박 예약 시스템

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

앱이 떴는지는 `curl localhost:8000/health`로 확인합니다.

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

## 문서

| 문서 | 내용 |
|---|---|
| `docs/submission/` | 제출용 최종 문서 |
| `docs/spec/` | 문제 정의와 feature별 스펙 |
| `docs/decisions/` | 의사결정 이력 (ADR) |
| `docs/architecture/` | 아키텍처·코딩 규칙 |
| `docs/load-test/` | k6 부하테스트 시나리오와 결과 |
