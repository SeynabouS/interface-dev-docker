# Interface d’Analyse Réseau (Flask + PostGIS + Docker)

![Flask](https://img.shields.io/badge/Flask-2.3.x-blue)
![PostGIS](https://img.shields.io/badge/PostGIS-3.4-green)
![Docker](https://img.shields.io/badge/Docker-Compose-orange)
![Python](https://img.shields.io/badge/Python-3.11-yellow)

Application Flask permettant d'importer et analyser des exports télécoms avec PostgreSQL/PostGIS, incluant une interface cartographique pour la résilience réseau.

## ✨ Fonctionnalités

- **Import et stockage** d'exports télécoms dans PostgreSQL/PostGIS
- **Analyses de cohérence** avec export HTML/CSV
- **Page Résilience Réseau** pour charger et visualiser des couches SIG
- **Interface cartographique** interactive (Leaflet)
- **Gestion d'utilisateurs** avec authentification

## 🏗️ Architecture

```
Backend : Python 3.11 · Flask · SQLAlchemy · GeoAlchemy2
Base de données : PostgreSQL + PostGIS
Conteneurisation : Docker & Docker Compose
Schémas DB : gracethd, resilience, public (via search_path)
Ports : 8000 (web) · 5432 (db)
```

## 📋 Prérequis

- **Docker Desktop** (ou Docker Engine + Docker Compose)
- **Ports disponibles** : 8000 et 5432
- **Git** pour cloner le dépôt

## 🚀 Installation Rapide

### 1. Cloner le dépôt
```bash
git clone https://github.com/SeynabouS/interface-dev-docker.git
cd interface-dev-docker
```

### 2. Configuration de l'environnement
```bash
cp .env.docker.example .env
```

Les valeurs par défaut (.env) :
```env
DB_USERNAME=app
DB_PASSWORD=app
DB_NAME=telecom_db
SECRET_KEY=change-me-please
PGADMIN_DEFAULT_EMAIL=admin@example.com
PGADMIN_DEFAULT_PASSWORD=admin
RESET_LINK_VIA_UI=1
```

### 3. Démarrage des conteneurs
```bash
docker compose up -d --build
```

### 4. Initialisation de la base de données
```bash
docker compose exec web flask --app app init-db
```

### 5. Création d'un utilisateur
```bash
docker compose exec web python create_user.py admin admin123
```

### 6. Restauration du backup (nécessaire actuellement)

**Windows (PowerShell) :**
```powershell
docker run --rm --network interface-local_default -v "${PWD}/db/import:/import" -e PGPASSWORD=app postgres:17 pg_restore --clean --if-exists --no-owner --role=app -h db -p 5432 -U app -d telecom_db /import/gracethd.backup
```

**Linux/macOS (Bash) :**
```bash
docker run --rm --network interface-local_default \
  -v "${PWD}/db/import:/import" \
  -e PGPASSWORD=app \
  postgres:17 \
  pg_restore --clean --if-exists --no-owner --role=app -h db -p 5432 -U app -d telecom_db /import/gracethd.backup
```

> **Note :** Si le réseau Docker a un nom différent, vérifiez avec `docker network ls` et adaptez la commande.

### 7. Vérification
```bash
curl http://localhost:8000/healthz
```
Réponse attendue : `{"status":"ok","db":true}`

### 8. Accéder à l'application
- **URL :** http://localhost:8000
- **Identifiants :** admin / admin123

## 📁 Structure du projet

```
interface-dev-docker/
├── app.py                      # Application Flask principale
├── Dockerfile                  # Image du service web
├── docker-compose.yml          # Services Docker
├── requirements.txt            # Dépendances Python
├── .env.docker.example         # Exemple de fichier d'environnement
├── db/
│   ├── init/                   # Scripts d'initialisation DB
│   │   └── 00_init_postgis.sql
│   └── import/                 # Backups à restaurer
├── scripts/
│   ├── dump.sh                 # Sauvegarde de la base
│   └── restore.sh              # Restauration de la base
├── templates/                  # Templates HTML
│   ├── interface.html          # Page principale
│   ├── resilience.html         # Page Résilience Réseau
│   └── ...                     # Pages d'authentification
├── static/                     # Fichiers statiques
│   ├── js/                     # JavaScript
│   ├── css/                    # Feuilles de style
│   ├── exports/                # Exports téléchargeables
│   └── results/                # Résultats d'analyse
├── uploads/                    # Fichiers importés
└── temp_shapefiles/            # Fichiers SIG temporaires
```

## 🔐 Authentification

### Créer un utilisateur
```bash
docker compose exec web python create_user.py <username> <password>
```

### Réinitialisation de mot de passe
- Accédez à `/forgot` depuis l'interface
- Si `RESET_LINK_VIA_UI=1`, le lien s'affiche dans l'UI
- Sinon, consultez les logs : `docker compose logs -f web | grep RESET`

## 🗺️ Page "Résilience Réseau"

Accessible via le bouton "Résilience Réseau" sur la page principale.

**Fonctionnalités :**
- Import de couches géospatiales (SHP, GeoJSON, etc.) dans le schéma `resilience`
- Visualisation interactive sur carte Leaflet
- Gestion des couches (affichage/masquage, suppression, coloration)
- Analyse des objets avec couches support "aléas"

## 🔧 Endpoints utiles

- **Healthcheck :** `GET http://localhost:8000/healthz`
- **Résultats d'analyse :** servis depuis `static/results/`

## 🐛 Dépannage

### Redémarrer complètement (supprime la base)
```bash
docker compose down -v && docker compose up -d --build
```

### Consulter les logs
```bash
docker compose logs -f web
```

### Port déjà utilisé
Modifiez le mapping dans `docker-compose.yml` :
```yaml
ports:
  - "8080:8000"  # Au lieu de "8000:8000"
```

### Accéder à pgAdmin (si activé)
- **URL :** http://localhost:5050
- **Connexion DB :**
  - Host: `db`
  - Port: `5432`
  - Database: `telecom_db`
  - Username: `app`
  - Password: `app`

## 🧯 Arrêt et nettoyage

### Arrêt simple (conserve les données)
```bash
docker compose down
```

### Arrêt complet (supprime volumes et données)
```bash
docker compose down -v
```

## 📝 Notes

- L'upload via interface est temporairement désactivé - utilisez la restauration de backup
- L'image PostGIS utilisée est `postgis/postgis:16-3.4` pour une meilleure stabilité
- Les scripts d'initialisation créent automatiquement les extensions et schémas nécessaires

## 🤝 Contribution

Les issues et pull requests sont les bienvenues pour améliorer l'application.

## 📄 Licence

[À compléter selon la licence du projet]
