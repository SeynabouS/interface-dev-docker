Interface d’Analyse Réseau (Flask + PostGIS + Docker)

Salut Romain 👋
Voici tout ce qu’il te faut pour cloner, lancer et tester l’appli localement.

⚠️ État actuel

Sur la page Interface, l’upload est temporairement HS depuis la dockerisation (problème de conversion/encodage).
👉 Pour tester, restaure le backup placé dans db/import/ après avoir démarré l’appli.
Une fois restauré, tous les boutons d’analyses fonctionnent sur les exports existants.

Sur la page Résilience Réseau, tout fonctionne (import, carte, gestion des couches).

🧱 Stack & services

Backend : Flask (Python 3.11), SQLAlchemy, GeoAlchemy2

DB : PostgreSQL + PostGIS

Conteneurs : Docker & Docker Compose

Schémas DB : gracethd, resilience, public (dans le search_path)

Ports : 8000 (web) · 5432 (db)

Les scripts d’init activent PostGIS et créent gracethd & resilience au premier démarrage.

🔧 Prérequis

Docker Desktop (ou Docker Engine) + Docker Compose v2

Ports libres : 8000 (appli) et 5432 (PostgreSQL)

⚙️ Configuration

Cloner le dépôt

git clone https://github.com/SeynabouS/interface-dev-docker.git
cd interface-dev-docker


Variables d’environnement
Copier l’exemple et adapter si besoin :

cp .env.docker.example .env


Valeurs par défaut (OK en local) :

DB_USERNAME=app
DB_PASSWORD=app
DB_NAME=telecom_db
SECRET_KEY=change-me-please

# pgAdmin est activé dans docker-compose pour vérifier la base et l’import
PGADMIN_DEFAULT_EMAIL=admin@example.com
PGADMIN_DEFAULT_PASSWORD=admin

# Dev : afficher le lien de reset de mot de passe dans l’UI
RESET_LINK_VIA_UI=1


DB_HOST/DB_PORT sont gérés par Docker (db:5432).

▶️ Démarrage rapide (TL;DR)

À la racine du projet :

# 1) Construire et démarrer
docker compose up -d --build

# 2) Vérifier la santé
curl http://localhost:8000/healthz   # attendu: {"status":"ok","db":true}

# 3) Créer un utilisateur pour l’UI
docker compose exec web python create_user.py admin admin123

🔁 Restaurer le backup (OBLIGATOIRE pour tester actuellement)

L’upload est HS sur Interface, il faut restaurer un dump que je te fournis depuis db/import/.

Pour importer dans la DB :

docker compose exec db bash -lc "pg_restore --clean --if-exists --no-owner --no-acl -f - /import/gracethd.backup | psql -U app -v ON_ERROR_STOP=1 -d telecom_db"


Le dossier hôte ./db/import/ est monté dans le conteneur DB sous /import (voir docker-compose.yml).

Ensuite, ouvre l’UI : http://localhost:8000

Identifiants de test : admin / admin123

💡 Repartir d’une base vierge :
docker compose down -v && docker compose up -d --build

🗺️ Pages & fonctionnalités
Page Interface

Upload (temporairement HS) — à la remise en service :
sélection d’un dossier (CSV/DBF/SHP/XLSX/JSON), saisie de date d’export, chargement en base (gracethd).

Analyses (OK avec backup restauré) :

Analyser Tout (export unique)

Présence des champs (presence_champ_csv)

BPE (analyze_bpe)

Câbles (analyze_cable)

Chambres (analyze_chambre)

Fourreaux (analyze_fourreaux)
Résultats générés en HTML/CSV dans static/results/ (liens dans l’UI).

Analyses logiques — Référence des points du réseau (OK avec backup restauré) :

Analyser t_baie ℹ️

Analyser t_cab_cond ℹ️

Analyser t_cassette ℹ️

Analyser t_cheminement ℹ️

Analyser t_cond_chem ℹ️

Analyser cohérence câble ℹ️

Analyser t_conduite → t_organisme ℹ️

Analyser t_ebp ℹ️

Analyser t_fibre → t_cable ℹ️

Analyser position ℹ️

Analyser t_ltech ℹ️

Analyser p_ptech ℹ️

Analyser t_ropt ℹ️

Analyser t_sitetech ℹ️

Analyser t_suf ℹ️

Analyser t_tiroir ℹ️

Analyser t_cableline ℹ️

Analyser t_noeud ℹ️

Comparaison de deux exports (quand 2 versions sont en base) :
compare_ebp · compare_cable · compare_PointTechnique · compare_cheminement.

Page Résilience Réseau ✅

Import de couches SIG (CSV/DBF/SHP…) → schéma resilience

Carte Leaflet, affichage/masquage par couche, suppression, couleurs, etc.

Temporaires dans temp_shapefiles/.

🔐 Authentification

Créer un utilisateur :

docker compose exec web python create_user.py <login> <motdepasse>


Réinitialisation via “Mot de passe oublié” (/forgot) :

si RESET_LINK_VIA_UI=1 → lien dans l’UI et dans les logs,

sinon, récupérer le lien :

docker compose logs -f web | grep RESET

🗂️ Structure utile du projet
interface-dev-docker/
├─ app.py
├─ Dockerfile
├─ docker-compose.yml
├─ requirements.txt
├─ .env.docker.example
├─ db/
│  ├─ init/00_init_postgis.sql
│  └─ import/                # ⬅️ place/vois ici le backup à restaurer
├─ scripts/
│  ├─ dump.sh                # sauvegarde -> ./db/import/*.dump
│  └─ restore.sh             # restauration depuis ./db/import
├─ templates/
│  ├─ interface.html         # (uploads HS)
│  ├─ resilience.html        # (OK)
│  └─ ...                    # login / reset mdp / résultats
├─ static/
│  ├─ js/                    # script.js, resilience.js, …
│  ├─ css/
│  ├─ exports/               # rapports
│  └─ results/               # HTML/CSV générés
├─ uploads/                  # (HS pour l’instant)
└─ temp_shapefiles/          # temporaires SIG

🧪 Endpoints utiles

Healthcheck : GET http://localhost:8000/healthz → {"status":"ok","db":true}

Résultats : servis depuis static/results/

🐛 Dépannage

Uploads (Interface) → 500 + “Unexpected token '<' … not valid JSON”
Problème connu (page HTML renvoyée au lieu du JSON).

Utiliser le backup (voir Démarrage rapide).

Vérifier la session (être connecté).

Vérifier la DB : curl http://localhost:8000/healthz (doit afficher db:true).

Logs :

docker compose logs -f web


Repartir propre :

docker compose down -v && docker compose up -d --build


Port occupé : modifier ports: dans docker-compose.yml (ex. 8080:8000).

pgAdmin (si activé) : hôte db, port 5432, login DB_USERNAME / DB_PASSWORD.

✉️ Contact

Si un point bloque, ping moi.
Bon test ! 🚀
