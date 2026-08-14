# PMS — 숙박 예약 시스템

동시성 제어, 멱등성, 상태 전이를 중심으로 설계한 숙박 예약 시스템입니다.

## 실행 방법

Docker가 필요합니다.

```bash
docker compose up -d        # MySQL 8.4, Redis 7.4
./gradlew bootRun
```

## 테스트

테스트는 H2가 아니라 Testcontainers로 실제 MySQL·Redis를 띄워 검증합니다.

```bash
./gradlew test
```

## 기술 스택

Java 21 · Spring Boot 4.0.7 (MVC) · MySQL 8.4 · Redis 7.4 · Flyway · Testcontainers · k6

## 문서

| 문서 | 내용 |
|---|---|
| `docs/submission/` | 제출용 최종 문서 |
| `docs/spec/` | 문제 정의와 feature별 스펙 |
| `docs/decisions/` | 의사결정 이력 (ADR) |
| `docs/architecture/` | 아키텍처·코딩 규칙 |
| `docs/load-test/` | k6 부하테스트 시나리오와 결과 |
