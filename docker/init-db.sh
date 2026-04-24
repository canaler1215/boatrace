#!/bin/bash
# Drizzle migration ファイルを番号順に適用する
set -e

MIGRATION_DIR="/docker-entrypoint-initdb.d/migrations"

for sql in $(ls "$MIGRATION_DIR"/*.sql | sort); do
    echo "Applying migration: $sql"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" < "$sql"
done

echo "All migrations applied."
