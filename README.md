Interface d’Analyse Réseau (Flask + PostGIS + Docker)

Salut Romain 👋
Voici tout ce qu’il te faut pour cloner, lancer et tester l’appli localement sans connaître la structure interne.

But de l’appli :

Importer un export (lot de fichiers) et le stocker en PostgreSQL/PostGIS

Lancer des analyses qualité / cohérence (rapports HTML/CSV)

Une page dédiée “Résilience Réseau” pour importer des couches SIG et les afficher sur une carte (Leaflet)

ℹ️ Important (état actuel)

Sur la page Interface, les uploads ne fonctionnent plus depuis la dockerisation (problème de conversion/encodage).
👉 Solution pour tester : restaurer le backup que j’ai placé dans db/import/ après avoir démarré l’appli.
Une fois le backup restauré, tous les boutons d’analyses fonctionnent sur les exports existants.

Sur la page Résilience Réseau, toutes les fonctionnalités (import, affichage, gestion des couches) fonctionnent.

🧱 Stack & services

Backend : Flask (Python 3.11), SQLAlchemy, GeoAlchemy2

DB : PostgreSQL + PostGIS

Conteneurs : Docker & Docker Compose

Schémas DB : gracethd, resilience, public (search_path par défaut)

Ports : 8000 (web) · 5432 (db)

Les scripts d’init créent PostGIS + les schémas gracethd et resilience au premier démarrage de la base.

🔧 Prérequis

Docker Desktop (ou Docker Engine) + Docker Compose v2

Ports libres : 8000 (appli) et 5432 (PostgreSQL)

⚙️ Configuration

Cloner le dépôt

git clone <URL_DU_REPO> le-moot
cd le-moot/interface-local


Variables d’environnement
Copie l’exemple puis adapte si besoin :

cp .env.docker.example .env


Valeurs par défaut (OK pour un test local) :

DB_USERNAME=app
DB_PASSWORD=app
DB_NAME=telecom_db
SECRET_KEY=change-me-please

# Optionnel si pgAdmin est activé dans docker-compose
PGADMIN_DEFAULT_EMAIL=admin@example.com
PGADMIN_DEFAULT_PASSWORD=admin

# Dev: afficher le lien de reset de mot de passe dans l’UI
RESET_LINK_VIA_UI=1


DB_HOST/DB_PORT sont gérés par Docker (service db:5432).

▶️ Démarrage rapide (TL;DR)

Dans interface-local/ :

# 1) Construire et démarrer
docker compose up -d --build

# 2) Vérifier la santé
curl http://localhost:8000/healthz
# attendu: {"status":"ok","db":true}

# 3) Créer un utilisateur pour se connecter à l’UI
docker compose exec web python create_user.py admin admin123

# 4) IMPORTANT (état actuel) : restaurer le backup fourni
#   → nécessaire car les uploads de la page Interface sont momentanément HS.
# Option A (script fourni s’il est présent) :
scripts/restore.sh db/import/<NOM_DU_BACKUP>.dump
# Option B (manuel, pour un .dump):
docker compose exec db bash -lc 'pg_restore -U "$DB_USERNAME" -d "$DB_NAME" /import/<NOM_DU_BACKUP>.dump'
# Option C (manuel, pour un .sql en clair) :
docker compose exec db bash -lc 'psql -U "$DB_USERNAME" -d "$DB_NAME" -f /import/<NOM_DU_BACKUP>.sql'

# 5) Ouvrir l’UI
# http://localhost:8000
# Identifiants : admin / admin123


💡 Pour repartir d’une base vierge :
docker compose down -v && docker compose up -d --build

🗂️ Structure utile
interface-local/
├─ app.py                         # App Flask (routes, analyses, import, auth)
├─ Dockerfile                     # Image du service web
├─ docker-compose.yml             # Services : db (PostGIS) + web (Flask)
├─ requirements.txt               # Dépendances Python
├─ .env.docker.example            # Exemple d’env
├─ db/
│  ├─ init/00_init_postgis.sql    # Création PostGIS + schémas gracethd/resilience
│  └─ import/                     # ⬅️ backup(s) à restaurer (fourni ici)
├─ scripts/
│  ├─ dump.sh                     # Sauvegarde DB -> ./db/import/*.dump
│  └─ restore.sh                  # Restauration depuis ./db/import
├─ templates/                     # Pages HTML (Jinja2)
│  ├─ interface.html              # Page principale (analyses, uploads - HS)
│  ├─ resilience.html             # Page Résilience (OK)
│  └─ ...                         # Login / reset mdp / résultats
├─ static/
│  ├─ js/                         # script.js, resilience.js, etc.
│  ├─ css/
│  ├─ exports/                    # rapports téléchargeables
│  └─ results/                    # résultats HTML/CSV générés
├─ uploads/                       # fichiers importés (Interface) — (HS pour l’instant)
└─ temp_shapefiles/               # temporaires SIG (Résilience)

🔐 Authentification

Créer au moins un user :

docker compose exec web python create_user.py <login> <motdepasse>


Réinitialiser via “Mot de passe oublié” (/forgot)

En dev, si RESET_LINK_VIA_UI=1, le lien de reset s’affiche dans l’UI et dans les logs.

Sinon, récupérer le lien dans les logs :

docker compose logs -f web | grep RESET

📥 Import / Données (état actuel)

Page Interface — Uploads : non fonctionnels (depuis la dockerisation).
👉 Utilise obligatoirement le backup fourni dans db/import/ pour tester les analyses.

Les tables de l’export restauré se trouvent dans le schéma gracethd.

Quand les uploads seront rétablis :

On sélectionne un dossier d’export (CSV/DBF/SHP/XLSX/JSON)

On renseigne la date d’export (ex. 2025-09-15)

Les tables sont créées sous gracethd (search_path: gracethd,resilience,public)

🔎 Lancer des analyses (OK avec le backup)

Sur la page Interface (après restauration du backup) :

Analyser Tout (export unique) : exécute l’ensemble des contrôles sur les fichiers importés.

Analyses ciblées :

Présence des champs (presence_champ_csv)

BPE (analyze_bpe)

Câbles (analyze_cable)

Chambres (analyze_chambre)

Fourreaux (analyze_fourreaux)

Chaque analyse génère des rapports HTML/CSV dans static/results/ (liens de téléchargement dans l’UI).

Comparer deux exports

Une fois un deuxième export disponible en base, lancer :

Comparer BPE (compare_ebp)

Comparer Câbles (compare_cable)

Comparer Points Techniques (compare_PointTechnique)

Comparer Cheminement (compare_cheminement)

🗺️ Page “Résilience Réseau” (OK)

Accès : bouton “Résilience Réseau” depuis la page principale.

Tout fonctionne ici : import de couches (CSV/DBF/SHP…), stockage dans resilience, affichage sur carte (Leaflet), masquage/affichage par couche, suppression, coloration, etc.

Les fichiers temporaires transitent par temp_shapefiles/.

🧰 Scripts utiles
# Sauvegarde la base (-> ./db/import/backup_<date>.dump)
scripts/dump.sh [nom.dump]

# Restaure un dump/SQL placé dans ./db/import/
scripts/restore.sh <nom.dump|nom.sql>


Selon le type de fichier :

.dump → pg_restore

.sql → psql -f

🧪 Endpoints utiles

Healthcheck : GET http://localhost:8000/healthz → {"status":"ok","db":true}

Résultats : servis depuis static/results/

🐛 Dépannage

Uploads (Interface) renvoient 500 + “Unexpected token '<' … not valid JSON”
→ Connus : le serveur renvoie une page HTML d’erreur au lieu du JSON attendu.

Utiliser le backup (section démarrage rapide).

Vérifier la session (être connecté).

Vérifier la DB : curl http://localhost:8000/healthz (doit afficher db:true).

Logs :

docker compose logs -f web


Repartir propre :

docker compose down -v && docker compose up -d --build


Port occupé : changer le mapping ports: dans docker-compose.yml (ex. 8080:8000).

pgAdmin (si activé) : se connecter avec PGADMIN_DEFAULT_*.
Hôte : db · Port : 5432 · Auth : DB_USERNAME / DB_PASSWORD.

🧯 Arrêt & nettoyage
# Arrêter
docker compose down

# Tout supprimer (volumes inclus → DB réinitialisée)
docker compose down -v

🔒 Notes sécurité (local)

Le SECRET_KEY et les mots de passe de démo ne sont pas faits pour la prod.

En environnement partagé, change-les.

🙋‍♀️ Besoin d’aide ?

Tu peux me ping si quelque chose ne tourne pas rond.
Bon test ! 🚀
