Interface d’Analyse Réseau (Flask + PostGIS + Docker)

Salut Romain 👋
Voici un guide clair et rapide pour cloner, lancer et tester l’application en local.

Cette application Flask permet :

d’importer et stocker des exports télécoms dans PostgreSQL/PostGIS,

d’exécuter des analyses de cohérence (HTML/CSV),

d’utiliser une page dédiée Résilience Réseau pour charger des couches SIG et les exploiter sur une carte.

🧱 Stack & Services

Backend : Python 3.11 · Flask · SQLAlchemy · GeoAlchemy2

DB : PostgreSQL + PostGIS

Conteneurs : Docker & Docker Compose

Schémas DB : gracethd, resilience, public (via search_path)

Ports : 8000 (web) · 5432 (db)

✅ Image DB PostGIS utilisée : postgis/postgis:16-3.4 (plus stable sur Mac/Windows)

⚙️ Au premier démarrage, les scripts d’init créent l’extension PostGIS et les schémas gracethd et resilience.

🔧 Prérequis

Docker Desktop (ou Docker Engine) + Docker Compose

Ports libres : 8000 (appli) et 5432 (PostgreSQL)

⚙️ Installation & Configuration
1) Cloner le dépôt
git clone https://github.com/SeynabouS/interface-dev-docker.git
cd interface-dev-docker

2) Créer le fichier .env
cp .env.docker.example .env


Valeurs par défaut (OK en local) :

DB_USERNAME=app
DB_PASSWORD=app
DB_NAME=telecom_db
SECRET_KEY=change-me-please

# pgAdmin activé via docker-compose (si présent)
PGADMIN_DEFAULT_EMAIL=admin@example.com
PGADMIN_DEFAULT_PASSWORD=admin

# Dev : affiche le lien de réinit mdp dans l’UI
RESET_LINK_VIA_UI=1


DB_HOST/DB_PORT sont gérés par Docker (connexion interne db:5432).

▶️ Démarrage rapide (guide “prêt à tester”)

Dans le dossier du projet :

Étape 1 — Build + démarrage des conteneurs
docker compose up -d --build

Étape 2 — Initialiser la base (OBLIGATOIRE)
docker compose exec web flask --app app init-db

Étape 3 — Créer un utilisateur pour se connecter à l’UI
docker compose exec web python create_user.py admin admin123

Étape 4 — Restaurer le backup (OBLIGATOIRE actuellement)

📌 L’upload via l’interface est HS pour le moment → on restaure le dump fourni :
Le fichier attendu est dans db/import/ : gracethd.backup

✅ Commande PowerShell (Windows)
docker run --rm --network interface-local_default `
  -v "${PWD}/db/import:/import" `
  -e PGPASSWORD=app `
  postgres:17 `
  pg_restore --clean --if-exists --no-owner --role=app -h db -p 5432 -U app -d telecom_db /import/gracethd.backup

✅ Commande Bash (Linux/macOS)
docker run --rm --network interface-local_default \
  -v "${PWD}/db/import:/import" \
  -e PGPASSWORD=app \
  postgres:17 \
  pg_restore --clean --if-exists --no-owner --role=app -h db -p 5432 -U app -d telecom_db /import/gracethd.backup


ℹ️ Si ton réseau Docker ne s’appelle pas interface-local_default, liste-le avec :

docker network ls


et remplace interface-local_default par le bon nom.

Étape 5 — Vérifier que tout est OK
curl http://localhost:8000/healthz


Attendu :

{"status":"ok","db":true}

Étape 6 — Ouvrir l’application

URL : http://localhost:8000

Login : admin

Password : admin123

🗂️ Structure utile du projet
interface-dev-docker/
├─ app.py                         # App Flask (routes, analyses, import, auth)
├─ Dockerfile                     # Image du service web
├─ docker-compose.yml             # Services : db (PostGIS) + web (Flask)
├─ requirements.txt               # Dépendances Python
├─ .env.docker.example            # Exemple d’env
├─ db/
│  ├─ init/00_init_postgis.sql    # Création PostGIS + schémas gracethd/resilience
│  └─ import/                     # dumps à restaurer (gracethd.backup)
├─ scripts/
│  ├─ dump.sh                     # Sauvegarde DB
│  └─ restore.sh                  # Restauration DB
├─ templates/
│  ├─ interface.html              # Page principale (import + analyses)
│  ├─ resilience.html             # Page Résilience (Leaflet)
│  └─ ...                         # login / reset mdp / pages résultats
├─ static/
│  ├─ js/                         # script.js, resilience.js, etc.
│  ├─ css/
│  ├─ exports/                    # exports téléchargeables
│  └─ results/                    # résultats HTML/CSV générés
├─ uploads/                       # fichiers importés via l’UI
└─ temp_shapefiles/               # temporaires SIG

🔐 Authentification

Créer un user :

docker compose exec web python create_user.py <login> <motdepasse>


Réinitialisation mdp : /forgot

Si RESET_LINK_VIA_UI=1, le lien s’affiche dans l’UI + dans les logs.

Sinon, logs :

docker compose logs -f web | grep RESET

🗺️ Page “Résilience Réseau”

Accès : bouton “Résilience Réseau” depuis la page principale.

Objectif :

Importer des couches géospatiales (shp, geojson, etc.) dans le schéma resilience

Afficher les couches sur une carte (Leaflet)

Exploiter les couches support “aléas” pour enrichir / analyser les objets

Fonctions côté UI :

affichage/masquage par couche

suppression (avec dépendances)

coloration

🧪 Endpoints utiles

Healthcheck : GET http://localhost:8000/healthz

Résultats d’analyses : servis depuis static/results/

🐛 Dépannage rapide

Repartir de zéro (DB incluse) :

docker compose down -v && docker compose up -d --build


Logs web :

docker compose logs -f web


Port occupé : modifier le mapping dans docker-compose.yml (ex: 8080:8000)

pgAdmin : connexion PostgreSQL via :

Host : db

Port : 5432

DB : telecom_db

User : app

Password : app

🧯 Arrêt & nettoyage
docker compose down
docker compose down -v   # supprime aussi les volumes (DB reset)
