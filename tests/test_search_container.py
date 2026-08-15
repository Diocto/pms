"""캐시 구현 선택과 값 노출이 같은 프로바이더를 본다 (TDD 13, D15, T6).

보장이 타입에서 조립 설정으로 내려왔으므로 테스트로 고정한다 — 값만 맞고
구현이 다른 상태("꺼졌다고 보고하는데 실제로는 도는")를 잡는 것이 목적이다.
"""

from contextlib import contextmanager
from datetime import date

import pytest
from dependency_injector import providers

from app.common.config import Settings
from app.containers import AppContainer
from app.inventory.query.application.commands import (
    SearchAvailableRoomsQuery,
    Source,
    StayRange,
)


@pytest.fixture()
def off_container(monkeypatch):
    monkeypatch.setenv("PMS_SEARCH_CACHE_ENABLED", "false")
    container = AppContainer()
    container.settings.override(providers.Object(Settings(_env_file=None)))
    yield container
    container.settings.reset_override()


def test_T13_끄면_NoOp_구현이_선택된다(off_container):
    cache = off_container.inventory_query.search_cache()
    assert type(cache).__name__ == "NoOpAvailabilityCacheAdapter"
    assert off_container.inventory_query.stale_tolerance_seconds() == 0


def test_T13_기여자의_보고가_선택된_실물과_일치한다(off_container):
    cache = off_container.inventory_query.search_cache()
    report = off_container.inventory_query.runtime_contributor().report()
    # 키는 조작자가 셸에 치는 환경변수 이름 그대로다 (설정 키 예외)
    assert report.load_test["PMS_SEARCH_CACHE_ENABLED"] is False
    assert report.load_test["PMS_SEARCH_CACHE_TTL_SECONDS"] == 10
    # 손으로 적은 문자열이 아니라 실제 주입된 객체의 이름이어야 한다
    assert report.implementations["searchCache"] == type(cache).__name__
    assert report.counters == {}  # 누적 카운터는 싣지 않는다 (D15)


class _FakeTransactionManager:
    @contextmanager
    def read(self):
        yield object()


class _FakeQueryAdapter:
    def search(self, session, query):
        return []

    def diagnose(self, session, query):
        from app.inventory.query.application.commands import AvailabilityDiagnosis

        return AvailabilityDiagnosis(
            room_type_count=1,
            fitting_room_type_count=1,
            sales_open_until=date(2026, 12, 31),
        )


def test_T13_끄면_항상_DB에서_읽는다(off_container):
    off_container.inventory_query.query_adapter.override(
        providers.Object(_FakeQueryAdapter())
    )
    off_container.inventory_query.transaction_manager.override(
        providers.Object(_FakeTransactionManager())
    )
    usecase = off_container.inventory_query.search_available_rooms()
    query = SearchAvailableRoomsQuery(
        hotel_id=1,
        stay=StayRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 4)),
        guest_count=2,
        room_count=1,
    )
    first = usecase.execute(query)
    second = usecase.execute(query)  # 두 번째도 캐시가 아니다
    assert (first.source, second.source) == (Source.DB, Source.DB)
    assert first.stale_tolerance_seconds == 0  # 끄면 낡음의 상한도 0이다


def test_켜면_Redis_구현이_선택되고_보고도_일치한다(monkeypatch):
    monkeypatch.setenv("PMS_SEARCH_CACHE_ENABLED", "true")
    monkeypatch.setenv("PMS_SEARCH_CACHE_TTL_SECONDS", "7")
    container = AppContainer()
    container.settings.override(providers.Object(Settings(_env_file=None)))
    try:
        cache = container.inventory_query.search_cache()
        assert type(cache).__name__ == "RedisAvailabilityCacheAdapter"
        assert container.inventory_query.stale_tolerance_seconds() == 7
        report = container.inventory_query.runtime_contributor().report()
        assert report.load_test["PMS_SEARCH_CACHE_ENABLED"] is True
        assert report.load_test["PMS_SEARCH_CACHE_TTL_SECONDS"] == 7
        assert report.implementations["searchCache"] == type(cache).__name__
    finally:
        container.settings.reset_override()
