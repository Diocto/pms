-- S3. 멱등성 폭주 — 불변식 DB 검증
--
-- 주의: DB 행 수만 세면 "두 건 생겼다가 하나 지워진" 경우를 놓친다.
-- k6의 rsv_created(201 응답 수)도 정확히 키 개수여야 한다.
-- 그 확인은 k6 요약본에서 하고, 여기서는 저장된 상태를 본다.
--
-- 대상: 객실타입 1 (스탠다드), 2026-09-04
--   MODE=a : 키 20개  -> 예약 20건, 잔여 80
--   MODE=b : 키 100개 -> 예약 100건, 잔여 0
-- 실행: mysql -h127.0.0.1 -upms -ppms pms < verify/s3.sql

SET @rt   = 1;
SET @d    = '2026-09-04';
SET @keys = 20;   -- MODE=b 로 돌렸으면 100 으로 바꾼다

SELECT '--- I1. 예약 행 수 (기대: 키 개수) ---' AS check_name;
SELECT COUNT(*) AS reservations, @keys AS expected
  FROM reservation
 WHERE room_type_id = @rt AND check_in = @d
   AND status NOT IN ('CANCELLED', 'EXPIRED');

SELECT '--- I2. 멱등키 중복 (기대: 0행) ---' AS check_name;
-- 키는 (user_id, idempotency_key) 조합으로 저장된다. 조합이 두 건이면
-- 같은 요청이 두 예약을 만든 것이다.
SELECT user_id, idempotency_key, COUNT(*) AS cnt
  FROM reservation
 WHERE check_in = @d
 GROUP BY user_id, idempotency_key
HAVING COUNT(*) > 1;

SELECT '--- I3. 재고 차감량 (기대: total_quantity - 키 개수) ---' AS check_name;
SELECT i.remaining, rt.total_quantity,
       rt.total_quantity - i.remaining AS consumed, @keys AS expected_consumed
  FROM room_daily_inventory i
  JOIN room_type rt ON rt.id = i.room_type_id
 WHERE i.room_type_id = @rt AND i.stay_date = @d;

SELECT '--- I7. 확인번호 목록 (k6가 남긴 code 집합과 대조) ---' AS check_name;
SELECT confirmation_code, user_id, idempotency_key, total_price
  FROM reservation
 WHERE room_type_id = @rt AND check_in = @d
 ORDER BY idempotency_key;

SELECT '--- 참고. 한 키에 확인번호가 여러 개인가 (기대: 0행) ---' AS check_name;
SELECT user_id, idempotency_key, COUNT(DISTINCT confirmation_code) AS codes
  FROM reservation
 WHERE check_in = @d
 GROUP BY user_id, idempotency_key
HAVING COUNT(DISTINCT confirmation_code) > 1;
