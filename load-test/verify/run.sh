#!/usr/bin/env bash
#
# 사후 검증 실행기 — **모집단 단언을 하드 게이트로 건다**
#
# ---------------------------------------------------------------------------
# 왜 이 파일이 따로 있는가
# ---------------------------------------------------------------------------
# verify/*.sql 의 검증은 전부 "결과가 비면 통과" 형태다. 그래서 검사 대상이
# 0건이어도 통과로 보인다. **깨진 게 아니라 아무것도 안 본 것인데 초록불이
# 켜진다.**
#
# 특히 값 필터가 위험하다:
#
#   WHERE event IN ('CANCEL', 'PAYMENT_FAILED', 'EXPIRE')
#
# Enum 이 이름(CANCEL)이 아니라 값(cancel)으로 저장되면 이 필터가 0행을
# 돌려주고, "이중 복원 0건"이 초록불로 뜬다. **재고 복원이 정확히 한 번임을
# DB 로 증명하는 유일한 수단이 이 쿼리다.** 그게 무력화되면 동시성 증명
# 전체가 거짓이 된다.
#
# common.sql 의 (0-b) 가 실제 표기를 나열하지만 그건 **눈으로 보는 항목**이다.
# 눈으로 보는 것은 새벽에 건너뛴다. 그래서 여기서 종료 코드로 강제한다.
#
# 규칙: **위반이 0인지 보기 전에, 검사 대상이 0이 아닌지 먼저 단언한다.**
#
# ---------------------------------------------------------------------------
# 시나리오마다 기대가 다르다 — 이게 중요하다
# ---------------------------------------------------------------------------
# "복원 이벤트가 1건 이상"을 전 시나리오에 걸면 S1 에서 정당하게 실패한다.
# S1 은 생성만 하므로 상태 전이 이력이 아예 없는 게 정상이다.
#
# **잘못 우는 게이트는 조작자가 꺼버린다.** 그러면 없느니만 못하다.
# 그래서 시나리오별로 무엇을 기대할지 아래 표에 나눠 적는다.
#
# 사용법:
#   ./verify/run.sh s4        # 전제 확인 -> common.sql -> s4.sql
#   ./verify/run.sh           # 전제 확인 -> common.sql 만
#
set -euo pipefail

MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_USER="${MYSQL_USER:-pms}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-pms}"
MYSQL_DB="${MYSQL_DB:-pms}"

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SCENARIO="${1:-}"

q() {
    mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" \
        -D "$MYSQL_DB" --batch --skip-column-names -e "$1"
}

run_sql_file() {
    mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" \
        -D "$MYSQL_DB" < "$1"
}

# 이 시나리오가 상태 전이를 일으키는가.
# 일으키지 않는 시나리오에서 이력이 비어 있는 것은 정상이다.
case "$SCENARIO" in
    s4|s4b|s6)  EXPECT_HISTORY=1 ;;   # 취소·만료·혼합 — 복원 이벤트가 반드시 나온다
    *)          EXPECT_HISTORY=0 ;;   # 생성 전용(S1·S1-C·S2·S3·S5·S8) 등
esac

echo "[verify] 시나리오=${SCENARIO:-(공통만)}  이력 기대=${EXPECT_HISTORY}"

# --------------------------------------------------------------------------
# 0. 검증 전제 — 여기서 막히면 아래 결과는 전부 믿을 수 없다
# --------------------------------------------------------------------------
FAILED=0

HIST_ROWS=$(q "SELECT COUNT(*) FROM reservation_status_history;")
echo "[verify] 이력 행 수 = $HIST_ROWS"

# 기대 표기를 벗어난 값이 있는가. 있으면 값 필터가 조용히 빗나가고 있다는 뜻이다.
BAD_EVENT=$(q "
SELECT COUNT(*) FROM reservation_status_history
 WHERE event NOT IN ('CONFIRM','PAYMENT_FAILED','CANCEL','EXPIRE','CHECK_IN','CHECK_OUT');")
BAD_STATUS=$(q "
SELECT COUNT(*) FROM reservation_status_history
 WHERE to_status NOT IN ('PENDING','CONFIRMED','CHECKED_IN','CHECKED_OUT','CANCELLED','EXPIRED');")

if [ "$BAD_EVENT" != "0" ] || [ "$BAD_STATUS" != "0" ]; then
    echo "[verify] 실패: 기대하지 않은 표기가 저장돼 있다 (event=$BAD_EVENT행, status=$BAD_STATUS행)." >&2
    echo "[verify] Enum 이 이름이 아니라 값으로 저장됐을 가능성이 크다." >&2
    echo "[verify] 실제 저장된 표기:" >&2
    q "SELECT DISTINCT event FROM reservation_status_history;" >&2
    q "SELECT DISTINCT to_status FROM reservation_status_history;" >&2
    echo "[verify] **verify/*.sql 의 값 필터를 고치기 전에는 어떤 결과도 믿지 마라.**" >&2
    FAILED=1
fi

if [ "$EXPECT_HISTORY" = "1" ]; then
    if [ "$HIST_ROWS" = "0" ]; then
        echo "[verify] 실패: 이 시나리오는 상태 전이를 일으키는데 이력이 비어 있다." >&2
        echo "[verify] 부하가 실제로 안 걸렸거나 테이블명이 다르다." >&2
        FAILED=1
    fi

    # 핵심 단언. 필터가 실제로 무언가를 잡고 있어야
    # 그다음 "HAVING COUNT(*) > 1 이 0행"이 의미를 갖는다.
    RESTORE_ROWS=$(q "
    SELECT COUNT(*) FROM reservation_status_history
     WHERE event IN ('CANCEL','PAYMENT_FAILED','EXPIRE');")
    echo "[verify] 복원 이벤트 행 수 = $RESTORE_ROWS"

    if [ "$RESTORE_ROWS" = "0" ]; then
        echo "[verify] 실패: 복원 이벤트 필터가 0행을 잡았다." >&2
        echo "[verify] 이 상태에서 '이중 복원 0건'은 통과가 아니라 **미검사**다." >&2
        FAILED=1
    fi
fi

if [ "$FAILED" != "0" ]; then
    echo "[verify] 전제가 깨졌다. 검증을 진행하지 않는다." >&2
    exit 1
fi
echo "[verify] 전제 통과. 검증을 진행한다."

# --------------------------------------------------------------------------
# 1. 공통 검증 + 시나리오 검증
# --------------------------------------------------------------------------
run_sql_file "${SCRIPT_DIR}/common.sql"

if [ -n "$SCENARIO" ]; then
    SCENARIO_SQL="${SCRIPT_DIR}/${SCENARIO}.sql"
    if [ -f "$SCENARIO_SQL" ]; then
        run_sql_file "$SCENARIO_SQL"
    else
        echo "[verify] 경고: ${SCENARIO}.sql 이 없다. 공통 검증만 돌렸다." >&2
    fi
fi

echo "[verify] 끝. **결과가 비어 있는지 눈으로 확인하는 것은 여전히 사람 몫이다.**"
