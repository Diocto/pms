# 백엔드(FastAPI) 배포 이미지.
#
# Railway가 이 파일을 그대로 빌드한다. 로컬 개발은 여전히 docker-compose + venv이고,
# 이 이미지는 배포에만 쓴다 — 로컬 절차를 바꾸지 않는다.
#
# **마이그레이션을 이미지 안에 넣는다.** 스키마의 진실은 마이그레이션이라는 원칙
# (docs/architecture/coding-rules.md)이 배포에서도 같아야 한다. 기동 시 `alembic
# upgrade head`를 먼저 돌리고, 실패하면 앱을 띄우지 않는다 — 스키마가 어긋난 채
# 뜨는 것보다 안 뜨는 쪽이 안전하다.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 의존성 설치를 먼저 하면 앱 코드만 바뀌었을 때 이 층이 재사용된다.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY migrations ./migrations
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 루트로 돌리지 않는다. 이 이미지는 쓰기가 필요 없다.
RUN useradd --create-home --uid 10001 pms
USER pms

EXPOSE 8000

CMD ["/entrypoint.sh"]
