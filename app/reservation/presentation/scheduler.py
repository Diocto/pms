"""만료 스케줄러 (스펙 2.5절) — 유스케이스를 부르기만 한다.

라우터와 같은 성격의 들어오는 경계다 — 계기가 HTTP냐 시각이냐만 다르다.
비즈니스 판단은 전부 유스케이스와 도메인에 있다 (T73).

스케줄러가 멈춰도 데이터는 안전하다 — 확정 유스케이스가 `now >= expiresAt`을
스스로 검사한다. **스케줄러는 재고 회수 담당이지 정합성 담당이 아니다.**
겹쳐 돌아도 조건부 UPDATE 때문에 재고가 두 번 복원되지 않는다.
"""

import logging
import threading

logger = logging.getLogger(__name__)


class ExpireScheduler:
    def __init__(self, usecase_factory, interval_seconds: int) -> None:
        self._usecase_factory = usecase_factory
        self._interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="expire-scheduler", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        # Event.wait는 stop() 즉시 깨어난다 — time.sleep이면 종료가 주기만큼 늦는다
        while not self._stop_event.wait(self._interval_seconds):
            try:
                self._usecase_factory().execute()
            except Exception:
                # 한 주기의 실패가 스케줄러를 죽이면 안 된다. 삼키지 않고 기록한다
                logger.exception("만료 스케줄러 주기 실패")
