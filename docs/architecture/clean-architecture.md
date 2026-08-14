# 아키텍처 구조

## 왜 이렇게 나누는가

레이어를 나누는 목적은 하나다. **도메인 규칙이 기술 결정에 끌려다니지 않게 하는 것.** 객실 재고를 어떻게 차감하는지는 MySQL을 쓰든 Redis를 쓰든 HTTP로 부르든 똑같아야 한다. 그 규칙이 JPA 세션 관리나 HTTP 요청 객체와 얽히면, DB를 바꿀 때가 아니라 **테스트를 쓸 때 바로 아프다.**

그래서 판단 기준은 항상 이것이다. 이 코드를 DB와 웹 없이 테스트할 수 있는가.

## 레이어와 의존 방향

```
   adapter (in/web, out/persistence, out/lock, out/cache)
      │  의존
      ▼
   application (유스케이스, 포트)
      │  의존
      ▼
   domain (애그리거트, VO, 도메인 서비스, 리포지토리 인터페이스)
```

의존은 **안쪽으로만** 향한다. `domain`은 `application`을 모르고, `application`은 `adapter`를 모른다.

바깥 기술을 안쪽에서 써야 할 때는 **포트**를 쓴다. 안쪽이 인터페이스를 정의하고 바깥이 구현한다. 예를 들어 유스케이스가 분산락이 필요하면 `application/port/out/LockPort`를 정의하고, Redis 구현은 `adapter/out/lock`에 둔다. 이렇게 하면 유스케이스 테스트에서 락을 가짜 구현으로 바꿔 끼울 수 있다.

## 패키지 구조

```
com.pms
├── PmsApplication.java
├── common/
│   ├── config/         전역 설정 (Redis, JPA, Web, 시간)
│   ├── exception/      공통 예외 계층과 에러 코드
│   ├── response/       API 공통 응답 포맷
│   └── support/        공통 유틸 (Clock 등)
└── <context>/          바운디드 컨텍스트 (reservation, inventory 등)
    ├── domain/
    │   ├── model/      애그리거트 루트, 엔티티, VO, 상태·이벤트 enum
    │   ├── service/    한 애그리거트에 담기지 않는 도메인 규칙
    │   └── repository/ 리포지토리 인터페이스 (구현은 adapter)
    ├── application/
    │   ├── port/in/    유스케이스 인터페이스
    │   ├── port/out/   외부 의존 포트 (락, 캐시, 멱등성 저장소)
    │   ├── usecase/    유스케이스 구현 (@Service, @Transactional)
    │   └── dto/        유스케이스 입출력 (Command, Result)
    └── adapter/
        ├── in/web/     컨트롤러, 요청·응답 DTO
        └── out/
            ├── persistence/  Spring Data JPA 리포지토리, 도메인 리포지토리 구현
            ├── lock/         Redis 분산락 구현
            └── cache/        Redis 캐시 구현
```

## 도메인과 JPA를 통합한 것에 대한 규칙

이 프로젝트는 도메인 모델에 `@Entity`를 직접 붙인다. 순수 도메인 객체와 JPA 엔티티를 따로 두고 매핑하는 방식보다 코드가 절반이고, 더티 체킹을 그대로 쓸 수 있어서다. 3일 반이라는 기간이 이 선택의 가장 큰 이유다. 자세한 근거는 `docs/decisions/`에 있다.

대신 통합의 대가를 규칙으로 막는다.

**`domain` 패키지가 의존해도 되는 것은 `jakarta.persistence`와 JDK뿐이다.** `org.springframework.*`, `jakarta.servlet.*`, Redis 관련 타입이 `domain`에 들어오면 규칙 위반이다.

**Spring Data JPA의 `JpaRepository`는 `domain`에 두지 않는다.** `domain/repository`에는 순수 인터페이스를 두고, `adapter/out/persistence`에 `JpaRepository`를 상속한 인터페이스와 이를 감싸는 구현체를 둔다.

```java
// domain/repository/ReservationRepository.java  ← 순수 인터페이스
public interface ReservationRepository {
    Optional<Reservation> findById(Long id);
    Reservation save(Reservation reservation);
}

// adapter/out/persistence/ReservationJpaRepository.java  ← Spring Data
interface ReservationJpaRepository extends JpaRepository<Reservation, Long> { }

// adapter/out/persistence/ReservationRepositoryAdapter.java  ← 구현
@Repository
@RequiredArgsConstructor
public class ReservationRepositoryAdapter implements ReservationRepository {
    private final ReservationJpaRepository jpaRepository;
    // ...
}
```

번거로워 보이지만 이 한 겹이 유스케이스 테스트를 DB 없이 돌게 만든다.

**도메인 객체에 `@Transactional`을 붙이지 않는다.** 트랜잭션 경계는 유스케이스에만 있다.

## 레이어별 책임

### domain

비즈니스 규칙이 산다. 예약이 취소 가능한 상태인지, 재고를 차감할 수 있는지, 기간이 유효한지를 판단한다.

**들어가면 안 되는 것:** HTTP 개념(요청, 응답, 상태코드), 트랜잭션 어노테이션, Spring 빈 등록, 외부 시스템 호출.

**판단 기준:** 이 클래스를 `new`로 만들어서 순수 JUnit 테스트를 쓸 수 있는가. 없다면 잘못된 위치다.

### application

유스케이스 하나가 클래스 하나다. 도메인 객체를 불러오고, 규칙을 실행시키고, 저장한다. **트랜잭션 경계가 여기 있다.**

유스케이스는 조율만 한다. 비즈니스 판단을 유스케이스에서 하고 있으면 그 로직은 도메인으로 내려가야 한다. `if (reservation.getStatus() == CONFIRMED)` 같은 코드가 유스케이스에 있으면 신호다. `reservation.cancel()`이 스스로 판단하게 만든다.

**들어가면 안 되는 것:** HTTP 요청·응답 객체, JPA 리포지토리 직접 참조(포트를 통한다), SQL.

### adapter

바깥 세상과의 접점이다. HTTP 요청을 유스케이스 입력으로 바꾸고, 유스케이스 결과를 HTTP 응답으로 바꾼다. DB 접근을 실제로 수행한다.

컨트롤러는 얇아야 한다. 검증과 변환만 하고 유스케이스를 부른다. **컨트롤러에 비즈니스 판단이 있으면 안 된다.**

## 자주 나오는 위반과 판별법

| 증상 | 왜 문제인가 | 어떻게 고치나 |
|---|---|---|
| 유스케이스가 상태를 직접 비교하고 분기 | 규칙이 도메인 밖으로 샜다 | 애그리거트에 판단 메서드를 만든다 |
| 컨트롤러가 리포지토리를 직접 호출 | 레이어를 건너뛰었다 | 유스케이스를 거친다 |
| 도메인 클래스에 `@Service`, `@Component` | 도메인이 Spring에 묶였다 | 순수 클래스로 만들고 유스케이스에서 생성 |
| 도메인이 `RedisTemplate`을 참조 | 기술이 도메인에 침투 | 포트를 정의하고 어댑터에서 구현 |
| DTO가 도메인 객체를 그대로 노출 | 내부 구조가 API에 새어나감 | 응답 전용 DTO를 만든다 |

## 바운디드 컨텍스트 나누기

컨텍스트는 **같은 단어가 다른 뜻을 가지는 지점**에서 나눈다. 억지로 잘게 나누지 않는다. 이 규모에서는 컨텍스트가 하나여도 문제없다.

컨텍스트를 추가하려면 ADR을 남긴다. 병렬 작업에서 컨텍스트는 소유권의 단위이기도 하다. `docs/architecture/parallel-work.md`를 참고한다.
