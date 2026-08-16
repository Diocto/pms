# 숙박 예약 사이트 첫 진입(랜딩) 페이지 조사

- 조사일: 2026-08-16
- 조사 방법: 각 사이트 첫 화면 WebFetch 직접 확인 시도 + 2차 자료(UX/CRO 분석 글, 규제 기관 발표) 보완
- 접속 결과 요약:
  - **직접 확인 성공**: 야놀자(NOL), 트립닷컴 한국판
  - **부분 확인**: 여기어때(서버는 응답했으나 화면이 스크립트로 그려져 본문을 못 읽음. 메타 정보만 확인)
  - **직접 확인 실패(봇 차단·빈 응답)**: Booking.com(403·빈 응답), Airbnb(403), Agoda(빈 응답), Expedia(429), Hotels.com(시간 초과) → 전부 2차 자료로 대체
- 원칙: 출처 없는 내용은 적지 않았다. 확인 못 한 칸은 "확인 못 함"으로 남겼다.

---

## 1. 사이트별 요약 표

| 사이트 | 첫 화면의 주인공 | 헤드라인 문구(실제 문구) | 끌어들이는 장치 톱3 | 확인 방식 / 출처 |
|---|---|---|---|---|
| **야놀자 (nol.yanolja.com)** | 카테고리 아이콘 줄 + 회전 프로모션 배너 | "국내여행 준비 NOLDAY" (직접 확인) | ① 기획전 배너(엔터 썸머 페스티벌 등) ② 최근 본 상품·위시리스트(개인화) ③ 랭킹 섹션("많이 찾는 즐길거리" 1~5위) | 직접 확인 (2026-08-16, https://nol.yanolja.com/) |
| **트립닷컴 한국판 (kr.trip.com)** | 카테고리 탭(숙소·항공·투어…) + 검색 | "지금, 나만의 숙소로 체크인하세요" (직접 확인) | ① 특가 배너("5성급 국내 호텔 5만원 찬스! 트립찬스") ② 신뢰 문구("보다 안전한 안심 결제 시스템", "24시간 연중무휴 고객센터") ③ 카테고리 탭으로 전 상품 노출 | 직접 확인 (2026-08-16, https://kr.trip.com/) |
| **여기어때 (yeogi.com)** | 확인 못 함(스크립트 렌더링). 메타 타이틀은 "여기어때 \| 해외여행, 호텔, 리조트, 캠핑, 펜션, 모텔, 풀빌라, 패키지여행, 항공권 예약" | 확인 못 함 | ① 숙소 타입(카테고리) 우선 탐색 구조 — "홈 화면에서 숙소 타입을 선택하면 지역 화면으로" ② 특가·쿠폰팩 ③ 도메인 통합 탐색(숙소·항공·레저 한 화면) | 부분 직접 확인 + 자사 기술블로그: https://techblog.gccompany.co.kr/복잡한-검색-홈-구조는-유연하게-화면은-부드럽게-개선하기-7e499720c5c4 (검색 결과 요약으로 확인), https://techblog.gccompany.co.kr/사소한-영역이라도-개선이-필요해요-2fe7653dcf1e |
| **Booking.com** | 대형 검색폼(목적지·날짜·인원)이 첫 화면 상단, 강한 노란색 검색 버튼 | 정확한 현재 문구 직접 확인 못 함. "find your next stay" 계열 문구가 2차 자료 다수에서 언급됨 | ① 긴급성·희소성 메시지("Only 1 room left", "Last booked 5 minutes ago") ② 사회적 증거("Booked 3 times in the last 24 hours", "X people are looking at this property") ③ 첫 화면 상단 할인·오퍼 배치와 통화 현지화 | 2차 자료: https://www.markhub24.com/post/booking-com-s-urgency-based-ux-design , https://ashokpoudel.medium.com/best-travel-ui-ux-2020-tips-from-booking-coms-home-page-dfb6a87b3529 , https://goodui.org/leaks/booking.com-ab-tested-single-vs-multiple-line-search-forms/ |
| **Airbnb** | 알약형(pill) 검색바 — Where / When / Who 세 칸 + 원형 검색 버튼, 아래는 숙소 카드 그리드 | 대형 헤드라인 없음(검색바와 카드가 곧 첫 화면) — 2차 자료 기준 | ① "Guest favorite" 배지(사회적 증거를 배지 하나로 압축) ② Homes/Experiences/Services 탭 ③ 카드에 평점·가격 즉시 노출 | 2차 자료: https://github.com/VoltAgent/awesome-design-md/blob/main/design-md/airbnb/DESIGN.md , https://intellihost.co/blog/the-impact-of-airbnb-s-guest-favorites-badge-on-listings-in-2025 , https://uxdesign.cc/key-takeaways-from-airbnbs-winter-redesign-c1de0efa7818 |
| **Agoda** | 호텔 검색 위젯이 기본으로 열려 있음(항공은 바텀시트) — 2차 자료 기준 | 확인 못 함 | ① Insider Deals — 로그인 회원에게만 보이는 할인가(최대 30%), 배지로 표시 ② VIP 등급제(가입 즉시 Bronze) + 최저가 보장 ③ 매일 갱신되는 Today's Deals·플래시세일 | 2차 자료: https://partnerhub.agoda.com/what-is-agoda-private-sale/ , https://www.rankandstyle.com/deals/agoda-promo-code , https://medium.com/@himanshu88634/ux-ui-case-study-improving-redesigning-the-agoda-travel-app-f0befd5ac7e1 |
| **Expedia** | 검색 탭 묶음(Stays, Flights, Packages, Things to do, Cruises, Deals…) | 확인 못 함(429로 접속 실패) | ① One Key 회원가 — 회원이면 10%↑, 등급 오르면 15~20%↑ 할인 ② 항공+호텔 묶음 할인("호텔을 항공에 붙이면 최대 30% 절약") ③ 과거 예약 기반 맞춤 오퍼(개인화) | 2차 자료: https://www.expedia.com/Hotels (검색 결과 스니펫), https://upgradedpoints.com/travel/expedia-one-key-rewards-program/ , https://www.prnewswire.com/news-releases/expedia-group-announces-one-key-a-groundbreaking-new-loyalty-program-that-rewards-every-traveler-301878422.html |

### 첫 진입 → 검색까지의 조작 횟수

- **트립닷컴(직접 확인)**: 카테고리 탭이 이미 열려 있어 목적지 입력 → 날짜 → 검색, 3~4회 조작.
- **야놀자(직접 확인)**: 검색창보다 카테고리 아이콘이 앞에 있음. 카테고리 탭 → (지역/검색) → 날짜 → 조회, 3~4회.
- **여기어때(2차 자료)**: 자사 기술블로그 기준 "숙소 타입 선택 → 지역 화면" 구조. 타입 → 지역 → 날짜 → 조회, 약 4회.
- **Booking/Airbnb/Agoda/Expedia(2차 자료 기준)**: 첫 화면 검색폼에서 목적지 → 날짜 → 인원 → 검색, 3~4회. Booking은 검색폼 줄 수(한 줄 vs 여러 줄)까지 A/B 테스트했다(https://goodui.org/leaks/booking.com-ab-tested-single-vs-multiple-line-search-forms/).
- 공통: **어느 곳도 검색까지 5회를 넘기지 않는다.** 첫 화면의 존재 이유가 "검색을 시키는 것"이라는 데는 전부 일치한다. 다른 점은 검색 앞에 무엇을 한 겹 끼우는가(국내 앱: 카테고리, 해외: 없음)이다.

---

## 2. 공통 패턴 — 끌어들이는 포인트

### ① 검색창이 주인공
- **건드리는 심리**: 목적이 있는 방문자의 관성. 생각할 거리를 줄이고 바로 행동시킨다.
- **사례**: Booking.com은 첫 화면 상단에 검색폼을 두고 노란 버튼·두꺼운 패딩으로 시선을 고정, 폼 구성 자체를 A/B 테스트했다. Airbnb는 헤드라인조차 없이 알약형 검색바(Where/When/Who)가 화면 정체성이다. Agoda는 호텔 검색 위젯을 기본으로 열어 둔다.
- **부작용**: 목적지를 아직 못 정한 방문자에게는 빈 벽이다. Booking은 이를 푸터의 방대한 목적지 링크로, Airbnb는 숙소 카드 그리드로 보완한다.
- 출처: https://goodui.org/leaks/booking.com-ab-tested-single-vs-multiple-line-search-forms/ , https://github.com/VoltAgent/awesome-design-md/blob/main/design-md/airbnb/DESIGN.md , https://baymard.com/blog/travel-site-ux-best-practices

### ② 급하게 만들기 (긴급성·희소성)
- **건드리는 심리**: 놓치는 것에 대한 두려움(손실 회피). 비교·숙고를 끊고 즉시 결제로 민다.
- **사례**: Booking.com — "Only 1 room left", "Last booked 5 minutes ago", "Limited-time deal". 트립닷컴 한국판 — "5성급 국내 호텔 5만원 찬스" 같은 기간 한정 배너(직접 확인). Agoda — 플래시세일, 매일 바뀌는 Today's Deals.
- **부작용(실제 규제 사례)**: 이 패턴은 숙박 업계에서 가장 많이 제재받았다.
  - EU 소비자보호협력(CPC) 당국 공동 조치로 **Booking.com(2019 합의)과 Expedia(2020 합의)는 "인위적 희소성 암시를 하지 않겠다"를 포함한 시정을 약속**했다. 객실 잔여 표시는 "해당 사이트 기준"임을 명확히 하는 것 등이 포함됐다. (https://www.acm.nl/en/publications/booking-and-expedia-inform-consumers-more-clearly-about-their-offers-following-action-european-consumer-authorities , https://commission.europa.eu/system/files/2020-12/factsheet-expedia_enforcement_action_1.pdf)
  - 영국 CMA는 2019년 호텔 예약 사이트들의 압박 판매·희소성 표시에 시정 조치를 했고, 2024년에는 기준가(할인 전 가격)·긴급성 표시에 대한 공식 지침을 냈다. (https://www.gordonsllp.com/dark-patterns-legal-and-regulatory-considerations/ , https://www.brownejacobson.com/insights/consumer-law-enforcement-hot-topics-harmful-online-choice-architecture-and-dark-patterns)
  - 헝가리 경쟁당국은 2020년 Booking.com에 카운트다운·압박 표시 등으로 약 25억 포린트 벌금을 부과했다. 네덜란드 소비자단체는 2025년 집단소송을 제기했다. (https://behavioralinsight.substack.com/p/dark-patterns-on-bookingcom-manipulation)

### ③ 남들이 좋다고 말하게 하기 (사회적 증거)
- **건드리는 심리**: 동조. "많이 골랐다면 안전한 선택"이라는 지름길 판단.
- **사례**: Airbnb "Guest favorite" 배지 — 평점·리뷰라는 복잡한 정보를 배지 하나로 압축해 첫 화면 카드에서 바로 보인다. Booking.com — "Booked 3 times in the last 24 hours", "X people are looking at this property". 야놀자 — "많이 찾는 즐길거리" 랭킹 1~5위 섹션(직접 확인).
- **부작용**: "지금 N명이 보는 중"류는 검증 불가능한 실시간 수치라 위 ②와 함께 규제 대상이 됐다. 반면 축적된 리뷰 수·평점·배지는 실데이터 기반이라 논란이 적다 — Airbnb가 실시간 압박 대신 배지를 택한 것이 이 구분의 좋은 예다.
- 출처: https://intellihost.co/blog/the-impact-of-airbnb-s-guest-favorites-badge-on-listings-in-2025 , https://www.markhub24.com/post/booking-com-s-urgency-based-ux-design

### ④ 할인 전 가격 보여주기 (가격 앵커)
- **건드리는 심리**: 닻내림. 먼저 본 큰 숫자가 기준이 되어 할인가가 싸 보인다.
- **사례**: Booking.com은 첫 화면 상단에 할인·오퍼를 배치한다("검색하고 필터하게 둘 수도 있었지만, 할인은 언제나 끌리는 것" — 2차 분석). Agoda의 Insider Deal 배지는 원가 대비 최대 30% 절감을 표기한다.
- **부작용**: 실제로 그 가격에 판 적 없는 "정가"를 취소선으로 긋는 것은 허위 기준가로, CMA가 2024년 지침으로 정면 겨냥한 영역이다. EU CPC 합의에도 "할인은 실제로 비교 가능한 가격 기준일 것"이 포함됐다.
- 출처: https://ashokpoudel.medium.com/best-travel-ui-ux-2020-tips-from-booking-coms-home-page-dfb6a87b3529 , https://www.acm.nl/en/publications/booking-and-expedia-inform-consumers-more-clearly-about-their-offers-following-action-european-consumer-authorities , https://www.brownejacobson.com/insights/consumer-law-enforcement-hot-topics-harmful-online-choice-architecture-and-dark-patterns

### ⑤ 회원에게만 주기 (로열티 잠금)
- **건드리는 심리**: 소속과 손해 회피. "로그인만 하면 더 싸다"는 즉시 보상 + 재방문 습관 형성.
- **사례**: Agoda Insider Deals(로그인해야 보이는 가격, 가입 즉시 VIP Bronze). Expedia One Key(회원가 10%↑, 등급별 15~20%↑, 항공+호텔 묶음 최대 30%). 트립닷컴·야놀자·여기어때 모두 쿠폰·기획전을 첫 화면 배너로 민다(트립닷컴·야놀자는 직접 확인).
- **부작용**: "회원 전용가"가 사실상 누구나 받는 가격이면 허위 우대가 된다. 또 가격 비교를 어렵게 만들어(로그인 장벽) 다크패턴 논의에서 "숨김 가격"으로 분류되기도 한다.
- 출처: https://partnerhub.agoda.com/what-is-agoda-private-sale/ , https://upgradedpoints.com/travel/expedia-one-key-rewards-program/

### ⑥ 내 흔적 되돌려주기 (개인화)
- **건드리는 심리**: 자이가르닉 효과(하다 만 일이 계속 떠오름). 지난번 보다 만 숙소를 다시 보여주면 이어서 하게 된다.
- **사례**: 야놀자는 상단 메뉴에 "최근 본 상품"과 위시리스트를 상시 노출한다(직접 확인). Expedia는 과거 예약 기반 맞춤 오퍼를 내세운다. Booking.com도 방문 이력에 따라 홈이 달라진다(2차 분석).
- **부작용**: 과한 추적은 프라이버시 반감을 부른다. 또 첫 방문자에게는 아무 효과가 없어 첫 화면의 주인공으로 쓰기는 어렵다.
- 출처: 야놀자 직접 확인, https://www.prnewswire.com/news-releases/expedia-group-announces-one-key-a-groundbreaking-new-loyalty-program-that-rewards-every-traveler-301878422.html , https://ashokpoudel.medium.com/best-travel-ui-ux-2020-tips-from-booking-coms-home-page-dfb6a87b3529

### ⑦ 불안 지우기 (신뢰 장치)
- **건드리는 심리**: 결제 직전의 망설임 제거. "취소해도 된다", "떼이지 않는다"가 확인되면 클릭 비용이 낮아진다.
- **사례**: 트립닷컴 한국판 첫 화면 — "보다 안전한 안심 결제 시스템", "24시간 연중무휴 고객센터"(직접 확인). Agoda — 최저가 보장. Booking.com — FAQ·고객지원 링크를 눈에 띄게 배치(2차 분석). 무료 취소 표시는 업계 표준이 됐다.
- **부작용**: "최저가 보장"은 실제 보상 절차가 까다로우면 오히려 신뢰를 깎는다. 지킬 수 있는 약속만 첫 화면에 올려야 한다.
- 출처: 트립닷컴 직접 확인, https://www.rankandstyle.com/deals/agoda-promo-code , https://ashokpoudel.medium.com/best-travel-ui-ux-2020-tips-from-booking-coms-home-page-dfb6a87b3529

### ⑧ 어디 갈지 대신 골라주기 (목적지 영감)
- **건드리는 심리**: 선택 마비 해소. 목적지를 못 정한 방문자에게 "여기 어때?"를 먼저 던진다.
- **사례**: 야놀자 홈 스크롤은 사실상 전부 이것이다 — "추천 숙소", "여름 풀빌라 펜션 모음", "호캉스 지역별 추천"(직접 확인). Airbnb는 첫 화면부터 숙소 카드 그리드. Booking.com은 "여행자가 어디로 갈지 정하지 못할 때"를 위해 목적지 링크를 대량 배치한다.
- **부작용**: 추천이 재고·수수료 사정으로 왜곡되면(광고를 추천처럼) 신뢰가 무너진다. EU 규제에서도 광고 결과와 자연 결과의 구분 표시가 요구됐다.
- 출처: 야놀자 직접 확인, https://ashokpoudel.medium.com/best-travel-ui-ux-2020-tips-from-booking-coms-home-page-dfb6a87b3529 , https://www.acm.nl/en/publications/bookingcom-commits-adjusting-its-website-following-action-european-consumer-authorities

---

## 3. 우리 사이트에 적용할 수 있는 것 / 없는 것

전제: 데모용 예약 시스템. 호텔 100곳 × 객실타입 3종, 실데이터는 검색·예약·리뷰(더미)·위시리스트. 일별 재고 테이블이 시스템의 심장. 로그인은 X-User-Id 헤더(진짜 인증 없음), 결제는 모의. **없는 기능을 있는 것처럼 보이는 장치는 금지.**

### 정직하게 구현 가능 (실데이터가 있다)

| 패턴 | 구현 방법 | 근거 데이터 |
|---|---|---|
| ① 검색창 주인공 | 첫 화면 중앙 대형 검색폼(목적지·날짜·인원) | 검색 기능 실존 |
| ②' 정직한 잔여 표시 | "오늘 2실 남음" — **일별 재고 행의 실제 잔여 수량**이므로 허위가 아님. 단, EU 합의 사례를 따라 "이 사이트 기준" 명시 | (객실타입, 날짜) 재고 행 |
| ③ 사회적 증거(축적형) | 평점·리뷰 수·"평점 4.5 이상" 배지(Airbnb Guest favorite 방식). 리뷰가 더미인 것은 데모 안내 문구로 밝힘 | 리뷰 테이블(더미지만 실제 저장·집계) |
| ⑥ 개인화 | "최근 본 숙소"(조회 이력 저장 시), "내 위시리스트" 재노출 | 위시리스트 실데이터 |
| ⑧ 목적지 영감 | 호텔 100곳을 지역·무드별 큐레이션 그리드로. 추천 기준(평점순 등)을 명시 | 호텔·리뷰 실데이터 |
| ⑦ 신뢰 장치(일부) | 취소 정책 표시 — 예약 상태머신에 취소 전이가 실존하므로 "무료 취소 가능" 표시는 정직함 | 예약 상태 전이 테이블 |

### 가짜라서 안 되는 것 (금지)

| 패턴 | 왜 안 되는가 |
|---|---|
| "지금 N명이 보는 중" | 동시 조회 추적 기능이 없다. 숫자를 지어내는 순간 Booking이 제재받은 바로 그 패턴이 된다 |
| "5분 전에 예약됐어요" | 예약 이벤트 자체는 실존하나, 데모 트래픽에서는 표시할 실사건이 거의 없어 결국 지어내게 된다. 비추천 |
| 카운트다운 타임세일·오늘의 특가 | 특가 기능(F02)은 폐기됐다. 없는 할인에 시계를 붙이면 이중 허위 |
| 취소선 정가(가격 앵커) | 정가-할인가 체계가 없다. 판 적 없는 가격에 취소선을 긋는 것은 CMA가 지침으로 겨냥한 허위 기준가 |
| 회원 등급가·회원 전용 쿠폰 | 진짜 인증이 없다(X-User-Id 헤더). "회원만"이라는 주장 자체가 성립 안 함 |
| 최저가 보장 | 비교할 외부 가격이 없다. 지킬 수 없는 약속 |

**요약하면: 우리는 "급하게 만들기" 대신 "정직한 잔여 재고"를 쓸 수 있는 드문 처지다.** 일별 재고가 실데이터이므로, 남들이 지어내다 벌금 문 숫자를 우리는 그대로 보여줄 수 있다. 이것을 첫 화면의 차별점으로 삼는 것을 권한다.

---

## 4. 첫 진입 페이지 구성 제안 (시안의 재료)

톤: 세리프 리조트 무드 — 큰 세리프 헤드라인, 여백, 절제된 사진.

### A안. 「검색이 주인공」 — Booking/Airbnb 정석형
- **주인공**: 화면 중앙의 대형 검색폼(목적지 → 체크인·아웃 → 인원, 3조작으로 검색 도달). 배경은 풀블리드 리조트 사진 1장 + 세리프 헤드라인.
- **스크롤 순서**: ① 검색폼+헤드라인 → ② 지역별 인기 호텔(평점순, 기준 명시) → ③ 평점 4.5+ 배지 숙소 카드(리뷰 수 표기) → ④ 신뢰 밴드(취소 정책·데모 안내) → 푸터(지역 링크 — Booking 푸터 전략).
- **헤드라인 카피 예시**:
  - "머무는 순간이 여행이 됩니다"
  - "백 곳의 호텔, 단 하나의 밤을 위해"

### B안. 「목적지 영감」 — 야놀자/Airbnb 그리드형
- **주인공**: 지역·무드별 큐레이션 카드 그리드(호텔 100곳을 "바다가 보이는", "도심 한가운데" 식으로 묶음). 검색은 상단 고정 슬림바로 항상 접근 가능.
- **스크롤 순서**: ① 슬림 검색바 + 카드 그리드 첫 줄 → ② "이번 주말 방이 남은 곳"(실재고 기반) → ③ 리뷰 하이라이트(실제 저장된 리뷰 인용) → ④ 위시리스트/최근 본 숙소(재방문자 전용 블록).
- **헤드라인 카피 예시**:
  - "어디로 갈지 몰라도 괜찮습니다"
  - "이번 주말, 바다와 도심 사이 어디쯤"

### C안. 「정직한 빈 방」 — 우리만 할 수 있는 차별형
- **주인공**: 검색폼 + 오늘 날짜 기준 **실시간 잔여 재고 카운트**("오늘 밤 예약 가능한 방 217실"). 시스템의 심장(일별 재고)을 그대로 첫 화면에 올린다. 급박함을 지어내는 대신 사실을 보여준다 — 규제 사례의 정반대 포지션.
- **스크롤 순서**: ① 검색폼 + 잔여 카운트 헤드라인 → ② "오늘 2실 남음" 배지가 붙은 마감 임박 숙소(실재고) → ③ 평점 상위 숙소 → ④ "숫자는 지어내지 않습니다" 신뢰 선언 블록(데모 성격 안내와 자연스럽게 결합).
- **헤드라인 카피 예시**:
  - "오늘 밤, 비어 있는 방이 당신을 기다립니다"
  - "남은 방의 숫자까지, 있는 그대로"
  - "천천히 고르셔도 됩니다"

**추천 우선순위**: C안 ≥ A안 > B안. C안은 조사에서 확인된 업계 최대 리스크(허위 긴급성)를 뒤집어 강점으로 만들고, 이 프로젝트의 기술적 핵심(일별 재고·동시성)을 첫 화면에서 그대로 증명한다. B안은 큐레이션 콘텐츠(사진·무드 분류) 제작 비용이 커서 데모 범위에는 무겁다.

---

## 부록: 주요 출처 목록

**직접 확인 (2026-08-16)**
- 야놀자 NOL: https://nol.yanolja.com/
- 트립닷컴 한국판: https://kr.trip.com/
- 여기어때(부분): https://www.yeogi.com/

**첫 화면·UX 분석**
- Booking.com 홈 분석: https://ashokpoudel.medium.com/best-travel-ui-ux-2020-tips-from-booking-coms-home-page-dfb6a87b3529
- Booking.com 검색폼 A/B 테스트: https://goodui.org/leaks/booking.com-ab-tested-single-vs-multiple-line-search-forms/
- 여행 사이트 UX 모범 사례: https://baymard.com/blog/travel-site-ux-best-practices
- Airbnb 디자인 시스템 문서: https://github.com/VoltAgent/awesome-design-md/blob/main/design-md/airbnb/DESIGN.md
- Airbnb Guest Favorite 배지 효과: https://intellihost.co/blog/the-impact-of-airbnb-s-guest-favorites-badge-on-listings-in-2025
- Airbnb 윈터 리디자인: https://uxdesign.cc/key-takeaways-from-airbnbs-winter-redesign-c1de0efa7818
- Agoda Private Sale/Insider Deals: https://partnerhub.agoda.com/what-is-agoda-private-sale/
- Agoda 앱 UX 케이스 스터디: https://medium.com/@himanshu88634/ux-ui-case-study-improving-redesigning-the-agoda-travel-app-f0befd5ac7e1
- Expedia One Key: https://upgradedpoints.com/travel/expedia-one-key-rewards-program/ , https://www.prnewswire.com/news-releases/expedia-group-announces-one-key-a-groundbreaking-new-loyalty-program-that-rewards-every-traveler-301878422.html
- 여기어때 검색 홈 구조(자사 기술블로그): https://techblog.gccompany.co.kr/복잡한-검색-홈-구조는-유연하게-화면은-부드럽게-개선하기-7e499720c5c4

**긴급성·다크패턴 규제**
- Booking.com 긴급성 UX 사례: https://www.markhub24.com/post/booking-com-s-urgency-based-ux-design
- EU CPC 조치(Booking·Expedia 시정 약속): https://www.acm.nl/en/publications/booking-and-expedia-inform-consumers-more-clearly-about-their-offers-following-action-european-consumer-authorities , https://www.acm.nl/en/publications/bookingcom-commits-adjusting-its-website-following-action-european-consumer-authorities , https://commission.europa.eu/system/files/2020-12/factsheet-expedia_enforcement_action_1.pdf
- 영국 CMA 조치·2024 지침: https://www.gordonsllp.com/dark-patterns-legal-and-regulatory-considerations/ , https://www.brownejacobson.com/insights/consumer-law-enforcement-hot-topics-harmful-online-choice-architecture-and-dark-patterns
- Booking.com 벌금·소송 정리: https://behavioralinsight.substack.com/p/dark-patterns-on-bookingcom-manipulation
