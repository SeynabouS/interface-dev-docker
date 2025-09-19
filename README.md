
# Le Moot — Interface d’Analyse Réseau (Flask + PostGIS + Docker)

Salut Romain 👋  
Voici tout ce qu’il te faut pour **cloner, lancer et tester** l’appli localement sans connaître la structure interne.  
L’objectif : importer un export (lot de fichiers), le stocker en base **PostgreSQL/PostGIS**, lancer des **analyses qualité/cohérence** et afficher des résultats (HTML/CSV). Une page dédiée **“Résilience Réseau”** permet aussi d’importer des couches SIG et de les afficher sur une carte (Leaflet).

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

# Optionnel si tu actives pgAdmin dans docker-compose
PGADMIN_DEFAULT_EMAIL=admin@example.com
PGADMIN_DEFAULT_PASSWORD=admin

# Option dev : affiche le lien de réinit de mot de passe dans l’UI
RESET_LINK_VIA_UI=1
```

> **DB_HOST** et **DB_PORT** sont déjà gérés par Docker (`db:5432`).

---

## ▶️ Démarrage rapide (TL;DR)

Dans le dossier `interface-local/` :

```bash
# 1) Construire et démarrer
docker compose up -d --build

# 2) Vérifier la santé
curl http://localhost:8000/healthz  # doit renvoyer {"status":"ok","db":true}

# 3) Créer les tables applicatives (dans le schéma gracethd)
docker compose exec web flask --app app init-db

# 4) Créer un utilisateur pour se connecter à l’UI
docker compose exec web python create_user.py admin admin123

# 5) Ouvrir l’UI
# http://localhost:8000
# Identifiants : admin / admin123
```

> Si tu veux repartir d’une base **vierge** : `docker compose down -v` puis relance le démarrage rapide.

---

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

---

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
   `YYYY-MM-DD_nomFichier.ext` (ex. `2025-09-15_t_cable.csv`).

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

### Comparer deux exports
1. **Importer la 2ᵉ version** via le formulaire “Comparaison” (`/upload_different_version`).  
2. Lancer :  
   - **Comparer BPE** (`compare_ebp`)  
   - **Comparer Câbles** (`compare_cable`)  
   - **Comparer Points Techniques** (`compare_PointTechnique`)  
   - **Comparer Cheminement** (`compare_cheminement`)  

---

## 🗺️ Page “Résilience Réseau” (SIG)

- Accès : bouton **“Résilience Réseau”** depuis la page principale.  
- Objectif : **importer des couches** (CSV/DBF/SHP…) dans le schéma `resilience`, puis les **afficher sur une carte** (Leaflet).  
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

- **pgAdmin (optionnel)** : si un service pgAdmin est configuré dans `docker-compose.yml`, connecte‑toi avec les variables `PGADMIN_DEFAULT_*` de ton `.env`. Crée une connexion vers l’hôte `db` (port `5432`).

---

## 🧯 Arrêt & nettoyage

```bash
# Arrêter les conteneurs
docker compose down

# Tout supprimer (y compris les volumes -> DB réinitialisée)
docker compose down -v
```

---

## 🔒 Notes sécurité (local)

- Le `SECRET_KEY` et les mots de passe de démo **ne sont pas faits pour la prod**.  
- En local, on garde les valeurs par défaut pour aller vite. En environnement partagé, **change-les**.

---

## 🙋‍♀️ Besoin d’aide ?

Tu peux me ping si quelque chose ne tourne pas rond.  
Bon test ! 🚀
