"""앱 전역 설정.

**설정은 이 파일 한 곳에서만 읽는다.** 같은 값을 두 곳에서 따로 선언하면
"꺼졌다고 보고하는데 실제로는 도는" 상태가 만들어진다. 부하테스트가 실행 전에
스위치 값을 확인하는데, 그 값의 출처가 실제로 쓰는 객체와 다르면 확인이 아니다.

**필드 이름이 아니라 `validation_alias`의 환경변수 이름이 계약이다.**
조작자가 셸에 치는 이름과 부하테스트 리포트에 적히는 이름이 같아야 한다.
번역 계층이 하나 끼면 리포트를 보고 실험을 재현하려는 사람이 그 문자열을
그대로 붙여넣을 수 없다. 편의가 아니라 재현성 문제다.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- 인프라 접속 ---
    database_url: str = Field(
        default="mysql+pymysql://pms:pms@127.0.0.1:3306/pms",
        validation_alias="PMS_DATABASE_URL",
    )
    redis_url: str = Field(
        default="redis://127.0.0.1:6379/0",
        validation_alias="PMS_REDIS_URL",
    )

    # --- 1차 방어선: 분산락 ---
    # 이 스위치를 끄고 같은 동시성 시나리오를 다시 돌려서, 2차 방어선(조건부 UPDATE)
    # 만으로도 불변식이 지켜지는지 증명한다. 끌 수 없는 층은 살아 있는지 확인할
    # 방법이 없다.
    lock_enabled: bool = Field(default=True, validation_alias="PMS_LOCK_ENABLED")
    lock_wait_millis: int = Field(default=200, validation_alias="PMS_LOCK_WAIT_MILLIS")
    lock_ttl_seconds: int = Field(default=3, validation_alias="PMS_LOCK_TTL_SECONDS")

    # --- 예약 ---
    reservation_hold_minutes: int = Field(
        default=10, validation_alias="PMS_RESERVATION_HOLD_MINUTES"
    )
    reservation_expire_scan_seconds: int = Field(
        default=30, validation_alias="PMS_RESERVATION_EXPIRE_SCAN_SECONDS"
    )

    # --- 결제 시뮬레이션 ---
    # 실제 PG가 없으므로 실패율을 주입해 실패 경로를 재현한다.
    payment_decline_rate: float = Field(
        default=0.0, validation_alias="PMS_PAYMENT_DECLINE_RATE"
    )

    # --- 검색 캐시 (검색) ---
    # 절단 1순위(00 D4). 끈 채로도 전체가 돌아야 하므로 이 스위치가 계약이다.
    search_cache_enabled: bool = Field(
        default=True, validation_alias="PMS_SEARCH_CACHE_ENABLED"
    )
    search_cache_ttl_seconds: int = Field(
        default=10, validation_alias="PMS_SEARCH_CACHE_TTL_SECONDS"
    )
