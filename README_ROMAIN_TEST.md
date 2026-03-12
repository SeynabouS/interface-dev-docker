# Guide Test - Nouvelle Version (Romain)

Ce document permet de tester rapidement la version separee des 2 applications:

- Interface Analyse Cartographique
- SippeResiste - Resilience Reseau

## 1) Prerequis

- Docker Desktop demarre
- Port `8000` libre (Interface)
- Port `8001` libre (Resilience)
- Port `5432` libre (DB Interface)
- Port `5433` libre (DB Resilience)

## 2) Preparation

Depuis la racine du projet:

```bash
cp .env.docker.example .env
docker compose up -d --build
```

## 3) Verification rapide

```bash
curl http://localhost:8000/healthz
curl http://localhost:8001/healthz
docker compose ps
```

Les deux endpoints doivent repondre sans erreur.

## 4) Creation des comptes de test

Utilisateur Interface:

```bash
docker compose exec web python create_user.py admin_interface motdepasse123
```

Utilisateur Resilience:

```bash
docker compose exec web_resilience python create_user.py admin_resilience motdepasse123
```

## 5) Scenarios a tester

### Interface principale

- Ouvrir `http://localhost:8000`
- Se connecter avec `admin_interface`
- Verifier que les routes resilience ne sont pas accessibles depuis cette app

### Resilience

- Ouvrir `http://localhost:8001/resilience`
- Se connecter avec `admin_resilience`
- Verifier:
  - Upload des couches resilience
  - Lancement d'analyse (alea simple / batch)
  - Historique des runs
  - Export CSV

## 6) Arret

```bash
docker compose down
```

Reset complet (volumes inclus):

```bash
docker compose down -v
```

