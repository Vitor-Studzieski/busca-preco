FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS build
WORKDIR /build
RUN python -m venv /opt/venv
COPY requirements.txt .
RUN /opt/venv/bin/pip install --no-cache-dir --require-hashes -r requirements.txt

FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
ENV PATH="/opt/venv/bin:${PATH}" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /portal
RUN useradd --no-create-home --uid 10001 app && mkdir -p /portal/staticfiles && chown app /portal/staticfiles
COPY --from=build /opt/venv /opt/venv
COPY --chown=app:app manage.py ./manage.py
COPY --chown=app:app project ./project
COPY --chown=app:app pricing ./pricing
USER app
RUN python manage.py collectstatic --noinput
CMD ["sh", "-c", "exec gunicorn project.wsgi:application --bind 0.0.0.0:8000 --workers 2 --access-logfile - --access-logformat '%(m)s %(U)s %(s)s %(D)s'"]
