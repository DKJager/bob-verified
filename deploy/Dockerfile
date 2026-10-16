FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY bobverified ./bobverified

ENV PYTHONUNBUFFERED=1

RUN useradd --no-create-home --shell /bin/false appuser
USER appuser

EXPOSE 8080

# Mount the run directory (produced by a bobverified run) at /data/run.
# Use -v /path/to/run:/data/run:rw so that re-verify can write its log there.
VOLUME ["/data/run"]

CMD ["python", "-m", "bobverified.dashboard", "--run", "/data/run", "--host", "0.0.0.0", "--port", "8080"]
