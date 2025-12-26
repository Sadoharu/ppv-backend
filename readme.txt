docker compose --profile dev --env-file .env up -d --build
docker compose --profile dev --env-file .env logs -f api


docker compose exec api sh
cd migrations
alembic revision -m "Add GC indexes"
alembic upgrade head