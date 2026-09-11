FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m playwright install --with-deps chromium \
    && apt-get update \
    && apt-get install -y --no-install-recommends tini xauth xvfb \
    && command -v xvfb-run \
    && command -v xauth \
    && command -v tini \
    && rm -rf /var/lib/apt/lists/*

COPY src/ src/
COPY data/ data/

ENTRYPOINT ["tini", "--", "xvfb-run", "-a"]
CMD ["python", "src/daily.py"]
