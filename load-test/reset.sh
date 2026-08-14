#!/usr/bin/env bash
#
# F04 부하테스트 — 실행 전 초기화
#
# 이전 실행의 잔여 데이터가 섞이면 불변식 검증이 전부 무의미해진다.
# "성공이 정확히 10건인가"라는 판정 자체가 성립하지 않기 때문이다.
# 그래서 매 실행 전에 반드시 돌린다.
#
# 초기화 대상 (PM 승인 D5 조건 4에 따른 명시)
#   - reservation                 : 대상 날짜 대역 행 DELETE          [F01 소유]
#   - reservation_status_history  : 대상 날짜 대역 행 DELETE          [F01 소유]
#   - room_daily_inventory        : remaining = total_quantity 로 복원 [F01 소유]
#   - promotion_inventory         : S7 실행 시에만 초기값 복원        [F02 소유, 이름 미확정]
#   - Redis 전체                  : FLUSHDB (멱등키·분산락·캐시)
#
# 스키마와 마이그레이션은 절대 건드리지 않는다. DDL을 실행하지 않으며 DML만 한다.
# 위 목록에 없는 테이블을 초기화해야 할 상황이 생기면 스크립트를 고치기 전에
# PM에게 보고한다.
#
# 재고를 임의 값으로 바꾸지 않고 total_quantity 로 되돌리는 이유:
#   F01 시드의 초기 remaining 이 전부 total_quantity 와 같다. 그래서 이 스크립트가
#   만드는 상태는 완전 재시드(docker compose down -v && 재기동)와 정확히 같아진다.
#   임의 값으로 줄이면 보존식(remaining + 점유 = total_quantity)이 깨지고,
#   "빠른 초기화로 돌린 결과"와 "완전 재시드로 돌린 결과"가 달라진다.
#   그 차이는 원인 찾기가 아주 어렵다.
#
# 사용법:
#   ./reset.sh s1        # 시나리오 하나
#   ./reset.sh all       # 시드 범위 전체
#
set -euo pipefail

MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_USER="${MYSQL_USER:-pms}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-pms}"
MYSQL_DB="${MYSQL_DB:-pms}"
REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"

# --------------------------------------------------------------------------
# 안전장치 — 로컬이 아니면 아무것도 하지 않는다
# --------------------------------------------------------------------------
# 이 스크립트는 예약을 지우고 재고를 되돌린다. 실수로 로컬이 아닌 곳을
# 가리키면 복구할 수 없다. PM 승인 조건(2)이기도 하다.
case "$MYSQL_HOST" in
    127.0.0.1|localhost|::1) ;;
    *)
        echo "거부: MYSQL_HOST=$MYSQL_HOST 는 localhost가 아니다." >&2
        echo "이 스크립트는 로컬 부하테스트 환경에서만 돌린다." >&2
        exit 1
        ;;
esac
case "$REDIS_HOST" in
    127.0.0.1|localhost|::1) ;;
    *)
        echo "거부: REDIS_HOST=$REDIS_HOST 는 localhost가 아니다." >&2
        exit 1
        ;;
esac

SCENARIO="${1:-}"
if [ -z "$SCENARIO" ]; then
    echo "사용법: ./reset.sh <시나리오>   (s1 s1c s2 s3 s4 s4b s5on s5off s6 s7 s8 all)" >&2
    exit 1
fi

# 시나리오별 날짜 대역. config.js 의 PLAN 과 반드시 일치시킨다.
# 한쪽만 고치면 초기화한 날짜와 부하를 넣는 날짜가 어긋나, 재고가 안 돌아온
# 채로 실행돼 성공 0건이 나온다.
case "$SCENARIO" in
    s1)    FROM=2026-09-01; TO=2026-09-01 ;;
    s1c)   FROM=2026-09-02; TO=2026-09-02 ;;
    s2)    FROM=2026-09-03; TO=2026-09-03 ;;
    s3)    FROM=2026-09-04; TO=2026-09-04 ;;
    s4)    FROM=2026-09-05; TO=2026-09-07 ;;
    s4b)   FROM=2026-09-08; TO=2026-09-11 ;;
    s5on)  FROM=2026-09-12; TO=2026-09-12 ;;
    s5off) FROM=2026-09-13; TO=2026-09-13 ;;
    s7)    FROM=2026-09-14; TO=2026-09-16 ;;
    s6)    FROM=2026-09-21; TO=2026-09-30 ;;
    s8)    FROM=2026-10-01; TO=2026-10-10 ;;
    all)   FROM=2026-08-01; TO=2026-10-29 ;;
    *) echo "알 수 없는 시나리오: $SCENARIO" >&2; exit 1 ;;
esac

mysql_run() {
    mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" \
        -D "$MYSQL_DB" --batch --skip-column-names -e "$1"
}

echo "[reset] 시나리오=$SCENARIO 날짜=$FROM ~ $TO"

# --------------------------------------------------------------------------
# 1. 예약 삭제
# --------------------------------------------------------------------------
# 이력을 먼저 지운다 (reservation FK 때문에 순서가 중요하다).
# F01이 아직 안 병합됐으면 테이블이 없으므로 조용히 넘어간다.
mysql_run "
DELETE h FROM reservation_status_history h
  JOIN reservation r ON r.id = h.reservation_id
 WHERE r.check_in BETWEEN '$FROM' AND '$TO';
" 2>/dev/null || echo "[reset] reservation_status_history 없음 — 건너뜀"

mysql_run "DELETE FROM reservation WHERE check_in BETWEEN '$FROM' AND '$TO';"

# --------------------------------------------------------------------------
# 2. 재고 복원
# --------------------------------------------------------------------------
mysql_run "
UPDATE room_daily_inventory i
  JOIN room_type rt ON rt.id = i.room_type_id
   SET i.remaining = rt.total_quantity
 WHERE i.stay_date BETWEEN '$FROM' AND '$TO';
"

# 프로모션 재고 (S7 전용). 테이블 이름이 미확정이라 실패해도 넘어간다.
if [ "$SCENARIO" = "s7" ] || [ "$SCENARIO" = "all" ]; then
    mysql_run "
    UPDATE promotion_inventory p
       SET p.remaining = p.total_quantity
     WHERE p.stay_date BETWEEN '$FROM' AND '$TO';
    " 2>/dev/null || echo "[reset] promotion_inventory 없음 — 건너뜀 (F02 미병합)"
fi

# --------------------------------------------------------------------------
# 3. Redis 비우기
# --------------------------------------------------------------------------
# 이걸 빼먹으면 S3(멱등성)이 이전 실행의 키에 걸려 전부 409를 받는다.
redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" FLUSHDB > /dev/null
echo "[reset] Redis FLUSHDB 완료"

# --------------------------------------------------------------------------
# 4. 초기 상태 검증 — 여기서 안 맞으면 실행하지 않는다
# --------------------------------------------------------------------------
# 검증 쿼리가 컬럼명 오타로 0행을 반환하면 "불변식 통과"로 오독된다.
# 이 단계가 그 1차 방어선이다. 데이터를 실제로 잡고 있는지 매번 확인한다.
LEFTOVER=$(mysql_run "SELECT COUNT(*) FROM reservation WHERE check_in BETWEEN '$FROM' AND '$TO';")
MISMATCH=$(mysql_run "
SELECT COUNT(*) FROM room_daily_inventory i
  JOIN room_type rt ON rt.id = i.room_type_id
 WHERE i.stay_date BETWEEN '$FROM' AND '$TO'
   AND i.remaining <> rt.total_quantity;
")
ROWS=$(mysql_run "
SELECT COUNT(*) FROM room_daily_inventory
 WHERE stay_date BETWEEN '$FROM' AND '$TO';
")

echo "[reset] 남은 예약=$LEFTOVER  재고 불일치 행=$MISMATCH  대상 재고 행=$ROWS"

if [ "$LEFTOVER" != "0" ] || [ "$MISMATCH" != "0" ]; then
    echo "[reset] 실패: 초기 상태가 기대와 다르다. 부하를 넣지 마라." >&2
    exit 1
fi
if [ "$ROWS" = "0" ]; then
    echo "[reset] 실패: 대상 날짜에 재고 행이 하나도 없다." >&2
    echo "[reset] 날짜가 시드 범위(2026-08-01 ~ 2026-10-29) 밖이거나 컬럼명이 다르다." >&2
    exit 1
fi

echo "[reset] 준비 완료."
