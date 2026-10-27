FROM python:3.12-slim-bookworm AS checker-download

ARG CHECKER_VERSION=build-3880
ARG CHECKER_SHA256=aa1c61e8781c73405529dc7f894176eda84c0e3f660d6a1968304fbd9588756d

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    archive="/tmp/proxy-scraper-checker-${CHECKER_VERSION}.zip"; \
    curl --fail --location --silent --show-error --retry 3 \
      "https://github.com/monosans/proxy-scraper-checker/releases/download/${CHECKER_VERSION}/proxy-scraper-checker-binary-x86_64-unknown-linux-gnu.zip" \
      --output "$archive"; \
    echo "${CHECKER_SHA256}  ${archive}" | sha256sum --check -; \
    python -c "import pathlib, zipfile; z=zipfile.ZipFile('$archive'); names=[n for n in z.namelist() if pathlib.PurePosixPath(n).name=='proxy-scraper-checker']; assert len(names)==1, names; p=pathlib.Path('/usr/local/bin/proxy-scraper-checker'); p.write_bytes(z.read(names[0])); p.chmod(0o755)"

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PROXY_SCRAPER_BINARY=/usr/local/bin/proxy-scraper-checker

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app \
    && mkdir -p /app/input /app/out /app/data \
    && chown -R app:app /app

COPY --from=checker-download /usr/local/bin/proxy-scraper-checker /usr/local/bin/proxy-scraper-checker
COPY --chown=app:app proxy_scout/ /app/proxy_scout/
COPY --chown=app:app config/ /app/config/
COPY --chown=app:app README.md LICENSE THIRD_PARTY_NOTICES.md /app/

USER app

CMD ["python", "-m", "proxy_scout"]
