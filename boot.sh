#!/bin/bash
# Retry loop for DB to be ready
echo "Waiting for database to be ready..."
until flask db upgrade; do
  echo "DB not ready, retrying in 5 secs..."
  sleep 5
done

exec gunicorn -w 1 -b :5000 --access-logfile - --error-logfile - run:app