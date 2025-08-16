docker compose --profile dev --env-file .env up -d --build
docker compose --profile dev --env-file .env.dev logs -f api