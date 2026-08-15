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
# [재고 쪽]
# 1. 검증용 날짜(부하 시나리오가 쓰지 않는 날짜)의 재고 행을 하나 고른다
# 2. remaining 을 +1 해서 보존식을 일부러 깨뜨린다
# 3. 보존식 쿼리가 그 행을 잡아내는지 본다  -> 못 잡으면 검증기가 고장난 것
# 4. remaining 을 총량 초과로 만들어 복원 과다 쿼리가 잡는지 본다
# 5. remaining 을 음수로 만들어 초과 판매 쿼리가 잡는지 본다
# 6. 원래 값으로 되돌리고, 되돌아갔는지 확인한다
#
# [이력 쪽 — 6·7번]
# 6. 이력 한 줄의 event 를 없는 표기로 바꾼다 -> 표기 검사가 잡아야 한다
# 7. 한 예약에 복원 이벤트를 두 줄로 만든다   -> 이중 복원 쿼리가 잡아야 한다
#
# **이력 검증이 재고 검증보다 조용히 망가지기 쉽다.** 재고 쿼리는 컬럼명이
# 틀리면 에러로 시끄럽게 터지지만, 이력 쿼리는 값 필터라서 표기만 어긋나도
# 0행을 돌려주고 초록불이 된다. 그래서 여기서도 일부러 깨뜨려 본다.
#
# 실행: ./verify/selftest.sh
# 실행 시점: F01 병합 직후 한 번. 그리고 검증 SQL을 고칠 때마다.
#
# ⚠ 이력 항목은 이력 행이 있어야 돌아간다. 병합 직후에는 비어 있으므로
#   **전이가 있는 시나리오(S4·S4-B·S6)를 한 번 돌린 뒤 다시 실행한다.**
#   행이 없으면 건너뛰되, 건너뛴 사실을 크게 찍는다 — 조용히 넘어가면
#   "검증기를 검증했다"는 문장이 절반만 참인 채로 리포트에 들어간다.
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

# ---------------------------------------------------------------------------
# 이력 검증기 자체 검증
# ---------------------------------------------------------------------------
# 여기부터는 reservation_status_history 를 건드린다. 값을 바꿨다가 되돌린다.

count_bad_event() {
    q "SELECT COUNT(*) FROM reservation_status_history
        WHERE event NOT IN ('CONFIRM','PAYMENT_FAILED','CANCEL','EXPIRE',
                            'CHECK_IN','CHECK_OUT');"
}

# common.sql (1) 과 같은 형태여야 한다. 여기를 고치면 저기도 고친다.
count_double_restore() {
    q "SELECT COUNT(*) FROM (
         SELECT reservation_id FROM reservation_status_history
          WHERE event IN ('CANCEL','PAYMENT_FAILED','EXPIRE')
          GROUP BY reservation_id HAVING COUNT(*) > 1
       ) v;"
}

set_event() {   # $1 = 이력 행 id, $2 = 새 event 값
    q "UPDATE reservation_status_history SET event = '$2' WHERE id = $1;"
}

HIST_ROWS=$(q "SELECT COUNT(*) FROM reservation_status_history;")

if [ "$HIST_ROWS" = "0" ]; then
    echo ""
    echo "[selftest] ================================================================"
    echo "[selftest] 건너뜀: 이력 행이 없어 **이력 검증기는 검증하지 못했다.**"
    echo "[selftest] S4·S4-B·S6 중 하나를 돌린 뒤 이 스크립트를 다시 실행해라."
    echo "[selftest] 이걸 안 하면 '검증기를 검증했다'가 절반만 참이다."
    echo "[selftest] ================================================================"
    HISTORY_TESTED=0
else
    HISTORY_TESTED=1

    echo "[selftest] 5. 이력 표기 검사 — 깨뜨리기 전에는 조용해야 한다"
    expect "이상 표기 없음" "$(count_bad_event)" "0"

    # 아무 행이나 하나 골라 표기를 망가뜨린다.
    PROBE_ID=$(q "SELECT id FROM reservation_status_history ORDER BY id LIMIT 1;")
    PROBE_EVENT=$(q "SELECT event FROM reservation_status_history WHERE id = $PROBE_ID;")
    echo "[selftest] 6. 이력 한 줄의 event 를 없는 표기로 바꾼다 (id=$PROBE_ID, $PROBE_EVENT -> selftest_bogus)"

    # 여기서 죽어도 되돌아가게 한다. 재고 복구 trap 에 이어 붙인다.
    # DUP_ID·DUP_EVENT 는 아직 없을 수 있으므로 둘 다 있을 때만 되돌린다.
    trap 'set_remaining "$ORIGINAL" 2>/dev/null || true;
          set_event "$PROBE_ID" "$PROBE_EVENT" 2>/dev/null || true;
          if [ -n "${DUP_ID:-}" ] && [ -n "${DUP_EVENT:-}" ]; then
              set_event "$DUP_ID" "$DUP_EVENT" 2>/dev/null || true
          fi' EXIT

    set_event "$PROBE_ID" "selftest_bogus"
    # 이게 0이면, Enum 표기가 통째로 바뀌어도 아무도 모른다는 뜻이다.
    expect "표기 검사가 이상 값을 잡아낸다" "$(count_bad_event)" "1"

    set_event "$PROBE_ID" "$PROBE_EVENT"
    expect "표기 복구됨" "$(count_bad_event)" "0"

    # 한 예약에 복원 이벤트를 두 줄로 만든다.
    # 복원 이벤트가 이미 하나 있는 예약에서, 복원이 아닌 다른 줄을 복원으로 바꾼다.
    # INSERT 를 쓰지 않는 이유: NOT NULL 컬럼 구성을 추측하게 되고,
    # 스키마가 조금만 달라도 자체 검증이 스키마 문제로 실패한다.
    DUP_ID=$(q "
    SELECT h2.id
      FROM reservation_status_history h2
      JOIN (SELECT reservation_id FROM reservation_status_history
             WHERE event IN ('CANCEL','PAYMENT_FAILED','EXPIRE')
             GROUP BY reservation_id) r ON r.reservation_id = h2.reservation_id
     WHERE h2.event NOT IN ('CANCEL','PAYMENT_FAILED','EXPIRE')
     ORDER BY h2.id LIMIT 1;")

    if [ -z "$DUP_ID" ]; then
        echo "[selftest] 건너뜀: 이중 복원을 만들 만한 이력 조합이 없다."
        echo "[selftest]          (복원 이벤트와 비복원 이벤트를 함께 가진 예약이 필요하다)"
        echo "[selftest]          S6 를 돌린 뒤 다시 실행하면 대개 생긴다."
    else
        DUP_EVENT=$(q "SELECT event FROM reservation_status_history WHERE id = $DUP_ID;")
        echo "[selftest] 7. 이중 복원을 만든다 (id=$DUP_ID, $DUP_EVENT -> CANCEL)"

        BEFORE_DUP=$(count_double_restore)
        set_event "$DUP_ID" "CANCEL"
        AFTER_DUP=$(count_double_restore)

        # 깨뜨린 만큼 정확히 하나 늘어야 한다.
        expect "이중 복원 쿼리가 잡아낸다" "$AFTER_DUP" "$((BEFORE_DUP + 1))"

        set_event "$DUP_ID" "$DUP_EVENT"
        expect "이중 복원 복구됨" "$(count_double_restore)" "$BEFORE_DUP"
    fi
fi

if [ "$FAILED" = "0" ]; then
    echo "[selftest] 전부 통과. 검증 쿼리가 실제로 위반을 잡아낸다."
    if [ "$HISTORY_TESTED" = "1" ]; then
        echo "[selftest] 재고 검증기와 이력 검증기를 **둘 다** 검증했다."
    else
        echo "[selftest] ⚠ 재고 검증기만 검증했다. 이력 검증기는 아직이다."
    fi
    echo "[selftest] 이 결과를 리포트 §5에 기록할 것 — 검증기가 검증됐다는 근거다."
else
    echo "[selftest] 실패 항목이 있다. **검증 쿼리를 고치기 전에는 부하 결과를 믿지 마라.**" >&2
    exit 1
fi
