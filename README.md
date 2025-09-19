
# Interface d’Analyse Réseau (Flask + PostGIS + Docker)

Salut Romain 👋  
Voici tout ce qu’il te faut pour **cloner, lancer et tester** l’appli localement.  
Cette application Flask permet d'analyser des exports de données de réseaux télécoms, de les stocker dans une base PostgreSQL, d'effectuer des vérifications de cohérence, et propose désormais une interface dédiée à la résilience du réseau

---

## 🧱 Stack & services

- **Backend** : Flask (Python 3.11), SQLAlchemy, GeoAlchemy2
- **DB** : PostgreSQL + **PostGIS**
- **Conteneurs** : Docker & Docker Compose
- **Schemas DB** : `gracethd`, `resilience`, `public` (search_path par défaut)
- **Ports** : `8000` (web) · `5432` (db)

> Les scripts d’init auto‑créent PostGIS et les schémas `gracethd` & `resilience` au **premier démarrage** de la base.

---

## 🔧 Prérequis

- Docker Desktop (ou Docker Engine) + Docker Compose
- Ports libres : **8000** (appli) et **5432** (PostgreSQL)

---

## ⚙️ Configuration

1) **Cloner le dépôt**  
```bash
git clone <URL_DU_REPO> le-moot
cd le-moot/interface-local
```

2) **Variables d’environnement**  
Copie le fichier d’exemple et adapte si besoin :
```bash
cp .env.docker.example .env
```

Valeurs par défaut (tu peux les garder en local) :  
```env
DB_USERNAME=app
DB_PASSWORD=app
DB_NAME=telecom_db
SECRET_KEY=change-me-please

# pgAdmin est activé dans docker-compose pour vérifier la base et l’import
PGADMIN_DEFAULT_EMAIL=admin@example.com
PGADMIN_DEFAULT_PASSWORD=admin

# Option dev : affiche le lien de réinit de mot de passe dans l’UI
RESET_LINK_VIA_UI=1

DB_HOST et DB_PORT sont déjà gérés par Docker (db:5432).

▶️ Démarrage rapide (TL;DR)

Dans le dossier interface-dev-docker/ :

# 1) Construire et démarrer
docker compose up -d --build

# 2) Vérifier la santé
curl http://localhost:8000/healthz   # doit renvoyer {"status":"ok","db":true}

# 3) Créer un utilisateur pour se connecter à l’UI
docker compose exec web python create_user.py admin admin123

# 🔁 Restaurer le backup (OBLIGATOIRE actuellement)

L’upload sur Interface est HS. Restaure le dump fourni (présent dans db/import/).

docker compose exec db bash -lc "pg_restore --clean --if-exists --no-owner --no-acl -f - /import/gracethd.backup | psql -U app -v ON_ERROR_STOP=1 -d telecom_db"

Ensuite, ouvre l’UI : http://localhost:8000

Identifiants : admin / admin123

Repartir d’une base vierge :
docker compose down -v && docker compose up -d --build

# 🗂️ Structure utile du projet
interface-dev-docker/
├─ app.py                         # App Flask (routes, analyses, import, auth)
├─ Dockerfile                     # Image du service web
├─ docker-compose.yml             # Services : db (PostGIS) + web (Flask)
├─ requirements.txt               # Dépendances Python
├─ .env.docker.example            # Exemple d’env
├─ db/
│  ├─ init/00_init_postgis.sql    # Création PostGIS + schémas gracethd/resilience
│  └─ import/                     # ⬅️ backup .backup (monté en /import dans le conteneur)
├─ scripts/
│  ├─ dump.sh                     # Sauvegarde DB -> ./db/import/*.dump
│  └─ restore.sh                  # Restauration depuis ./db/import
├─ templates/
│  ├─ interface.html              # Page principale — uploads HS pour l’instant
│  ├─ resilience.html             # Page Résilience (Leaflet)
│  └─ ...                         # Login / reset mdp / pages résultats
├─ static/
│  ├─ js/                         # script.js, resilience.js, etc.
│  ├─ css/
│  ├─ exports/                    # Rapports téléchargeables
│  └─ results/                    # Résultats HTML/CSV générés
├─ uploads/                       # Fichiers importés (HS pour l’instant)
└─ temp_shapefiles/               # Temporaires SIG

# 🔐 Authentification

Créer un utilisateur :

docker compose exec web python create_user.py <login> <motdepasse>

Réinitialiser : menu “Mot de passe oublié” (/forgot)

En dev, si RESET_LINK_VIA_UI=1, le lien de reset apparaît dans l’UI et dans les logs.

Sinon, récupérer le lien :

docker compose logs -f web | grep RESET

# 📥 Importer un export (jeu de fichiers)

Se connecter à l’UI → “Analyse d’un Export à une Date Donnée”

Sélectionner un dossier (le bouton accepte un dossier complet)

Formats supportés : .csv, .dbf, .shp, .xlsx, .json (auto-détection encodage & séparateur)

Renseigner la date d’export (ex. 2025-09-15)

Cliquer “Importer dans la Base”

Les tables sont créées dans gracethd avec le nom : YYYY-MM-DD_nomFichier.ext
(ex. 2025-09-15_t_cable.csv)

Actuellement l’upload est HS. Utiliser la restauration du backup (section ci-dessus) pour tester les analyses.

# 🔎 Lancer des analyses

Toujours sur la page principale :

Analyser Tout (export unique) : exécute l’ensemble des contrôles

Analyses ciblées :

Présence des champs (presence_champ_csv)

BPE (analyze_bpe)

Câbles (analyze_cable)

Chambres (analyze_chambre)

Fourreaux (analyze_fourreaux)

Chaque analyse génère des HTML/CSV dans static/results/ (liens dans l’UI).

Analyses logiques — Référence des points du réseau

t_baie, t_cab_cond, t_cassette, t_cheminement, t_cond_chem, cohérence câble,
t_conduite → t_organisme, t_ebp, t_fibre → t_cable, position, t_ltech,
p_ptech, t_ropt, t_sitetech, t_suf, t_tiroir, t_cableline, t_noeud

Comparer deux exports

Importer la 2ᵉ version via le formulaire “Comparaison” (/upload_different_version)

Lancer : Comparer BPE (compare_ebp) · Comparer Câbles (compare_cable) ·
Comparer Points Techniques (compare_PointTechnique) · Comparer Cheminement (compare_cheminement)

🗺️ Page “Résilience Réseau” (SIG)

Accès : bouton “Résilience Réseau” depuis la page principale

Objectif : importer des couches (CSV/DBF/SHP…) dans resilience, puis afficher sur carte (Leaflet)

Fonctions : affichage/masquage par couche, suppression, couleurs, etc.

Temporaires : temp_shapefiles/

🧰 Scripts utiles
# Sauvegarder la base (-> ./db/import/backup.dump)
scripts/dump.sh [nom.dump]

# Restaurer un dump placé dans ./db/import/
scripts/restore.sh <nom.dump|nom.sql>

🧪 Endpoints utiles (débogage)

Healthcheck : GET http://localhost:8000/healthz → {"status":"ok","db":true}

Résultats : servis depuis static/results/

# 🐛 Dépannage

Uploads (Interface) → 500 + “Unexpected token '<' … not valid JSON” (page HTML renvoyée au lieu du JSON)

Utiliser le backup (voir Démarrage rapide)

Vérifier la session (être connecté)

Vérifier la DB : curl http://localhost:8000/healthz (doit afficher db:true)

Logs :

docker compose logs -f web

Repartir propre :

docker compose down -v && docker compose up -d --build

Port occupé : modifier ports: dans docker-compose.yml (ex. 8080:8000)

pgAdmin (si activé) : hôte db, port 5432, login DB_USERNAME / DB_PASSWORD

🧯 Arrêt & nettoyage
# Arrêter les conteneurs
docker compose down

# Tout supprimer (y compris les volumes -> DB réinitialisée)
docker compose down -v

# 🙋‍♀️ Besoin d’aide ?

Tu peux me ping si quelque chose ne tourne pas rond.
Bon test ! 🚀
