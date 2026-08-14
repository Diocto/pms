-- S1. 재고 경합 (순간 집중) — 불변식 DB 검증
--
-- k6 결과만 보고 끝내지 않는다. 부하가 끝난 뒤 DB를 직접 조회해 확인한다.
-- 리포트의 핵심 문장은 이것이다:
--   k6가 받은 201 응답 수 = DB의 예약 행 수 = 초기 재고 수
--
-- 대상: 객실타입 3 (스위트, 10실), 2026-09-01
-- 실행: mysql -h127.0.0.1 -upms -ppms pms < verify/s1.sql

SET @rt = 3;
SET @d  = '2026-09-01';

SELECT '--- I2. 활성 예약 행 수 (기대: 10) ---' AS check_name;
SELECT COUNT(*) AS active_reservations
  FROM reservation
 WHERE room_type_id = @rt AND check_in = @d
   AND status NOT IN ('CANCELLED', 'EXPIRED');

SELECT '--- I3. 재고 음수 행 (기대: 0행. 한 행이라도 나오면 즉시 실패) ---' AS check_name;
SELECT * FROM room_daily_inventory WHERE remaining < 0;

SELECT '--- I4. 해당 날짜 잔여 (기대: 0) ---' AS check_name;
SELECT remaining FROM room_daily_inventory
 WHERE room_type_id = @rt AND stay_date = @d;

SELECT '--- I5. 보존식: 잔여 + 점유 = total_quantity (기대: 10, diff=0) ---' AS check_name;
SELECT i.remaining,
       COALESCE(SUM(r.room_count), 0)                    AS held,
       rt.total_quantity,
       i.remaining + COALESCE(SUM(r.room_count), 0)      AS total,
       i.remaining + COALESCE(SUM(r.room_count), 0) - rt.total_quantity AS diff
  FROM room_daily_inventory i
  JOIN room_type rt ON rt.id = i.room_type_id
  LEFT JOIN reservation r
    ON r.room_type_id = i.room_type_id
   AND i.stay_date >= r.check_in AND i.stay_date < r.check_out
   AND r.status NOT IN ('CANCELLED', 'EXPIRED')
 WHERE i.room_type_id = @rt AND i.stay_date = @d
 GROUP BY i.remaining, rt.total_quantity;

SELECT '--- 참고. 상태 분포 ---' AS check_name;
SELECT status, COUNT(*) AS cnt
  FROM reservation
 WHERE room_type_id = @rt AND check_in = @d
 GROUP BY status;
