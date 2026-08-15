-- S1-C. 재고 경합 (부분 소진, roomCount 혼합) — 불변식 DB 검증
--
-- 요청 실수가 섞이면 최종 잔여가 0이 아닐 수 있다. 잔여 2에 3실 요청만
-- 남으면 2가 남은 채 끝난다. 그래서 "잔여 == 0"으로 판정할 수 없고
-- 보존식으로만 판정한다.
--
-- 대상: 객실타입 5 (오션뷰 스위트, 20실), 2026-09-02
-- 실행: mysql -h127.0.0.1 -upms -ppms pms < verify/s1c.sql

SET @rt = 5;
SET @d  = '2026-09-02';

SELECT '--- I1. 초과 판매: remaining < 0 (기대: 0행) — 이 시나리오의 주 표적 ---' AS check_name;
SELECT * FROM room_daily_inventory WHERE remaining < 0;

SELECT '--- I2. 보존식 (기대: total=20, diff=0) ---' AS check_name;
SELECT i.remaining,
       COALESCE(SUM(r.room_count), 0)               AS rooms_held,
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

SELECT '--- I3. 최종 잔여 (기대: 0. 3 이상이면 부당하게 거절된 것) ---' AS check_name;
-- 1실 요청이 100건이나 남아 있으므로 마지막 한 칸까지 채워지는 것이 정상이다.
-- 잔여가 3 이상이면 들어갈 자리가 있는데 못 들어간 것이고,
-- 이는 초과 판매의 반대편 오류다 (조건 판정이 과하게 보수적이라는 신호).
SELECT remaining FROM room_daily_inventory
 WHERE room_type_id = @rt AND stay_date = @d;

SELECT '--- I4. 성공 예약의 실수 합과 건수 (k6의 rooms_sold 와 대조) ---' AS check_name;
SELECT COUNT(*) AS rows_cnt, COALESCE(SUM(room_count), 0) AS rooms_sum
  FROM reservation
 WHERE room_type_id = @rt AND check_in = @d
   AND status NOT IN ('CANCELLED', 'EXPIRED');

SELECT '--- 참고. 요청 실수별 성공 분포 (경계 판정이 고르게 작동했는가) ---' AS check_name;
SELECT room_count, COUNT(*) AS cnt
  FROM reservation
 WHERE room_type_id = @rt AND check_in = @d
   AND status NOT IN ('CANCELLED', 'EXPIRED')
 GROUP BY room_count ORDER BY room_count;
