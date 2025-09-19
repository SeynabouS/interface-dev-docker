Interface d’Analyse Réseau (Flask + PostGIS + Docker)

Salut Romain 👋
Ce dépôt contient l’application pour analyser des exports réseau : stockage en PostgreSQL/PostGIS, analyses de cohérence (rapports HTML/CSV) et une page “Résilience Réseau” pour importer/visualiser des couches SIG (Leaflet).

⚠️ État actuel

Sur la page Interface, l’upload est temporairement HS depuis la dockerisation (problème de conversion/encodage).
👉 Pour tester, il faut restaurer le backup placé dans db/import/ après avoir démarré l’appli.
Une fois restauré, tous les boutons d’analyse fonctionnent sur les exports existants.

Sur la page Résilience Réseau, toutes les fonctionnalités (import, affichage carte, gestion des couches) fonctionnent.

🧱 Stack

Backend : Flask (Python 3.11), SQLAlchemy, GeoAlchemy2

Base de données : PostgreSQL + PostGIS

Conteneurisation : Docker & Docker Compose

Schémas DB : gracethd, resilience, public (dans le search_path)

Ports : 8000 (web) · 5432 (db)

La base est initialisée au premier démarrage (activation PostGIS + création des schémas gracethd et resilience).

🔧 Prérequis

Docker Desktop (ou Docker Engine) + Docker Compose v2

Ports libres : 8000 (appli) et 5432 (PostgreSQL)

⚙️ Configuration
1) Cloner le dépôt
git clone <URL_DU_REPO> interface-dev-docker
cd interface-dev-docker

2) Variables d’environnement

Copier l’exemple, puis adapter si besoin :

cp .env.docker.example .env


Valeurs par défaut (OK pour un test local) :

DB_USERNAME=app
DB_PASSWORD=app
DB_NAME=telecom_db
SECRET_KEY=change-me-please

# Optionnel si pgAdmin est activé dans docker-compose
PGADMIN_DEFAULT_EMAIL=admin@example.com
PGADMIN_DEFAULT_PASSWORD=admin

# Dev : afficher le lien de reset de mot de passe dans l’UI
RESET_LINK_VIA_UI=1


Pas besoin de définir DB_HOST/DB_PORT : Docker fournit db:5432.

▶️ Démarrage rapide

Dans la racine du projet :

# 1) Construire et démarrer
docker compose up -d --build

# 2) Vérifier la santé
curl http://localhost:8000/healthz
# attendu : {"status":"ok","db":true}

# 3) Créer un utilisateur pour se connecter à l’UI
docker compose exec web python create_user.py admin admin123

🔁 Restaurer le backup (OBLIGATOIRE actuellement)

L’upload sur la page Interface est HS, il faut restaurer le dump fourni dans db/import/ pour tester les analyses.

Si vous avez un .dump (format pg_dump -Fc) :

docker compose exec db bash -lc 'pg_restore -U "$DB_USERNAME" -d "$DB_NAME" /import/<NOM_DU_BACKUP>.dump'


Si vous avez un .sql (script SQL en clair) :

docker compose exec db bash -lc 'psql -U "$DB_USERNAME" -d "$DB_NAME" -f /import/<NOM_DU_BACKUP>.sql'


Le dossier du dépôt ./db/import/ est monté dans le conteneur à /import (cf. docker-compose.yml).

Ensuite, ouvrir l’UI : http://localhost:8000

Identifiants de test : admin / admin123

💡 Repartir d’une base vierge :

docker compose down -v && docker compose up -d --build

🗺️ Pages & fonctionnalités
Page Interface

Upload (temporairement HS) — à la remise en service, elle permet :

de sélectionner un dossier d’export (.csv, .dbf, .shp, .xlsx, .json),

de renseigner la date d’export (ex. 2025-09-15),

de charger en base (schéma gracethd).

Analyses (OK avec backup restauré) :

Analyser Tout (export unique)

Présence des champs (presence_champ_csv)

BPE (analyze_bpe)

Câbles (analyze_cable)

Chambres (analyze_chambre)

Fourreaux (analyze_fourreaux)

Résultats générés en HTML/CSV dans static/results/ (liens dans l’UI).

Comparaison de deux exports (une fois 2 versions en base) :
compare_ebp · compare_cable · compare_PointTechnique · compare_cheminement.

Page Résilience Réseau (OK)

Import de couches SIG (CSV/DBF/SHP…) → schéma resilience

Affichage carte (Leaflet), affichage/masquage par couche, suppression, couleurs, etc.

Fichiers temporaires dans temp_shapefiles/.

🔐 Authentification

Créer un utilisateur :

docker compose exec web python create_user.py <login> <motdepasse>


Réinitialiser via “Mot de passe oublié” (/forgot) :

# Si RESET_LINK_VIA_UI=1, le lien s’affiche dans l’UI et dans les logs
docker compose logs -f web | grep RESET

🗂️ Arborescence (résumé)
interface-dev-docker/
├─ app.py                         # App Flask (routes, analyses, import, auth)
├─ Dockerfile                     # Image du service web
├─ docker-compose.yml             # Services : db (PostGIS) + web (Flask)
├─ requirements.txt               # Dépendances Python
├─ .env.docker.example            # Exemple d'env
├─ db/
│  ├─ init/00_init_postgis.sql    # PostGIS + schémas gracethd/resilience
│  └─ import/                     # ⬅️ backup(s) à restaurer
├─ scripts/                       # (si présents)
│  ├─ dump.sh                     # Sauvegarde DB -> ./db/import/*.dump
│  └─ restore.sh                  # Restauration depuis ./db/import
├─ templates/
│  ├─ interface.html              # Page principale (uploads HS)
│  ├─ resilience.html             # Page Résilience (OK)
│  └─ ...                         # Login / reset mdp / résultats
├─ static/
│  ├─ js/                         # script.js, resilience.js, etc.
│  ├─ css/
│  ├─ exports/                    # Rapports téléchargeables
│  └─ results/                    # Résultats HTML/CSV générés
├─ uploads/                       # Uploads (HS pour l’instant)
└─ temp_shapefiles/               # Temporaires SIG (Résilience)

🧪 Endpoints utiles

Healthcheck : GET http://localhost:8000/healthz → {"status":"ok","db":true}

Résultats : servis depuis static/results/

🐛 Dépannage

Uploads (Interface) → 500 + “Unexpected token '<' … not valid JSON”
Problème connu (retour HTML d’erreur au lieu de JSON).

Utiliser le backup (section Démarrage rapide).

Vérifier la session (être connecté).

Vérifier la DB : curl http://localhost:8000/healthz (doit afficher db:true).

Consulter les logs :

docker compose logs -f web


Repartir propre :

docker compose down -v && docker compose up -d --build


Port occupé : modifier le mapping ports: dans docker-compose.yml (ex. 8080:8000).

pgAdmin (si activé) : se connecter avec PGADMIN_DEFAULT_*
Hôte : db · Port : 5432 · Identifiants : DB_USERNAME / DB_PASSWORD.

📦 Fichiers volumineux (dump)

Si vous récupérez ce dépôt avec un dump volumineux, il peut être stocké via Git LFS.
Sinon, alternative : publier le dump comme asset d’une Release GitHub, puis le télécharger localement dans db/import/ avant restauration.

🔒 Notes sécurité (local)

Le SECRET_KEY et les mots de passe de démo ne sont pas faits pour la prod.

Changez-les pour tout environnement partagé.

✉️ Contact

Pour toute question, ping moi directement.
Bon test ! 🚀
