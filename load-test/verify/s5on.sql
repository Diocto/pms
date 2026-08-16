-- S5 락 ON 회차 — 불변식 DB 검증 (부하는 s2 스크립트, 날짜만 2026-09-12)
--
-- s2.sql 과 같은 검증을 S5 ON 대역에 건다. 날짜를 손으로 바꿔 돌리다
-- 한 회차라도 s2 날짜(09-03)를 보면 "빈 날짜 = 통과"로 오독되므로
-- 파일을 분리해 run.sh 가 시나리오 이름으로 바로 찾게 한다.
--
-- 실행: ./verify/run.sh s5on

SET @rt = 1;
SET @d  = '2026-09-12';

SELECT '--- I1/I2. 활성 예약 행 수 (기대: 100) ---' AS check_name;
SELECT COUNT(*) AS active_reservations
  FROM reservation
 WHERE room_type_id = @rt AND check_in = @d
   AND status NOT IN ('CANCELLED', 'EXPIRED');

SELECT '--- I3. 재고 음수 행 (기대: 0행) ---' AS check_name;
SELECT * FROM room_daily_inventory WHERE remaining < 0;

SELECT '--- I4. 해당 날짜 잔여 (기대: 0) ---' AS check_name;
SELECT remaining FROM room_daily_inventory
 WHERE room_type_id = @rt AND stay_date = @d;

SELECT '--- I5. 보존식 (기대: diff=0) ---' AS check_name;
SELECT i.remaining,
       COALESCE(SUM(r.room_count), 0)               AS held,
       rt.total_quantity,
       i.remaining + COALESCE(SUM(r.room_count), 0) - rt.total_quantity AS diff
  FROM room_daily_inventory i
  JOIN room_type rt ON rt.id = i.room_type_id
  LEFT JOIN reservation r
    ON r.room_type_id = i.room_type_id
   AND i.stay_date >= r.check_in AND i.stay_date < r.check_out
   AND r.status NOT IN ('CANCELLED', 'EXPIRED')
 WHERE i.room_type_id = @rt AND i.stay_date = @d
 GROUP BY i.remaining, rt.total_quantity;
