# SIGNAL — production container.
# Used by Railway for both the web service and the cron / one-shot importer.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system dependencies needed by some Python wheels.
RUN apt-get update -y \
 && apt-get install -y --no-install-recommends build-essential curl \
 && rm -rf /var/lib/apt/lists/*

# Install Python deps first so this layer caches across rebuilds.
COPY requirements.txt pyproject.toml ./
RUN pip install --upgrade pip \
 && pip install -r requirements.txt

# Copy the rest of the app (excluding what's in .dockerignore) and install
# our own package in editable mode so `streamlit run src/signalwarn/app.py`
# can `from signalwarn.X import Y`.
COPY . .
RUN pip install -e .

EXPOSE 8080

# FastAPI via uvicorn. Railway routes traffic to this port.
#
# --workers 1: the /admin background-task pattern uses a module-level dict
# for status (web/app.py::_admin_status). Multiple workers don't share that
# memory, so the polling user could land on a worker that doesn't know about
# the running job → ghost-job UI bugs. SIGNAL is a single-user internal tool;
# we don't need horizontal scaling. Move state to Postgres if/when this needs
# to scale past one worker.
CMD uvicorn web.app:app --host 0.0.0.0 --port 8080 --workers 1 --proxy-headers --forwarded-allow-ips="*"
