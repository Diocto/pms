# 테스트 규칙

## 순서를 지킨다

실패하는 테스트를 먼저 쓴다. 구현부터 쓰고 테스트를 나중에 붙이지 않는다.

순서를 지키는 이유는 규율 때문이 아니다. 테스트를 먼저 쓰면 **쓰기 어려운 설계가 즉시 드러나기 때문**이다. 유스케이스 테스트를 쓰려는데 DB를 띄워야만 한다면, 그건 레이어가 새고 있다는 신호다. 구현을 먼저 하면 이 신호를 놓치고 나중에 갚는다.

한 사이클은 이렇다.

1. 실패하는 테스트를 쓴다. **실패를 눈으로 확인한다.** 통과하는 걸 보고 넘어가면 그 테스트는 아무것도 검증하지 않을 수 있다.
2. 통과할 만큼만 구현한다.
3. 정리한다. 테스트는 계속 통과해야 한다.

## 테스트 계층

| 계층 | 대상 | 인프라 | 속도 |
|---|---|---|---|
| 도메인 단위 | 애그리거트, VO, 상태머신 | 없음 | 밀리초 |
| 유스케이스 | 유스케이스 구현 | 포트를 가짜 구현으로 | 밀리초 |
| 영속성 통합 | 리포지토리, 마이그레이션, 락 | Testcontainers MySQL | 초 |
| 동시성 | 경합 상황의 불변식 | Testcontainers MySQL + Redis | 초 |
| API | 컨트롤러부터 DB까지 | Testcontainers 전체 | 초 |

**대부분의 테스트는 위 두 계층에 있어야 한다.** 통합 테스트는 실제로 DB가 필요한 것만 쓴다. 도메인 규칙을 통합 테스트로 검증하고 있으면 잘못 배치된 것이다.

## H2를 쓰지 않는다

H2는 락 동작이 MySQL과 다르다. `SELECT ... FOR UPDATE`의 대기 동작, 갭락, 데드락 감지가 실제와 다르게 흉내 낸 것이다. 동시성이 주제인 프로젝트에서 H2로 동시성 테스트를 하면 **그 테스트는 아무것도 증명하지 못한다.** 통과해도 운영에서 깨지고, 실패해도 진짜 문제인지 알 수 없다.

Testcontainers로 실제 MySQL을 띄운다. 느리지만 이건 타협 대상이 아니다.

## Testcontainers 설정

컨테이너는 테스트 클래스마다 새로 띄우지 않는다. 재사용해야 전체 시간이 감당된다.

```java
@Testcontainers
public abstract class IntegrationTestBase {

    @Container
    @ServiceConnection
    static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.4")
        .withCommand("--transaction-isolation=REPEATABLE-READ")
        .withReuse(true);

    @Container
    @ServiceConnection
    static final GenericContainer<?> REDIS = new GenericContainer<>("redis:7.4-alpine")
        .withExposedPorts(6379)
        .withReuse(true);
}
```

`static` 필드로 두면 JVM 하나 안에서 컨테이너가 공유된다. `@ServiceConnection`이 접속 정보를 자동으로 주입한다.

**테스트 간 데이터 격리는 각 테스트가 책임진다.** `@Transactional`로 롤백하는 방식은 동시성 테스트에서 쓸 수 없다. 여러 스레드가 각자 트랜잭션을 열어야 하기 때문이다. 동시성 테스트에서는 테이블을 직접 비우는 방식을 쓴다.

## 동시성 테스트

동시성 코드에는 **반드시** 동시성 테스트가 따라붙는다. 단일 스레드 테스트만 있으면 리뷰에서 반려된다.

핵심은 두 가지다. 스레드들이 **동시에 출발**해야 하고, 검증은 **불변식**을 봐야 한다.

```java
@Test
@DisplayName("같은 객실을 100명이 동시에 예약하면 재고 수량만큼만 성공한다")
void 동시_예약_요청은_재고_수량을_초과하지_않는다() throws Exception {
    int 재고 = 10;
    int 동시요청 = 100;
    재고를_준비한다(roomTypeId, 날짜, 재고);

    var 출발신호 = new CountDownLatch(1);
    var 완료신호 = new CountDownLatch(동시요청);
    var 성공 = new AtomicInteger();
    var 실패 = new AtomicInteger();

    try (var pool = Executors.newFixedThreadPool(32)) {
        for (int i = 0; i < 동시요청; i++) {
            pool.submit(() -> {
                try {
                    출발신호.await();          // 모든 스레드가 여기서 대기하다 함께 출발
                    예약_유스케이스.execute(요청());
                    성공.incrementAndGet();
                } catch (Exception e) {
                    실패.incrementAndGet();
                } finally {
                    완료신호.countDown();
                }
            });
        }
        출발신호.countDown();
        assertThat(완료신호.await(30, TimeUnit.SECONDS)).isTrue();
    }

    // 불변식을 검증한다. "성공 횟수가 재고와 같다"만 보면 부족하다.
    assertThat(성공.get()).isEqualTo(재고);
    assertThat(잔여재고를_조회한다(roomTypeId, 날짜)).isZero();
    assertThat(확정된_예약_수를_센다(roomTypeId, 날짜)).isEqualTo(재고);
}
```

주의할 점이 있다.

**출발 신호 없이 루프에서 바로 submit하면 경합이 안 일어난다.** 먼저 제출된 작업이 이미 끝나버린다. `CountDownLatch`로 모아뒀다가 한 번에 푼다.

**예외를 삼키지 않는다.** `catch (Exception e)`로 실패만 세면 어떤 예외인지 모른다. 예상한 예외(재고 부족)와 예상 못 한 예외(데드락, NPE)를 구분해서 센다. 예상 못 한 예외가 하나라도 있으면 테스트는 실패해야 한다.

**결과 수뿐 아니라 DB 상태를 본다.** 성공 10건이 나왔어도 실제로 예약 행이 11건 들어갔을 수 있다. 최종 상태를 직접 조회해 확인한다.

**멱등성 테스트는 같은 키로 동시에 보낸다.** 같은 멱등성 키로 100번 동시 요청했을 때 예약이 정확히 1건만 생기는지 본다.

## 테스트 이름

`@DisplayName`에 한국어로 시나리오를 쓴다. 메서드 이름도 한국어로 쓴다. 실패했을 때 무엇이 깨졌는지 바로 읽혀야 한다.

```java
@DisplayName("확정된 예약은 체크인 이후 취소할 수 없다")
void 확정된_예약은_체크인_이후_취소할_수_없다() { }
```

"성공한다", "정상 동작한다" 같은 이름은 쓰지 않는다. 무엇이 성공인지가 이름에 있어야 한다.

## 구조

Given-When-Then으로 나누고 빈 줄로 구분한다. 주석으로 표시할 필요는 없다. 세 덩어리가 눈에 보이면 된다.

한 테스트는 하나를 검증한다. `assertAll`로 여러 필드를 함께 보는 건 괜찮지만, 서로 다른 시나리오를 한 테스트에 넣지 않는다.

## 테스트하지 않는 것

게터·세터, 프레임워크 동작, 라이브러리 자체. Spring이 빈을 주입하는지는 테스트하지 않는다.

커버리지 숫자를 목표로 삼지 않는다. 커버리지를 채우려고 의미 없는 테스트를 쓰면 유지보수 비용만 늘어난다. 대신 **동시성과 상태 전이는 빠짐없이** 덮는다. 상태 전이는 표의 모든 칸을 순회해 허용·금지를 전수 검증한다.

## 실행

```bash
./gradlew test                      # 전체
./gradlew test --tests "*동시*"      # 동시성만
```

동시성 테스트는 느리므로 `@Tag("concurrency")`를 붙여 분리한다. 개발 중에는 빼고 돌리고, 커밋 전에는 반드시 포함해 돌린다.
