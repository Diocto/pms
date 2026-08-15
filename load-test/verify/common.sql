-- 전 시나리오 공통 사후 검증
--
-- **모든 시나리오 실행 후에 이걸 먼저 돌린다.** 비용이 거의 없고,
-- 어느 시나리오에서 샜는지도 알려준다.
--
-- 세 쿼리 전부 결과가 비어야 통과다.
--
-- ---------------------------------------------------------------------------
-- (3)번이 이 파일의 핵심이다
-- ---------------------------------------------------------------------------
-- 거부된 전이는 예외로 트랜잭션이 롤백되므로 이력에 남지 않는다. 그래서
-- "금지 전이가 시도됐다가 막혔다"는 DB로 증명할 수 없다.
--
-- 그런데 (3)은 다른 것을 증명한다 — **표 밖의 전이가 실제로는 한 번도
-- 일어나지 않았다.** 시도의 부재가 아니라 결과의 부재이고, 무엇보다
-- **운영 데이터로 하는 증명**이라 전수 테스트와 값이 다르다.
--   전수 테스트: "코드가 거부하도록 짜여 있다"
--   이 쿼리    : "실제 부하에서 한 건도 새지 않았다"
--
-- 리포트 문장: "부하테스트 중 발생한 N건의 상태 전이가 전부 전이 표 안에 있었다."
--
-- ⚠ 순서 판단은 occurred_at 이 아니라 id 순번으로 한다.
--   한 트랜잭션에서 읽은 now 를 쓰므로 occurred_at 이 같은 값일 수 있고,
--   시각으로 정렬하면 순서가 뒤집힌다.
--
-- 실행: mysql -h127.0.0.1 -upms -ppms pms < verify/common.sql

SELECT '=== (1) 이중 복원: 예약당 재고 복원이 두 번 이상 (기대: 0행) ===' AS check_name;
-- 복원을 일으키는 이벤트는 정확히 셋이다.
-- CONFIRM·CHECK_IN·CHECK_OUT은 재고를 건드리지 않는다.
SELECT reservation_id, COUNT(*) AS restore_count
  FROM reservation_status_history
 WHERE event IN ('CANCEL', 'PAYMENT_FAILED', 'EXPIRE')
 GROUP BY reservation_id
HAVING COUNT(*) > 1;

SELECT '=== (2) 종료 상태에 두 번 도달 (기대: 0행) ===' AS check_name;
-- 종료 상태는 나갈 수 없다. 두 번 도달했다면 종료 상태에서 다시 움직인 것이다.
SELECT reservation_id, COUNT(*) AS terminal_count
  FROM reservation_status_history
 WHERE to_status IN ('CANCELLED', 'EXPIRED', 'CHECKED_OUT')
 GROUP BY reservation_id
HAVING COUNT(*) > 1;

SELECT '=== (3) 실제로 일어난 전이 목록 — 허용 7행의 부분집합이어야 한다 ===' AS check_name;
-- 아래 7행 밖의 조합이 하나라도 나오면 명제 (다) 위반이다.
-- 전이 표는 36칸(상태 6 x 이벤트 6) = 허용 7 + 멱등 6 + 거부 23이다.
-- D4(NO_SHOW) 기각으로 49칸에서 줄었다 (2026-08-15).
--   PENDING     CONFIRM         CONFIRMED
--   PENDING     PAYMENT_FAILED  CANCELLED
--   PENDING     CANCEL          CANCELLED
--   PENDING     EXPIRE          EXPIRED
--   CONFIRMED   CANCEL          CANCELLED
--   CONFIRMED   CHECK_IN        CHECKED_IN
--   CHECKED_IN  CHECK_OUT       CHECKED_OUT
SELECT from_status, event, to_status, COUNT(*) AS occurrences
  FROM reservation_status_history
 GROUP BY from_status, event, to_status
 ORDER BY from_status, event;

SELECT '=== (3-b) 표 밖 전이만 골라내기 (기대: 0행) ===' AS check_name;
SELECT from_status, event, to_status, COUNT(*) AS occurrences
  FROM reservation_status_history
 WHERE (from_status, event, to_status) NOT IN (
        ('PENDING',    'CONFIRM',        'CONFIRMED'),
        ('PENDING',    'PAYMENT_FAILED', 'CANCELLED'),
        ('PENDING',    'CANCEL',         'CANCELLED'),
        ('PENDING',    'EXPIRE',         'EXPIRED'),
        ('CONFIRMED',  'CANCEL',         'CANCELLED'),
        ('CONFIRMED',  'CHECK_IN',       'CHECKED_IN'),
        ('CHECKED_IN', 'CHECK_OUT',      'CHECKED_OUT'))
 GROUP BY from_status, event, to_status;

SELECT '=== (4) 참고: 총 전이 건수 (리포트 문장에 쓸 숫자) ===' AS check_name;
SELECT COUNT(*) AS total_transitions FROM reservation_status_history;

SELECT '=== (5) 전 구간 재고 이상 (기대: 0행) ===' AS check_name;
-- 초과 판매(음수)와 복원 과다(총량 초과)를 한 번에 본다.
SELECT i.room_type_id, i.stay_date, i.remaining, rt.total_quantity,
       CASE WHEN i.remaining < 0 THEN '초과 판매'
            ELSE '복원 과다' END AS problem
  FROM room_daily_inventory i
  JOIN room_type rt ON rt.id = i.room_type_id
 WHERE i.remaining < 0 OR i.remaining > rt.total_quantity;
