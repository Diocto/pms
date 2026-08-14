# 다이어그램 표기 시안

문서 작성 규칙 선정용 비교 문서다. 같은 내용(F01 예약 생성 시퀀스, 도메인 모델, ERD, 상태머신)을 네 방식으로 그렸다. 하나를 고르면 그 방식이 하네스 규칙이 된다.

**렌더링 호환성 (중요)**

| 시안 | GitHub 웹 | Claude 세션 패널 | Bear |
|---|---|---|---|
| A. Mermaid 표준형 | 그려짐 | 그려짐 | 코드로만 보임 |
| B. Mermaid 그룹·색상형 | 그려짐 | 그려짐 | 코드로만 보임 |
| C. 커스텀 HTML 카드형 | **안 그려짐** (HTML 제거됨) | 그려짐 | 안 그려짐 |
| D. Mermaid + 상세 표 병기 | 그려짐 | 그려짐 | 표만 보임 |

---

# 시안 A. Mermaid 표준형

각 목적에 맞는 mermaid 기본 다이어그램을 장식 없이 쓴다.

## A-1. 시퀀스 (UC-2 예약 생성)

```mermaid
sequenceDiagram
    autonumber
    actor C as 클라이언트
    participant API as 예약 API
    participant R as Redis
    participant DB as MySQL

    C->>API: POST /api/reservations (Idempotency-Key)
    API->>R: 멱등성 키 선점 (SET NX)
    alt 키가 이미 존재
        R-->>API: 실패
        API-->>C: 409 처리 중 / 200 기존 결과
    end
    API->>R: 분산락 획득 lock:inventory:{roomTypeId}
    rect rgb(235, 235, 235)
        note over API,DB: 트랜잭션
        API->>DB: 재고 조건부 UPDATE (날짜 오름차순)
        alt 갱신 행 수 부족
            DB-->>API: 재고 부족
            API-->>C: 409 INSUFFICIENT_INVENTORY (롤백)
        end
        API->>DB: Reservation INSERT (PENDING)
    end
    API->>R: 락 해제
    API->>R: 멱등성 키에 결과 저장
    API-->>C: 201 예약 생성 (PENDING)
```

## A-2. 도메인 모델

```mermaid
classDiagram
    class Reservation {
        <<AggregateRoot>>
        Long id
        String userId
        Long roomTypeId
        StayPeriod stayPeriod
        int roomCount
        BigDecimal totalPrice
        ReservationStatus status
        handle(ReservationEvent)
        cancel()
    }
    class StayPeriod {
        <<ValueObject>>
        LocalDate checkIn
        LocalDate checkOut
        occupiedDates()
        nights()
    }
    class ReservationStateMachine {
        next(status, event) Optional
    }
    class RoomDailyInventory {
        <<AggregateRoot>>
        Long roomTypeId
        LocalDate stayDate
        int totalQuantity
        int remaining
    }
    class RoomType {
        <<참조데이터>>
        Long hotelId
        String name
        BigDecimal pricePerNight
    }
    Reservation *-- StayPeriod
    Reservation ..> ReservationStateMachine : 전이 판단
    Reservation ..> RoomTypeId만 참조
    RoomDailyInventory ..> RoomTypeId만 참조
```

## A-3. ERD

```mermaid
erDiagram
    hotel ||--o{ room_type : "1:N"
    room_type ||--o{ room_daily_inventory : "1:N"
    room_type ||--o{ reservation : "ID 참조"

    hotel {
        bigint id PK
        varchar name
    }
    room_type {
        bigint id PK
        bigint hotel_id FK
        varchar name
        int capacity
        decimal price_per_night
        int total_quantity
    }
    room_daily_inventory {
        bigint id PK
        bigint room_type_id "UK(+stay_date)"
        date stay_date
        int total_quantity
        int remaining "CHECK >= 0"
    }
    reservation {
        bigint id PK
        varchar user_id "UK(+idempotency_key)"
        bigint room_type_id
        date check_in
        date check_out
        int room_count
        decimal total_price
        varchar status
        varchar idempotency_key
    }
```

## A-4. 상태머신

```mermaid
stateDiagram-v2
    [*] --> PENDING : 예약 생성
    PENDING --> CONFIRMED : CONFIRM (결제 성공)
    PENDING --> CANCELLED : CANCEL / PAYMENT_FAILED
    PENDING --> EXPIRED : EXPIRE (10분 경과)
    CONFIRMED --> CANCELLED : CANCEL (전날까지)
    CONFIRMED --> CHECKED_IN : CHECK_IN
    CHECKED_IN --> CHECKED_OUT : CHECK_OUT
    CANCELLED --> [*]
    EXPIRED --> [*]
    CHECKED_OUT --> [*]
```

---

# 시안 B. Mermaid 그룹·색상형

방어 계층·구역(컨텍스트) 같은 구조를 subgraph와 색으로 강조한다.

## B-1. 흐름도 (UC-2, 방어선 강조)

```mermaid
flowchart TD
    C([클라이언트 요청]) --> IDEM

    subgraph L1 [1차 방어선 · Redis]
        IDEM{멱등성 키<br>선점 성공?}
        LOCK[분산락 획득<br>lock:inventory:roomTypeId]
    end
    subgraph L2 [2차 방어선 · 조건부 UPDATE]
        DEC[재고 차감<br>WHERE remaining >= n<br>날짜 오름차순]
        CHK{갱신 행 수 =<br>날짜 수?}
    end
    subgraph L3 [3차 방어선 · DB 제약]
        INS[Reservation INSERT<br>UK user_id+idem_key<br>CHECK remaining >= 0]
    end

    IDEM -- 아니오 --> DUP[409 또는 기존 결과 반환]
    IDEM -- 예 --> LOCK --> DEC --> CHK
    CHK -- 아니오 --> FAIL[롤백 · 409 재고 부족]
    CHK -- 예 --> INS --> OK([201 PENDING 생성])

    classDef redis fill:#fff3cd,stroke:#b8860b
    classDef db fill:#d1e7dd,stroke:#146c43
    classDef final fill:#cfe2ff,stroke:#0a58ca
    class IDEM,LOCK redis
    class DEC,CHK db
    class INS final
```

## B-2. 도메인 모델 (구역 강조)

```mermaid
flowchart LR
    subgraph RSV [예약 구역 reservation]
        direction TB
        R["Reservation (루트)<br>─────────<br>userId · roomTypeId<br>stayPeriod · roomCount<br>totalPrice · status"]
        SP["StayPeriod (VO)<br>checkIn · checkOut"]
        SM["ReservationStateMachine<br>(상태, 이벤트) → 다음 상태"]
        R --- SP
        R -. 전이 판단 .-> SM
    end
    subgraph INV [재고 구역 inventory]
        direction TB
        I["RoomDailyInventory (루트)<br>─────────<br>roomTypeId · stayDate<br>remaining ≥ 0"]
        RT["RoomType (참조 데이터)<br>hotelId · name · 단가"]
    end
    R -. "roomTypeId (ID로만 참조)" .-> RT
    I -. roomTypeId .-> RT

    classDef agg fill:#cfe2ff,stroke:#0a58ca,stroke-width:2px
    classDef vo fill:#e2e3e5,stroke:#495057
    classDef ref fill:#f8f9fa,stroke:#adb5bd,stroke-dasharray: 3 3
    class R,I agg
    class SP,SM vo
    class RT ref
```

## B-3. ERD (핵심 컬럼만 + 제약은 표로)

```mermaid
erDiagram
    hotel ||--o{ room_type : ""
    room_type ||--o{ room_daily_inventory : ""
    room_type ||--o{ reservation : "ID 참조"
    room_daily_inventory {
        bigint room_type_id UK
        date stay_date UK
        int remaining "CHECK>=0"
    }
    reservation {
        varchar user_id UK
        varchar idempotency_key UK
        varchar status
        date check_in
        date check_out
    }
```

| 제약 | 대상 | 역할 |
|---|---|---|
| UNIQUE | (room_type_id, stay_date) | 재고 행 유일성 |
| CHECK remaining >= 0 | room_daily_inventory | 초과 판매 최후 방어선 |
| UNIQUE | (user_id, idempotency_key) | 중복 예약 최후 방어선 |

---

# 시안 C. 커스텀 HTML 카드형

색·배치 자유도가 가장 높다. 단 **GitHub와 Bear에서는 안 보인다.**

## C-1. 시퀀스 (단계 카드)

<div style="font-family:sans-serif; max-width:720px;">
  <div style="display:flex; gap:6px; margin-bottom:10px;">
    <div style="flex:1; text-align:center; padding:6px; background:#343a40; color:#fff; border-radius:6px;">클라이언트</div>
    <div style="flex:1; text-align:center; padding:6px; background:#0a58ca; color:#fff; border-radius:6px;">예약 API</div>
    <div style="flex:1; text-align:center; padding:6px; background:#b8860b; color:#fff; border-radius:6px;">Redis</div>
    <div style="flex:1; text-align:center; padding:6px; background:#146c43; color:#fff; border-radius:6px;">MySQL</div>
  </div>
  <div style="border-left:3px solid #0a58ca; padding:8px 12px; margin:6px 0; background:#f8f9fa;">
    <b>1. 멱등성 키 선점</b> <span style="color:#b8860b;">API → Redis</span><br>
    <code>SET idem:{user}:{key} NX</code> 실패 시: 처리 중이면 <b style="color:#dc3545;">409</b>, 완료면 기존 결과 반환
  </div>
  <div style="border-left:3px solid #b8860b; padding:8px 12px; margin:6px 0; background:#fff9e6;">
    <b>2. 분산락 획득</b> <span style="color:#b8860b;">API → Redis</span> · <code>lock:inventory:{roomTypeId}</code> · 1차 방어선
  </div>
  <div style="border:2px solid #146c43; border-radius:8px; padding:8px 12px; margin:6px 0; background:#f0fff4;">
    <b style="color:#146c43;">트랜잭션</b>
    <div style="padding:6px 10px; margin:6px 0; background:#fff; border-radius:6px;">
      <b>3. 재고 차감</b> · 날짜 오름차순 조건부 UPDATE (<code>WHERE remaining ≥ n</code>) · 2차 방어선<br>
      갱신 행 부족 → <b style="color:#dc3545;">전체 롤백, 409 재고 부족</b>
    </div>
    <div style="padding:6px 10px; margin:6px 0; background:#fff; border-radius:6px;">
      <b>4. Reservation INSERT</b> (PENDING) · UNIQUE 멱등 키 = 3차 방어선
    </div>
  </div>
  <div style="border-left:3px solid #b8860b; padding:8px 12px; margin:6px 0; background:#fff9e6;">
    <b>5. 락 해제 → 멱등성 키에 결과 저장</b>
  </div>
  <div style="border-left:3px solid #343a40; padding:8px 12px; margin:6px 0; background:#f8f9fa;">
    <b>6. 응답</b> · <b style="color:#146c43;">201</b> 예약 생성 (PENDING, 결제 기한 10분)
  </div>
</div>

## C-2. 도메인 모델 (애그리거트 카드)

<div style="display:flex; gap:14px; flex-wrap:wrap; font-family:sans-serif;">
  <div style="flex:1; min-width:250px; border:2px solid #0a58ca; border-radius:10px; overflow:hidden;">
    <div style="background:#0a58ca; color:#fff; padding:8px 12px;"><b>Reservation</b> · 애그리거트 루트</div>
    <div style="padding:10px 12px;">
      <div style="color:#495057; font-size:0.9em;">불변식: 상태는 전이 표 경로로만 변경</div>
      <hr style="border:none; border-top:1px solid #dee2e6;">
      userId · roomTypeId · roomCount · totalPrice · status
      <div style="margin-top:8px; padding:6px 10px; background:#e2e3e5; border-radius:6px;">
        <b>StayPeriod</b> (VO) checkIn · checkOut
      </div>
      <div style="margin-top:6px; padding:6px 10px; background:#e2e3e5; border-radius:6px;">
        <b>ReservationStateMachine</b> (상태,이벤트)→다음
      </div>
    </div>
  </div>
  <div style="flex:1; min-width:250px; border:2px solid #146c43; border-radius:10px; overflow:hidden;">
    <div style="background:#146c43; color:#fff; padding:8px 12px;"><b>RoomDailyInventory</b> · 애그리거트 루트</div>
    <div style="padding:10px 12px;">
      <div style="color:#495057; font-size:0.9em;">불변식: remaining ≥ 0</div>
      <hr style="border:none; border-top:1px solid #dee2e6;">
      roomTypeId · stayDate · totalQuantity · remaining
    </div>
  </div>
  <div style="flex-basis:100%; border:1px dashed #adb5bd; border-radius:10px; padding:8px 12px; color:#495057;">
    <b>Hotel · RoomType</b> — 시드 참조 데이터. 두 애그리거트 모두 roomTypeId(ID)로만 참조. 객체 참조 금지.
  </div>
</div>

## C-3. ERD (테이블 카드)

<div style="display:flex; gap:12px; flex-wrap:wrap; font-family:monospace; font-size:0.85em;">
  <div style="border:1px solid #adb5bd; border-radius:8px; min-width:210px;">
    <div style="background:#f8f9fa; padding:6px 10px; border-bottom:1px solid #adb5bd;"><b>room_daily_inventory</b></div>
    <div style="padding:8px 10px;">
      <span style="color:#0a58ca;">PK</span> id<br>
      <span style="color:#b8860b;">UK</span> room_type_id, stay_date<br>
      total_quantity<br>
      remaining <span style="color:#dc3545;">CHECK ≥ 0</span>
    </div>
  </div>
  <div style="border:1px solid #adb5bd; border-radius:8px; min-width:210px;">
    <div style="background:#f8f9fa; padding:6px 10px; border-bottom:1px solid #adb5bd;"><b>reservation</b></div>
    <div style="padding:8px 10px;">
      <span style="color:#0a58ca;">PK</span> id<br>
      <span style="color:#b8860b;">UK</span> user_id, idempotency_key<br>
      room_type_id · check_in · check_out<br>
      room_count · total_price · status<br>
      <span style="color:#6c757d;">IX</span> (status, created_at)
    </div>
  </div>
  <div style="border:1px solid #adb5bd; border-radius:8px; min-width:180px;">
    <div style="background:#f8f9fa; padding:6px 10px; border-bottom:1px solid #adb5bd;"><b>room_type</b> (시드)</div>
    <div style="padding:8px 10px;">
      <span style="color:#0a58ca;">PK</span> id<br>
      <span style="color:#6c757d;">FK</span> hotel_id<br>
      name · capacity · price_per_night
    </div>
  </div>
</div>

---

# 시안 D. Mermaid 최소 + 상세 표 병기

다이어그램은 구조·흐름의 뼈대만 보여주고, 세부(컬럼, 조건, 예외)는 바로 밑 표가 담당한다. 그림이 작아서 안 깨지고, 세부는 검색 가능한 텍스트로 남는다.

## D-1. 시퀀스

```mermaid
sequenceDiagram
    actor C as 클라이언트
    participant A as API
    participant R as Redis
    participant M as MySQL
    C->>A: 예약 생성
    A->>R: ① 멱등 키 선점 → ② 락
    A->>M: ③ 재고 차감 + ④ 예약 생성 (한 트랜잭션)
    A->>R: ⑤ 락 해제, 키에 결과 저장
    A-->>C: 201 PENDING
```

| 단계 | 실패 조건 | 응답 | 부작용 |
|---|---|---|---|
| ① 멱등 키 | 키 존재(처리 중) | 409 REQUEST_IN_PROGRESS | 없음 |
| ① 멱등 키 | 키 존재(완료) | 200 기존 결과 | 없음 |
| ② 락 | 대기 초과 | 503 LOCK_ACQUISITION_FAILED | 없음 |
| ③ 재고 | 갱신 행 < 날짜 수 | 409 INSUFFICIENT_INVENTORY | 롤백 |
| ④ INSERT | 멱등 키 UNIQUE 충돌 | 200 기존 예약 조회 반환 | 롤백 |

## D-2. 도메인 모델

```mermaid
flowchart LR
    R[Reservation] --- SP([StayPeriod VO])
    R -.->|roomTypeId| RT[RoomType 참조]
    I[RoomDailyInventory] -.->|roomTypeId| RT
```

| 애그리거트 | 불변식 | 구성 요소 |
|---|---|---|
| Reservation | 전이 표 밖 상태 변경 금지 | StayPeriod(VO), status, ReservationStateMachine |
| RoomDailyInventory | remaining ≥ 0 | (roomTypeId, stayDate) 단위 수량 |

## D-3. ERD

```mermaid
erDiagram
    hotel ||--o{ room_type : ""
    room_type ||--o{ room_daily_inventory : ""
    room_type ||--o{ reservation : "ID"
```

| 테이블 | 주요 컬럼 | 제약·인덱스 |
|---|---|---|
| room_daily_inventory | room_type_id, stay_date, remaining | UK(type,date), CHECK remaining≥0 |
| reservation | user_id, idempotency_key, status, 기간 | UK(user,idem_key), IX(status,created_at) |
| room_type / hotel | 시드 데이터 | FK hotel_id |
