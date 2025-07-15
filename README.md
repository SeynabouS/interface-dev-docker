# TELECOM Data Analyzer 🚀

Cette application Flask permet d'analyser des exports de données de réseaux télécoms, de les stocker dans une base PostgreSQL, d'effectuer des vérifications de cohérence, et propose désormais une interface dédiée à la résilience du réseau.

---

## 📌 Fonctionnalités

* **Import et stockage d'exports réseau** en base PostgreSQL
* **Analyses de cohérence** : câble, conduite, BPE, etc.
* **Interface Résilience Réseau** : gestion, visualisation et analyse des données réseau avec Leaflet
* **Téléchargement de rapports détaillés** en CSV et HTML

---

## 🛠️ Installation

### 1. Clonage du dépôt :

```bash
git clone https://github.com/SeynabouS/-telecom-data-analyzer.git
cd -telecom-data-analyzer
```

### 2. Configuration de l'environnement :

Copiez et modifiez le fichier `.env.example` :

```bash
cp .env.example .env
```

### 3. Installation des dépendances :

```bash
pip install -r requirements.txt
```

### 4. Création de la base de données PostgreSQL :

```sql
CREATE DATABASE TELECOM;
CREATE SCHEMA gracethd;
CREATE SCHEMA resilience;
```

### 5. Création des tables nécessaires :

Exécutez le contenu du fichier SQL :

```
creation table exports.txt
```

---

## 🔐 Création d'un utilisateur administrateur

Utilisez le script Python `create_user.py` :

```bash
python create_user.py <username> <password>
```

Par exemple :

```bash
python create_user.py admin admin123
```

Ce script :

* Vérifie si l'utilisateur existe déjà
* Hash le mot de passe
* Ajoute l'utilisateur à la base

---

## 🌐 Lancer l'application

```bash
flask run
```

L'application sera accessible sur : [http://127.0.0.1:5000](http://127.0.0.1:5000)

---

## 📁 Structure du projet

```
telecom-data-analyzer/
│
├── app/
│   ├── templates/                # Templates HTML
│   ├── static/                   # CSS, JS, images, exports
│   │   ├── exports/              # Résultats d'analyses
│   │   ├── css/                  # Styles CSS
│   │   └── js/                   # Scripts JavaScript
│   ├── routes.py                 # Définition des routes Flask
│   ├── models.py                 # Modèles SQLAlchemy
│   ├── utils.py                  # Fonctions utilitaires
│   └── resilience/               # Module dédié à la Résilience Réseau
│       ├── __init__.py
│       ├── routes.py
│       ├── schemas.py
│       └── data_processing.py
│
├── uploads/                      # Fichiers d'export à analyser
├── .env                          # Variables d'environnement (non versionné)
├── .env.example                  # Exemple de configuration
├── requirements.txt              # Librairies nécessaires
├── create_user.py                # Script de création utilisateur
└── creation table exports.txt    # SQL pour création table exports
```

---

## 🌍 Interface Résilience Réseau

Cette nouvelle page permet :

* **Import et visualisation des données** géospatiales dans PostgreSQL (PostGIS)
* **Gestion dynamique des couches cartographiques** : affichage, masquage, suppression
* **Alertes et gestion des dépendances** des couches
* **Coloration dynamique des couches** pour faciliter l'analyse
* Visualisation interactive avec **Leaflet**

---

## 📚 Technologies utilisées

* Python
* Flask
* PostgreSQL / PostGIS
* Pandas
* SQLAlchemy
* Leaflet
* HTML/CSS/JavaScript

---

## 🙋‍♀️ Auteur

**Seynabou S.**

