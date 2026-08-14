-- S7. 프로모션 스파이크 — 불변식 DB 검증
--
-- 대상: P1 (객실타입 1 스탠다드, 2026-09-14, 특가 20실)
-- 실행: mysql -h127.0.0.1 -upms -ppms pms < verify/s7.sql
--
-- 테이블·컬럼명은 F02 V202 병합 후 대조해 확정한다.

SET @rt = 1;
SET @d  = '2026-09-14';
SET @qty = 20;

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
