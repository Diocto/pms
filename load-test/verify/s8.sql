-- S8. 조회 폭주 속 예약 · 캐시 유무 대조 — 불변식 DB 검증
--
-- **초과 판매 0건이 절대 조건이다.** F03도 이것만을 절대 조건으로 든다.
-- 나머지(히트율, stale window, 409 비율)는 k6 지표에서 읽는다.
--
-- 대상: 2026-10-01 ~ 2026-10-10, 전 객실타입
-- 실행: mysql -h127.0.0.1 -upms -ppms pms < verify/s8.sql
--
-- 캐시 ON/OFF 두 회차 모두에서 결과가 같아야 한다. 캐시는 조회 계층이므로
-- 저장된 상태에 영향을 주면 안 된다.

SET @from = '2026-10-01';
SET @to   = '2026-10-10';

SELECT '--- I1. 초과 판매 (기대: 0행). 절대 조건 ---' AS check_name;
SELECT * FROM room_daily_inventory
 WHERE stay_date BETWEEN @from AND @to AND remaining < 0;

SELECT '--- I2. 보존식 위반 (기대: 0행) ---' AS check_name;
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

SELECT '--- 복원 과다 (기대: 0행) ---' AS check_name;
SELECT i.*, rt.total_quantity
  FROM room_daily_inventory i
  JOIN room_type rt ON rt.id = i.room_type_id
 WHERE i.stay_date BETWEEN @from AND @to
   AND i.remaining > rt.total_quantity;

SELECT '--- 참고. 스위트(경합 대상)의 날짜별 잔여 ---' AS check_name;
-- 재고 10실짜리라 검색의 minRemaining이 10 -> 0으로 가는 것을 관찰할 수 있다.
-- 캐시 ON/OFF 두 회차에서 이 분포가 비슷해야 한다. 크게 다르면
-- 캐시가 예약 성공률에 영향을 준 것이므로 그 자체가 발견이다.
SELECT stay_date, remaining
  FROM room_daily_inventory
 WHERE room_type_id = 3 AND stay_date BETWEEN @from AND @to
 ORDER BY stay_date;

SELECT '--- 참고. 예약 건수 (캐시 ON/OFF 비교용) ---' AS check_name;
SELECT room_type_id, COUNT(*) AS cnt
  FROM reservation
 WHERE check_in BETWEEN @from AND @to
   AND status NOT IN ('CANCELLED', 'EXPIRED')
 GROUP BY room_type_id ORDER BY room_type_id;
