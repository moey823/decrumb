FROM python:3.13-slim-trixie@sha256:8d9d0b8bcf6506481eae4907c18f5e3e7902e629f5f6d684f9e7c32e85e3ddf0
ARG SOURCE_REVISION=development
ARG RELEASE_VERSION=development
LABEL org.opencontainers.image.title="Decrumb" \
      org.opencontainers.image.description="Private Signal link cleaner with a browser dashboard" \
      org.opencontainers.image.source="https://github.com/moey823/decrumb" \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.version=$RELEASE_VERSION \
      org.opencontainers.image.revision=$SOURCE_REVISION
RUN apt-get update && apt-get install -y --no-install-recommends qrencode libstdc++6 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir /data && chown 1000:1000 /data
WORKDIR /app
COPY decrumb.py runtime_platform.py diagnostics.py release.json notes.py phone_commands.py portable_cleaner.py web_server.py container_dependency.py LICENSE ./
COPY rules/defaults.json ./rules/defaults.json
COPY container/dependencies.json ./container/dependencies.json
COPY linux/dependencies.json ./linux/dependencies.json
COPY web/ ./web/
COPY docs/PROVENANCE.md docs/THIRD-PARTY.md ./docs/
RUN chmod 0555 /app/portable_cleaner.py
ENV PYTHONDONTWRITEBYTECODE=1 HOME=/data
USER 1000:1000
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).close()"]
ENTRYPOINT ["python3", "-B", "/app/web_server.py"]
