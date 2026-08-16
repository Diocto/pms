"""`TransactionManager` — 세션과 트랜잭션의 수명 계약 (D28, 테스트 T27a~T27d).

세션 하나 = 트랜잭션 하나. 세션을 여는 진입점은 `write()`·`read()` 둘뿐이다.

이 중 T27c가 유일하게 조용한 실패를 잡는다. 조회 경로가 트랜잭션을 안 닫아도
조회 결과는 정상이라 보통 테스트는 전부 통과하고, 증상은 부하가 걸려
커넥션 풀이 마를 때 처음 나타난다. 그래서 결과가 아니라 **커넥션 상태를
직접 본다** — `information_schema.innodb_trx`에 그 커넥션의 트랜잭션이
남아 있는지 확인한다.
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.common.db import TransactionManager


@pytest.fixture(scope="module")
def engine(mysql_container, database_url):
    # T27c가 `information_schema.innodb_trx`를 읽는데, 앱 계정에는 그 권한
    # (PROCESS)이 없다. 검증 전용 권한이므로 테스트에서만 root로 부여한다.
    root_url = database_url.replace(
        f"//{mysql_container.username}:{mysql_container.password}@",
        f"//root:{mysql_container.root_password}@",
    )
    root_engine = create_engine(root_url)
    with root_engine.begin() as conn:
        conn.execute(
            text(f"GRANT PROCESS ON *.* TO '{mysql_container.username}'@'%'")
        )
    root_engine.dispose()

    engine = create_engine(database_url)
    # 도메인 테이블에 기대지 않는다. 이 계약은 스키마보다 아래층이라
    # 전용 검증 테이블을 하나 만들어 쓴다.
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS tx_probe ("
                "  id BIGINT AUTO_INCREMENT PRIMARY KEY,"
                "  note VARCHAR(100) NOT NULL"
                ")"
            )
        )
    yield engine
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS tx_probe"))
    engine.dispose()


@pytest.fixture()
def tx(engine):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM tx_probe"))
    return TransactionManager(sessionmaker(bind=engine))


def _count(engine, note: str) -> int:
    # 검증은 항상 새 커넥션으로 한다. 같은 세션으로 세면 커밋 여부가 안 보인다.
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM tx_probe WHERE note = :note"), {"note": note}
        ).scalar_one()


def test_T27a_write가_정상_종료하면_커밋된다(tx, engine):
    """트랜잭션 관리자 — write() 블록이 정상 종료하면 안의 INSERT가 커밋된다.
    커밋 여부는 별도의 새 커넥션으로 세어 실제 DB 상태로 판정한다."""
    with tx.write() as session:
        session.execute(text("INSERT INTO tx_probe (note) VALUES ('t27a')"))
    assert _count(engine, "t27a") == 1


def test_T27b_write_안에서_예외가_나면_전부_롤백된다(tx, engine):
    """트랜잭션 관리자 — write() 블록 안에서 예외가 나면 안의 INSERT가 전부
    되돌아간다. "함께 커밋하거나 함께 롤백한다" 계약의 롤백 절반이다."""
    with pytest.raises(RuntimeError):
        with tx.write() as session:
            session.execute(text("INSERT INTO tx_probe (note) VALUES ('t27b')"))
            raise RuntimeError("일부러")
    assert _count(engine, "t27b") == 0


def test_T27c_read는_커밋하지_않고_유휴_트랜잭션도_남기지_않는다(tx, engine):
    """트랜잭션 관리자 — read()는 커밋하지 않고, 커넥션을 유휴 트랜잭션 상태로
    반납하지도 않는다. 후자는 innodb_trx를 직접 조회해 판정한다 — rollback을
    빠뜨린 구현도 "커밋 안 됐다" 단언만으로는 통과하기 때문이다."""
    with tx.read() as session:
        session.execute(text("INSERT INTO tx_probe (note) VALUES ('t27c')"))
        # 이 커넥션의 스레드 id를 잡아둔다. 블록을 나간 뒤 이 id로
        # 열린 트랜잭션이 남아 있는지 본다.
        thread_id = session.execute(text("SELECT CONNECTION_ID()")).scalar_one()

    # 커밋되지 않았다
    assert _count(engine, "t27c") == 0

    # 그리고 커넥션이 유휴 트랜잭션 상태로 반납되지 않았다.
    # rollback을 빠뜨려도 위 단언은 통과할 수 있어서, 이쪽이 진짜 판정이다.
    with engine.connect() as conn:
        lingering = conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.innodb_trx"
                " WHERE trx_mysql_thread_id = :tid"
            ),
            {"tid": thread_id},
        ).scalar_one()
    assert lingering == 0, "조회 트랜잭션이 닫히지 않은 채 커넥션이 반납됐다"


def test_T27d_write_두_번_중_두_번째가_실패해도_첫_번째는_남는다(tx, engine):
    """"한 유스케이스에 write() 하나"가 규칙인 이유를 고정한다.

    두 번 열면 첫 번째는 이미 커밋되어 되돌릴 수 없다 — 그 사이에 남이
    끼어들 수 있는 상태가 된다. 이 테스트는 그 사실 자체를 기록한다.
    """
    with tx.write() as session:
        session.execute(text("INSERT INTO tx_probe (note) VALUES ('t27d-1')"))

    with pytest.raises(RuntimeError):
        with tx.write() as session:
            session.execute(text("INSERT INTO tx_probe (note) VALUES ('t27d-2')"))
            raise RuntimeError("일부러")

    assert _count(engine, "t27d-1") == 1  # 첫 번째는 되돌아가지 않는다
    assert _count(engine, "t27d-2") == 0
