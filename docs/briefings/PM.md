# PM 세션 · 인수인계서

이 문서는 PM 역할을 맡는 세션의 시작점이다. 이 저장소의 문서 밖에 있는 맥락은 전제하지 않는다.

## 네 역할

- 하네스·규칙 문서(`CLAUDE.md`, `docs/architecture/**`, 템플릿, 스킬)의 유지보수와 개정
- 전체 범위 문서(`docs/spec/00-problem-and-scope.md`) 소유. feature 분할·일정 관리
- feature 세션 착수 브리핑(`docs/briefings/<feature>.md`) 작성
- 세션 간 조율: 공유 파일 변경 중재, main 병합 순서 결정
- feature 세션의 질문 응대. **답은 대화로 끝내지 않고 반드시 해당 문서에 반영한다**
- 승인 게이트에서 관리자 보조 (보고서 사전 검토, 터미널 요약)

**하지 않는 것:** 구현 코드, 테스트, feature별 스펙 작성. feature 세션이 자기 스펙부터 dev-cycle까지 전 과정을 담당한다 (CLAUDE.md 세션 역할 절).

## 프로젝트 한 줄 요약

숙박 예약 시스템 채용 과제. 마감 **2026-08-17 23:59:59 (KST)**. 본질은 동시성 제어·멱등성·상태 전이를 수치로 증명하는 것. 기능 폭보다 이 셋의 깊이가 항상 우선한다.

## 현재 상태 (2026-08-15 기준)

| 항목 | 상태 |
|---|---|
| 하네스 (규칙 5종, 스킬 6종, 리뷰어 에이전트 3종, 템플릿) | 완료, main 병합됨 |
| 빌드·인프라 (Boot 4.0.7, Gradle wrapper, docker-compose, Testcontainers 스모크 2건) | 완료, 통과 확인됨 |
| `docs/spec/00-problem-and-scope.md` | **승인됨** (결정 검토란 D1~D6 전항 동의) |
| F01 스펙 | 초안이 있었으나 **2026-08-15 폐기** (git 이력에만 존재). F01 세션이 새로 쓴다 |
| F01 스펙 검토 기록 (`docs/reviews/F01-spec-review-업계정합성.md`) | 유효. 반영 후보 7개는 **관리자 미결정** — F01 스펙의 결정 검토란에서 결정된다 |
| F02·F03·F04 브리핑 | **아직 없음. PM의 다음 산출물** (F01 병합 즈음 작성) |
| 제출 문서 (`docs/submission/`) | 구성 계획만 있음 (README) |

## 남은 일정 (00 문서와 동기화 유지할 것)

| 날짜 | 목표 |
|---|---|
| 8/15 | F01 세션 착수: 스펙 → 승인 → dev-cycle |
| 8/16 | F01 승인·병합. F02·F03 병렬 + F04 부하테스트 착수 |
| 8/17 | 부하테스트 리포트, 제출 문서, 최종 점검 |

지연 시 절단 순서(승인된 결정): F03 캐시 → UC-6 체크인아웃 → F02 프로모션. F01과 부하테스트는 자르지 않는다.

## 즉시 다음 액션

1. 관리자가 새 세션을 열어 F01을 시작시키면(`docs/briefings/F01.md`), 그 세션의 스펙 승인 요청을 중계한다
2. F01 진행 중 질문 응대. 답변은 문서 반영까지가 한 세트
3. F01 병합 시점에 F02·F03·F04 브리핑을 작성한다 (형식은 F01.md를 따른다. 소유 범위는 00 문서 feature 분할 표가 진실)
4. 병합 순서 관리: feature 브랜치 → PR → 관리자 승인 후 병합. main 직접 푸시 금지

## 운영 절차 (관리자와 합의된 방식)

**승인 게이트.** 검토 문서는 `open -a Bear <파일>`로 열고 SendUserFile로도 보내며 GitHub 링크를 함께 준다. 터미널에는 3~5줄 요약. 승인 문서에는 결정 검토란(D 항목: 결정·이유·트레이드오프·대안·확인 질문)이 반드시 있고, **동의는 문서 전체가 아니라 D 항목 단위로 받는다.** 관리자는 Bear 노트에 `-> ` 접두어로 코멘트를 달기도 한다. Bear 노트는 파일로 돌아오지 않으므로 Bear DB에서 읽는다:

```bash
sqlite3 -readonly "$HOME/Library/Group Containers/9K33E3U3T4.net.shinyfrog.bear/Application Data/database.sqlite" \
  "SELECT ZTEXT FROM ZSFNOTE WHERE ZTITLE LIKE '%<문서 제목>%' ORDER BY ZMODIFICATIONDATE DESC LIMIT 1"
```

**관리자 협업 스타일.** 새 기술·개념이 나오면 결정 전에 쉬운 한국어로 설명부터 한다 (번역투·영어투 금지, CLAUDE.md 언어 절). 결정은 관리자가 내린다. 트레이드오프 없는 결정 제안은 반려된다. 결정이 나면 ADR(`decision-log` 스킬), 새 개념은 학습 노트 제목 쌓기(`learning-note` 스킬).

**git.** 계정은 Diocto (repo-local user.name/email 설정됨). 커밋 메시지 한국어. worktree에서 작업하고 PR로 병합한다. 관리자의 로컬 main checkout은 뒤처져 있을 수 있으니 병합 후 `git pull`을 안내한다.

## 주소

- 저장소: https://github.com/Diocto/pms (private, 기본 브랜치 main)
- 착수 브리핑: `docs/briefings/` (F01.md, 이 문서)
- 승인된 범위: `docs/spec/00-problem-and-scope.md`
- 의사결정 이력: `docs/decisions/INDEX.md` (ADR-0001~0006)
- 폐기된 F01 초안: git 이력 `spec-problem-and-scope` 브랜치 (복사 금지, 참고만)

## 조심할 것

- F01 세션이 `inventory.query.**`를 만들면 F03 소유권 침범이다. 브리핑에 명시돼 있지만 리뷰에서 한 번 더 본다
- 검토 반영 후보 7개를 F01 세션이 빠뜨리고 스펙을 쓰면 승인 전에 돌려보낸다 (브리핑에 지시돼 있음)
- 문서 간 불일치를 발견하면 즉시 고친다. "구현 세션은 문서만 보고 작업한다"가 이 체계의 전제라서, 문서 불일치가 곧 장애다
