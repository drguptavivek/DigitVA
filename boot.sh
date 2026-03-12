#!/bin/bash
# Wait for DB and run migrations
echo "Waiting for database to be ready..."
until uv run flask db upgrade; do
  echo "DB not ready, retrying in 5 secs..."
  sleep 5
done

exec uv run gunicorn -w 1 -b :5000 --access-logfile - --error-logfile - run:app
