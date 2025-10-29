
# Interface d’Analyse Réseau (Flask + PostGIS + Docker)

Salut Romain 👋  
Voici tout ce qu’il te faut pour **cloner, lancer et tester** l’appli localement.  
Cette application Flask permet d'analyser des exports de données de réseaux télécoms, de les stocker dans une base PostgreSQL, d'effectuer des vérifications de cohérence, et propose désormais une interface dédiée à la résilience du réseau

---

## 🧱 Stack & Services

- **Backend** : Python 3.11 · Flask · SQLAlchemy · GeoAlchemy2  
- **Base de données** : PostgreSQL **+ PostGIS**  
- **Conteneurs** : Docker & Docker Compose  
- **Schémas DB** : `gracethd`, `resilience`, `public` (dans le `search_path`)  
- **Ports** : `8000` (web) · `5432` (db) 

> ⚙️ Au **premier démarrage**, les scripts d’init créent l’extension **PostGIS** et les schémas `gracethd` & `resilience`.

# 🔧 Prérequis

Docker Desktop (ou Docker Engine) + Docker Compose

Ports libres : 8000 (appli) et 5432 (PostgreSQL)

## ⚙️ Configuration

1) **Cloner le dépôt**  
```bash
git clone https://github.com/SeynabouS/interface-dev-docker.git
cd nterface-dev-docker
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

# pgAdmin est activé dans docker-compose
PGADMIN_DEFAULT_EMAIL=admin@example.com
PGADMIN_DEFAULT_PASSWORD=admin

# Option dev : affiche le lien de réinit de mot de passe dans l’UI
RESET_LINK_VIA_UI=1
```

> **DB_HOST** et **DB_PORT** sont déjà gérés par Docker (`db:5432`).


pgAdmin est activé dans docker-compose pour vérifier la base et l’import
PGADMIN_DEFAULT_EMAIL=admin@example.com
PGADMIN_DEFAULT_PASSWORD=admin

# Option dev : affiche le lien de réinit de mot de passe dans l’UI
RESET_LINK_VIA_UI=1

▶️ Démarrage rapide (TL;DR)

Dans le dossier interface-dev-docker/ :

# 1) Construire et démarrer
docker compose up -d --build

# 2) Vérifier la santé
curl http://localhost:8000/healthz   # doit renvoyer {"status":"ok","db":true}

# 3) Créer un utilisateur pour se connecter à l’UI
docker compose exec web python create_user.py admin admin123

🔁 Restaurer le backup (OBLIGATOIRE actuellement)

L’upload sur Interface est HS. Restaure le dump fourni (présent dans db/import/).

docker compose exec db bash -lc "pg_restore --clean --if-exists --no-owner --no-acl -f - /import/gracethd.backup | psql -U app -v ON_ERROR_STOP=1 -d telecom_db"


Ensuite, ouvre l’UI : http://localhost:8000

Identifiants : admin / admin123

Repartir d’une base vierge :
docker compose down -v && docker compose up -d --build

## 🗂️ Structure utile du projet

```
interface-local/
├─ app.py                         # App Flask (routes, analyses, import, auth)
├─ Dockerfile                     # Image du service web
├─ docker-compose.yml             # Services : db (PostGIS) + web (Flask)
├─ requirements.txt               # Dépendances Python
├─ .env.docker.example            # Exemple d’env
├─ db/
│  ├─ init/00_init_postgis.sql    # Création PostGIS + schémas gracethd/resilience
│  └─ import/                     # (Option) dumps à restaurer
├─ scripts/
│  ├─ dump.sh                     # Sauvegarde DB -> ./db/import/*.dump
│  └─ restore.sh                  # Restauration depuis ./db/import
├─ templates/                     # Pages HTML (Jinja2)
│  ├─ interface.html              # Page principale (import + analyses)
│  ├─ resilience.html             # Page Résilience (Leaflet)
│  └─ ...                         # Pages résultats / login / reset mdp
├─ static/
│  ├─ js/                         # script.js, resilience.js, etc.
│  ├─ css/
│  ├─ exports/                    # fichiers d’export/rapports à télécharger
│  └─ results/                    # résultats HTML/CSV générés
├─ uploads/                       # fichiers importés par l’utilisateur
└─ temp_shapefiles/               # fichiers temporaires (SIG)
```
## 🔐 Authentification

- L’UI est protégée. Crée au moins **un user** :  
  ```bash
  docker compose exec web python create_user.py <login> <motdepasse>
  ```
- Réinitialisation : menu **“Mot de passe oublié”** (`/forgot`).  
  - En dev, si `RESET_LINK_VIA_UI=1`, le lien de reset apparaît directement dans l’UI **et** dans les logs.  
  - Sinon, récupère le lien dans les logs :  
    ```bash
    docker compose logs -f web | grep RESET
    ```

---

## 📥 Importer un export (jeu de fichiers)

1. Connecte-toi à l’UI → **“Analyse d’un Export à une Date Donnée”**.  
2. **Sélectionne le dossier** de l’export (le bouton accepte un **dossier** complet).  
   - Fichiers supportés : **.csv**, **.dbf**, **.shp**, **.xlsx**, **.json** (auto-détection d’encodage & séparateur).  
3. Renseigne **la date d’export** (ex. `2025-09-15`).  
4. Clique **“Importer dans la Base”**.  
5. Les tables sont créées dans le schéma **`gracethd`** avec le nom :  
   `YYYY-MM_nomFichier.ext` (ex. `2025-09_t_cable.csv`).

> L’app utilise le `search_path = gracethd,resilience,public`. Pas besoin de préfixer les schémas dans les requêtes.

---

## 🔎 Lancer des analyses

Toujours sur la page principale :
- **Analyser Tout (export unique)** : exécute l’ensemble des contrôles sur les fichiers importés.  
- Analyses ciblées disponibles :  
  - **Présence des champs** (`presence_champ_csv`)  
  - **BPE** (`analyze_bpe`)  
  - **Câbles** (`analyze_cable`)  
  - **Chambres** (`analyze_chambre`)  
  - **Fourreaux** (`analyze_fourreaux`)  
- Chaque analyse génère des **HTML/CSV** déposés dans `static/results/` (avec liens de téléchargement depuis l’UI).

### Analyses logiques — Référentiels & cohérences
`t_baie`, `t_cab_cond`, `t_cassette`, `t_cheminement`, `t_cond_chem`, cohérence câble,  
`t_conduite → t_organisme`, `t_ebp`, `t_fibre → t_cable`, `position`, `t_ltech`,  
`p_ptech`, `t_ropt`, `t_sitetech`, `t_suf`, `t_tiroir`, `t_cableline`, `t_noeud`

### Comparer deux exports
1. **Importer la 2ᵉ version** via le formulaire “Comparaison” (`/upload_different_version`).  
2. Lancer :  
   - **Comparer BPE** (`compare_ebp`)  
   - **Comparer Câbles** (`compare_cable`)  
   - **Comparer Points Techniques** (`compare_PointTechnique`)  
   - **Comparer Cheminement** (`compare_cheminement`)  

---

## 🗺️ Page “Résilience Réseau”

- Accès : bouton **“Résilience Réseau”** depuis la page principale.  
- Objectif : **importer des couches** importer des couches gesospatiales  dans le schéma `resilience`, puis les **afficher sur une carte et trouver leur alea de relisilience** (Leaflet).  
- Fonctions côté UI : affichage/masquage par couche, suppression, coloration, etc.  
- Les fichiers temporaires passent par `temp_shapefiles/` côté conteneur web.

---

## 🧰 Scripts utiles

```bash
# Sauvegarder la base (dans ./db/import/backup.dump)
scripts/dump.sh [nom.dump]

# Restaurer un dump placé dans ./db/import/
scripts/restore.sh <nom.dump|nom.sql>
```

---

## 🧪 Endpoints utiles (débogage)

- **Healthcheck** : `GET http://localhost:8000/healthz` → `{"status":"ok","db":true}`  
- **Static / Results** : les rapports sont servis depuis `static/results/`

---

## 🐛 Dépannage

- **500 Internal Server Error lors de l’upload** + erreur console _“Unexpected token '<' ... not valid JSON”_  
  → Le client attend du JSON, le serveur renvoie une page d’erreur HTML.  
  - Vérifier que tu es **bien connecté** (session valide).  
  - Que **la date d’export** est renseignée.  
  - Que **PostgreSQL** est **UP** : `curl http://localhost:8000/healthz` doit renvoyer `db:true`.  
  - Regarder les logs du service web :  
    ```bash
    docker compose logs -f web
    ```
  - Si besoin, supprime les volumes pour repartir propre :  
    ```bash
    docker compose down -v && docker compose up -d --build
    ```

- **Port occupé** : change le port mappé dans `docker-compose.yml` (ex. `8080:8000`).

- **pgAdmin** : si un service pgAdmin est configuré dans `docker-compose.yml`, connecte‑toi avec les variables `PGADMIN_DEFAULT_*` de ton `.env`. Crée une connexion vers l’hôte `db` (port `5432`).


---

## 🧯 Arrêt & nettoyage

```bash
# Arrêter les conteneurs
docker compose down

# Tout supprimer (y compris les volumes -> DB réinitialisée)
docker compose down -v
```

🙋‍♀️ Besoin d’aide ?

Tu peux me ping si quelque chose ne tourne pas rond.
Bon test ! 🚀
