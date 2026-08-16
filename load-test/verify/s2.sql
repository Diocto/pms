-- S2 (지속 부하) / S5 (락 유무 대조) — 불변식 DB 검증
--
-- S5는 이 파일을 날짜만 바꿔 두 번 돌린다.
--   락 ON  : 2026-09-12
--   락 OFF : 2026-09-13
--
-- S5의 결론은 여기서 나온다: **락을 꺼도 성공이 정확히 100건인가.**
-- 그렇다면 2차 방어선(조건부 UPDATE)이 실제로 작동한다는 뜻이고,
-- Redis가 죽어도 데이터가 안 깨진다는 뜻이다.
-- 초과 판매가 나온다면 그건 F04의 실패가 아니라 발견이다.
--
-- 대상: 객실타입 1 (스탠다드, 100실)
-- 실행: mysql -h127.0.0.1 -upms -ppms pms < verify/s2.sql
--       (날짜를 바꾸려면 아래 @d 를 수정한다)

SET @rt = 1;
SET @d  = '2026-09-03';   -- S5: '2026-09-12'(ON) / '2026-09-13'(OFF)

SELECT '--- I2. 활성 예약 행 수 (기대: 100) ---' AS check_name;
SELECT COUNT(*) AS active_reservations
  FROM reservation
 WHERE room_type_id = @rt AND check_in = @d
   AND status NOT IN ('CANCELLED', 'EXPIRED');

SELECT '--- I3. 재고 음수 행 (기대: 0행) ---' AS check_name;
SELECT * FROM room_daily_inventory WHERE remaining < 0;

SELECT '--- I4. 해당 날짜 잔여 (기대: 0) ---' AS check_name;
SELECT remaining FROM room_daily_inventory
 WHERE room_type_id = @rt AND stay_date = @d;

SELECT '--- I5. 보존식 (기대: total=100, diff=0) ---' AS check_name;
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
