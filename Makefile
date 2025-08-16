
.PHONY: dev prod logs stop migrate

dev:
	docker compose --profile dev --env-file .env.dev up -d --build

prod:
	docker compose --profile prod --env-file .env.prod up -d --build

logs:
	docker compose logs -f

stop:
	docker compose down

migrate:
	docker compose run --rm api-prod python -c "from alembic.config import Config; from alembic import command; cfg=Config('migrations/alembic.ini'); command.upgrade(cfg, 'head')"
