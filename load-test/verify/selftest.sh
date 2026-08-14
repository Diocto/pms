#!/usr/bin/env bash
#
# 검증기를 검증한다 (self-test)
#
# ---------------------------------------------------------------------------
# 왜 필요한가
# ---------------------------------------------------------------------------
# 이 프로젝트의 불변식 검증은 전부 **"결과가 비면 통과"** 형태다.
#
#   SELECT ... HAVING diff <> 0;        -- 0행이면 통과
#   SELECT ... WHERE remaining < 0;     -- 0행이면 통과
#
# 그래서 쿼리가 조용히 잘못되면 — 컬럼명 오타, 날짜 범위 어긋남, JOIN 조건
# 실수 — **모든 검증이 초록이 된다.** 그리고 리포트에는 "전 시나리오 불변식
# 통과"라고 적힌다. 검증 체계 전체가 한 번에 무력화되는데 아무도 모른다.
#
# reset.sh의 "대상 재고 행 수 > 0" 검사가 1차 방어선이지만, 그건 "행을 잡고
# 있다"만 보장할 뿐 "위반을 실제로 잡아낸다"는 보장하지 않는다.
#
# 그래서 **일부러 깨뜨려보고 검증 쿼리가 잡는지 확인한다.**
# 5분이면 되고, 이게 없으면 "모든 검증 통과"가 무의미할 수 있다는 가능성이
# 리포트에 그대로 남는다.
#
# ---------------------------------------------------------------------------
# 무엇을 하는가
# ---------------------------------------------------------------------------
# 1. 검증용 날짜(부하 시나리오가 쓰지 않는 날짜)의 재고 행을 하나 고른다
# 2. remaining 을 +1 해서 보존식을 일부러 깨뜨린다
# 3. 보존식 쿼리가 그 행을 잡아내는지 본다  -> 못 잡으면 검증기가 고장난 것
# 4. remaining 을 총량 초과로 만들어 복원 과다 쿼리가 잡는지 본다
# 5. remaining 을 음수로 만들어 초과 판매 쿼리가 잡는지 본다
# 6. 원래 값으로 되돌리고, 되돌아갔는지 확인한다
#
# 실행: ./verify/selftest.sh
# 실행 시점: F01 병합 직후 한 번. 그리고 검증 SQL을 고칠 때마다.
#
set -euo pipefail

MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_USER="${MYSQL_USER:-pms}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-pms}"
MYSQL_DB="${MYSQL_DB:-pms}"

# 안전장치. reset.sh와 같은 이유다.
case "$MYSQL_HOST" in
    127.0.0.1|localhost|::1) ;;
    *) echo "거부: MYSQL_HOST=$MYSQL_HOST 는 localhost가 아니다." >&2; exit 1 ;;
esac

# 어떤 부하 시나리오도 쓰지 않는 날짜를 고른다.
# 09-17 ~ 09-20 은 S7(~09-16)과 S6(09-21~) 사이의 빈 구간이다.
TEST_DATE="${TEST_DATE:-2026-09-18}"
TEST_RT="${TEST_RT:-3}"   # 스위트. 총 10실이라 눈으로 확인하기 쉽다

q() {
    mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" \
        -D "$MYSQL_DB" --batch --skip-column-names -e "$1"
}

# 보존식 위반 행 수를 센다. verify/*.sql 의 보존식 쿼리와 같은 형태여야 한다.
# **이 쿼리를 고치면 verify/*.sql 의 보존식도 같이 고쳐야 한다.**
count_conservation_violations() {
    q "
    SELECT COUNT(*) FROM (
      SELECT i.room_type_id, i.stay_date
        FROM room_daily_inventory i
        JOIN room_type rt ON rt.id = i.room_type_id
        LEFT JOIN reservation r
          ON r.room_type_id = i.room_type_id
         AND i.stay_date >= r.check_in AND i.stay_date < r.check_out
         AND r.status NOT IN ('CANCELLED', 'EXPIRED')
       WHERE i.stay_date = '$TEST_DATE' AND i.room_type_id = $TEST_RT
       GROUP BY i.room_type_id, i.stay_date, i.remaining, rt.total_quantity
      HAVING i.remaining + COALESCE(SUM(r.room_count), 0) <> rt.total_quantity
    ) v;"
}

count_negative() {
    q "SELECT COUNT(*) FROM room_daily_inventory
        WHERE stay_date = '$TEST_DATE' AND room_type_id = $TEST_RT AND remaining < 0;"
}

count_over_restore() {
    q "SELECT COUNT(*) FROM room_daily_inventory i
         JOIN room_type rt ON rt.id = i.room_type_id
        WHERE i.stay_date = '$TEST_DATE' AND i.room_type_id = $TEST_RT
          AND i.remaining > rt.total_quantity;"
}

set_remaining() {
    q "UPDATE room_daily_inventory SET remaining = $1
        WHERE stay_date = '$TEST_DATE' AND room_type_id = $TEST_RT;"
}

FAILED=0
expect() {
    local label="$1" actual="$2" want="$3"
    if [ "$actual" = "$want" ]; then
        echo "  통과  $label (기대=$want, 실제=$actual)"
    else
        echo "  실패  $label (기대=$want, 실제=$actual)" >&2
        FAILED=1
    fi
}

echo "[selftest] 대상: room_type_id=$TEST_RT, stay_date=$TEST_DATE"

TOTAL=$(q "SELECT total_quantity FROM room_type WHERE id = $TEST_RT;")
ORIGINAL=$(q "SELECT remaining FROM room_daily_inventory
               WHERE stay_date = '$TEST_DATE' AND room_type_id = $TEST_RT;")

if [ -z "$ORIGINAL" ]; then
    echo "[selftest] 실패: 대상 재고 행이 없다. 날짜나 테이블명을 확인할 것." >&2
    exit 1
fi
echo "[selftest] 총 객실 수=$TOTAL, 현재 잔여=$ORIGINAL"

# 되돌리기를 보장한다. 중간에 죽어도 원래 값으로 복구된다.
trap 'set_remaining "$ORIGINAL" 2>/dev/null || true' EXIT

echo "[selftest] 0. 깨뜨리기 전 — 검증 쿼리가 조용해야 한다"
expect "보존식 위반 없음" "$(count_conservation_violations)" "0"
expect "음수 없음"        "$(count_negative)" "0"
expect "복원 과다 없음"   "$(count_over_restore)" "0"

echo "[selftest] 1. 보존식을 깨뜨린다 (잔여 +1)"
set_remaining "$((ORIGINAL + 1))"
# 이게 0이면 보존식 쿼리가 위반을 못 잡는다는 뜻이다. 검증기가 고장난 것이다.
expect "보존식 쿼리가 위반을 잡아낸다" "$(count_conservation_violations)" "1"

echo "[selftest] 2. 복원 과다를 만든다 (잔여 = 총량 + 5)"
set_remaining "$((TOTAL + 5))"
expect "복원 과다 쿼리가 잡아낸다" "$(count_over_restore)" "1"

echo "[selftest] 3. 초과 판매를 만든다 (잔여 = -1)"
# CHECK 제약이 있으면 이 UPDATE 자체가 거부된다. 그건 실패가 아니라
# **최후 방어선이 살아 있다는 증거**이므로 그렇게 기록한다.
if set_remaining "-1" 2>/dev/null; then
    expect "음수 쿼리가 잡아낸다" "$(count_negative)" "1"
    echo "  참고  DB CHECK 제약이 음수를 막지 않았다. 3차 방어선을 확인할 것."
else
    echo "  통과  DB CHECK 제약이 음수 UPDATE를 거부했다 — 3차 방어선이 살아 있다"
fi

echo "[selftest] 4. 원래 값으로 되돌린다"
set_remaining "$ORIGINAL"
RESTORED=$(q "SELECT remaining FROM room_daily_inventory
               WHERE stay_date = '$TEST_DATE' AND room_type_id = $TEST_RT;")
expect "잔여가 원래 값으로 복구됨" "$RESTORED" "$ORIGINAL"
expect "보존식 위반 없음 (복구 후)" "$(count_conservation_violations)" "0"

if [ "$FAILED" = "0" ]; then
    echo "[selftest] 전부 통과. 검증 쿼리가 실제로 위반을 잡아낸다."
    echo "[selftest] 이 결과를 리포트에 기록할 것 — 검증기가 검증됐다는 근거다."
else
    echo "[selftest] 실패 항목이 있다. **검증 쿼리를 고치기 전에는 부하 결과를 믿지 마라.**" >&2
    exit 1
fi
