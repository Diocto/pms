-- S7. 프로모션 스파이크 — 불변식 DB 검증
--
-- 대상: P1 (객실타입 1 스탠다드, 2026-09-14, 특가 20실)
-- 실행: mysql -h127.0.0.1 -upms -ppms pms < verify/s7.sql
--
-- 테이블·컬럼명은 F02 V202 병합 후 대조해 확정한다.

SET @rt = 1;
SET @d  = '2026-09-14';
SET @qty = 20;
SET @promo_price = 75000;   -- 정가 150,000의 50%
SET @list_price  = 150000;

SELECT '--- I1,I3. 특가 예약 건수 (기대: 20) ---' AS check_name;
SELECT COUNT(*) AS promo_claims
  FROM promotion_claim
 WHERE status = 'CLAIMED';

SELECT '--- 홀드 잔류 (기대: 0행. HELD로 남으면 정리 스케줄러가 못 돈 것) ---' AS check_name;
SELECT * FROM promotion_claim WHERE status = 'HELD';

SELECT '--- I2. 특가 재고 (기대: remaining = 0, 음수 아님) ---' AS check_name;
SELECT * FROM promotion_inventory
 WHERE room_type_id = @rt AND stay_date = @d;

SELECT '--- 특가 재고 음수 (기대: 0행) ---' AS check_name;
-- CHECK 제약이 있으므로 여기 걸리면 제약도 함께 뚫린 것이다.
SELECT * FROM promotion_inventory WHERE remaining < 0;

SELECT '--- 멱등성: (user_id, idempotency_key) 중복 (기대: 0행) ---' AS check_name;
SELECT user_id, idempotency_key, COUNT(*) AS cnt
  FROM promotion_claim
 GROUP BY user_id, idempotency_key
HAVING COUNT(*) > 1;

SELECT '--- I5. 일반 재고와의 관계 — Q7 확정 후 둘 중 하나를 본다 ---' AS check_name;
-- 경우 1 (차감 연동): 특가가 팔리면 일반 재고도 준다.
--   F02 스펙 R3이 "특가 요청과 일반 예약이 같은 재고 행을 쓴다"고 하므로
--   이쪽이 유력하다. 그러면 기대값은 remaining = 100 - 20 = 80 이고,
--   보존식(잔여 + 점유 = total_quantity)이 그대로 성립해야 한다.
-- 경우 2 (별도 재고): 일반 재고는 변화 없이 100.
--   이 경우 "특가 판매 + 일반 판매 <= 총 객실 수" 상위 불변식을 따로 봐야 한다.
SELECT i.remaining, rt.total_quantity,
       COALESCE(SUM(r.room_count), 0) AS held,
       i.remaining + COALESCE(SUM(r.room_count), 0) - rt.total_quantity AS diff
  FROM room_daily_inventory i
  JOIN room_type rt ON rt.id = i.room_type_id
  LEFT JOIN reservation r
    ON r.room_type_id = i.room_type_id
   AND i.stay_date >= r.check_in AND i.stay_date < r.check_out
   AND r.status NOT IN ('CANCELLED', 'EXPIRED')
 WHERE i.room_type_id = @rt AND i.stay_date = @d
 GROUP BY i.remaining, rt.total_quantity;

SELECT '--- 생성된 Reservation 건수 (기대: 20. 특가도 Reservation을 만든다) ---' AS check_name;
SELECT COUNT(*) AS reservations
  FROM reservation
 WHERE room_type_id = @rt AND check_in = @d
   AND status NOT IN ('CANCELLED', 'EXPIRED');

SELECT '--- 금액 불변식: 특가 예약에 정가가 박힌 행 (기대: 0행) ---' AS check_name;
-- price_per_night 에는 **실제로 청구한 단가**가 들어간다.
-- 특가 사용권이 발급된 예약인데 정가(150,000)가 박혀 있으면,
-- 사용자가 요청하지 않은 금액을 청구한 것이다. fail-closed가 뚫린 흔적이다.
SELECT r.id, r.confirmation_code, r.price_per_night, @promo_price AS expected
  FROM reservation r
  JOIN promotion_claim c ON c.reservation_id = r.id
 WHERE r.price_per_night <> @promo_price;

SELECT '--- 역방향: 특가 단가인데 사용권이 없는 예약 (기대: 0행) ---' AS check_name;
-- 사용권 없이 특가를 받았다면 재고를 차감하지 않고 할인만 받은 것이다.
SELECT r.id, r.confirmation_code, r.price_per_night
  FROM reservation r
  LEFT JOIN promotion_claim c ON c.reservation_id = r.id
 WHERE r.room_type_id = @rt AND r.check_in = @d
   AND r.price_per_night = @promo_price
   AND c.id IS NULL;

SELECT '--- 사용권 수와 특가 예약 수가 같은가 (기대: 두 값이 20으로 동일) ---' AS check_name;
-- 세 구역(특가 차감·사용권 발급·예약 생성)이 한 트랜잭션이므로
-- 하나라도 어긋나면 전부 롤백돼야 한다. 수가 다르면 그 원자성이 깨진 것이다.
SELECT
  (SELECT COUNT(*) FROM promotion_claim WHERE status = 'CLAIMED') AS claims,
  (SELECT COUNT(*) FROM reservation r
     JOIN promotion_claim c ON c.reservation_id = r.id) AS promo_reservations;
