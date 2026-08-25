# Resilience Reseau

Application Flask dediee a la partie Resilience uniquement.

- Web local: `http://localhost:8001/resilience`
- Base locale: `db_resilience` PostGIS, port hote `5433`
- Schema auth/data: `resilience`
- Login template: `login_resilience.html`
- Imports applicatifs: GPKG uniquement. L'import Shapefile est desactive pour les couches alea et les couches infra temporaires.

## Lancement local

Copier l'exemple d'environnement puis remplacer les secrets:

```bash
cp .env.docker.example .env
```

Variables obligatoires ou principales:

- `DB_USERNAME_RESILIENCE`: utilisateur PostgreSQL existant, `app` par defaut.
- `DB_PASSWORD_RESILIENCE`: obligatoire. Ne pas utiliser `app`; mettre un secret robuste.
- `DB_NAME_RESILIENCE`: base PostgreSQL, `telecom_resilience_db` par defaut.
- `SECRET_KEY`: secret Flask long et aleatoire.
- `RESET_LINK_VIA_UI`: `0` en production.

Demarrer sans supprimer le volume PostgreSQL:

```bash
docker compose up -d --build
```

## Verification

```bash
docker compose ps
curl http://localhost:8001/healthz
```

## Compte administrateur initial

Le compte admin doit etre cree avec le role administrateur:

```bash
docker compose exec web_resilience python create_user.py admin_resilience "<MOT_DE_PASSE_ADMIN_ROBUSTE>" --admin
```

Si le compte existe deja sans droit admin, la meme commande avec `--admin` le promeut administrateur sans changer son mot de passe.

Les autres comptes peuvent ensuite etre crees et geres depuis l'onglet `Admin. & Acces` par un administrateur connecte.

## Deploiement serveur HTTPS avec PostgreSQL existant

Ne jamais commiter `.env`, `.env.docker`, un vrai mot de passe ou un dump de production.

1. Recuperer la branche de deploiement:

```bash
git fetch origin
git checkout romain-test-nouvelle-version
git pull --ff-only origin romain-test-nouvelle-version
```

2. Mettre a jour `.env` sur le serveur avec un secret robuste:

```env
DB_USERNAME_RESILIENCE=app
DB_PASSWORD_RESILIENCE=<NOUVEAU_SECRET_POSTGRESQL_ROBUSTE>
DB_NAME_RESILIENCE=telecom_resilience_db
RESET_LINK_VIA_UI=0
```

3. Si la base existe deja, appliquer le nouveau mot de passe au role PostgreSQL. Modifier `POSTGRES_PASSWORD` dans `.env` ne change pas le mot de passe du role deja initialise:

```bash
docker compose up -d db_resilience
docker compose exec -T db_resilience sh -lc 'psql -U app -d "$POSTGRES_DB" -v pw="$POSTGRES_PASSWORD" -c "ALTER ROLE app WITH PASSWORD :'\''pw'\'';"'
```

4. Reconstruire et relancer l'application Flask:

```bash
docker compose up -d --build web_resilience
```

5. Verifier:

```bash
docker compose ps
curl https://<DOMAINE_HTTPS>/healthz
```

## Imports de donnees

L'application accepte uniquement des fichiers `.gpkg` pour:

- les couches alea partagees;
- la couche infra temporaire utilisee dans une analyse reseau.

Les composants Shapefile (`.shp`, `.shx`, `.dbf`, `.prj`, `.cpg`, etc.) ne sont plus acceptes a l'import.

## Render Blueprint

Le fichier `render.yaml` permet de creer:

- un service web Docker `sipperesiste-resilience`
- une base Postgres `sipperesiste-resilience-db`
- les variables d'environnement necessaires a l'application

L'application active PostGIS et cree le schema `resilience` automatiquement au premier acces.

## Render manuel

Creer un service web Docker qui lance:

```bash
gunicorn -w 2 -b 0.0.0.0:$PORT --timeout 0 --graceful-timeout 300 app_resilience:app
```

Variables principales:

```env
SECRET_KEY=<SECRET_FLASK_LONG_ET_ALEATOIRE>
DB_HOST=host_interne_render_postgres
DB_PORT=5432
DB_USERNAME=user_render
DB_PASSWORD=<SECRET_POSTGRESQL_RENDER>
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
