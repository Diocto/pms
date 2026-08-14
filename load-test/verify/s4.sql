-- S4. 상태 전이 경합 (취소 × 확정) — 불변식 DB 검증
--
-- 판정이 단순하지 않다. PENDING에서 CONFIRM과 CANCEL은 둘 다 전이 표 안에
-- 있고, CONFIRMED에서 CANCEL도 표 안에 있다. "둘 다 성공"이 곧 위반은 아니다.
-- 진짜 위반은 CANCEL이 성공했는데 최종이 CONFIRMED인 경우, 종료 상태에서
-- 다시 움직인 경우, 그리고 최종이 PENDING으로 남은 경우다.
--
-- 대상: 객실타입 1 (스탠다드), 2026-09-05 ~ 2026-09-07 (100실 × 3일 = 300건)
-- 실행: mysql -h127.0.0.1 -upms -ppms pms < verify/s4.sql

SET @rt   = 1;
SET @from = '2026-09-05';
SET @to   = '2026-09-07';

SELECT '--- I1,I2. 최종 상태 분포 (기대: CONFIRMED + CANCELLED = 300, 그 외 0) ---' AS check_name;
SELECT status, COUNT(*) AS cnt
  FROM reservation
 WHERE room_type_id = @rt AND check_in BETWEEN @from AND @to
 GROUP BY status;

SELECT '--- I1. PENDING 잔류 (기대: 0행. 둘 중 하나는 반드시 먹혀야 한다) ---' AS check_name;
SELECT confirmation_code, check_in, status
  FROM reservation
 WHERE room_type_id = @rt AND check_in BETWEEN @from AND @to
   AND status = 'PENDING';

SELECT '--- I2. 이 시나리오가 보내지 않은 이벤트의 상태 (기대: 0행) ---' AS check_name;
-- confirm/cancel만 보냈으므로 CHECKED_IN·CHECKED_OUT·NO_SHOW·EXPIRED가
-- 나오면 안 된다.
SELECT status, COUNT(*) AS cnt
  FROM reservation
 WHERE room_type_id = @rt AND check_in BETWEEN @from AND @to
   AND status NOT IN ('CONFIRMED', 'CANCELLED')
 GROUP BY status;

SELECT '--- I3. 예약별 최종 상태 (k6의 "CANCEL이 2xx였던 확인번호" 목록과 대조) ---' AS check_name;
-- 대조 결과 CANCEL 2xx인데 status=CONFIRMED 인 것이 하나라도 있으면 위반이다.
SELECT confirmation_code, check_in, status
  FROM reservation
 WHERE room_type_id = @rt AND check_in BETWEEN @from AND @to
 ORDER BY check_in, confirmation_code;

SELECT '--- I4. 상태와 재고가 짝이 맞는가 (기대: diff=0) ---' AS check_name;
-- CANCELLED는 재고를 반납했으므로 잔여 = total_quantity - CONFIRMED 건수.
SELECT i.stay_date, i.remaining, rt.total_quantity,
       COALESCE(SUM(r.room_count), 0) AS held,
       i.remaining + COALESCE(SUM(r.room_count), 0) - rt.total_quantity AS diff
  FROM room_daily_inventory i
  JOIN room_type rt ON rt.id = i.room_type_id
  LEFT JOIN reservation r
    ON r.room_type_id = i.room_type_id
   AND i.stay_date >= r.check_in AND i.stay_date < r.check_out
   AND r.status NOT IN ('CANCELLED', 'EXPIRED')
 WHERE i.room_type_id = @rt AND i.stay_date BETWEEN @from AND @to
 GROUP BY i.stay_date, i.remaining, rt.total_quantity;
