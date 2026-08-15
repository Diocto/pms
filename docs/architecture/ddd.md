# 도메인 모델링 규칙

도메인 모델을 만들거나 고칠 때 읽는다. 리뷰어는 이 문서를 기준으로 지적한다.

## 무엇을 도메인에 두는가

**"이 규칙이 깨지면 데이터가 틀린 것인가, 아니면 사용자가 잘못 요청한 것인가."** 앞이면 도메인, 뒤면 입력 검증이다.

- 잔여 수량이 음수가 될 수 없다 → **도메인 불변식**
- 예약은 전이 표에 없는 상태로 갈 수 없다 → **도메인 불변식**
- 체크인이 체크아웃보다 늦을 수 없다 → **도메인 불변식**
- 날짜 문자열이 `2026-13-45`다 → 입력 검증

**불변식은 도메인 메서드에 둔다.** Pydantic validator에만 두면 요청 파싱 계층의 관심사로 읽히고, **코드에서 객체를 직접 만들 때 우회된다.** 시드 마이그레이션, 테스트 픽스처, 배치가 전부 그 우회 경로다.

## 애그리거트

**애그리거트는 "함께 지켜져야 하는 규칙의 범위"다.** 한 트랜잭션에서 통째로 지켜지는 단위이지, 화면에서 함께 보이는 단위가 아니다.

이 프로젝트의 애그리거트는 셋이다.

| 애그리거트 | 지키는 불변식 |
|---|---|
| `Reservation` | 상태는 전이 표대로만 바뀐다 |
| `RoomDailyInventory` | `0 <= remaining <= total_quantity` |
| `PromotionInventory` | `0 <= remaining <= total_quantity` |

**애그리거트 간에는 ID로만 참조한다.** 예약은 재고 행 객체를 갖지 않고 `room_type_id`와 날짜 범위만 갖는다.

**`relationship()`을 걸지 않는다.** 걸면 무심코 다른 애그리거트를 함께 로드하고, 그것을 수정하면 트랜잭션 경계가 조용히 넓어진다. 조인이 필요하면 **조회 전용 쿼리**에서 명시적으로 쓴다.

**한 트랜잭션에서 한 애그리거트만 고치는 것이 원칙이다.** 이 프로젝트는 예약 생성에서만 예외를 둔다 — 재고 차감과 예약 생성이 함께 성공하거나 함께 실패해야 하기 때문이다. **예외라는 것을 문서에 명시하고, 예외를 늘리지 않는다.**

## 값 객체(VO)

**의미가 있는 값은 원시 타입으로 두지 않는다.** `int`가 아니라 `RoomCount`, 두 날짜가 아니라 `StayPeriod`다.

이유는 두 가지다. **검증을 한 곳에 모을 수 있고**, 함수 시그니처에서 무엇을 받는지가 드러난다. `create(1, 3, 2)`는 읽을 수 없지만 `create(RoomTypeId(1), RoomCount(3), GuestCount(2))`는 읽힌다.

**VO는 불변으로 만든다.** 만들 때 검증하고, 만들어진 뒤에는 바뀌지 않는다.

```python
@dataclass(frozen=True)
class StayPeriod:
    check_in: date
    check_out: date

    def __post_init__(self) -> None:
        if self.check_out <= self.check_in:
            raise InvalidStayPeriodError(...)

    def occupied_dates(self) -> list[date]:
        """점유 날짜. 체크아웃 당일은 자지 않으므로 제외한다."""
        n = (self.check_out - self.check_in).days
        return [self.check_in + timedelta(days=i) for i in range(n)]
```

**계산 규칙을 VO에 둔다.** 위의 `occupied_dates()`가 그 예다. "체크아웃 당일은 점유하지 않는다"는 도메인 지식이고, 이걸 유스케이스마다 다시 쓰면 언젠가 한 곳이 어긋난다.

**VO와 DB 제약을 둘 다 둔다.** 중복이지만 막는 것이 다르다 — VO는 코드 경로를, CHECK는 시드·배치·수동 SQL을 막는다.

## 상태 전이는 표로 구현한다

**`(현재 상태, 이벤트) → 다음 상태` 맵을 두고 그 표로만 판단한다.** if-else 분기로 상태를 전이시키지 않는다.

```python
# domain/transitions.py — 이 파일 하나가 규칙 전부다
TRANSITIONS: dict[tuple[Status, Event], Status] = {
    (Status.PENDING,   Event.CONFIRM):        Status.CONFIRMED,
    (Status.PENDING,   Event.PAYMENT_FAILED): Status.CANCELLED,
    ...
}

IDEMPOTENT: set[tuple[Status, Event]] = {
    (Status.CONFIRMED, Event.CONFIRM),   # 이미 그 상태다. 200을 주고 아무것도 안 한다
    ...
}
```

**표를 파일 하나에 둔다.** 스펙의 표와 1:1로 대조돼야 하고, 흩어지면 대조할 수 없다.

**세터를 만들지 않는다.** `set_status()` 같은 것은 존재하지 않는다. 외부는 이벤트만 던지고, 도메인이 표를 보고 판단한다.

```python
def handle(self, event: Event) -> None:
    key = (self.status, event)
    if key in IDEMPOTENT:
        return                       # 상태를 바꾸지 않는다
    nxt = TRANSITIONS.get(key)
    if nxt is None:
        raise InvalidStateTransitionError(self.status, event)
    self.status = nxt
```

**표에 없는 조합은 전부 거부한다.** "아마 괜찮겠지"로 통과시키는 칸을 만들지 않는다.

**멱등 성공과 허용 전이를 구분한다.** 이미 확정된 예약에 확정을 다시 요청하는 것은 실패가 아니지만 상태를 바꾸지도 않는다. 이 구분이 없으면 재시도가 상태를 밀어버린다.

**표의 크기가 곧 테스트의 크기다.** 상태 × 이벤트의 모든 칸을 순회해 허용·멱등·거부를 전수 검증한다. 자세한 것은 `tdd.md`에 있다.

## 상태 전이의 부수 효과를 표에 묶는다

재고를 되돌리려는 요청은 여럿인데(취소·결제 실패·만료) **되돌릴 기회는 한 번뿐이다.** 이걸 "누가 먼저 왔나"로 풀면 경합에서 진다.

**전이에 성공한 하나만 부수 효과를 실행하게 한다.**

```python
result = session.execute(
    update(Reservation)
    .where(Reservation.id == rid, Reservation.status == expected)
    .values(status=next_status)
    .execution_options(synchronize_session=False)
)
if result.rowcount == 0:
    raise InvalidStateTransitionError(...)   # 졌다. 여기서 끝난다

restore_inventory(session, ...)              # 이긴 하나만 여기 도달한다
```

**"정확히 한 번"을 보장하는 별도 장치가 없다.** 동시성 제어가 이미 하고 있는 일에 부수 효과를 얹었을 뿐이다. 장치를 하나 더 만들면 그 장치가 또 경합의 대상이 된다.

**부수 효과 대상은 이벤트 기준으로 적는다.** 도착 상태로 적으면 한 칸에 여러 이벤트가 들어가서(`CANCELLED`에 `CANCEL`과 `PAYMENT_FAILED`가 함께) **구현이 표를 한 줄씩 옮길 수 없다.** 표를 두는 목적이 사라진다.

## 도메인 서비스

**한 애그리거트에 담기지 않는 규칙**만 도메인 서비스로 뺀다. 가격 계산이 그 예다 — 객실타입 단가와 할인이 함께 필요해서 예약 하나가 답할 수 없다.

**애그리거트에 둘 수 있으면 애그리거트에 둔다.** 도메인 서비스가 늘어나면 애그리거트가 데이터 덩어리로 전락한다.

**도메인 서비스도 세션을 받지 않는다.** 필요한 값은 인자로 받는다.

## 도메인이 의존해도 되는 것

**`sqlmodel`·`sqlalchemy`와 표준 라이브러리, 그리고 `app.common`의 프레임워크 무의존 부분(예외 계층, 시계)뿐이다.** `fastapi`, `redis`, `dependency_injector`가 `domain`에 들어오면 규칙 위반이다. 자세한 근거는 `clean-architecture.md`에 있다.

**시각을 직접 읽지 않는다.** `datetime.now()`를 도메인에서 부르면 테스트가 실제 시각에 묶인다. 시계를 주입받거나 인자로 받는다.

```python
def can_check_in(self, today: date) -> bool:
    return self.period.check_in <= today < self.period.check_out
```

**세션을 받지 않는다.** 도메인 객체는 자기 상태만 다룬다. 받는 순간 DB 없이 테스트할 수 없게 된다.

## 바운디드 컨텍스트

이 프로젝트는 셋으로 나눈다 — `reservation`, `inventory`, `promotion`.

**나누는 기준은 규칙이 다른가이지 테이블 수가 아니다.** 재고 구역의 규칙은 "남은 방이 0 밑으로 내려가지 않는다"이고, 예약 구역의 규칙은 "상태는 표대로만 바뀐다"다. 서로 상관이 없으므로 나눈다.

**컨텍스트를 넘는 호출은 포트를 거친다.** 다른 컨텍스트의 도메인 객체를 직접 import하지 않는다.

**다른 컨텍스트가 내 트랜잭션에 참여해야 하면 확장 지점을 정의한다.** 정의하는 쪽은 호출부이고, 구현하는 쪽이 참여자다. **의존 방향은 참여자 → 호출부** 한 방향이다. 호출부가 참여자를 import하면 그 feature 없이는 코어가 돌지 않게 된다.

**확장 지점이 넷을 넘어가면 멈추고 다시 본다.** 호출 순서 자체가 계약이 되어 문서 없이는 읽을 수 없어지는 지점이 있다. 그때는 훅을 더 만들 것이 아니라 상대에게 자기 진입점을 주는 쪽을 검토한다.

## 흔한 실수

| 실수 | 왜 문제인가 |
|---|---|
| 유스케이스에 `if status == ...` 분기 | 그 규칙은 도메인에 있어야 한다. 유스케이스는 순서만 정한다 |
| VO 없이 `int`, `str`을 그대로 | 검증이 흩어지고 시그니처가 안 읽힌다 |
| 애그리거트에 `relationship()` | 트랜잭션 경계가 조용히 넓어진다 |
| 도메인에서 `datetime.now()` | 테스트가 실제 시각에 묶인다 |
| 불변식을 Pydantic validator에만 | 코드에서 객체를 만들 때 우회된다 |
| 부수 효과를 도착 상태로 적기 | 한 칸에 여러 이벤트가 들어가 구현이 표를 못 옮긴다 |
| 상태 세터 | 표를 우회하는 문이 생긴다 |
