FROM python:3.12-slim@sha256:5b8b1421ccb6a525860a77863c049eab5847076cda34e030c75a80c58faf3f3c

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -f /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip install --no-cache-dir --disable-pip-version-check --requirement requirements.txt \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app
COPY --chown=app:app app ./app
USER app
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "app:create_app()"]
