"""검색 캐시 설정과 루트 배선 (스펙 3절 "공유 파일에 추가하는 줄", T2).

설정 자체가 계약이다 — 캐시는 절단 1순위(00 D4)라 스위치로 껐다 켤 수
있어야 하고, 조작자가 셸에 치는 환경변수 이름이 그대로 계약 문자열이다.
"""

import pytest

from app.common.config import Settings
from app.containers import AppContainer


def _settings(**env: str) -> Settings:
    # .env 파일이 있으면 기본값 검증이 로컬 파일에 좌우되므로 끊는다
    return Settings(_env_file=None, **env)


def test_검색_캐시_기본값은_켜짐_10초() -> None:
    settings = _settings()
    assert settings.search_cache_enabled is True
    assert settings.search_cache_ttl_seconds == 10


def test_환경변수로_스위치가_뒤집힌다(monkeypatch: pytest.MonkeyPatch) -> None:
    # 키 문자열이 계약이다. 필드 이름이 아니라 이 문자열로 뒤집혀야 한다
    monkeypatch.setenv("PMS_SEARCH_CACHE_ENABLED", "false")
    monkeypatch.setenv("PMS_SEARCH_CACHE_TTL_SECONDS", "3")
    settings = _settings()
    assert settings.search_cache_enabled is False
    assert settings.search_cache_ttl_seconds == 3


def test_루트가_검색_컨텍스트를_배선한다() -> None:
    """루트 컨테이너가 inventory_query 컨테이너에 네 의존을 전부 넘긴다.

    설정을 두 곳에서 따로 읽지 않는다 — 검색 컨텍스트가 받는 settings가
    루트의 그 싱글턴이어야, 노출되는 값과 실제 쓰는 값이 같은 출처가 된다.
    """
    container = AppContainer()
    assert container.inventory_query.settings() is container.settings()
    assert container.inventory_query.clock() is container.clock()
    assert (
        container.inventory_query.transaction_manager()
        is container.transaction_manager()
    )
    assert container.inventory_query.redis_client() is container.redis_client()
