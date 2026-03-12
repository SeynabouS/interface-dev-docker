# Interface & Resilience - Separation Complete

Deux applications Flask sont maintenant isolees:

- Application 1: **Interface Analyse Cartographique**
  - Web: `http://localhost:8000`
  - Base: `db_interface` (PostGIS), port hote `5432`
  - Login template: `login_interface.html`
  - Schema auth/data: `gracethd`

- Application 2: **Resilience Reseau**
  - Web: `http://localhost:8001/resilience`
  - Base: `db_resilience` (PostGIS), port hote `5433`
  - Login template: `login_resilience.html`
  - Schema auth/data: `resilience`

Il n'y a plus de lien de navigation entre les deux interfaces.

## Lancement

```bash
docker compose up -d --build
```

## Verification

```bash
curl http://localhost:8000/healthz
curl http://localhost:8001/healthz
docker compose ps
```

## Creation des utilisateurs (separes)

Utilisateur pour l'app Interface:

```bash
docker compose exec web python create_user.py admin_interface motdepasse123
```

Utilisateur pour l'app Resilience:

```bash
docker compose exec web_resilience python create_user.py admin_resilience motdepasse123
```

## Variables d'environnement

Copier `.env.docker.example` vers `.env` puis ajuster:

- `DB_USERNAME_INTERFACE`, `DB_PASSWORD_INTERFACE`, `DB_NAME_INTERFACE`
- `DB_USERNAME_RESILIENCE`, `DB_PASSWORD_RESILIENCE`, `DB_NAME_RESILIENCE`
- `SECRET_KEY`

## Arret / reset complet

```bash
docker compose down
docker compose down -v
```
