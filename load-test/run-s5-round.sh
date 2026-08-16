#!/usr/bin/env bash
#
# S5 락 유무 대조 — 한 회차 실행기
#
# 한 회차 = 앱 재기동(스위치 주입) → reset(스위치 실물 확인 포함) → DB 지표
# 스냅샷 → k6 부하 → DB 지표 델타 → 사후 검증 → 로그 카운트.
#
# 사용법:
#   ./run-s5-round.sh on 1     # 락 ON, 1회차
#   ./run-s5-round.sh off 1    # 락 OFF, 1회차
#
# 환경변수:
#   UVICORN_BIN  uvicorn 실행 파일 (기본: PATH의 uvicorn)
#   WORKERS      uvicorn 워커 수 (기본 4. **ON/OFF 두 조건이 반드시 같아야 한다**)
#   PORT         부하 대상 포트 (기본 8080 — 8000은 시연용이라 건드리지 않는다)
#
# 이 스크립트가 8080 리스너를 죽이고 다시 띄운다. 8000(시연용)은 절대
# 건드리지 않는다.
set -euo pipefail

COND="${1:?on|off}"
ROUND="${2:?회차 번호}"
case "$COND" in on|off) ;; *) echo "COND는 on|off" >&2; exit 1 ;; esac

PORT="${PORT:-8080}"
WORKERS="${WORKERS:-4}"
UVICORN_BIN="${UVICORN_BIN:-uvicorn}"

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
APP_DIR="${SCRIPT_DIR}/.."
RESULTS_DIR="${APP_DIR}/docs/load-test/results"
mkdir -p "$RESULTS_DIR"

TAG="s5${COND}-r${ROUND}"
APP_LOG="${RESULTS_DIR}/app-${TAG}.log"
BASE_URL="http://localhost:${PORT}"

if [ "$COND" = "on" ]; then LOCK=true; else LOCK=false; fi

MYSQL_ARGS=(-h 127.0.0.1 -P 3306 -u pms -ppms -D pms --batch --skip-column-names)
mq() { mysql "${MYSQL_ARGS[@]}" -e "$1"; }

echo "=== [${TAG}] 락=${LOCK} 워커=${WORKERS} 포트=${PORT} ==="

# ---------------------------------------------------------------------------
# 1. 앱 재기동 (스위치는 환경변수로만 주입한다)
# ---------------------------------------------------------------------------
OLD_PIDS=$(lsof -ti tcp:"${PORT}" -sTCP:LISTEN 2>/dev/null | sort -u || true)
if [ -n "$OLD_PIDS" ]; then
    echo "[${TAG}] 기존 ${PORT} 리스너 종료: $OLD_PIDS"
    kill $OLD_PIDS 2>/dev/null || true
    for _ in $(seq 1 20); do
        lsof -ti tcp:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1 || break
        sleep 0.5
    done
fi

(
    cd "$APP_DIR"
    PMS_LOCK_ENABLED="$LOCK" nohup "$UVICORN_BIN" app.main:app \
        --host 127.0.0.1 --port "$PORT" --workers "$WORKERS" \
        > "$APP_LOG" 2>&1 &
)

UP=0
for _ in $(seq 1 60); do
    if curl -sf --max-time 2 "${BASE_URL}/health" > /dev/null 2>&1; then UP=1; break; fi
    sleep 0.5
done
if [ "$UP" != "1" ]; then
    echo "[${TAG}] 실패: 앱이 안 뜬다. ${APP_LOG} 확인." >&2
    exit 1
fi

# 워커가 전부 뜰 시간을 준다 (health 는 첫 워커만 떠도 응답한다)
sleep 2

# ---------------------------------------------------------------------------
# 2. 초기화 + 스위치 실물 확인 (reset.sh 가 다르면 중단한다)
# ---------------------------------------------------------------------------
BASE_URL="$BASE_URL" "${SCRIPT_DIR}/reset.sh" "s5${COND}"
cp "${RESULTS_DIR}/settings-s5${COND}.json" "${RESULTS_DIR}/settings-${TAG}.json"

# ---------------------------------------------------------------------------
# 3. DB 지표 스냅샷(前) + 커넥션 표본 수집기 기동
# ---------------------------------------------------------------------------
mq "SHOW GLOBAL STATUS WHERE Variable_name IN
    ('Innodb_row_lock_waits','Innodb_row_lock_time','Innodb_row_lock_current_waits',
     'Com_insert','Com_update','Threads_connected','Max_used_connections');" \
    > "${RESULTS_DIR}/dbstat-${TAG}-before.txt"

SAMPLER_OUT="${RESULTS_DIR}/dbsample-${TAG}.txt"
: > "$SAMPLER_OUT"
(
    while :; do
        mq "SELECT CONCAT(UNIX_TIMESTAMP(NOW(3)),' ',
                   (SELECT VARIABLE_VALUE FROM performance_schema.global_status WHERE VARIABLE_NAME='Threads_running'),' ',
                   (SELECT VARIABLE_VALUE FROM performance_schema.global_status WHERE VARIABLE_NAME='Threads_connected'),' ',
                   (SELECT VARIABLE_VALUE FROM performance_schema.global_status WHERE VARIABLE_NAME='Innodb_row_lock_current_waits'));" \
            >> "$SAMPLER_OUT" 2>/dev/null || true
        sleep 0.5
    done
) &
SAMPLER_PID=$!
trap 'kill $SAMPLER_PID 2>/dev/null || true' EXIT

# ---------------------------------------------------------------------------
# 4. 부하 (S2 스크립트 재사용 — "같은 부하"의 보장이 곧 같은 코드다)
# ---------------------------------------------------------------------------
# p99까지 요약에 싣는다. 락 대기는 지연 꼬리에 얹히므로 p95만으로는
# 대조의 핵심이 안 보인다 (scenarios.md §4 S5 비교 항목).
export K6_SUMMARY_TREND_STATS="avg,min,med,max,p(90),p(95),p(99)"

set +e
(
    cd "$SCRIPT_DIR"
    TARGET="s5${COND}" BASE_URL="$BASE_URL" k6 run s2-inventory-sustained.js \
        --summary-export="${RESULTS_DIR}/${TAG}-k6-summary.json" \
        2>&1 | tee "${RESULTS_DIR}/${TAG}-k6-stdout.log"
    exit "${PIPESTATUS[0]}"
)
K6_EXIT=$?
set -e

kill $SAMPLER_PID 2>/dev/null || true
trap - EXIT

# ---------------------------------------------------------------------------
# 5. DB 지표 스냅샷(後) + 사후 검증 + 로그 카운트
# ---------------------------------------------------------------------------
mq "SHOW GLOBAL STATUS WHERE Variable_name IN
    ('Innodb_row_lock_waits','Innodb_row_lock_time','Innodb_row_lock_current_waits',
     'Com_insert','Com_update','Threads_connected','Max_used_connections');" \
    > "${RESULTS_DIR}/dbstat-${TAG}-after.txt"

set +e
"${SCRIPT_DIR}/verify/run.sh" "s5${COND}" > "${RESULTS_DIR}/verify-${TAG}.log" 2>&1
VERIFY_EXIT=$?
set -e

LOCK_NOT_OWNED=$(grep -c LockNotOwnedError "$APP_LOG" || true)
INTERNAL_ERR=$(grep -c INTERNAL_ERROR "$APP_LOG" || true)

echo "=== [${TAG}] 끝 ==="
echo "k6 종료코드=${K6_EXIT}  verify 종료코드=${VERIFY_EXIT}"
echo "LockNotOwnedError=${LOCK_NOT_OWNED}  INTERNAL_ERROR=${INTERNAL_ERR}"
echo "결과: ${RESULTS_DIR}/${TAG}-k6-summary.json, verify-${TAG}.log, dbstat-${TAG}-{before,after}.txt"
