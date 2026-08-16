# Railway 배포

GitHub Actions가 테스트를 돌리고, 통과하면 Railway에 배포한다.

- CI: `.github/workflows/ci.yml` — `main` 푸시와 PR에서 백엔드·프론트엔드 테스트
- CD: `.github/workflows/cd.yml` — CI가 **성공으로 끝났을 때만** 배포. 손으로도 돌릴 수 있다

AWS가 아니라 Railway를 쓴 이유는 요금이다. 이 과제는 시연이 목적이라 관리형 MySQL·Redis를 한 곳에서 붙일 수 있으면 충분하다.

---

## 1. Railway에 만들 것

프로젝트 하나에 서비스 넷을 둔다.

| 서비스 | 무엇 | 만드는 법 |
|---|---|---|
| `MySQL` | DB | Railway 템플릿 (MySQL 8) |
| `Redis` | 캐시·락 | Railway 템플릿 |
| `pms-api` | 백엔드 | 이 저장소, 루트 디렉터리 `/`, Dockerfile 빌드 |
| `pms-web` | 화면 | 이 저장소, 루트 디렉터리 `frontend`, Dockerfile 빌드 |

서비스 이름을 다르게 짓겠다면 GitHub 저장소 변수(Settings → Secrets and variables → Actions → Variables)에 `RAILWAY_BACKEND_SERVICE`, `RAILWAY_FRONTEND_SERVICE`로 실제 이름을 넣는다. 안 넣으면 위 이름을 쓴다.

## 2. 변수

### `pms-api`

| 키 | 값 |
|---|---|
| `PMS_DATABASE_URL` | `mysql+pymysql://${{MySQL.MYSQLUSER}}:${{MySQL.MYSQLPASSWORD}}@${{MySQL.RAILWAY_PRIVATE_DOMAIN}}:3306/${{MySQL.MYSQLDATABASE}}` |
| `PMS_REDIS_URL` | `redis://default:${{Redis.REDISPASSWORD}}@${{Redis.RAILWAY_PRIVATE_DOMAIN}}:6379/0` |
| `WEB_CONCURRENCY` | `2` (시연이면 `1`도 된다 — 아래 「워커 수」 참고) |

**`mysql://`가 아니라 `mysql+pymysql://`이다.** Railway가 주는 `MYSQL_URL`을 그대로 넣으면 SQLAlchemy가 드라이버를 못 찾는다. 위 형태로 직접 조립해야 한다.

### `pms-web`

| 키 | 값 |
|---|---|
| `PMS_BACKEND_ORIGIN` | `http://${{pms-api.RAILWAY_PRIVATE_DOMAIN}}:8000` |

**이 값은 빌드 시점에 필요하다.** Next.js의 `rewrites`는 빌드할 때 `.next/routes-manifest.json`에 문자열로 구워지므로, 실행할 때 환경변수를 바꿔도 이미 늦다. 실제로 실행 시점에만 넣고 돌려봤더니 `localhost:8000`으로 굳어 프록시가 500을 냈다. Railway는 서비스 변수를 빌드 인자로도 넘겨주므로 위 변수 하나면 되지만, **백엔드 주소를 바꾸면 프론트를 다시 빌드해야 한다.**

## 3. GitHub에 넣을 것

| 종류 | 이름 | 값 |
|---|---|---|
| Secret | `RAILWAY_TOKEN` | Railway → 프로젝트 → Settings → Tokens에서 만든 **프로젝트 토큰** |
| Variable (선택) | `RAILWAY_ENVIRONMENT` | 기본 `production` |
| Variable (선택) | `RAILWAY_BACKEND_SERVICE` | 기본 `pms-api` |
| Variable (선택) | `RAILWAY_FRONTEND_SERVICE` | 기본 `pms-web` |

**토큰이 없으면 CD는 배포를 건너뛴다.** 빨간 X가 아니라 건너뜀으로 처리한 이유는, 토큰을 넣기 전의 상태와 진짜 실패가 구분돼야 하기 때문이다.

## 4. 배포가 도는 순서

```
main 푸시
  → CI: 백엔드 pytest(실제 MySQL·Redis) · 프론트 vitest·타입체크·빌드
  → 통과하면 CD: railway up (백엔드 · 프론트)
  → Railway가 빌드·기동
```

CD는 **CI가 통과한 그 커밋**을 배포한다(`workflow_run.head_sha`). 배포만 다시 하고 싶으면 Actions 탭에서 `CD (Railway)` → Run workflow로 대상을 골라 돌린다.

## 5. 기동할 때 무슨 일이 일어나는가

`docker/entrypoint.sh`가 이 순서로 돈다.

1. `PMS_DATABASE_URL`·`PMS_REDIS_URL`이 있는지 본다. 없으면 **바로 죽는다**(종료 코드 1)
2. `alembic upgrade head` — 스키마와 시드를 적용한다
3. `uvicorn` 기동

접속 정보가 없을 때 기본값(localhost)으로 조용히 뜨는 것이 가장 나쁘다. 헬스체크만 통과하고 모든 요청이 실패한다. 그래서 먼저 크게 죽인다.

**마이그레이션이 실패하면 앱이 뜨지 않는다.** 스키마가 어긋난 채 뜨는 것보다 안 뜨는 쪽이 안전하다.

## 6. 알아둘 것

**워커 수.** 만료 스케줄러가 워커마다 하나씩 돈다. 만료는 조건부 UPDATE라 여러 워커가 같은 예약을 집어도 한 번만 성공하므로 정합성 문제는 없지만, 불필요한 스캔이 워커 수만큼 늘어난다. DB 커넥션도 워커당 최대 15개를 쓴다(`WEB_CONCURRENCY=2`면 상한 30). 시연 목적이면 `1`로 두는 것이 단순하다.

**시연 데이터.** 마이그레이션 시드는 호텔 100곳과 재고까지만 만든다. 예약은 0건이므로 「내 예약」 화면이 비어 있는 것이 정상이다. 채우려면 배포된 백엔드를 향해 `frontend/demo-seed.py`를 돌린다.

**이 배포는 부하테스트 결과의 근거가 아니다.** 리포트의 수치는 전부 노트북 한 대에서 잰 것이고(`docs/load-test/report.md` §2), Railway 인스턴스에서 다시 재지 않았다. 두 환경의 수치를 섞어 읽으면 안 된다.

**비용.** 서비스 넷이 상시로 돈다. 시연이 끝나면 내리거나 sleep을 걸어두는 편이 좋다.
