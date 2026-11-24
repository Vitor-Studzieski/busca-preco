#!/usr/bin/env bash
set -euo pipefail
umask 077
: "${BACKUP_DIR:?Defina uma pasta de backup com acesso restrito}"
: "${AGE_RECIPIENT:?Defina a chave pública de backup}"
: "${PGDATABASE:?Defina a base a copiar}"
mkdir -p -- "$BACKUP_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
output="$BACKUP_DIR/pompeia-$stamp.dump.age"
partial="$(mktemp "$BACKUP_DIR/.pompeia-$stamp.XXXXXXXX")"
trap 'if [ -f "$partial" ]; then unlink "$partial"; fi' EXIT
pg_dump --format=custom --no-password | age --encrypt --recipient "$AGE_RECIPIENT" --output "$partial"
test -s "$partial"
ln -- "$partial" "$output"
printf 'Backup criptografado: %s\n' "$output"
