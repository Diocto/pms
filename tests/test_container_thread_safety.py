"""컨테이너 싱글턴의 스레드 안전 (T90, D34).

F04 부하테스트 실측: 앱 재기동 직후 첫 요청이 수백 동시면 스레드마다 엔진이
만들어져 MySQL 커넥션 한도(151)를 넘겼다 — 워커 하나가 커넥션 44개.
`providers.Singleton`은 "있나 보고 → 없으면 만든다" 사이에 잠금이 없어서
냉시동 창에 스레드 수만큼 엔진이 생긴다. 커넥션을 쥐는 부품은 전부
`ThreadSafeSingleton`이어야 한다.
"""

import threading
import time

from dependency_injector import providers

import app.containers as containers_module
from app.containers import AppContainer
from app.reservation.container import ReservationContainer

_THREADS = 16


def test_T90_동시_첫_접근에도_엔진은_하나만_만들어진다(monkeypatch):
    # 실제 create_engine 대신 느린 가짜를 꽂아 냉시동 창을 재현한다.
    # sleep이 없으면 첫 스레드가 창이 열리기 전에 만들기를 끝내 경합이 안 보인다
    created = []

    def slow_create_engine(url, **kwargs):
        marker = object()
        created.append(marker)
        time.sleep(0.05)
        return marker

    monkeypatch.setattr(containers_module, "create_engine", slow_create_engine)

    container = AppContainer()
    barrier = threading.Barrier(_THREADS)
    results: list[object] = [None] * _THREADS

    def first_db_access(index: int) -> None:
        barrier.wait()  # 전원이 동시에 첫 접근을 하게 줄 세운다
        results[index] = container.engine()

    threads = [
        threading.Thread(target=first_db_access, args=(i,)) for i in range(_THREADS)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(created) == 1, f"엔진이 {len(created)}개 만들어졌다 — 냉시동 폭주"
    assert len({id(result) for result in results}) == 1


def test_T90b_컨테이너의_싱글턴은_전부_스레드_안전_판이다():
    # 개별 재발을 막는 구조 검사 — 잠금 없는 Singleton이 하나라도 남으면 빨간불.
    # ThreadSafeSingleton은 별도 클래스라 type 비교로 가려진다
    unsafe = [
        name
        for cls in (AppContainer, ReservationContainer)
        for name, provider in cls.providers.items()
        if type(provider) is providers.Singleton
    ]
    assert unsafe == [], f"잠금 없는 Singleton: {unsafe}"
