-- S6. 혼합 지속 부하 — 재고 누수 검증
--
-- 이 시나리오는 검증이 본론이다. 두 각도로 본다.
--   1. 보존식     — 최종 상태가 맞는가
--   2. 이력 줄 수 — 예약당 재고 복원이 정확히 한 번 일어났는가
--
-- 2번이 없으면 "두 번 깎고 두 번 되돌린" 경우를 놓친다. 최종 잔여만 보면
-- 맞아떨어져 통과하지만, 타이밍이 조금만 달랐으면 음수로 내려갔거나 총량을
-- 넘었을 것이다. 통과한 게 아니라 운이 좋았던 것이다.
--
-- 대상: 전 객실타입, 2026-09-21 ~ 2026-09-30
-- 실행: mysql -h127.0.0.1 -upms -ppms pms < verify/s6.sql

SET @from = '2026-09-21';
SET @to   = '2026-09-30';

SELECT '--- I1. 보존식 위반 행 (기대: 0행) ---' AS check_name;
SELECT i.room_type_id, i.stay_date, i.remaining, rt.total_quantity,
       COALESCE(SUM(r.room_count), 0) AS held,
       i.remaining + COALESCE(SUM(r.room_count), 0) - rt.total_quantity AS diff
  FROM room_daily_inventory i
  JOIN room_type rt ON rt.id = i.room_type_id
  LEFT JOIN reservation r
    ON r.room_type_id = i.room_type_id
   AND i.stay_date >= r.check_in AND i.stay_date < r.check_out
   AND r.status NOT IN ('CANCELLED', 'EXPIRED')
 WHERE i.stay_date BETWEEN @from AND @to
 GROUP BY i.room_type_id, i.stay_date, i.remaining, rt.total_quantity
HAVING diff <> 0;

SELECT '--- I2. 초과 판매: remaining < 0 (기대: 0행) ---' AS check_name;
SELECT * FROM room_daily_inventory
 WHERE stay_date BETWEEN @from AND @to AND remaining < 0;

SELECT '--- I3. 복원 과다: remaining > total_quantity (기대: 0행) ---' AS check_name;
-- 초과 판매의 반대편 오류다. 없는 방을 파는 결과가 된다.
-- 초과 판매만 보고 이걸 안 보면 취소가 재고를 두 번 되돌리는 버그를 통과시킨다.
SELECT i.*, rt.total_quantity
  FROM room_daily_inventory i
  JOIN room_type rt ON rt.id = i.room_type_id
 WHERE i.stay_date BETWEEN @from AND @to
   AND i.remaining > rt.total_quantity;

SELECT '--- I4. 이중 복원: 예약당 재고 복원 이벤트가 2줄 이상 (기대: 0행) ---' AS check_name;
-- 이력 테이블은 성공한 전이만 기록한다. 복원을 일으키는 전이는
-- CANCEL / PAYMENT_FAILED / EXPIRE 세 가지다.
-- 한 예약에 이 이벤트가 두 줄이면 재고가 두 번 돌아온 것이다.
-- 테이블·컬럼명은 F01 병합 후 마이그레이션과 대조해 확정한다 (scenarios.md §8 Q4, Q12).
SELECT h.reservation_id, COUNT(*) AS restore_events
  FROM reservation_status_history h
  JOIN reservation r ON r.id = h.reservation_id
 WHERE r.check_in BETWEEN @from AND @to
   AND h.event IN ('CANCEL', 'PAYMENT_FAILED', 'EXPIRE')
 GROUP BY h.reservation_id
HAVING COUNT(*) > 1;

SELECT '--- I5. 전이 표 밖 상태 (기대: 0행) ---' AS check_name;
SELECT DISTINCT status FROM reservation
-- 상태는 6개뿐이다. NO_SHOW는 D4 기각으로 사라졌으므로 여기 넣으면 안 된다.
-- 목록에 남겨두면 있어서는 안 될 상태가 나와도 이 쿼리가 통과한다.
 WHERE status NOT IN ('PENDING','CONFIRMED','CANCELLED','EXPIRED',
                      'CHECKED_IN','CHECKED_OUT');

SELECT '--- 참고. 상태 분포 ---' AS check_name;
SELECT status, COUNT(*) AS cnt
  FROM reservation
 WHERE check_in BETWEEN @from AND @to
 GROUP BY status;
