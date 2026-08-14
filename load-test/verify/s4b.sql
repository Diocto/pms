-- S4-B. 상태 전이 경합 (만료 × 확정) — 불변식 DB 검증
--
-- 만료는 배치다. 한 번의 호출이 대상 전부를 훑으며 상태를 바꾸고 재고를
-- 복원한다. 그래서 개별 요청 시나리오로는 안 잡히는 두 버그가 여기서 잡힌다.
--   1. 확정된 예약이 만료 처리된다 (전이 표상 CONFIRMED에 EXPIRE는 없다)
--   2. 한 예약의 재고가 두 번 복원된다
--
-- 대상: 객실타입 1 (스탠다드), 2026-09-08 ~ 2026-09-11 (100실 × 4일 = 400건)
-- 실행: mysql -h127.0.0.1 -upms -ppms pms < verify/s4b.sql

SET @rt   = 1;
SET @from = '2026-09-08';
SET @to   = '2026-09-11';

SELECT '--- I1. 최종 상태 분포 (기대: CONFIRMED + EXPIRED = 400, PENDING 0) ---' AS check_name;
SELECT status, COUNT(*) AS cnt
  FROM reservation
 WHERE room_type_id = @rt AND check_in BETWEEN @from AND @to
 GROUP BY status;

SELECT '--- I3. 만료 건수 (k6의 expired_reported 합계와 대조) ---' AS check_name;
-- 합계가 이 숫자보다 크면 같은 예약을 두 번 만료시킨 것이다.
SELECT COUNT(*) AS expired_rows
  FROM reservation
 WHERE room_type_id = @rt AND check_in BETWEEN @from AND @to
   AND status = 'EXPIRED';

SELECT '--- I2. 확정 건수 (k6의 confirm_succeeded 와 대조) ---' AS check_name;
-- k6가 200 CONFIRMED를 받은 수보다 이 값이 작으면,
-- 확정에 성공한 예약이 그 뒤 만료된 것이다. 금지 전이 통과다.
SELECT COUNT(*) AS confirmed_rows
  FROM reservation
 WHERE room_type_id = @rt AND check_in BETWEEN @from AND @to
   AND status = 'CONFIRMED';

SELECT '--- I4,I5. 재고 보존식과 복원 과다 (기대: diff=0, remaining <= total) ---' AS check_name;
SELECT i.stay_date, i.remaining, rt.total_quantity,
       COALESCE(SUM(r.room_count), 0) AS held,
       i.remaining + COALESCE(SUM(r.room_count), 0) - rt.total_quantity AS diff,
       CASE WHEN i.remaining > rt.total_quantity THEN '복원 과다!' ELSE 'ok' END AS over_restore
  FROM room_daily_inventory i
  JOIN room_type rt ON rt.id = i.room_type_id
  LEFT JOIN reservation r
    ON r.room_type_id = i.room_type_id
   AND i.stay_date >= r.check_in AND i.stay_date < r.check_out
   AND r.status NOT IN ('CANCELLED', 'EXPIRED')
 WHERE i.room_type_id = @rt AND i.stay_date BETWEEN @from AND @to
 GROUP BY i.stay_date, i.remaining, rt.total_quantity;

SELECT '--- 이중 만료: 예약당 EXPIRE 이력이 2줄 이상 (기대: 0행) ---' AS check_name;
-- 이력 테이블이 없으면 이 쿼리는 실패한다. 그때는 I3의 합계 대조로 대신한다.
SELECT h.reservation_id, COUNT(*) AS expire_events
  FROM reservation_status_history h
  JOIN reservation r ON r.id = h.reservation_id
 WHERE r.check_in BETWEEN @from AND @to
   AND h.event = 'EXPIRE'
 GROUP BY h.reservation_id
HAVING COUNT(*) > 1;
