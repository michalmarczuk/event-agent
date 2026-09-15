FROM docker.io/tailscale/tailscale:stable AS tailscale

FROM python:3.13-slim

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
RUN python -m camoufox fetch \
    && python -m camoufox version

COPY src/ src/
COPY data/ data/
COPY scripts/ scripts/
RUN chmod 0755 scripts/run_hf.sh

ENTRYPOINT ["tini", "-g", "--"]
CMD ["xvfb-run", "-a", "python", "src/daily.py"]
