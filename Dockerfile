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

COPY \
    scripts/system_integration/run_hf_smoke.sh \
    scripts/system_integration/run_hf_smoke_qase.sh \
    scripts/system_integration/
COPY scripts/support/run_hf_smoke_runtime.sh scripts/support/
COPY tests/__init__.py tests/conftest.py tests/
COPY tests/system_integration/ tests/system_integration/
COPY tests/system/ tests/system/
COPY \
    tests/support/__init__.py \
    tests/support/fake_external_services.py \
    tests/support/system_scenarios.py \
    tests/support/
COPY pytest.ini qase.config.json ./
RUN chmod 0755 \
    scripts/system_integration/run_hf_smoke.sh \
    scripts/system_integration/run_hf_smoke_qase.sh \
    scripts/support/run_hf_smoke_runtime.sh

ENTRYPOINT ["tini", "-g", "--"]
CMD ["/app/scripts/system_integration/run_hf_smoke.sh"]

FROM runtime-base AS production

COPY src/ src/
COPY data/ data/
COPY scripts/__init__.py scripts/
COPY \
    scripts/system_integration/__init__.py \
    scripts/system_integration/run_hf_mosir_live_smoke.sh \
    scripts/system_integration/run_hf_mosir_live_smoke_qase.sh \
    scripts/system_integration/run_mosir_live_smoke.py \
    scripts/system_integration/qase_mosir_smoke_reporter.py \
    scripts/system_integration/
COPY scripts/runtime/run_hf_production.sh scripts/runtime/
RUN chmod 0755 \
    scripts/runtime/run_hf_production.sh \
    scripts/system_integration/run_hf_mosir_live_smoke.sh \
    scripts/system_integration/run_hf_mosir_live_smoke_qase.sh

ENTRYPOINT ["tini", "-g", "--"]
CMD ["xvfb-run", "-a", "python", "-m", "src.app.daily"]
