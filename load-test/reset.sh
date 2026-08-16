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
#   - Redis 전체                  : FLUSHDB (멱등키·분산락·캐시)
#
# promotion_inventory 는 목록에서 뺐다 — F02 폐기 (ADR-0058, 2026-08-16).
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
    echo "사용법: ./reset.sh <시나리오>   (s1 s1c s2 s3 s4 s4b s5on s5off s6 s8 s8on s8off all)" >&2
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
    # 09-14~16 은 비어 있다. F02 특가(S7)가 점유했던 대역인데 폐기됐다 (ADR-0058).
    # 다른 시나리오를 옮겨 붙이지 않는다 — 날짜를 옮기면 config.js PLAN 과
    # 어긋나 초기화와 부하가 다른 날짜를 보게 된다.
    s6)    FROM=2026-09-21; TO=2026-09-30 ;;
    # S8 은 캐시 ON/OFF 두 회차가 **같은 대역**을 쓴다. S5 처럼 날짜를 나누지
    # 않는 이유: 캐시 히트율은 재고 상태에 따라 달라지므로 두 회차의 출발
    # 재고가 같아야 한다. 대신 회차마다 이 초기화를 다시 돌려 대역을 되돌린다.
    s8|s8on|s8off) FROM=2026-10-01; TO=2026-10-10 ;;
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

# --------------------------------------------------------------------------
# 5. 앱 스위치 검증 — S5 대조가 진짜 대조인지 확인한다
# --------------------------------------------------------------------------
# 이 검사가 없으면 가장 위험한 거짓 통과가 그대로 통과한다:
#   락을 껐다고 생각했는데 실제로는 켜져 있으면, 두 회차가 같은 조건이 되어
#   "락 유무에 차이가 없다"는 결론이 나온다. 그 문장은 그럴듯하게 읽히고,
#   "우리는 락이 필요 없다"로 오독된다. 아무도 이상하게 여기지 않는다.
#
# 그래서 S5는 스위치 확인에 실패하면 부하를 넣지 않는다.
# (scenarios.md §3-10 S5 항목의 자동화가 이것이다)
#
# 경로 확정 (2026-08-16 대조 완료).
#   GET /api/internal/config 가 main 에 실제로 있다
#   (app/reservation/presentation/actuator.py). 응답의 바깥 필드는
#   loadTest / implementations / counters / processId 넷이다.
#   다르게 바뀌면 CONFIG_URL 로 덮어쓴다.
#
# 노출 범위를 최소로 잡는다.
#   설정 전체를 그대로 여는 방식(예전 스택의 actuator env 마스킹 해제)은
#   DB 접속 정보까지 같이 열린다. 로컬 전용이라 실질 위험은 없지만, 제출
#   문서에 "이 설정 그대로 실서비스에 올리면 사고"라는 각주가 붙는다.
#   우리가 확인해야 하는 값만 싣는 쪽을 골랐다.
#
# 기대 응답 (2026-08-15 확정):
#   {"loadTest":{"PMS_LOCK_ENABLED":false,"PMS_RESERVATION_HOLD_MINUTES":10,...}}
#
#   **바깥은 camelCase 인데 안쪽 키는 환경변수 이름 그대로다.** 표기 규칙에
#   대놓고 어긋나지만 그렇게 정했다 — 조작자가 셸에 치는 문자열, 앱의
#   validation_alias, 리포트에 적히는 이름이 전부 같아야 하기 때문이다.
#   중간에 번역이 한 겹 끼면 리포트를 보고 재현하려는 사람이 그 문자열을
#   그대로 붙여넣을 수 없다. 편의가 아니라 재현성 문제라서 규칙에 예외를 뒀다.
INFO_URL="${CONFIG_URL:-${BASE_URL:-http://localhost:8080}/api/internal/config}"

# info 응답에서 키 하나의 값을 꺼낸다. 없으면 빈 문자열.
info_value() {
    local key="$1" body="$2" key_re
    key_re=$(printf '%s' "$key" | sed 's/[.[\*^$]/\\&/g')   # 점을 정규식 메타로 안 읽게
    printf '%s' "$body" \
        | tr -d ' \n' \
        | grep -o "\"${key_re}\":[^,}]*" \
        | head -1 \
        | sed "s/^\"[^\"]*\"://" \
        | tr -d '"'
}

check_switch() {
    local key="$1" expected="$2"
    local body actual

    if ! body=$(curl -sf --max-time 5 "$INFO_URL"); then
        echo "[reset] 실패: ${INFO_URL} 를 읽을 수 없다." >&2
        echo "[reset] 앱이 안 떠 있거나 설정 노출 엔드포인트가 안 열려 있다." >&2
        echo "[reset] 경로가 바뀌었으면 CONFIG_URL 환경변수로 지정해라." >&2
        echo "[reset] S5는 스위치가 실제 값인지 확인하지 못하면 의미가 없으므로 중단한다." >&2
        return 1
    fi

    actual=$(info_value "$key" "$body")

    if [ -z "$actual" ] || [ "$actual" = "null" ]; then
        echo "[reset] 실패: info 응답에 ${key} 가 없다." >&2
        echo "[reset] 응답: ${body}" >&2
        echo "[reset] F01의 InfoContributor 가 이 키를 싣고 있는지 확인해라." >&2
        return 1
    fi
    if [ "$actual" != "$expected" ]; then
        echo "[reset] 실패: ${key} 가 '${actual}' 이다. '${expected}' 를 기대했다." >&2
        echo "[reset] 이대로 돌리면 두 회차가 같은 조건이 되어 대조가 성립하지 않는다." >&2
        return 1
    fi
    echo "[reset] 스위치 확인: ${key} = ${actual} (기대와 일치)"
}

# 설정 키 이름. 스택 전환으로 환경변수 이름 표기를 제안해둔 상태다.
# F01 이 다르게 정하면 아래 기본값만 바꾸거나 환경변수로 덮어쓴다.
# 키가 틀리면 check_switch 가 응답 본문을 통째로 찍고 중단하므로,
# 실제 키 이름을 그 자리에서 눈으로 확인할 수 있다.
LOCK_KEY="${LOCK_KEY:-PMS_LOCK_ENABLED}"
HOLD_KEY="${HOLD_KEY:-PMS_RESERVATION_HOLD_MINUTES}"
CACHE_KEY="${CACHE_KEY:-PMS_SEARCH_CACHE_ENABLED}"

case "$SCENARIO" in
    s5on)  check_switch "$LOCK_KEY" "true"  || exit 1 ;;
    s5off) check_switch "$LOCK_KEY" "false" || exit 1 ;;
    s4b)   check_switch "$HOLD_KEY" "1"     || exit 1 ;;
    # S8 캐시 대조. 락 대조와 같은 이유로 스위치를 실물 확인한다 —
    # 껐다고 생각했는데 켜져 있으면 두 회차가 같은 조건이 되고,
    # "캐시는 차이가 없더라"는 거짓 결론이 리포트에 실린다.
    s8on)  check_switch "$CACHE_KEY" "true"  || exit 1 ;;
    s8off) check_switch "$CACHE_KEY" "false" || exit 1 ;;
esac

# --------------------------------------------------------------------------
# 5-1. 프로세스 표본 — 워커가 실제로 몇 개 떠 있는지 실물로 잡는다
# --------------------------------------------------------------------------
# 응답의 processId 는 그 응답을 만든 프로세스의 pid 다. 여러 번 요청해
# 서로 다른 pid 가 나오면 워커가 여럿이라는 **확정 증거**다. (전부 같으면
# "여럿이 아니다"의 증명은 아니다 — 표본이 한 워커에만 갔을 수 있다.
# 그래서 단일 확인용이 아니라 다중 적발용으로 쓴다.)
#
# 왜 설정이 아니라 pid 인가: --workers 는 조작자가 쳤다고 믿는 값이고
# pid 는 실제로 떠 있는 값이다. 이 대조의 목적이 "선언과 실물의 어긋남"을
# 잡는 것이므로 실물 쪽을 읽는다. (F01이 F04 요청으로 실어줬다)
#
# REQUIRE_SINGLE_PROCESS=1 로 부르면 pid 가 2종 이상일 때 중단한다.
# 프로세스 단위 카운터(counters 칸)로 판정하는 회차가 이 모드를 쓴다.
# 지금은 counters 를 채우는 컨텍스트가 없어(F02 폐기) 상시 모드는 아니고,
# 카운터가 생기면 해당 회차의 실행 절차에 이 변수를 명시한다.
PIDS=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
    PID_BODY=$(curl -sf --max-time 5 "$INFO_URL") || PID_BODY=""
    P=$(info_value "processId" "$PID_BODY")
    [ -n "$P" ] && PIDS="$PIDS $P"
done
DISTINCT_PIDS=$(printf '%s\n' $PIDS | sort -u | grep -c . || true)
echo "[reset] 프로세스 표본: 요청 10회, 관측 pid ${DISTINCT_PIDS}종 ($(printf '%s\n' $PIDS | sort -u | tr '\n' ' '))"

if [ "${REQUIRE_SINGLE_PROCESS:-0}" = "1" ]; then
    if [ "$DISTINCT_PIDS" = "0" ]; then
        echo "[reset] 실패: processId 를 한 번도 못 읽었다. 확인 못 한 채 진행하지 않는다." >&2
        exit 1
    fi
    if [ "$DISTINCT_PIDS" -gt 1 ]; then
        echo "[reset] 실패: 워커가 여럿이다 (pid ${DISTINCT_PIDS}종)." >&2
        echo "[reset] 프로세스 단위 카운터로 판정하는 회차는 워커 1이 아니면 판정이 무효다." >&2
        echo "[reset] --workers 1 로 재기동한 뒤 다시 돌려라." >&2
        exit 1
    fi
fi

# 실제 설정값을 리포트에 그대로 싣기 위해 통째로 저장해둔다.
# 손으로 옮겨 적으면 틀리고, 틀려도 아무도 모른다. 실행 시점의 실제 값이
# 파일로 남아야 "같은 조건에서 쟀다"가 증거가 된다.
#
# 저장 위치는 스크립트 위치 기준으로 잡는다. 상대 경로로 두면 저장소 루트에서
# `load-test/reset.sh` 로 부를 때 저장소 밖에 파일이 생긴다.
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
RESULTS_DIR="${SCRIPT_DIR}/../docs/load-test/results"

if SNAPSHOT=$(curl -sf --max-time 5 "$INFO_URL"); then
    mkdir -p "$RESULTS_DIR"
    printf '%s\n' "$SNAPSHOT" > "${RESULTS_DIR}/settings-${SCENARIO}.json"
    echo "[reset] 설정 스냅샷 저장: docs/load-test/results/settings-${SCENARIO}.json"
else
    echo "[reset] 경고: 설정 스냅샷을 못 남겼다 (info 응답 없음)." >&2
fi

echo "[reset] 준비 완료."
