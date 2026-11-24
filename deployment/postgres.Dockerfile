FROM postgres:17
COPY --chmod=0644 deployment/create-app-role.sh /docker-entrypoint-initdb.d/10-app-role.sh
