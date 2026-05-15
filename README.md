# Resilience Reseau

Application Flask dediee a la partie Resilience uniquement.

- Web local: `http://localhost:8001/resilience`
- Base locale: `db_resilience` PostGIS, port hote `5433`
- Schema auth/data: `resilience`
- Login template: `login_resilience.html`

## Lancement local

```bash
docker compose up -d --build
```

## Verification

```bash
curl http://localhost:8001/healthz
docker compose ps
```

## Creation d'un utilisateur

```bash
docker compose exec web_resilience python create_user.py admin_resilience motdepasse123
```

## Variables d'environnement

Copier `.env.docker.example` vers `.env` puis ajuster:

- `DB_USERNAME_RESILIENCE`
- `DB_PASSWORD_RESILIENCE`
- `DB_NAME_RESILIENCE`
- `SECRET_KEY`

## Render Blueprint

Le fichier `render.yaml` permet de creer:

- un service web Docker `sipperesiste-resilience`
- une base Postgres `sipperesiste-resilience-db`
- les variables d'environnement necessaires a l'application

Le script `scripts/init_render_db.py` active PostGIS et cree le schema `resilience` pendant le deploiement.

## Render manuel

Creer un service web Docker qui lance:

```bash
gunicorn -w 2 -b 0.0.0.0:$PORT --timeout 0 --graceful-timeout 300 app_resilience:app
```

Variables principales:

```env
SECRET_KEY=une_valeur_longue_et_secrete
DB_HOST=host_interne_render_postgres
DB_PORT=5432
DB_USERNAME=user_render
DB_PASSWORD=password_render
DB_NAME=database_render
DB_SEARCH_PATH=resilience,public
AUTH_SCHEMA=resilience
LOGIN_TEMPLATE=login_resilience.html
RESET_LINK_VIA_UI=0
APP_BASE_URL=https://ton-service.onrender.com
```

Dans la base Render, activer PostGIS et le schema:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA IF NOT EXISTS resilience;
```
