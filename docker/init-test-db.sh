# Creates the test database next to the main one: <POSTGRES_DB>_test.
set -e
createdb -U "$POSTGRES_USER" "${POSTGRES_DB}_test"
