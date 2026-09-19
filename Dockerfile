FROM docker.io/tailscale/tailscale:stable AS tailscale

FROM python:3.13-slim AS runtime-base

WORKDIR /app

COPY --from=tailscale /usr/local/bin/tailscale /usr/local/bin/tailscale
COPY --from=tailscale /usr/local/bin/tailscaled /usr/local/bin/tailscaled

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m playwright install-deps firefox \
    && apt-get update \
    && apt-get install -y --no-install-recommends tini xauth xvfb \
    && command -v xvfb-run \
    && command -v xauth \
    && command -v tini \
    && command -v tailscale \
    && command -v tailscaled \
    && rm -rf /var/lib/apt/lists/*
RUN python -m camoufox set official/stable/152.0.4-beta.30 \
    && python -m camoufox fetch \
    && python -c 'from camoufox.pkgman import installed_verstr; version = installed_verstr(); print(f"Verified Camoufox browser: {version}")'

FROM runtime-base AS test-runtime

COPY requirements-test.txt .
RUN pip install --no-cache-dir -r requirements-test.txt

COPY src/ src/
COPY data/ data/
COPY scripts/ scripts/
COPY tests/ tests/
COPY pytest.ini .
RUN chmod 0755 scripts/run_hf.sh scripts/run_hf_smoke.sh

ENTRYPOINT ["tini", "-g", "--"]
CMD ["/app/scripts/run_hf_smoke.sh"]

FROM runtime-base AS production

COPY src/ src/
COPY data/ data/
COPY scripts/run_hf.sh scripts/run_hf.sh
RUN chmod 0755 scripts/run_hf.sh

ENTRYPOINT ["tini", "-g", "--"]
CMD ["xvfb-run", "-a", "python", "src/daily.py"]
