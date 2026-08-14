# 도메인 모델링 규칙

## 애그리거트

### 경계를 어떻게 정하는가

애그리거트는 **함께 지켜져야 하는 불변식의 범위**다. "이 규칙이 깨지면 데이터가 틀린 것"인 규칙들을 묶는다.

예약 도메인의 불변식은 이런 것들이다.

- 예약의 상태 전이는 정해진 표를 벗어날 수 없다.
- 확정된 예약의 투숙 기간은 바뀌지 않는다.
- 어떤 날짜의 잔여 재고는 음수가 될 수 없다.

앞의 둘은 `Reservation` 안에서 지켜진다. 마지막은 재고 쪽이다. **경계가 다르면 애그리거트가 다르다.**

### 애그리거트끼리는 ID로만 참조한다

`Reservation`이 `RoomInventory` 객체를 필드로 들고 있으면 안 된다. `roomTypeId`처럼 식별자만 들고, 필요하면 유스케이스에서 각각 불러온다.

이유는 두 가지다. 객체 참조를 허용하면 트랜잭션 범위가 어디까지인지 흐려진다. 그리고 JPA 연관관계를 타고 의도치 않은 락과 쿼리가 나간다. 동시성이 주제인 프로젝트에서 이건 치명적이다.

```java
// 안 된다
@ManyToOne
private RoomType roomType;

// 이렇게 한다
private Long roomTypeId;
```

### 한 트랜잭션에 애그리거트 하나

원칙적으로 한 트랜잭션에서는 애그리거트 하나만 수정한다. 예약 생성처럼 재고와 예약을 함께 바꿔야 하는 경우는 이 원칙을 어기는 것이고, **어기는 이유를 스펙에 명시한다.** 이 프로젝트에서는 강한 일관성이 필요하므로 같은 트랜잭션에서 처리하되, 그 판단을 ADR에 남긴다.

## 엔티티와 값 객체

**엔티티**는 식별자로 구분된다. 속성이 다 바뀌어도 같은 예약이다.

**값 객체(VO)**는 값으로 구분된다. 식별자가 없고 불변이다. 투숙 기간, 금액, 인원수 같은 것이 여기 해당한다.

VO를 쓰는 이유는 **규칙을 담을 자리가 생기기 때문**이다. `LocalDate checkIn, LocalDate checkOut`을 그냥 필드로 두면 "체크아웃이 체크인보다 빠르면 안 된다"는 규칙을 둘 곳이 없다. 이걸 `StayPeriod`로 묶으면 생성자에서 검증하고, 겹침 판정 같은 메서드를 붙일 수 있다.

```java
@Embeddable
public record StayPeriod(LocalDate checkIn, LocalDate checkOut) {
    public StayPeriod {
        if (checkIn == null || checkOut == null) {
            throw new IllegalArgumentException("투숙 기간은 비어 있을 수 없다");
        }
        if (!checkOut.isAfter(checkIn)) {
            throw new IllegalArgumentException("체크아웃은 체크인보다 뒤여야 한다");
        }
    }

    /** 투숙에 해당하는 날짜들. 체크아웃 당일은 포함하지 않는다. */
    public List<LocalDate> occupiedDates() {
        return checkIn.datesUntil(checkOut).toList();
    }

    public long nights() {
        return ChronoUnit.DAYS.between(checkIn, checkOut);
    }
}
```

VO는 `record`로 만든다. `@Embeddable`을 붙여 JPA에 매핑한다.

## 상태 전이

### 전이 테이블로만 구현한다

if-else 분기로 상태를 바꾸지 않는다. 규칙을 데이터로 표현하고, 그 데이터를 유일한 판단 근거로 삼는다.

```java
public enum ReservationStatus {
    PENDING, CONFIRMED, CHECKED_IN, CHECKED_OUT, CANCELLED, EXPIRED;

    public boolean isTerminal() {
        return this == CHECKED_OUT || this == CANCELLED || this == EXPIRED;
    }
}

public enum ReservationEvent {
    CONFIRM, CANCEL, PAYMENT_FAILED, CHECK_IN, CHECK_OUT, EXPIRE
}
```

전이 표는 별도 클래스에 둔다.

```java
public final class ReservationStateMachine {

    private record Key(ReservationStatus from, ReservationEvent event) {}

    private static final Map<Key, ReservationStatus> TABLE = Map.of(
        new Key(PENDING,    CONFIRM),        CONFIRMED,
        new Key(PENDING,    CANCEL),         CANCELLED,
        new Key(PENDING,    PAYMENT_FAILED), CANCELLED,
        new Key(PENDING,    EXPIRE),         EXPIRED,
        new Key(CONFIRMED,  CANCEL),         CANCELLED,
        new Key(CONFIRMED,  CHECK_IN),       CHECKED_IN,
        new Key(CHECKED_IN, CHECK_OUT),      CHECKED_OUT
    );

    /** 전이가 가능하면 다음 상태를, 불가능하면 빈 값을 돌려준다. */
    public static Optional<ReservationStatus> next(ReservationStatus from, ReservationEvent event) {
        return Optional.ofNullable(TABLE.get(new Key(from, event)));
    }
}
```

이 표는 스펙 문서에 그대로 옮긴다. 표와 문서가 어긋나면 둘 중 하나가 틀린 것이다.

### 세터를 만들지 않는다

`setStatus`는 존재하지 않는다. 외부는 이벤트만 던진다.

```java
public void handle(ReservationEvent event) {
    ReservationStatus next = ReservationStateMachine.next(this.status, event)
        .orElseThrow(() -> new InvalidStateTransitionException(this.status, event));
    this.status = next;
}
```

의미가 분명한 곳에서는 이벤트를 감싼 메서드를 둬도 된다. `cancel()`이 내부에서 `handle(CANCEL)`을 부르는 식이다. 판단은 여전히 표가 한다.

### 멱등한 전이

같은 이벤트가 두 번 들어오는 것은 정상 상황이다. 클라이언트 재시도, 네트워크 타임아웃 후 재전송에서 늘 일어난다.

**이미 목표 상태에 도달했다면 예외를 던지지 않고 조용히 성공으로 처리한다.**

```java
public void handle(ReservationEvent event) {
    ReservationStatus next = ReservationStateMachine.next(this.status, event)
        .orElseGet(() -> {
            // 이미 그 이벤트의 결과 상태라면 재시도로 보고 그대로 둔다
            if (ReservationStateMachine.isResultOf(this.status, event)) {
                return this.status;
            }
            throw new InvalidStateTransitionException(this.status, event);
        });
    this.status = next;
}
```

무엇을 멱등하게 볼지는 feature 스펙에 명시한다. 판단 없이 전부 조용히 넘기면 진짜 오류를 놓친다.

## 리포지토리

리포지토리는 **애그리거트 루트 단위로만** 만든다. 애그리거트 내부 엔티티를 위한 리포지토리는 만들지 않는다.

인터페이스는 `domain/repository`에, 구현은 `adapter/out/persistence`에 둔다. 자세한 규칙은 `clean-architecture.md`에 있다.

락이 필요한 조회는 메서드 이름에 드러낸다. `findById`와 `findByIdForUpdate`는 다른 메서드다. 호출하는 쪽이 락 여부를 모르면 안 된다.

## 도메인 서비스

**한 애그리거트에 담기지 않는 규칙**만 도메인 서비스로 뺀다. 여러 애그리거트를 걸치거나, 어느 한쪽의 책임이라고 말하기 어려운 계산이 여기 해당한다.

애그리거트에 넣을 수 있는 로직을 도메인 서비스로 빼면 애그리거트가 데이터 덩어리로 전락한다. 먼저 애그리거트에 넣을 자리를 찾고, 정말 없을 때만 도메인 서비스를 만든다.

도메인 서비스는 Spring 빈이 아니다. `@Service`를 붙이지 않고 정적 메서드나 순수 객체로 만든다.

## 도메인 예외

도메인은 자기 언어로 실패를 표현한다. `IllegalArgumentException`을 그대로 던지지 말고 의미 있는 예외를 정의한다.

```java
public class InvalidStateTransitionException extends DomainException { }
public class InsufficientInventoryException extends DomainException { }
```

HTTP 상태 코드로의 변환은 `adapter/in/web`에서 한다. 도메인은 HTTP를 모른다.

## 이 프로젝트에서 특히 주의할 것

**시간을 직접 읽지 않는다.** `LocalDate.now()`를 도메인 안에서 호출하면 테스트에서 시간을 고정할 수 없다. `Clock`을 주입받거나 시각을 파라미터로 받는다.

**컬렉션을 그대로 노출하지 않는다.** 게터가 내부 리스트를 반환하면 외부에서 애그리거트 규칙을 우회해 수정할 수 있다. 방어적 복사나 불변 컬렉션으로 반환한다.

**JPA를 위한 기본 생성자는 `protected`로 둔다.** `public`이면 아무나 불완전한 객체를 만들 수 있다.
