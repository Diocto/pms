#!/bin/sh
# 배포 기동 절차. 마이그레이션 → 앱 순서이고, 앞이 실패하면 뒤로 가지 않는다.
set -e

# 접속 정보가 없으면 조용히 기본값(localhost)으로 뜨는 것이 가장 나쁘다.
# 로컬을 가리킨 채 헬스체크만 통과하고 모든 요청이 실패한다. 먼저 크게 죽는다.
if [ -z "${PMS_DATABASE_URL}" ]; then
  echo "PMS_DATABASE_URL이 없다. Railway 변수에 mysql+pymysql://... 형식으로 넣어야 한다." >&2
  exit 1
fi
if [ -z "${PMS_REDIS_URL}" ]; then
  echo "PMS_REDIS_URL이 없다. Railway 변수에 redis://... 형식으로 넣어야 한다." >&2
  exit 1
fi

echo "[entrypoint] 마이그레이션 적용"
alembic upgrade head

# 워커 수는 기본 2다. 만료 스케줄러가 워커마다 하나씩 돌지만, 만료는 조건부
# UPDATE라 여러 번 시도해도 한 번만 성공한다(F01 상태 전이 표). 다만 불필요한
# 스캔이므로 시연 환경에서는 1로 두는 것도 맞다.
PORT="${PORT:-8000}"
WORKERS="${WEB_CONCURRENCY:-2}"

echo "[entrypoint] uvicorn 기동 (포트 ${PORT}, 워커 ${WORKERS})"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" --workers "${WORKERS}"
