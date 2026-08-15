"""세션과 트랜잭션의 수명 관리 (D28).

**세션 하나 = 트랜잭션 하나.** 한 유스케이스에서 커밋이 두 번 일어나면 그 사이에
남이 끼어든다 — 재고를 깎아 커밋한 뒤 예약 INSERT가 실패하면 재고만 줄어든
상태가 남는다. 세션을 여는 진입점을 아래 둘로 좁히면 그 실수가 구조적으로
불가능해진다.

유스케이스는 `sessionmaker`를 직접 부르지 않고 이 둘만 쓴다.

    with self._tx.write() as session:   # 쓰기 — 나오면 커밋, 예외면 롤백
    with self._tx.read() as session:    # 조회 — 끝에 rollback()

`with`를 쓰는 이유는 경계가 코드에 보이기 때문이다. 들여쓰기가 곧 트랜잭션의
범위다. `@transactional` 데코레이터를 쓰지 않는 이유도 같다 — 락이 트랜잭션
밖에 있다는 사실이 데코레이터 뒤로 숨는다.

락과의 순서는 `락 획득 → write() → (커밋) → 락 해제`다. 락 획득·해제와
Redis 접근은 전부 이 블록 밖에서 한다.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session, sessionmaker


class TransactionManager:
    """세션과 트랜잭션의 수명을 함께 관리한다. 유스케이스가 주입받는다."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @contextmanager
    def write(self) -> Iterator[Session]:
        """쓰기 경로. 정상 종료하면 커밋, 예외가 나면 롤백."""
        with self._session_factory() as session:
            with session.begin():
                yield session
            # begin() 블록을 나오며 커밋 · 예외면 롤백
        # 세션이 닫히며 커넥션 반납

    @contextmanager
    def read(self) -> Iterator[Session]:
        """조회 경로. 커밋하지 않는다.

        `rollback()`은 되돌릴 것이 있어서가 아니다. SQLAlchemy가 첫 SELECT에서
        자동으로 연 트랜잭션을 닫지 않으면 커넥션이 유휴 트랜잭션 상태로
        반납되고, MySQL에서 이 상태가 쌓이면 오래된 스냅샷이 유지되며 정리가
        밀린다. 명시적으로 닫는다.
        """
        with self._session_factory() as session:
            yield session
            session.rollback()
