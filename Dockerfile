FROM python:3.13-slim AS build
WORKDIR /build
RUN python -m venv /opt/venv
COPY requirements.txt .
RUN /opt/venv/bin/pip install --no-cache-dir --require-hashes -r requirements.txt

FROM python:3.13-slim
ENV PATH="/opt/venv/bin:${PATH}" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /portal
RUN useradd --no-create-home --uid 10001 app && mkdir -p /portal/staticfiles && chown app /portal/staticfiles
COPY --from=build /opt/venv /opt/venv
COPY --chown=app:app manage.py ./manage.py
COPY --chown=app:app project ./project
COPY --chown=app:app pricing ./pricing
USER app
CMD ["sh", "-c", "python manage.py collectstatic --noinput && exec gunicorn project.wsgi:application --bind 0.0.0.0:8000 --workers 2 --access-logfile -"]
