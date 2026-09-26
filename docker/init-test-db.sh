#!/bin/sh
# Создаёт БД для тестов рядом с основной: <POSTGRES_DB>_test.
set -e
createdb -U "$POSTGRES_USER" "${POSTGRES_DB}_test"
