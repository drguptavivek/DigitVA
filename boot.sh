#!/bin/bash
# Retry loop for DB to be ready
echo "Waiting for database to be ready..."
until uv run flask db upgrade; do
  echo "DB not ready, retrying in 5 secs..."
  sleep 5
done

exec uv run gunicorn -w 1 -b :5000 --access-logfile - --error-logfile - run:app
