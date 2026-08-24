# Documentation metiers et DSI - Application Resilience SippeResiste

Date : 13 juillet 2026  
Perimetre : application Resilience du projet `interface-local`  
Public vise : equipes metiers, DSI, exploitation, maintenance applicative

## 1. Synthese

L'application **Resilience SippeResiste** est une application web permettant d'analyser la resilience d'un reseau face a des couches d'alea geographiques.

Elle permet aux utilisateurs de :

- se connecter a une interface dediee ;
- importer des couches d'alea partagees ;
- importer une couche reseau temporaire pour lancer une analyse ;
- croiser le reseau avec les aleas dans PostgreSQL/PostGIS ;
- produire un score ou indicateur d'impact ;
- consulter l'historique des analyses ;
- exporter les resultats en CSV, GeoPackage ou Shapefile ;
- administrer les utilisateurs et la documentation disponible dans l'application.

Le deploiement local est realise avec Docker Compose. Il contient :

- un conteneur web Flask/Gunicorn ;
- un conteneur PostgreSQL/PostGIS ;
- des volumes pour conserver les donnees et les fichiers applicatifs.

## 2. Vue fonctionnelle pour les metiers

### 2.1 Objectif metier

L'objectif est de fournir un outil simple pour evaluer l'exposition d'un reseau a plusieurs risques ou aleas geographiques.

Le fonctionnement metier est le suivant :

1. L'administrateur importe les couches d'alea de reference.
2. L'utilisateur importe une couche reseau a analyser.
3. L'utilisateur selectionne les aleas a prendre en compte.
4. L'application calcule les intersections geographiques entre reseau et aleas.
5. L'application applique une matrice d'impact parametree.
6. L'utilisateur recupere le resultat dans l'historique et peut l'exporter.

### 2.2 Ecrans principaux

| Ecran | Usage |
|---|---|
| Connexion | Acces securise par identifiant et mot de passe. |
| Configuration | Import et gestion des couches d'alea partagees. |
| Analyse reseau | Import d'une couche reseau temporaire et lancement du calcul. |
| Historique | Consultation, recherche, suppression et export des runs. |
| Admin & Acces | Creation d'utilisateurs et gestion du role administrateur. |
| Aide & Doc | Mise a disposition d'une documentation utilisateur. |

### 2.3 Formats acceptes

Formats d'entree :

- GeoPackage : `.gpkg` ;
- Shapefile complet : `.shp`, `.shx`, `.dbf`, avec `.prj` et `.cpg` recommandes.

Formats de sortie :

- CSV ;
- GeoPackage ;
- Shapefile ;
- visualisation HTML selon les routes d'export disponibles.

## 3. Architecture technique

### 3.1 Schema general

```text
Navigateur utilisateur
  |
  | HTTP / JSON / SSE
  v
Gunicorn + Flask
  |
  | SQLAlchemy / GeoPandas / GDAL / PostGIS
  v
PostgreSQL + PostGIS
```

### 3.2 Conteneurs Docker

Le fichier `docker-compose.yml` declare deux services :

| Service | Conteneur | Role |
|---|---|---|
| `web_resilience` | `telecom_web_resilience` | Application Flask exposee sur le port hote `8001`. |
| `db_resilience` | `telecom_db_resilience` | Base PostgreSQL/PostGIS exposee sur le port hote `5433`. |

URL applicative locale :

```text
http://localhost:8001/resilience
```

Sonde technique :

```text
http://localhost:8001/healthz
```

### 3.3 Principaux fichiers du projet

| Fichier | Role |
|---|---|
| `app.py` | Code principal Flask : authentification, routes, imports, calculs PostGIS, exports, historique et administration. |
| `app_resilience.py` | Point d'entree isole pour l'application Resilience. Redirige `/` vers `/resilience` et bloque les routes hors perimetre. |
| `create_user.py` | Script de creation d'un utilisateur applicatif. |
| `Dockerfile` | Construction de l'image Python 3.11 avec dependances SIG et Gunicorn. |
| `docker-compose.yml` | Deploiement local avec web + base PostGIS. |
| `requirements.txt` | Dependances Python principales. |
| `requirements.docker.txt` | Dependances Python dediees au build Docker. |
| `templates/` | Pages HTML Jinja. |
| `static/js/resilience.js` | Logique front-end de l'application Resilience. |
| `static/css/` | Styles CSS. |
| `db/init_resilience/00_init_postgis.sql` | Initialisation PostGIS et schema `resilience`. |

## 4. Code de developpement important

Cette section reprend les extraits utiles pour comprendre le fonctionnement sans recopier tout le code source.

### 4.1 Connexion a la base

Dans `app.py`, l'application construit une chaine SQLAlchemy a partir des variables d'environnement :

```python
app.config['SQLALCHEMY_DATABASE_URI'] = (
    f'postgresql://{username}:{password}@{host}:{port}/{dbname}'
    f'?options=-csearch_path%3D{search_path}'
)
engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI'], pool_pre_ping=True)
```

Points importants pour la DSI :

- la base cible est PostgreSQL ;
- le schema applicatif principal est `resilience` ;
- le `search_path` attendu est `resilience,public` ;
- `pool_pre_ping=True` evite de reutiliser des connexions mortes.

### 4.2 Isolation de l'application Resilience

Dans `app_resilience.py`, seules les routes Resilience sont autorisees :

```python
@app.before_request
def isolate_resilience_application():
    if request.path == "/":
        return redirect("/resilience", code=302)

    if _is_resilience_path(request.path) and "user_id" not in session:
        return redirect(url_for("login"), code=302)

    if _is_allowed_on_resilience_app(request.path):
        return None

    return jsonify(
        {
            "status": "error",
            "message": "Route indisponible sur l'application Resilience.",
        }
    ), 404
```

Ce mecanisme evite d'exposer des routes applicatives qui ne font pas partie du perimetre Resilience.

### 4.3 Creation d'utilisateur

Le script `create_user.py` cree un compte et hashe le mot de passe :

```python
new_user = User(username=username)
new_user.set_password(password)
db.session.add(new_user)
db.session.commit()
```

Commande d'exploitation :

```powershell
docker compose exec web_resilience python create_user.py admin_resilience motdepasse123
```

Recommandation DSI : remplacer `motdepasse123` par un mot de passe robuste et le changer apres creation du compte initial.

### 4.4 Calcul de resilience

Le calcul est declenche par la route :

```text
GET /alea_view_batch_stream
```

Parametres principaux :

| Parametre | Role |
|---|---|
| `main_layer` | Couche reseau a analyser. |
| `view_name` | Nom du run/resultat. |
| `alea_tables` | Liste optionnelle des couches d'alea a utiliser. |

Principe technique :

1. L'application importe la couche reseau temporaire en base.
2. Elle cree une table temporaire de travail dans le schema `resilience`.
3. Elle parcourt les couches d'alea selectionnees.
4. Elle utilise PostGIS pour calculer les intersections.
5. Elle applique la matrice d'impact.
6. Elle cree une table resultat.
7. Elle journalise le run dans `resilience.run_history`.

### 4.5 Tables applicatives principales

Les tables sont creees ou maintenues par le code applicatif :

| Table | Role |
|---|---|
| `resilience.users` | Comptes utilisateurs et roles administrateurs. |
| `resilience.help_content` | Contenu d'aide textuel. |
| `resilience.help_documents` | Document d'aide fourni aux utilisateurs. |
| `resilience.run_history` | Historique des analyses lancees. |
| `resilience.private_run_layers` | Association entre resultats de runs et utilisateurs proprietaires. |
| `resilience.private_analysis_layers` | Couches reseau temporaires par utilisateur. |
| `resilience.analysis_upload_registry` | Registre technique des imports temporaires. |
| `resilience.impact_matrix` | Matrice d'impact par couche d'alea et niveau d'alea. |

## 5. Prerequis de deploiement

Sur la VM ou le serveur cible :

- Docker installe ;
- Docker Compose v2 disponible ;
- acces reseau pour telecharger les images Docker et dependances Python ;
- port `8001` disponible pour l'application ;
- port `5433` disponible si la base doit etre accessible depuis l'hote ;
- espace disque adapte aux donnees geographiques et aux exports ;
- sauvegarde reguliere du volume PostgreSQL.

## 6. Deploiement local ou VM avec Docker Compose

### 6.1 Emplacement du projet

Exemple local actuel :

```powershell
cd C:\Users\SEYSOU\Desktop\interface_docker_gracethd_sipperesiste\interface-local
```

### 6.2 Fichier d'environnement

Creer ou verifier le fichier `.env` a la racine de `interface-local` :

```env
SECRET_KEY=valeur_longue_et_secrete
DB_USERNAME_RESILIENCE=app
DB_PASSWORD_RESILIENCE=mot_de_passe_base
DB_NAME_RESILIENCE=telecom_resilience_db
RESET_LINK_VIA_UI=1
```

Recommandations :

- ne pas utiliser `app/app` en production ;
- utiliser une `SECRET_KEY` longue, aleatoire et non partagee ;
- stocker le `.env` hors gestion Git si un depot Git est utilise.

### 6.3 Demarrage

```powershell
docker compose up -d --build
```

### 6.4 Verification

Verifier l'etat des conteneurs :

```powershell
docker compose ps
```

Verifier la sonde applicative :

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost:8001/healthz
```

Resultat attendu :

```json
{"status":"ok","db":true}
```

### 6.5 Creation du premier utilisateur

```powershell
docker compose exec web_resilience python create_user.py admin_resilience motdepasse_robuste
```

Acceder ensuite a :

```text
http://localhost:8001/resilience
```

## 7. Exploitation quotidienne

### 7.1 Demarrer

```powershell
docker compose up -d
```

### 7.2 Arreter

```powershell
docker compose down
```

### 7.3 Redemarrer apres modification du code

```powershell
docker compose up -d --build
```

### 7.4 Consulter les logs

Logs applicatifs :

```powershell
docker compose logs -f web_resilience
```

Logs base de donnees :

```powershell
docker compose logs -f db_resilience
```

### 7.5 Entrer dans les conteneurs

Conteneur web :

```powershell
docker compose exec web_resilience sh
```

Base PostgreSQL :

```powershell
docker compose exec db_resilience psql -U app -d telecom_resilience_db
```

## 8. Sauvegarde et restauration

### 8.1 Donnees persistantes

Le volume Docker suivant contient la base PostgreSQL/PostGIS :

```text
db_resilience_data:/var/lib/postgresql/data
```

Les dossiers suivants sont montes dans le conteneur web :

```text
./uploads:/app/uploads
./temp_shapefiles:/app/temp_shapefiles
./static:/app/static
./templates:/app/templates
```

### 8.2 Sauvegarde recommandee

Commande adaptee au `docker-compose.yml` actuel :

```powershell
docker compose exec -T db_resilience pg_dump -U app -d telecom_resilience_db -Fc > backup_resilience.dump
```

### 8.3 Restauration recommandee

Copier le fichier `backup_resilience.dump` sur le serveur, puis executer :

```powershell
Get-Content backup_resilience.dump -Encoding Byte | docker compose exec -T db_resilience pg_restore -U app -d telecom_resilience_db --clean --if-exists
```

Alternative depuis un shell Linux :

```bash
cat backup_resilience.dump | docker compose exec -T db_resilience pg_restore -U app -d telecom_resilience_db --clean --if-exists
```

### 8.4 Point d'attention sur les scripts existants

Les scripts `scripts/dump.sh` et `scripts/restore.sh` sont presents dans le projet, mais ils referencent actuellement des noms generiques :

```text
service Docker : db
base par defaut : telecom_db
```

Or le fichier `docker-compose.yml` actuel utilise :

```text
service Docker : db_resilience
base par defaut : telecom_resilience_db
```

Avant une utilisation en exploitation, ces scripts doivent etre corriges ou remplaces par les commandes de sauvegarde ci-dessus.

## 9. Maintenance applicative

### 9.1 Ajouter ou modifier une fonctionnalite

Les fichiers les plus souvent modifies sont :

| Besoin | Fichiers concernes |
|---|---|
| Modifier une route ou un traitement backend | `app.py` |
| Modifier l'isolation du perimetre Resilience | `app_resilience.py` |
| Modifier l'ecran principal | `templates/resilience.html` |
| Modifier les interactions front-end | `static/js/resilience.js` |
| Modifier les styles | `static/css/resilience.css`, `static/css/style.css` |
| Ajouter une dependance Python | `requirements.txt` et/ou `requirements.docker.txt` |
| Modifier le packaging Docker | `Dockerfile`, `docker-compose.yml` |

### 9.2 Cycle de mise a jour recommande

1. Sauvegarder la base.
2. Sauvegarder les fichiers `.env`, `uploads`, `temp_shapefiles` si necessaire.
3. Appliquer les modifications de code.
4. Reconstruire l'image :

```powershell
docker compose up -d --build
```

5. Verifier les logs :

```powershell
docker compose logs -f web_resilience
```

6. Controler la sonde :

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost:8001/healthz
```

7. Tester un parcours fonctionnel complet :

- connexion ;
- import d'une couche d'alea ;
- import d'une couche reseau ;
- lancement d'une analyse ;
- verification dans l'historique ;
- export d'un resultat.

### 9.3 Tests techniques minimaux

Depuis `interface-local` :

```powershell
python -m py_compile app.py app_resilience.py create_user.py
docker compose config --quiet
```

Apres demarrage :

```powershell
docker compose ps
Invoke-WebRequest -UseBasicParsing http://localhost:8001/healthz
```

## 10. Supervision et points de controle DSI

### 10.1 Disponibilite

Controle principal :

```text
GET /healthz
```

Le controle doit confirmer :

- application joignable ;
- connexion base fonctionnelle.

### 10.2 Logs a surveiller

| Source | Commande | Alertes possibles |
|---|---|---|
| Web | `docker compose logs -f web_resilience` | erreurs Flask, erreurs import, erreurs PostGIS, erreurs export. |
| Base | `docker compose logs -f db_resilience` | indisponibilite, manque disque, redemarrages, erreurs SQL. |

### 10.3 Ressources systeme

Points a surveiller :

- espace disque Docker ;
- taille du volume PostgreSQL ;
- taille des fichiers uploades ;
- consommation memoire lors des gros traitements geographiques ;
- duree des calculs PostGIS ;
- nombre de runs conserves dans l'historique.

## 11. Securite

### 11.1 Authentification

L'application utilise une authentification locale avec table `resilience.users`. Les mots de passe sont haches par le code applicatif.

### 11.2 Comptes administrateurs

Le role administrateur permet :

- de creer des utilisateurs ;
- de modifier les roles ;
- de gerer certains contenus d'aide/documentation.

Recommandations :

- limiter le nombre de comptes administrateurs ;
- utiliser des mots de passe robustes ;
- supprimer les comptes non utilises ;
- tracer les operations sensibles via l'historique applicatif et les logs si necessaire.

### 11.3 Secrets

Ne pas exposer :

- `.env` ;
- mots de passe base ;
- `SECRET_KEY` ;
- sauvegardes PostgreSQL ;
- exports contenant des donnees sensibles.

## 12. Depannage courant

| Symptome | Cause probable | Action recommandee |
|---|---|---|
| `localhost:8001` ne repond pas | Conteneur web arrete ou port indisponible | `docker compose ps`, puis `docker compose logs web_resilience`. |
| `/healthz` retourne une erreur DB | Base indisponible ou mauvais identifiants | Verifier `db_resilience`, `.env`, logs PostgreSQL. |
| Connexion impossible | Compte absent ou mot de passe incorrect | Creer ou reinitialiser le compte via `create_user.py` ou route de reset. |
| Import Shapefile refuse | Fichiers `.shx` ou `.dbf` manquants | Fournir le Shapefile complet. |
| Calcul interrompu | Probleme donnees, PostGIS, timeout reseau ou redemarrage conteneur | Verifier logs web et base, puis relancer avec une couche plus petite si besoin. |
| Export impossible | Geometrie invalide ou dependance GDAL/OGR | Verifier les logs et la validite geometrique des donnees. |
| Historique vide | Aucun run pour l'utilisateur courant ou purge effectuee | Relancer une analyse et verifier `resilience.run_history`. |

## 13. Deploiement Render

Le projet contient aussi un fichier `render.yaml` permettant un deploiement sur Render.

Elements declares :

- service web Docker : `sipperesiste-resilience` ;
- base PostgreSQL : `sipperesiste-resilience-db` ;
- commande de lancement :

```bash
gunicorn -w 2 -b 0.0.0.0:$PORT --timeout 0 --graceful-timeout 300 app_resilience:app
```

Variables principales :

```env
SECRET_KEY=<generee>
DB_HOST=<host Render>
DB_PORT=5432
DB_USERNAME=<user Render>
DB_PASSWORD=<password Render>
DB_NAME=<database Render>
DB_SEARCH_PATH=resilience,public
AUTH_SCHEMA=resilience
LOGIN_TEMPLATE=login_resilience.html
RESET_LINK_VIA_UI=0
```

Point d'attention : verifier que l'extension PostGIS est disponible et activee sur la base cible.

## 14. Checklist de mise en production ou recette DSI

Avant ouverture aux utilisateurs :

- fichier `.env` renseigne avec des secrets robustes ;
- conteneurs demarres et sains ;
- `/healthz` retourne un statut OK ;
- premier compte administrateur cree ;
- test de connexion realise ;
- import d'une couche d'alea teste ;
- import d'une couche reseau teste ;
- calcul de resilience teste ;
- export CSV/GPKG/Shapefile teste ;
- sauvegarde PostgreSQL testee ;
- procedure de restauration testee ;
- logs consultables par l'equipe d'exploitation ;
- espace disque surveille ;
- mots de passe par defaut remplaces.

## 15. Resume operationnel

Commandes principales :

```powershell
cd C:\Users\SEYSOU\Desktop\interface_docker_gracethd_sipperesiste\interface-local
docker compose up -d --build
docker compose ps
Invoke-WebRequest -UseBasicParsing http://localhost:8001/healthz
docker compose exec web_resilience python create_user.py admin_resilience motdepasse_robuste
```

Adresse de l'application :

```text
http://localhost:8001/resilience
```

Commandes de maintenance :

```powershell
docker compose logs -f web_resilience
docker compose logs -f db_resilience
docker compose down
docker compose up -d
```

## 16. Annexe - code complet des pages et fichiers de developpement

Cette annexe contient le code source complet des pages et des fichiers necessaires a la comprehension, au deploiement et a la maintenance de l'application.

Le fichier binaire `templates/logo.png` n'est pas recopie dans le document car il s'agit d'une image. Il reste disponible dans le repertoire `templates/`.

### Pages HTML

#### templates/resilience.html

````html
<!DOCTYPE html>
<html lang="fr" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SippeRésiste - Plateforme d'Analyse</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: { brand: { 400: '#22d3ee', 500: '#06b6d4', 600: '#0891b2' } }
                }
            }
        }
    </script>
    <link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
    <style>
        .hidden-element { display: none !important; }
        .progress-bar { transition: width 0.5s ease-in-out; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #0f172a; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #475569; }
        #resilience-map { min-height: 520px; border-radius: 12px; border: 1px solid #1e293b; }
        #resilience-map-panel { position: relative; display: flex; flex-direction: column; }
        #resilience-map-panel:fullscreen,
        #resilience-map-panel:-webkit-full-screen,
        .resilience-map-panel-fallback-fullscreen {
            position: fixed;
            inset: 0;
            width: 100vw;
            height: 100vh;
            max-width: none;
            margin: 0;
            padding: 16px;
            border-radius: 0;
            background: #020617;
            z-index: 2500;
        }
        #resilience-map-panel:fullscreen #resilience-map,
        #resilience-map-panel:-webkit-full-screen #resilience-map,
        .resilience-map-panel-fallback-fullscreen #resilience-map {
            height: calc(100vh - 96px);
            min-height: 0;
            flex: 1 1 auto;
        }
        #analysis-map { height: 420px; border-radius: 12px; border: 1px solid #1e293b; }
        #analysis-map-panel { position: relative; display: flex; flex-direction: column; }
        #analysis-map-shell { position: relative; }
        #analysis-map-shell .analysis-map-overlay-btn { position: absolute; top: 12px; right: 12px; z-index: 500; }
        #analysis-map-status { min-height: 1.25rem; }
        #analysis-map-shell:fullscreen,
        #analysis-map-shell:-webkit-full-screen,
        .analysis-map-shell-fallback-fullscreen {
            position: fixed;
            inset: 0;
            width: 100vw;
            height: 100vh;
            max-width: none;
            margin: 0;
            padding: 12px;
            border-radius: 0;
            background: #020617;
            z-index: 2500;
        }
        #analysis-map-shell:fullscreen #analysis-map,
        #analysis-map-shell:-webkit-full-screen #analysis-map,
        .analysis-map-shell-fallback-fullscreen #analysis-map {
            height: calc(100vh - 24px);
            min-height: 0;
        }
        #file-names-container > div { background: #0b1220; border: 1px solid #1e293b; border-radius: 8px; padding: 10px; }
        #file-names-container input[type="text"] { width: 100%; background: #020617; border: 1px solid #334155; border-radius: 8px; color: #e2e8f0; padding: 8px 10px; margin-top: 8px; }
        #import-feedback, #analysis-import-feedback, #layer-action-feedback, #impact-matrix-feedback, #admin-user-feedback, #help-document-feedback { border-radius: 10px; padding: 10px 12px; font-size: 0.85rem; font-weight: 600; border: 1px solid transparent; }
        #import-feedback.success, #analysis-import-feedback.success, #layer-action-feedback.success, #impact-matrix-feedback.success, #admin-user-feedback.success, #help-document-feedback.success { color: #6ee7b7; background: rgba(6, 78, 59, 0.35); border-color: rgba(16, 185, 129, 0.45); }
        #import-feedback.error, #analysis-import-feedback.error, #layer-action-feedback.error, #impact-matrix-feedback.error, #admin-user-feedback.error, #help-document-feedback.error { color: #fca5a5; background: rgba(127, 29, 29, 0.35); border-color: rgba(239, 68, 68, 0.45); }
        .alea-support-card { 
            background: linear-gradient(135deg, rgba(15, 23, 42, 0.8) 0%, rgba(2, 6, 23, 0.9) 100%); 
            border: 1px solid #1e293b;
            box-shadow: 0 4px 20px rgba(6, 182, 212, 0.08);
        }
        .alea-support-meta { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
        .alea-support-meta h3 { background: linear-gradient(135deg, #22d3ee 0%, #06b6d4 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
        #alea-support-count { 
            display: inline-flex; 
            align-items: center; 
            justify-content: center; 
            padding: 6px 14px; 
            border-radius: 999px; 
            font-size: 0.75rem; 
            font-weight: 700; 
            color: #ecf0f1;
            background: linear-gradient(135deg, rgba(34, 211, 238, 0.2) 0%, rgba(6, 182, 212, 0.15) 100%);
            border: 1px solid rgba(34, 211, 238, 0.5);
            box-shadow: 0 2px 8px rgba(34, 211, 238, 0.15);
            white-space: nowrap; 
        }
        #alea-support-list { 
            min-height: 170px; 
            max-height: 310px; 
            overflow-y: auto; 
            overflow-x: hidden; 
            padding: 10px; 
            display: flex; 
            flex-direction: column; 
            gap: 10px; 
            background: linear-gradient(180deg, #020617 0%, #0b1220 100%);
            border: 1px solid #334155; 
            border-radius: 12px;
            box-shadow: inset 0 2px 8px rgba(0, 0, 0, 0.3);
        }
        #alea-support-list .alea-chip { 
            width: 100%; 
            overflow-wrap: anywhere; 
            word-break: break-word; 
            color: #e2e8f0; 
            background: linear-gradient(135deg, rgba(15, 23, 42, 0.9) 0%, rgba(30, 41, 59, 0.7) 100%);
            border: 1px solid rgba(34, 211, 238, 0.3);
            border-left: 4px solid #22d3ee;
            border-radius: 10px; 
            padding: 12px 14px; 
            display: flex; 
            justify-content: space-between; 
            align-items: center; 
            gap: 12px;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            box-shadow: 0 2px 8px rgba(34, 211, 238, 0.08);
            position: relative;
            overflow: hidden;
        }
        #alea-support-list .alea-chip::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent 0%, rgba(34, 211, 238, 0.1) 50%, transparent 100%);
            transition: left 0.5s ease;
        }
        #alea-support-list .alea-chip:hover {
            background: linear-gradient(135deg, rgba(34, 211, 238, 0.15) 0%, rgba(6, 182, 212, 0.1) 100%);
            border-color: rgba(34, 211, 238, 0.6);
            box-shadow: 0 4px 16px rgba(34, 211, 238, 0.15);
            transform: translateX(4px);
        }
        #alea-support-list .alea-chip:hover::before {
            left: 100%;
        }
        #alea-support-list .chip-title { 
            font-weight: 700; 
            font-size: 0.9rem; 
            line-height: 1.4;
        }
        #alea-support-list .chip-link { 
            flex-shrink: 0; 
            text-decoration: none; 
            color: #ecf0f1;
            border: 1px solid rgba(34, 211, 238, 0.6);
            background: linear-gradient(135deg, rgba(6, 182, 212, 0.3) 0%, rgba(8, 47, 73, 0.5) 100%);
            border-radius: 6px; 
            padding: 6px 12px; 
            font-size: 0.73rem; 
            font-weight: 600;
            transition: all 0.25s ease;
            box-shadow: 0 2px 6px rgba(34, 211, 238, 0.1);
            cursor: pointer;
        }
        #alea-support-list .chip-link:hover { 
            background: linear-gradient(135deg, #22d3ee 0%, #06b6d4 100%);
            color: #000;
            box-shadow: 0 4px 12px rgba(34, 211, 238, 0.3);
            transform: scale(1.05);
        }
        #alea-support-list .chip-link:active {
            transform: scale(0.98);
        }
        #alea-support-list em { 
            width: 100%; 
            color: #94a3b8; 
            font-style: normal; 
            font-weight: 600; 
            text-align: center; 
            padding: 20px 8px;
            font-size: 0.85rem;
        }
        #layer-controls, #analysis-map-layer-controls { max-height: 260px; overflow-y: auto; padding-right: 4px; }
        #layer-controls > div, #analysis-map-layer-controls > div { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 8px; background: #0b1220; border: 1px solid #1e293b; border-radius: 8px; padding: 8px; min-width: 0; }
        #layer-controls label, #analysis-map-layer-controls label { min-width: 0; flex: 1 1 220px; overflow-wrap: anywhere; word-break: break-word; }
        #layer-controls label strong, #analysis-map-layer-controls label strong { overflow-wrap: anywhere; word-break: break-word; }
        #layer-controls .download-format, #layer-controls .delete-layer-btn, #layer-controls .layer-color, #analysis-map-layer-controls .layer-color { background: #0f172a; border: 1px solid #334155; border-radius: 6px; color: #e2e8f0; padding: 6px 8px; }
        #layer-controls .delete-layer-btn { border-color: #7f1d1d; color: #fecaca; background: rgba(127, 29, 29, 0.2); }
        #layer-controls .delete-layer-btn:hover { background: rgba(127, 29, 29, 0.4); }
        #impact-matrix-container { border: 1px solid #334155; border-radius: 12px; background: #020617; overflow: auto; max-height: 340px; }
        #impact-matrix-container table { width: max-content; min-width: 100%; border-collapse: collapse; }
        #impact-matrix-container th, #impact-matrix-container td { border: 1px solid #334155; padding: 10px 12px; color: #d1d5db; text-align: center; white-space: nowrap; }
        #impact-matrix-container thead th { position: sticky; top: 0; z-index: 2; background: #0b1220; vertical-align: top; }
        #impact-matrix-container tbody th { position: sticky; left: 0; z-index: 1; background: #0f172a; text-align: left; }
        #impact-matrix-container tbody tr:nth-child(even) td { background: #0f172a; }
        #impact-matrix-container .impact-matrix-header { display: flex; flex-direction: column; align-items: stretch; gap: 8px; min-width: 150px; }
        #impact-matrix-container .impact-matrix-title { font-weight: 700; color: #f8fafc; overflow-wrap: anywhere; word-break: break-word; text-align: left; }
        #impact-matrix-container .impact-matrix-delete { border: 1px solid #7f1d1d; color: #fecaca; background: rgba(127, 29, 29, 0.2); border-radius: 8px; padding: 6px 8px; font-size: 0.75rem; font-weight: 700; }
        #impact-matrix-container .impact-matrix-delete:hover { background: rgba(127, 29, 29, 0.4); }
        #impact-matrix-container .impact-matrix-input { width: 90px; background: #0f172a; border: 1px solid #334155; border-radius: 8px; color: #e2e8f0; padding: 8px 10px; text-align: right; }
        #impact-matrix-container .impact-matrix-row-label { font-weight: 700; color: #e2e8f0; }
        #impact-matrix-container em { display: block; padding: 18px 14px; color: #94a3b8; font-style: normal; font-weight: 600; text-align: center; }
        #alea-support-list::-webkit-scrollbar { width: 9px; }
        #alea-support-list::-webkit-scrollbar-track { background: #0f172a; border-radius: 8px; }
        #alea-support-list::-webkit-scrollbar-thumb { background: #334155; border-radius: 8px; border: 2px solid #0f172a; }
        #alea-support-list::-webkit-scrollbar-thumb:hover { background: #475569; }
        .alea-select-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 8px; }
        #alea-selected-count { display: inline-flex; align-items: center; border: 1px solid #1f4b5f; background: rgba(8, 47, 73, 0.42); color: #67e8f9; border-radius: 999px; font-size: 0.72rem; font-weight: 700; padding: 3px 10px; white-space: nowrap; }
        #alea-selection-helper { font-size: 0.75rem; color: #94a3b8; line-height: 1.35; }
        #layer-alea.is-disabled { opacity: 0.5; filter: saturate(0.4); cursor: not-allowed; }
        #alea-clear-btn { margin-top: 8px; border: 1px solid #334155; color: #cbd5e1; background: rgba(15, 23, 42, 0.82); border-radius: 8px; padding: 6px 10px; font-size: 0.74rem; font-weight: 600; }
        #alea-clear-btn:hover { background: rgba(30, 41, 59, 0.95); border-color: #475569; }
        @media (max-width: 1100px) { .alea-support-meta { flex-direction: column; align-items: flex-start; } }
        #table-container { max-height: 62vh; overflow: auto; border: 1px solid #334155; border-radius: 10px; background: #020617; }
        #table-container table { width: max-content; min-width: 100%; border-collapse: collapse; }
        #table-container th, #table-container td { border: 1px solid #334155; padding: 8px 10px; text-align: left; color: #d1d5db; white-space: nowrap; }
        #table-container thead { background: #0b1220; }
        #table-container thead th { position: sticky; top: 0; z-index: 3; background: #0b1220; }
        #table-container tbody tr:nth-child(even) { background: #0f172a; }
        #table-container tbody tr:hover { background: rgba(6, 182, 212, 0.12); }
        #help-document-preview-frame { width: 100%; min-height: 70vh; border: 1px solid #1e293b; border-radius: 12px; background: #020617; }
        #help-document-meta { line-height: 1.5; }
    </style>
</head>
<body class="bg-slate-950 font-sans text-slate-300 min-h-screen flex flex-col overflow-x-hidden">

    <div id="app-container" class="flex-1 flex flex-col h-screen">
        <nav class="bg-slate-900 border-b border-slate-800 p-4 flex justify-between items-center shrink-0">
            <div class="flex items-center gap-4">
                <div class="w-24 h-14 rounded-[999px] bg-white/95 px-2 py-1 shadow-md ring-1 ring-slate-600 flex items-center justify-center">
                    <img src="/image/logo.png" alt="Logo SIPPEREC" class="h-12 w-auto object-contain">
                </div>
                <div class="font-bold text-xl tracking-wider text-brand-400 border-l border-slate-700 pl-4">SippeRésiste</div>
            </div>
            <div class="flex gap-6 text-sm font-medium">
                <button onclick="switchTab('config')" id="nav-config" class="pb-1 border-b-2 border-brand-400 text-brand-400">Configuration</button>
                <button onclick="switchTab('analyse')" id="nav-analyse" class="pb-1 border-b-2 border-transparent hover:text-slate-100">Analyse Réseau</button>
                <button onclick="switchTab('historique')" id="nav-historique" class="pb-1 border-b-2 border-transparent hover:text-slate-100">Historique runs</button>
                {% if resilience_context.is_admin %}
                <button onclick="switchTab('users')" id="nav-users" class="pb-1 border-b-2 border-transparent hover:text-slate-100">Admin. & Accès</button>
                {% endif %}
                <button onclick="switchTab('aide')" id="nav-aide" class="pb-1 border-b-2 border-transparent hover:text-slate-100">Aide & Doc</button>
            </div>
            <a href="{{ url_for('logout') }}" class="text-sm text-slate-500 hover:text-red-400 flex items-center gap-2">
                <span>Déconnexion</span> 🚪
            </a>
        </nav>

        <main class="flex-1 p-6 overflow-hidden flex flex-col">
            <div id="page-config" class="h-full flex gap-6">
                <div class="w-1/3 bg-slate-900 rounded-lg border border-slate-800 flex flex-col shadow-lg overflow-hidden">
                    <div class="p-6 overflow-y-auto h-full space-y-6">
                        <section>
                            <h2 class="text-xl font-semibold mb-3 text-slate-100">Import de couches</h2>
                            <p class="text-xs text-slate-400 mb-4">Tout import réalisé ici devient une couche d'aléa partagée, visible sur la carte et disponible pour les analyses de résilience.</p>

                            <form id="resilience-form" enctype="multipart/form-data" class="space-y-4">
                                <div class="border-2 border-dashed border-slate-700 bg-slate-950 rounded-lg p-4">
                                    <label for="resilience-files" class="block text-sm font-medium text-slate-300 mb-2">Fichiers GPKG ou Shapefile</label>
                                    <input type="file" id="resilience-files" name="files" multiple accept=".gpkg,.shp,.shx,.dbf,.prj,.cpg,.sbn,.sbx" class="w-full text-sm text-slate-300">
                                </div>

                                <div id="file-names-container" class="space-y-2"></div>

                                <button type="button" id="resilience-upload-btn" class="w-full bg-brand-600 hover:bg-brand-500 text-white font-bold py-3 rounded transition-colors shadow-lg shadow-brand-500/20">
                                    Importer dans la base
                                </button>

                                <div id="import-feedback" class="hidden-element"></div>
                            </form>
                        </section>

                        <hr class="border-slate-800">

                        <section class="alea-support-card rounded-xl p-6 shadow-2xl">
                            <div class="alea-support-meta">
                                <div>
                                    <h3 class="text-lg font-bold text-slate-100">Couches de support (aléas)</h3>
                                    <p class="text-xs text-slate-500 mt-2 font-medium">Couches d'aléa disponibles pour l'analyse de résilience</p>
                                </div>
                                <span id="alea-support-count">0 couche</span>
                            </div>

                            <div id="alea-support-list">
                                <!-- Les aléas s'affichent ici -->
                            </div>
                        </section>
                    </div>
                </div>

                <div class="w-2/3 bg-slate-950 rounded-lg border border-slate-800 flex flex-col relative overflow-hidden p-4">
                    <div id="resilience-map-panel" class="flex-1 flex flex-col">
                        <div class="flex justify-end mb-3">
                            <button type="button" id="resilience-map-fullscreen-btn" class="bg-slate-800 border border-slate-700 hover:bg-slate-700 text-slate-200 px-3 py-2 rounded text-sm">
                                Plein écran
                            </button>
                        </div>
                        <div id="resilience-map" class="flex-1"></div>
                    </div>

                    <div class="mt-3 grid grid-cols-1 gap-3">
                        <section class="bg-slate-900 border border-slate-800 rounded-lg p-3">
                            <h3 class="text-sm font-semibold mb-2 text-slate-100 uppercase tracking-wide">Gestion des couches</h3>
                            <p class="text-xs text-slate-400 mb-3">Visualisation, téléchargement et suppression des couches partagées de configuration.</p>
                            <div id="layer-controls"></div>
                            <div id="layer-action-feedback" class="hidden-element mt-3"></div>
                        </section>

                        <section class="bg-slate-900 border border-slate-800 rounded-lg p-3">
                            <div class="flex flex-wrap justify-between items-start gap-3 mb-3">
                                <div>
                                    <h3 class="text-sm font-semibold text-slate-100 uppercase tracking-wide">Matrice des impacts</h3>
                                    <p class="text-xs text-slate-400 mt-2">
                                        En colonnes: les niveaux d'aléa de 0 à 3. En lignes: les couches d'aléa configurées.
                                        Chaque cellule correspond à la valeur d'impact à appliquer pendant le run pour la couche et le niveau sélectionnés.
                                    </p>
                                </div>
                                <button type="button" id="impact-matrix-save-btn" class="bg-brand-600 hover:bg-brand-500 text-white font-bold px-4 py-2 rounded transition-colors shadow-lg shadow-brand-500/20">
                                    Enregistrer
                                </button>
                            </div>

                            <div id="impact-matrix-container"><em>Chargement de la matrice des impacts...</em></div>
                            <div id="impact-matrix-feedback" class="hidden-element mt-3"></div>
                        </section>
                    </div>
                </div>
            </div>

            <div id="page-analyse" class="hidden-element w-full max-w-5xl mx-auto overflow-y-auto pb-10 h-full">
                <h2 class="text-2xl font-semibold mb-4 text-slate-100">Nouvelle Analyse de Résilience</h2>

                <div class="bg-slate-900 p-6 rounded-lg border border-slate-800 mb-4">
                    <h3 class="text-sm font-semibold mb-3 text-slate-400 uppercase tracking-wide">Import de votre couche réseau</h3>
                    <p class="text-xs text-slate-400 mb-4">
                        Importez ici la couche réseau temporaire utilisée uniquement comme entrée d'analyse. Elle n'est pas enregistrée comme couche persistante dans l'application.
                    </p>

                    <form id="analysis-upload-form" enctype="multipart/form-data" class="space-y-4">
                        <div class="border-2 border-dashed border-slate-700 bg-slate-950 rounded-lg p-4">
                            <label for="analysis-layer-files" class="block text-sm font-medium text-slate-300 mb-2">Fichiers GPKG ou Shapefile</label>
                            <input type="file" id="analysis-layer-files" name="files" multiple accept=".gpkg,.shp,.shx,.dbf,.prj,.cpg,.sbn,.sbx" class="w-full text-sm text-slate-300">
                        </div>

                        <div id="analysis-file-names-container" class="space-y-2"></div>

                        <button type="button" id="analysis-upload-btn" class="w-full bg-slate-800 hover:bg-slate-700 text-white font-bold py-3 rounded transition-colors border border-slate-700">
                            Importer ma couche d'analyse
                        </button>

                        <div id="analysis-import-feedback" class="hidden-element"></div>
                    </form>
                </div>

                <div class="bg-slate-900 p-6 rounded-lg border border-slate-800 mb-4">
                    <h3 class="text-sm font-semibold mb-3 text-slate-400 uppercase tracking-wide">Injection des stress</h3>
                    <p class="text-xs text-brand-400 mb-4 bg-brand-900/20 p-3 rounded border border-brand-800/50">
                        Choisissez votre couche réseau temporaire ci-dessous, puis sélectionnez les couches aléas partagées à injecter en stress.
                        Seul le résultat du run est conservé pour votre compte.
                    </p>

                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-3">
                        <label class="text-sm text-slate-300">
                            Couche principale
                            <select id="alea-main-layer" class="w-full mt-1 bg-slate-950 border border-slate-700 rounded p-2 text-slate-200"></select>
                        </label>

                        <div>
                            <div class="alea-select-toolbar">
                                <label for="layer-alea" class="text-sm text-slate-300">Couches aléa (injection de stress)</label>
                                <span id="alea-selected-count">0/0</span>
                            </div>
                            <select id="layer-alea" multiple class="w-full mt-1 bg-slate-950 border border-slate-700 rounded p-2 text-slate-200 min-h-[120px]"></select>
                            <p id="alea-selection-helper" class="mt-2">Mode automatique: toutes les couches aléa seront injectées.</p>
                            <button type="button" id="alea-clear-btn">Vider la sélection manuelle</button>
                        </div>
                    </div>

                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 items-end">
                        <label class="flex items-center gap-2 text-sm text-slate-300 bg-slate-950/70 border border-slate-700 rounded-lg px-3 py-2">
                            <input type="checkbox" id="alea-all" checked>
                            Prendre toutes les couches aléa
                        </label>

                        <label class="text-sm text-slate-300">
                            Nom de la vue matérialisée
                            <input type="text" id="alea-view-name" placeholder="ex: ma_couche_alea_view" class="w-full mt-1 bg-slate-950 border border-slate-700 rounded p-2 text-slate-200">
                        </label>
                    </div>

                </div>

                <div id="analysis-map-panel" class="bg-slate-900 border border-slate-800 rounded-lg p-4 mt-4">
                    <div class="flex flex-wrap justify-between items-start gap-3 mb-3">
                        <div>
                            <h3 class="text-sm font-semibold text-slate-100 uppercase tracking-wide">Carte d'analyse</h3>
                            <p class="text-xs text-slate-400 mt-2">
                                Aperçu cartographique de la couche infra importée et des runs sélectionnés par l'utilisateur.
                                Fond de carte Positron.
                            </p>
                        </div>
                    </div>

                    <div id="analysis-map-shell">
                        <button type="button" id="analysis-map-fullscreen-btn" class="analysis-map-overlay-btn bg-slate-900/85 border border-slate-700 hover:bg-slate-800 text-slate-200 px-3 py-2 rounded text-sm">
                            Plein écran
                        </button>
                        <div id="analysis-map"></div>
                    </div>
                    <p id="analysis-map-status" class="mt-3 text-xs text-slate-400">
                        Importez une couche réseau temporaire pour afficher l'aperçu.
                    </p>
                    <div class="mt-4">
                        <div class="alea-support-meta mb-3">
                            <div>
                                <h4 class="text-sm font-semibold text-slate-100 uppercase tracking-wide">Affichage cartographique</h4>
                                <p class="text-xs text-slate-400 mt-2">
                                    Activez l'infra importée et les runs à superposer. Les couches aléa ne sont pas affichées sur cette carte.
                                </p>
                            </div>
                        </div>
                        <div id="analysis-map-layer-controls"></div>
                    </div>
                </div>

                <button id="alea-run-btn" class="w-full bg-brand-600 hover:bg-brand-500 text-white py-4 rounded-lg font-bold shadow-lg transition-colors text-lg">
                    Initier le calcul de résilience
                </button>

                <div class="bg-slate-900 border border-slate-800 p-4 rounded-lg mt-4">
                    <span id="alea-progress" class="inline-flex items-center bg-brand-900/30 text-brand-400 border border-brand-800/50 rounded-full px-3 py-1 text-xs" style="display:none;"></span>

                    <div class="flex flex-wrap gap-3 mt-3">
                        <a id="alea-download-link" class="bg-slate-800 border border-slate-700 hover:bg-slate-700 text-slate-200 px-4 py-2 rounded text-sm" href="#" style="display:none;">Télécharger CSV</a>
                        <a id="alea-download-gpkg" class="bg-slate-800 border border-slate-700 hover:bg-slate-700 text-slate-200 px-4 py-2 rounded text-sm" href="#" style="display:none;">Télécharger GPKG</a>
                        <a id="alea-download-shp" class="bg-slate-800 border border-slate-700 hover:bg-slate-700 text-slate-200 px-4 py-2 rounded text-sm" href="#" style="display:none;">Télécharger Shapefile</a>
                    </div>

                    <div id="alea-log" class="mt-4 bg-slate-950 border border-slate-800 rounded p-3 text-xs font-mono text-slate-300 min-h-[90px] max-h-[220px] overflow-y-auto"></div>
                </div>

                <div class="bg-slate-900 border border-slate-800 rounded-lg p-4 mt-6">
                    <h3 class="text-sm font-semibold mb-3 text-slate-400 uppercase tracking-wide">Table Attributaire</h3>
                    <div class="flex items-center gap-3 mb-3">
                        <label for="table-selector" class="text-sm text-slate-300">Table</label>
                        <select id="table-selector" class="bg-slate-950 border border-slate-700 rounded p-2 text-slate-200 min-w-[260px]"></select>
                    </div>
                    <div id="table-container" class="overflow-x-auto"></div>
                </div>
            </div>

            <div id="page-historique" class="hidden-element w-full max-w-6xl mx-auto overflow-y-auto pb-10 h-full">
                <div class="flex justify-between items-end mb-6">
                    <h2 class="text-2xl font-semibold text-slate-100">Historique des Runs</h2>
                    <div class="flex flex-wrap items-center gap-2">
                        <input id="history-search" type="text" placeholder="Rechercher un run..." class="bg-slate-900 border border-slate-800 text-sm p-2 rounded w-64 focus:outline-none focus:border-brand-500">
                        <button id="history-refresh-btn" type="button" class="bg-slate-800 border border-slate-700 hover:bg-slate-700 text-slate-200 px-3 py-2 rounded text-sm">Actualiser</button>
                        <button id="history-delete-selected-btn" type="button" disabled class="bg-red-900/40 border border-red-800/60 hover:bg-red-800/70 disabled:opacity-40 disabled:cursor-not-allowed text-red-200 px-3 py-2 rounded text-sm">Supprimer sélection</button>
                        <button id="history-reset-btn" type="button" class="bg-red-950/70 border border-red-900 hover:bg-red-900/70 text-red-200 px-3 py-2 rounded text-sm">Tout réinitialiser</button>
                    </div>
                </div>
                <p id="history-selection-info" class="text-xs text-slate-500 mb-2">Aucun run sélectionné.</p>
                <div class="bg-slate-900 shadow-lg rounded-lg border border-slate-800 overflow-x-auto">
                    <table class="w-full text-left text-sm whitespace-nowrap">
                        <thead class="bg-slate-950 text-slate-400 font-mono border-b border-slate-800">
                            <tr>
                                <th class="py-3 px-4 font-medium w-10 text-center">
                                    <input id="history-select-all" type="checkbox" class="accent-cyan-500">
                                </th>
                                <th class="py-3 px-4 font-medium">RUN_ID</th>
                                <th class="py-3 px-4 font-medium">Couche principale</th>
                                <th class="py-3 px-4 font-medium">Stress injectés</th>
                                <th class="py-3 px-4 font-medium">Statut</th>
                                <th class="py-3 px-4 font-medium text-right">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="history-list" class="divide-y divide-slate-800/50"></tbody>
                    </table>
                </div>
            </div>

            {% if resilience_context.is_admin %}
            <div id="page-users" class="hidden-element w-full max-w-6xl mx-auto overflow-y-auto pb-10 h-full">
                <h2 class="text-2xl font-semibold text-slate-100 mb-6">Administration & Utilisateurs</h2>
                <div class="grid grid-cols-1 xl:grid-cols-2 gap-6">
                    <section class="bg-slate-900 border border-slate-800 rounded-lg p-6">
                        <h3 class="text-lg font-semibold text-slate-100 mb-2">Créer un utilisateur</h3>
                        <p class="text-sm text-slate-400 mb-4">
                            Créez un compte local et choisissez s'il dispose des droits administrateur.
                        </p>
                        <form id="admin-user-form" class="space-y-4">
                            <label class="block text-sm text-slate-300">
                                Nom d'utilisateur
                                <input id="admin-user-username" type="text" class="w-full mt-1 bg-slate-950 border border-slate-700 rounded p-2 text-slate-200" placeholder="ex: jean.dupont">
                            </label>
                            <label class="block text-sm text-slate-300">
                                Mot de passe
                                <input id="admin-user-password" type="password" class="w-full mt-1 bg-slate-950 border border-slate-700 rounded p-2 text-slate-200" placeholder="8 caractères minimum">
                            </label>
                            <label class="flex items-center gap-2 text-sm text-slate-300 bg-slate-950/70 border border-slate-700 rounded-lg px-3 py-2">
                                <input id="admin-user-is-admin" type="checkbox">
                                Créer ce compte comme administrateur
                            </label>
                            <button type="submit" id="admin-user-submit" class="bg-brand-600 hover:bg-brand-500 text-white font-bold px-4 py-2 rounded transition-colors shadow-lg shadow-brand-500/20">
                                Créer l'utilisateur
                            </button>
                        </form>
                        <div id="admin-user-feedback" class="hidden-element mt-4"></div>
                    </section>

                    <section class="bg-slate-900 border border-slate-800 rounded-lg p-6">
                        <h3 class="text-lg font-semibold text-slate-100 mb-2">Utilisateurs existants</h3>
                        <p class="text-sm text-slate-400 mb-4">
                            Activez ou retirez le rôle administrateur sur les autres comptes.
                        </p>
                        <div id="admin-user-list" class="space-y-3">
                            <em class="text-slate-500 not-italic">Chargement des utilisateurs...</em>
                        </div>
                    </section>
                </div>
            </div>
            {% endif %}

            <div id="page-aide" class="hidden-element w-full max-w-5xl mx-auto overflow-y-auto pb-10 h-full">
                <div id="help-document-panel" class="bg-slate-900 border border-slate-800 rounded-lg p-6 mt-6">
                    <div class="flex flex-wrap justify-between items-start gap-4">
                        <div>
                            <h3 class="text-lg font-semibold text-slate-100 mb-2">Documentation utilisateur</h3>
                            <p class="text-sm text-slate-400">Document mis à disposition par l'administrateur pour les utilisateurs.</p>
                        </div>
                        <div id="help-document-actions" class="flex flex-wrap gap-3">
                            <a id="help-document-preview-link" class="hidden-element bg-slate-800 border border-slate-700 hover:bg-slate-700 text-slate-200 px-4 py-2 rounded text-sm" href="#" target="_blank" rel="noopener">Ouvrir la prévisualisation</a>
                            <a id="help-document-download-link" class="hidden-element bg-brand-600 hover:bg-brand-500 text-white font-bold px-4 py-2 rounded text-sm" href="#">Télécharger</a>
                        </div>
                    </div>
                    <div id="help-document-meta" class="text-sm text-slate-300 mt-4">
                        <em class="text-slate-500 not-italic">Aucun document de référence disponible.</em>
                    </div>
                    <div id="help-document-preview-shell" class="hidden-element mt-5">
                        <iframe id="help-document-preview-frame" title="Prévisualisation du document de référence"></iframe>
                    </div>
                </div>
                {% if resilience_context.is_admin %}
                <div class="bg-slate-900 border border-slate-800 rounded-lg p-6 mt-6">
                    <h3 class="text-lg font-semibold text-slate-100 mb-2">Document admin à diffuser</h3>
                    <p class="text-sm text-slate-400 mb-4">
                        Importez un document PDF ou Word pour les utilisateurs. Un nouvel import remplace immédiatement la version précédente. Pour une prévisualisation fidèle dans l'application, privilégiez un PDF.
                    </p>
                    <form id="help-document-form" class="space-y-4" enctype="multipart/form-data">
                        <label class="block text-sm text-slate-300">
                            Fichier PDF, DOC ou DOCX
                            <input id="help-document-file" type="file" accept=".pdf,.doc,.docx" class="w-full mt-1 bg-slate-950 border border-slate-700 rounded p-2 text-slate-200">
                        </label>
                        <div class="flex flex-wrap gap-3">
                            <button type="submit" id="help-document-upload-btn" class="bg-brand-600 hover:bg-brand-500 text-white font-bold px-4 py-2 rounded transition-colors shadow-lg shadow-brand-500/20">
                                Importer / Remplacer le document
                            </button>
                            <button type="button" id="help-document-delete-btn" class="bg-red-950/70 border border-red-900 hover:bg-red-900/70 text-red-200 px-4 py-2 rounded text-sm">
                                Supprimer le document
                            </button>
                        </div>
                    </form>
                    <div id="help-document-feedback" class="hidden-element mt-4"></div>
                </div>
                {% endif %}
            </div>
        </main>
    </div>

    <script>
        window.RESILIENCE_CONTEXT = {{ resilience_context|tojson }};

        function switchTab(tabName) {
            const tabs = ['config', 'analyse', 'historique', 'aide'];
            if (window.RESILIENCE_CONTEXT && window.RESILIENCE_CONTEXT.is_admin) {
                tabs.splice(3, 0, 'users');
            }
            if (!tabs.includes(tabName)) {
                tabName = 'config';
            }

            tabs.forEach(name => {
                const page = document.getElementById('page-' + name);
                const nav = document.getElementById('nav-' + name);
                if (page) page.classList.add('hidden-element');
                if (nav) nav.className = "pb-1 border-b-2 border-transparent hover:text-slate-100";
            });
            const activePage = document.getElementById('page-' + tabName);
            const activeNav = document.getElementById('nav-' + tabName);
            if (activePage) activePage.classList.remove('hidden-element');
            if (activeNav) activeNav.className = "pb-1 border-b-2 border-brand-400 text-brand-400";

            if (tabName === 'config' && window.__resilienceMap) {
                setTimeout(() => window.__resilienceMap.invalidateSize(), 120);
            }
            if (tabName === 'analyse' && window.__analysisMap) {
                setTimeout(() => window.__analysisMap.invalidateSize(), 120);
            }
            if (tabName === 'historique' && typeof window.loadResilienceHistory === 'function') {
                window.loadResilienceHistory();
            }
            if (tabName === 'users' && typeof window.loadResilienceAdminUsers === 'function') {
                window.loadResilienceAdminUsers();
            }
            if (tabName === 'aide' && typeof window.loadResilienceHelpContent === 'function') {
                window.loadResilienceHelpContent();
            }
        }

        document.addEventListener('DOMContentLoaded', function () {
            switchTab('config');
        });
    </script>

    <script src="{{ url_for('static', filename='js/resilience.js', v='20260410-admin-roles-help') }}"></script>
</body>
</html>
````

#### templates/login_resilience.html

````html
<!DOCTYPE html>
<html lang="fr" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Connexion - SippeRésiste Résilience</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: { brand: { 400: '#22d3ee', 500: '#06b6d4', 600: '#0891b2' } }
                }
            }
        }
    </script>
    <style>
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #0f172a; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #475569; }
    </style>
</head>
<body class="bg-slate-950 font-sans text-slate-300 min-h-screen flex items-center justify-center overflow-x-hidden">
    <div class="fixed inset-0 bg-slate-950 z-0 flex items-center justify-center">
        <div class="bg-gradient-to-br from-slate-900 to-slate-950 p-12 rounded-2xl border border-slate-800 shadow-2xl w-full max-w-md z-10">
            <div class="text-center mb-10">
                <div class="flex justify-center mb-6">
                    <div class="w-32 h-32 bg-slate-800 rounded-full flex items-center justify-center shadow-2xl border-4 border-brand-500" style="box-shadow: 0 20px 60px rgba(6, 182, 212, 0.8), 0 0 40px rgba(34, 211, 238, 0.5)">
                        <img src="https://sig.sipperec.com/maps/img/SIPPEREC_NEWLOGO-MONOCHROME_BLANC.png" alt="Logo SIPPEREC" class="h-24 object-contain filter drop-shadow-2xl">
                    </div>
                </div>
                <h1 class="font-bold text-3xl tracking-wider text-brand-400 mb-2">SippeRésiste</h1>
                <p class="text-slate-500 text-sm">Plateforme d'Analyse de Résilience Réseau</p>
            </div>

            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    <div class="mb-6 space-y-2">
                        {% for category, message in messages %}
                            <div class="{% if category == 'danger' %}bg-red-900/30 border border-red-800 text-red-300{% else %}bg-emerald-900/30 border border-emerald-800 text-emerald-300{% endif %} p-3 rounded-lg text-sm">
                                {{ message }}
                            </div>
                        {% endfor %}
                    </div>
                {% endif %}
            {% endwith %}

            <form method="POST" class="space-y-4">
                <div>
                    <label class="block text-sm font-medium text-slate-400 mb-1">Identifiant</label>
                    <input type="text" id="username" name="username" required class="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-slate-200 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500/30 transition-colors">
                </div>
                <div>
                    <label class="block text-sm font-medium text-slate-400 mb-1">Mot de passe</label>
                    <input type="password" id="password" name="password" required class="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-slate-200 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500/30 transition-colors">
                </div>

                <button type="submit" class="w-full bg-brand-600 hover:bg-brand-500 text-white font-bold py-3 rounded-lg mt-6 transition-colors shadow-lg shadow-brand-500/20">
                    Connexion Sécurisée
                </button>

                <div class="text-center pt-2">
                    <a href="{{ url_for('forgot_password') }}" class="text-sm text-brand-400 hover:text-brand-300 transition-colors">Mot de passe oublié ?</a>
                </div>
            </form>
        </div>
    </div>
</body>
</html>
````

#### templates/login.html

````html
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Connexion</title>
    <style>
        /* Reset de base */
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Poppins', sans-serif;
            background: linear-gradient(135deg, #003d6b, #005aa3);
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
        }

        /* Container de connexion */
        .login-container {
            background: #fff;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.2);
            text-align: center;
            width: 350px;
        }

        h2 {
            margin-bottom: 20px;
            color: #005aa3;
        }

        /* Champs de formulaire */
        .form-group {
            margin-bottom: 15px;
            text-align: left;
        }

        label {
            display: block;
            font-weight: bold;
            margin-bottom: 5px;
        }

        input {
            width: 100%;
            padding: 10px;
            border: 1px solid #ccc;
            border-radius: 5px;
        }

        /* Bouton */
        .btn {
            width: 100%;
            padding: 10px;
            background: #005aa3;
            border: none;
            border-radius: 5px;
            color: #fff;
            font-size: 1rem;
            font-weight: bold;
            cursor: pointer;
            transition: background 0.3s;
        }

        .btn:hover {
            background: #003d6b;
        }

        /* Messages d'erreur ou de succès */
        .flash-messages {
            margin-bottom: 15px;
        }

        .flash-messages p {
            padding: 10px;
            border-radius: 5px;
            font-size: 0.9rem;
        }

        .flash-messages .danger {
            background: #ffcccc;
            color: #900;
        }

        .flash-messages .success {
            background: #ccffcc;
            color: #090;
        }
    </style>
</head>
<body>

<div class="login-container">
    <h2>Connexion</h2>

    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            <div class="flash-messages">
                {% for category, message in messages %}
                    <p class="{{ category }}">{{ message }}</p>
                {% endfor %}
            </div>
        {% endif %}
    {% endwith %}

    <form method="POST">
        <div class="form-group">
            <label for="username">Nom d'utilisateur :</label>
            <input type="text" id="username" name="username" required>
        </div>

        <div class="form-group">
            <label for="password">Mot de passe :</label>
            <input type="password" id="password" name="password" required>
        </div>

        <button type="submit" class="btn">Se connecter</button>
        <p><a href="{{ url_for('forgot_password') }}">Mot de passe oublié ?</a></p>

    </form>
</div>

</body>
</html>
````

#### templates/forgot_password.html

````html
<!DOCTYPE html>
<html lang="fr" class="dark">
<head>
  <meta charset="utf-8">
  <title>Mot de passe oublié</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: { brand: { 400: '#22d3ee', 500: '#06b6d4', 600: '#0891b2' } }
        }
      }
    }
  </script>
  <style>
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: #0f172a; }
    ::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }
    ::-webkit-scrollbar-thumb:hover { background: #475569; }
  </style>
</head>
<body class="bg-slate-950 font-sans text-slate-300 min-h-screen flex items-center justify-center overflow-x-hidden">
  <div class="fixed inset-0 bg-slate-950 z-0 flex items-center justify-center">
    <div class="bg-gradient-to-br from-slate-900 to-slate-950 p-12 rounded-2xl border border-slate-800 shadow-2xl w-full max-w-md z-10">
      <div class="text-center mb-10">
        <div class="flex justify-center mb-6">
          <div class="w-32 h-32 bg-slate-800 rounded-full flex items-center justify-center shadow-2xl border-4 border-brand-500" style="box-shadow: 0 20px 60px rgba(6, 182, 212, 0.8), 0 0 40px rgba(34, 211, 238, 0.5)">
            <img src="https://sig.sipperec.com/maps/img/SIPPEREC_NEWLOGO-MONOCHROME_BLANC.png" alt="Logo SIPPEREC" class="h-24 object-contain filter drop-shadow-2xl">
          </div>
        </div>
        <h1 class="font-bold text-3xl tracking-wider text-brand-400 mb-2">Réinitialisation</h1>
        <p class="text-slate-500 text-sm">Mot de passe oublié</p>
      </div>

      {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
          <div class="mb-6 space-y-2">
            {% for category, message in messages %}
              <div class="{% if category == 'danger' %}bg-red-900/30 border border-red-800 text-red-300{% elif category == 'success' %}bg-emerald-900/30 border border-emerald-800 text-emerald-300{% elif category == 'warning' %}bg-yellow-900/30 border border-yellow-800 text-yellow-300{% else %}bg-cyan-900/30 border border-cyan-800 text-cyan-300{% endif %} p-3 rounded-lg text-sm">
                {{ message|safe }}
              </div>
            {% endfor %}
          </div>
        {% endif %}
      {% endwith %}

      <form method="POST" class="space-y-4">
        <div>
          <label for="username" class="block text-sm font-medium text-slate-300 mb-1">Identifiant</label>
          <input id="username" name="username" type="text" class="w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 transition" autocomplete="username" required>
        </div>

        <div class="pt-4 flex gap-3">
          <a href="{{ url_for('login') }}" class="flex-1 px-4 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 rounded-lg font-medium transition-colors text-center">Retour</a>
          <button type="submit" class="flex-1 px-4 py-2 bg-gradient-to-r from-brand-500 to-brand-600 hover:from-brand-600 hover:to-cyan-700 text-white rounded-lg font-medium shadow-lg hover:shadow-brand-500/50 transition-all">Envoyer le lien</button>
        </div>
      </form>
    </div>
  </div>

</body>
</html>
````

#### templates/reset_password.html

````html
<!DOCTYPE html>
<html lang="fr" class="dark">
<head>
  <meta charset="utf-8">
  <title>Réinitialiser le mot de passe</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: { brand: { 400: '#22d3ee', 500: '#06b6d4', 600: '#0891b2' } }
        }
      }
    }
  </script>
  <style>
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: #0f172a; }
    ::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }
    ::-webkit-scrollbar-thumb:hover { background: #475569; }
  </style>
</head>
<body class="bg-slate-950 font-sans text-slate-300 min-h-screen flex items-center justify-center overflow-x-hidden">
  <div class="fixed inset-0 bg-slate-950 z-0 flex items-center justify-center">
    <div class="bg-gradient-to-br from-slate-900 to-slate-950 p-12 rounded-2xl border border-slate-800 shadow-2xl w-full max-w-md z-10">
      <div class="text-center mb-10">
        <div class="flex justify-center mb-6">
          <div class="w-32 h-32 bg-slate-800 rounded-full flex items-center justify-center shadow-2xl border-4 border-brand-500" style="box-shadow: 0 20px 60px rgba(6, 182, 212, 0.8), 0 0 40px rgba(34, 211, 238, 0.5)">
            <img src="https://sig.sipperec.com/maps/img/SIPPEREC_NEWLOGO-MONOCHROME_BLANC.png" alt="Logo SIPPEREC" class="h-24 object-contain filter drop-shadow-2xl">
          </div>
        </div>
        <h1 class="font-bold text-3xl tracking-wider text-brand-400 mb-2">Réinitialisation</h1>
        <p class="text-slate-500 text-sm">Définir un nouveau mot de passe</p>
      </div>

      {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
          <div class="mb-6 space-y-2">
            {% for category, message in messages %}
              <div class="{% if category == 'danger' %}bg-red-900/30 border border-red-800 text-red-300{% elif category == 'success' %}bg-emerald-900/30 border border-emerald-800 text-emerald-300{% elif category == 'warning' %}bg-yellow-900/30 border border-yellow-800 text-yellow-300{% else %}bg-cyan-900/30 border border-cyan-800 text-cyan-300{% endif %} p-3 rounded-lg text-sm">
                {{ message }}
              </div>
            {% endfor %}
          </div>
        {% endif %}
      {% endwith %}

      <form method="POST" class="space-y-4">
        <div>
          <label for="password" class="block text-sm font-medium text-slate-300 mb-1">Nouveau mot de passe</label>
          <div class="relative">
            <input id="password" name="password" type="password" class="w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 transition" minlength="12" autocomplete="new-password" required>
            <button type="button" class="absolute right-3 top-8 text-sm text-brand-400 hover:text-brand-300 transition-colors font-medium" onclick="togglePwd('password', this)">Afficher</button>
          </div>
        </div>

        <div>
          <label for="confirm" class="block text-sm font-medium text-slate-300 mb-1">Confirmer le mot de passe</label>
          <div class="relative">
            <input id="confirm" name="confirm" type="password" class="w-full px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-100 placeholder-slate-500 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 transition" minlength="12" autocomplete="new-password" required>
            <button type="button" class="absolute right-3 top-8 text-sm text-brand-400 hover:text-brand-300 transition-colors font-medium" onclick="togglePwd('confirm', this)">Afficher</button>
          </div>
        </div>

        <div class="pt-4 flex gap-3">
          <a href="{{ url_for('login') }}" class="flex-1 px-4 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 rounded-lg font-medium transition-colors text-center">Retour</a>
          <button type="submit" class="flex-1 px-4 py-2 bg-gradient-to-r from-brand-500 to-brand-600 hover:from-brand-600 hover:to-cyan-700 text-white rounded-lg font-medium shadow-lg hover:shadow-brand-500/50 transition-all">Valider</button>
        </div>

        <p class="text-xs text-slate-500 text-center mt-6">Le lien de réinitialisation expire automatiquement et devient invalide dès que votre mot de passe change.</p>
      </form>
    </div>
  </div>

  <script>
    function togglePwd(id, btn) {
      const input = document.getElementById(id);
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.textContent = show ? 'Masquer' : 'Afficher';
    }
  </script>
</body>
</html>
````

### Front-end JavaScript

#### static/js/resilience.js

````javascript
// ========== RESILIENCE.JS COMPLET CORRIGÉ ==========

document.addEventListener('DOMContentLoaded', function () {
    const resilienceContext = window.RESILIENCE_CONTEXT || {};
    const isAdminUser = !!resilienceContext.is_admin;
    const map = L.map('resilience-map').setView([48.86, 2.35], 10);
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        subdomains: 'abcd',
        maxZoom: 20,
        attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
    }).addTo(map);
    window.__resilienceMap = map;

    let layerStore = {}; // Stocke les couches actives
    let mainLayers = [];
    let aleaLayers = [];

    const fileInput = document.getElementById('resilience-files');
    const fileNamesContainer = document.getElementById('file-names-container');
    const uploadBtn = document.getElementById('resilience-upload-btn');
    const configMapPanel = document.getElementById('resilience-map-panel');
    const configMapFullscreenBtn = document.getElementById('resilience-map-fullscreen-btn');
    const analysisFileInput = document.getElementById('analysis-layer-files');
    const analysisFileNamesContainer = document.getElementById('analysis-file-names-container');
    const analysisUploadBtn = document.getElementById('analysis-upload-btn');
    const analysisMapContainer = document.getElementById('analysis-map');
    const analysisMapShell = document.getElementById('analysis-map-shell');
    const analysisMapPanel = document.getElementById('analysis-map-panel');
    const analysisMapFullscreenBtn = document.getElementById('analysis-map-fullscreen-btn');
    const analysisMapStatus = document.getElementById('analysis-map-status');
    const analysisMapLayerControls = document.getElementById('analysis-map-layer-controls');

    const tableContainer = document.getElementById('table-container');
    const tableSelector = document.getElementById('table-selector');
    const layerControls = document.getElementById('layer-controls');
    const impactMatrixContainer = document.getElementById('impact-matrix-container');
    const impactMatrixSaveBtn = document.getElementById('impact-matrix-save-btn');

    // === Sélection des couches pour vue matérialisée ===
    const layerAlea = document.getElementById('layer-alea');
    const aleaAllCheckbox = document.getElementById('alea-all');

    // --- Test aléas ---
    const aleaMainLayer = document.getElementById('alea-main-layer');
    const aleaRunBtn = document.getElementById('alea-run-btn');
    const aleaProgress = document.getElementById('alea-progress');
    const aleaLog = document.getElementById('alea-log');
    const aleaDownloadCsv = document.getElementById('alea-download-link');
    const aleaDownloadGpkg = document.getElementById('alea-download-gpkg');
    const aleaDownloadShp = document.getElementById('alea-download-shp');
    const aleaViewName = document.getElementById('alea-view-name');
    const aleaSupportList = document.getElementById('alea-support-list');
    const aleaSupportCount = document.getElementById('alea-support-count');
    const aleaSelectedCount = document.getElementById('alea-selected-count');
    const aleaSelectionHelper = document.getElementById('alea-selection-helper');
    const aleaClearBtn = document.getElementById('alea-clear-btn');
    const historyList = document.getElementById('history-list');
    const historySearchInput = document.getElementById('history-search');
    const historyRefreshBtn = document.getElementById('history-refresh-btn');
    const historySelectAll = document.getElementById('history-select-all');
    const historyDeleteSelectedBtn = document.getElementById('history-delete-selected-btn');
    const historyResetBtn = document.getElementById('history-reset-btn');
    const historySelectionInfo = document.getElementById('history-selection-info');
    const adminUserForm = document.getElementById('admin-user-form');
    const adminUserUsername = document.getElementById('admin-user-username');
    const adminUserPassword = document.getElementById('admin-user-password');
    const adminUserIsAdmin = document.getElementById('admin-user-is-admin');
    const adminUserSubmit = document.getElementById('admin-user-submit');
    const adminUserList = document.getElementById('admin-user-list');
    const adminUserFeedback = document.getElementById('admin-user-feedback');
    const helpPageTitle = document.getElementById('help-page-title');
    const helpPageBody = document.getElementById('help-page-body');
    const helpDocumentPanel = document.getElementById('help-document-panel');
    const helpDocumentMeta = document.getElementById('help-document-meta');
    const helpDocumentPreviewLink = document.getElementById('help-document-preview-link');
    const helpDocumentDownloadLink = document.getElementById('help-document-download-link');
    const helpDocumentPreviewShell = document.getElementById('help-document-preview-shell');
    const helpDocumentPreviewFrame = document.getElementById('help-document-preview-frame');
    const helpDocumentForm = document.getElementById('help-document-form');
    const helpDocumentFileInput = document.getElementById('help-document-file');
    const helpDocumentUploadBtn = document.getElementById('help-document-upload-btn');
    const helpDocumentDeleteBtn = document.getElementById('help-document-delete-btn');
    const helpDocumentFeedback = document.getElementById('help-document-feedback');
    const selectedRunIds = new Set();
    let historySearchTimer = null;
    const importFeedback = document.getElementById('import-feedback');
    let importFeedbackTimer = null;
    const analysisImportFeedback = document.getElementById('analysis-import-feedback');
    let analysisImportFeedbackTimer = null;
    const layerActionFeedback = document.getElementById('layer-action-feedback');
    let layerActionFeedbackTimer = null;
    const impactMatrixFeedback = document.getElementById('impact-matrix-feedback');
    let impactMatrixFeedbackTimer = null;
    let adminUserFeedbackTimer = null;
    let helpDocumentFeedbackTimer = null;
    let analysisMapLayerStore = {};
    let analysisMapRefreshToken = 0;
    let analysisMapRefreshTimer = null;
    let analysisRunChoices = [];
    const analysisMap = analysisMapContainer
        ? L.map('analysis-map', { preferCanvas: true }).setView([48.86, 2.35], 10)
        : null;

    if (analysisMap) {
        L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
            subdomains: 'abcd',
            maxZoom: 20,
            attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
        }).addTo(analysisMap);
        window.__analysisMap = analysisMap;
    }

    // ========== Upload de fichiers ========== //
    const SHP_EXTS = new Set(['.shp', '.shx', '.dbf', '.prj', '.cpg', '.sbn', '.sbx']);
    const SHP_REQUIRED = ['.shp', '.shx', '.dbf'];
    const ALLOWED_EXTS = new Set(['.gpkg', '.shp', '.shx', '.dbf', '.prj', '.cpg', '.sbn', '.sbx']);
    let uploadDatasets = [];
    let analysisUploadDatasets = [];

    function getExt(filename) {
        const idx = filename.lastIndexOf('.');
        return idx >= 0 ? filename.slice(idx).toLowerCase() : '';
    }

    function escapeHtml(value) {
        return String(value)
            .replaceAll('&', '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;')
            .replaceAll('"', '&quot;')
            .replaceAll("'", '&#39;');
    }

    function prettifyLayerName(layer) {
        const stripped = String(layer).replace(/^alea_/, '');
        const withSpaces = stripped.replaceAll('_', ' ').replace(/\s+/g, ' ').trim();
        if (!withSpaces) return String(layer);
        return withSpaces.replace(/\b\w/g, (c) => c.toUpperCase());
    }

    function layerTypeLabel(type) {
        if (type === 'materialized_view') return 'vue materialisee';
        if (type === 'view') return 'vue';
        if (type === 'table') return 'table';
        return 'objet';
    }

    function normalizeLayerDependencies(dependencies) {
        if (!Array.isArray(dependencies)) return [];
        return dependencies
            .map((dep) => {
                if (!dep) return null;
                if (typeof dep === 'string') {
                    const name = dep.trim();
                    return name ? { name, type: 'object', label: 'objet' } : null;
                }

                const name = String(dep.name || '').trim();
                if (!name) return null;

                const type = String(dep.type || 'object').trim();
                const label = String(dep.label || layerTypeLabel(type)).trim();
                return { name, type, label };
            })
            .filter(Boolean);
    }

    function buildLayerDeleteConfirmMessage(layer, details) {
        const typeLabel = layerTypeLabel(details && details.layer_type);
        const dependencies = normalizeLayerDependencies(details && details.dependencies);
        const lines = [
            `Suppression de la couche "${layer}"`,
            '',
            `Type detecte : ${typeLabel}.`,
            "Cette action supprimera definitivement cette couche de la base Resilience."
        ];

        if (dependencies.length) {
            lines.push(
                '',
                `Impact detecte : ${dependencies.length} dependance(s) seront aussi supprimee(s) en cascade :`
            );
            dependencies.forEach((dep) => {
                lines.push(`- ${dep.name} (${dep.label})`);
            });
        } else {
            lines.push('', 'Aucune dependance applicative detectee.');
        }

        lines.push('', 'Cette action est irreversible.', 'Confirmer la suppression ?');
        return lines.join('\n');
    }

    function buildLayerDeleteFallbackMessage(layer, errorMessage) {
        return [
            `Suppression de la couche "${layer}"`,
            '',
            "L'impact n'a pas pu etre verifie avant suppression.",
            `Detail : ${errorMessage || 'information indisponible'}.`,
            '',
            'La suppression reste irreversible.',
            'Souhaitez-vous continuer ?'
        ].join('\n');
    }

    function buildLayerDeleteSuccessMessage(result, layer) {
        const dependencies = normalizeLayerDependencies(result && result.dependencies);
        const lines = [
            `Suppression terminee pour la couche "${layer}".`
        ];

        if (dependencies.length) {
            lines.push(
                `${dependencies.length} dependance(s) ont aussi ete supprimee(s) en cascade : ${dependencies.map((dep) => dep.name).join(', ')}.`
            );
        } else {
            lines.push('Aucune dependance supplementaire n\'a ete supprimee.');
        }

        return lines.join(' ');
    }

    function buildLayerDeleteErrorMessage(layer, errorMessage) {
        return `Suppression impossible pour la couche "${layer}" : ${errorMessage || 'erreur inconnue.'}`;
    }

    function setAnalysisMapStatus(message, tone = 'neutral') {
        if (!analysisMapStatus) return;
        analysisMapStatus.textContent = message;
        analysisMapStatus.classList.remove('text-slate-400', 'text-red-400', 'text-emerald-400', 'text-brand-400');
        if (tone === 'error') {
            analysisMapStatus.classList.add('text-red-400');
        } else if (tone === 'success') {
            analysisMapStatus.classList.add('text-emerald-400');
        } else if (tone === 'info') {
            analysisMapStatus.classList.add('text-brand-400');
        } else {
            analysisMapStatus.classList.add('text-slate-400');
        }
    }

    function isConfigMapFullscreen() {
        if (!configMapPanel) return false;
        return document.fullscreenElement === configMapPanel
            || document.webkitFullscreenElement === configMapPanel
            || configMapPanel.classList.contains('resilience-map-panel-fallback-fullscreen');
    }

    function syncConfigMapFullscreenButton() {
        if (!configMapFullscreenBtn) return;
        configMapFullscreenBtn.textContent = isConfigMapFullscreen() ? 'Quitter plein écran' : 'Plein écran';
        setTimeout(() => map.invalidateSize(), 140);
    }

    async function toggleConfigMapFullscreen() {
        if (!configMapPanel) return;

        try {
            if (document.fullscreenElement === configMapPanel || document.webkitFullscreenElement === configMapPanel) {
                if (document.exitFullscreen) {
                    await document.exitFullscreen();
                } else if (document.webkitExitFullscreen) {
                    document.webkitExitFullscreen();
                }
            } else if (configMapPanel.requestFullscreen) {
                await configMapPanel.requestFullscreen();
            } else if (configMapPanel.webkitRequestFullscreen) {
                configMapPanel.webkitRequestFullscreen();
            } else {
                configMapPanel.classList.toggle('resilience-map-panel-fallback-fullscreen');
            }
        } catch (_error) {
            configMapPanel.classList.toggle('resilience-map-panel-fallback-fullscreen');
        }

        syncConfigMapFullscreenButton();
    }

    function clearAnalysisMapLayers() {
        if (!analysisMap) return;
        Object.values(analysisMapLayerStore).forEach((layer) => {
            if (layer && analysisMap.hasLayer(layer)) {
                analysisMap.removeLayer(layer);
            }
        });
        analysisMapLayerStore = {};
    }

    function fetchResilienceLayerData(layerName) {
        return fetch(`/resilience_layer_data/${encodeURIComponent(layerName)}`)
            .then(async (response) => {
                const data = await response.json().catch(() => ({}));
                if (!response.ok || data.status !== 'ok') {
                    throw new Error(data.message || `HTTP ${response.status}`);
                }
                return data;
            });
    }

    function buildAnalysisPreviewPopup(layerName, roleLabel, properties) {
        const safeRole = escapeHtml(roleLabel);
        const safeLayer = escapeHtml(layerName);
        const propEntries = Object.entries(properties || {});
        const propHtml = propEntries.length
            ? propEntries.map(([key, value]) => `<strong>${escapeHtml(key)}</strong>: ${escapeHtml(value ?? '')}`).join('<br>')
            : '<em>Aucun attribut</em>';
        return `<div><strong>${safeRole}</strong><br><span>${safeLayer}</span><hr style="margin:6px 0;border-color:#334155;">${propHtml}</div>`;
    }

    function defaultAnalysisLayerColor(role, index = 0) {
        const runColors = ['#a855f7', '#ef4444', '#0ea5e9', '#84cc16', '#f59e0b', '#ec4899'];
        return role === 'main' ? '#f97316' : runColors[index % runColors.length];
    }

    function getAnalysisMapLayerStateMap() {
        const state = {};
        if (!analysisMapLayerControls) return state;

        Array.from(analysisMapLayerControls.querySelectorAll('.analysis-map-layer-row[data-layer]')).forEach((row, index) => {
            const layerName = String(row.dataset.layer || '').trim();
            if (!layerName) return;

            const role = String(row.dataset.role || 'run').trim();
            const toggle = row.querySelector('.analysis-map-layer-toggle');
            const colorInput = row.querySelector('.analysis-map-layer-color');
            state[layerName] = {
                checked: !!(toggle && toggle.checked),
                color: colorInput && colorInput.value ? colorInput.value : defaultAnalysisLayerColor(role, index),
                role
            };
        });

        return state;
    }

    function renderAnalysisMapLayerControls(preferredState = {}) {
        if (!analysisMapLayerControls) return;

        const mainLayerName = String((aleaMainLayer && aleaMainLayer.value) || '').trim();
        const doneRuns = Array.isArray(analysisRunChoices)
            ? analysisRunChoices
                .filter((run) => String(run.status || '').toLowerCase() === 'done')
                .filter((run) => String(run.view_name || run.layer_name || '').trim().length > 0)
            : [];

        analysisMapLayerControls.innerHTML = '';

        if (!mainLayerName && !doneRuns.length) {
            analysisMapLayerControls.innerHTML = '<em>Aucune couche infra temporaire ni aucun run disponible pour la carte.</em>';
            return;
        }

        if (mainLayerName) {
            const mainState = preferredState[mainLayerName] || {};
            const wrapper = document.createElement('div');
            wrapper.className = 'analysis-map-layer-row';
            wrapper.dataset.layer = mainLayerName;
            wrapper.dataset.role = 'main';
            wrapper.innerHTML = `
                <input type="checkbox" class="analysis-map-layer-toggle" data-layer="${escapeHtml(mainLayerName)}" checked>
                <label>
                    <strong>${escapeHtml(mainLayerName)}</strong><br>
                    <span class="text-xs text-slate-500">Couche infra importée pour l'analyse réseau</span>
                </label>
                <input type="color" class="layer-color analysis-map-layer-color" data-layer="${escapeHtml(mainLayerName)}" value="${escapeHtml(mainState.color || defaultAnalysisLayerColor('main', 0))}">
            `;
            const toggle = wrapper.querySelector('.analysis-map-layer-toggle');
            if (toggle) {
                toggle.checked = typeof mainState.checked === 'boolean' ? mainState.checked : true;
            }
            analysisMapLayerControls.appendChild(wrapper);
        }

        doneRuns.forEach((run, index) => {
            const layerName = String(run.view_name || run.layer_name || '').trim();
            if (!layerName) return;

            const runState = preferredState[layerName] || {};
            const subtitleParts = ['Run utilisateur'];
            const createdAt = formatRunDate(run.created_at);
            if (createdAt) subtitleParts.push(createdAt);
            if (run.main_layer) subtitleParts.push(`source: ${run.main_layer}`);

            const wrapper = document.createElement('div');
            wrapper.className = 'analysis-map-layer-row';
            wrapper.dataset.layer = layerName;
            wrapper.dataset.role = 'run';
            wrapper.innerHTML = `
                <input type="checkbox" class="analysis-map-layer-toggle" data-layer="${escapeHtml(layerName)}">
                <label>
                    <strong>${escapeHtml(layerName)}</strong><br>
                    <span class="text-xs text-slate-500">${escapeHtml(subtitleParts.join(' · '))}</span>
                </label>
                <input type="color" class="layer-color analysis-map-layer-color" data-layer="${escapeHtml(layerName)}" value="${escapeHtml(runState.color || defaultAnalysisLayerColor('run', index))}">
            `;
            const toggle = wrapper.querySelector('.analysis-map-layer-toggle');
            if (toggle) {
                toggle.checked = typeof runState.checked === 'boolean' ? runState.checked : false;
            }
            analysisMapLayerControls.appendChild(wrapper);
        });
    }

    function createAnalysisPreviewLayer(layerName, role, features, color) {
        const roleLabel = role === 'main' ? 'Couche infra importée' : 'Résultat de run';

        return L.geoJSON(features || [], {
            style: () => ({
                color,
                weight: 3,
                opacity: role === 'main' ? 0.95 : 0.8,
                fillColor: color,
                fillOpacity: role === 'main' ? 0.08 : 0.06,
                dashArray: role === 'main' ? null : '10 6'
            }),
            pointToLayer: (_feature, latlng) => L.circleMarker(latlng, {
                radius: 6,
                color,
                weight: 2,
                fillColor: color,
                fillOpacity: role === 'main' ? 0.3 : 0.12
            }),
            onEachFeature: (feature, layer) => {
                layer.bindPopup(buildAnalysisPreviewPopup(layerName, roleLabel, feature.properties || {}));
            }
        });
    }

    function getAnalysisPreviewSelection() {
        const mainLayerName = String((aleaMainLayer && aleaMainLayer.value) || '').trim();
        const selectedLayers = analysisMapLayerControls
            ? Array.from(analysisMapLayerControls.querySelectorAll('.analysis-map-layer-row[data-layer]'))
                .map((row, index) => {
                    const layerName = String(row.dataset.layer || '').trim();
                    if (!layerName) return null;

                    const toggle = row.querySelector('.analysis-map-layer-toggle');
                    if (!toggle || !toggle.checked) return null;

                    const role = String(row.dataset.role || 'run').trim();
                    const colorInput = row.querySelector('.analysis-map-layer-color');
                    return {
                        key: `${role}:${layerName}`,
                        name: layerName,
                        role,
                        index,
                        color: colorInput && colorInput.value ? colorInput.value : defaultAnalysisLayerColor(role, index)
                    };
                })
                .filter(Boolean)
            : [];

        return { mainLayerName, selectedLayers };
    }

    function scheduleAnalysisMapRefresh(delay = 120) {
        if (!analysisMap) return;
        if (analysisMapRefreshTimer) clearTimeout(analysisMapRefreshTimer);
        analysisMapRefreshTimer = setTimeout(() => {
            analysisMapRefreshTimer = null;
            refreshAnalysisMapPreview();
        }, delay);
    }

    async function refreshAnalysisMapPreview() {
        if (!analysisMap) return;

        const token = ++analysisMapRefreshToken;
        const { mainLayerName, selectedLayers } = getAnalysisPreviewSelection();
        clearAnalysisMapLayers();
        analysisMap.invalidateSize();

        if (!selectedLayers.length) {
            if (mainLayerName) {
                setAnalysisMapStatus("Cochez la couche infra importée et/ou les runs à afficher sur la carte.", 'neutral');
            } else {
                setAnalysisMapStatus("Importez une couche infra ou cochez un run utilisateur pour afficher la carte d'analyse.", 'neutral');
            }
            return;
        }

        setAnalysisMapStatus('Chargement de la carte d’analyse...', 'info');

        const results = await Promise.all(selectedLayers.map(async (spec) => {
            try {
                const data = await fetchResilienceLayerData(spec.name);
                if (token !== analysisMapRefreshToken) return null;
                const layer = createAnalysisPreviewLayer(spec.name, spec.role, data.features, spec.color);
                layer.addTo(analysisMap);
                analysisMapLayerStore[spec.key] = layer;
                return { spec, layer };
            } catch (error) {
                return { spec, error };
            }
        }));

        if (token !== analysisMapRefreshToken) return;

        const loadedLayers = results.filter((result) => result && result.layer);
        const failedLayers = results.filter((result) => result && result.error);

        if (!loadedLayers.length) {
            const firstError = failedLayers[0] && failedLayers[0].error ? failedLayers[0].error.message : "Aucune couche n'a pu être chargée.";
            setAnalysisMapStatus(firstError, 'error');
            return;
        }

        const boundsGroup = L.featureGroup(loadedLayers.map((entry) => entry.layer));
        const bounds = boundsGroup.getBounds();
        if (bounds && bounds.isValid()) {
            analysisMap.fitBounds(bounds.pad(0.08));
        }

        const hasMainLayer = selectedLayers.some((layer) => layer.role === 'main');
        const selectedRunCount = selectedLayers.filter((layer) => layer.role === 'run').length;
        let statusMessage = hasMainLayer
            ? `Couche infra affichée: ${mainLayerName || 'couche importée'}`
            : 'Couche infra non affichée';
        statusMessage += selectedRunCount
            ? ` · ${selectedRunCount} run(s) utilisateur superposé(s).`
            : ' · aucun run utilisateur affiché.';
        if (failedLayers.length) {
            statusMessage += ` · ${failedLayers.length} couche(s) n'ont pas pu être chargées.`;
        }
        setAnalysisMapStatus(statusMessage, failedLayers.length ? 'error' : 'success');
    }

    function isAnalysisMapFullscreen() {
        if (!analysisMapShell) return false;
        return document.fullscreenElement === analysisMapShell
            || document.webkitFullscreenElement === analysisMapShell
            || analysisMapShell.classList.contains('analysis-map-shell-fallback-fullscreen');
    }

    function syncAnalysisMapFullscreenButton() {
        if (!analysisMapFullscreenBtn) return;
        analysisMapFullscreenBtn.textContent = isAnalysisMapFullscreen() ? 'Quitter plein écran' : 'Plein écran';
        if (analysisMap) {
            setTimeout(() => analysisMap.invalidateSize(), 140);
        }
    }

    async function toggleAnalysisMapFullscreen() {
        if (!analysisMapShell) return;

        try {
            if (document.fullscreenElement === analysisMapShell || document.webkitFullscreenElement === analysisMapShell) {
                if (document.exitFullscreen) {
                    await document.exitFullscreen();
                } else if (document.webkitExitFullscreen) {
                    document.webkitExitFullscreen();
                }
            } else if (analysisMapShell.requestFullscreen) {
                await analysisMapShell.requestFullscreen();
            } else if (analysisMapShell.webkitRequestFullscreen) {
                analysisMapShell.webkitRequestFullscreen();
            } else {
                analysisMapShell.classList.toggle('analysis-map-shell-fallback-fullscreen');
            }
        } catch (_error) {
            analysisMapShell.classList.toggle('analysis-map-shell-fallback-fullscreen');
        }

        syncAnalysisMapFullscreenButton();
    }

    function updateAleaSelectedCount() {
        if (!layerAlea || !aleaSelectedCount) return;
        const total = layerAlea.options.length;
        const selected = Array.from(layerAlea.selectedOptions).length;
        if (aleaAllCheckbox && aleaAllCheckbox.checked) {
            aleaSelectedCount.textContent = `Toutes (${total})`;
            return;
        }
        aleaSelectedCount.textContent = `${selected}/${total}`;
    }

    function syncAleaSelectionMode() {
        const useAll = aleaAllCheckbox ? aleaAllCheckbox.checked : true;
        if (layerAlea) {
            layerAlea.disabled = useAll;
            layerAlea.classList.toggle('is-disabled', useAll);
        }
        if (aleaSelectionHelper) {
            aleaSelectionHelper.textContent = useAll
                ? "Mode automatique: toutes les couches aléa seront injectées."
                : "Mode manuel: sélectionnez les couches de support à injecter.";
        }
        updateAleaSelectedCount();
    }

    function renderAleaSupportList() {
        if (!aleaSupportList) return;

        if (aleaSupportCount) {
            const total = aleaLayers.length;
            aleaSupportCount.textContent = `${total} couche${total > 1 ? 's' : ''}`;
        }

        if (!aleaLayers.length) {
            aleaSupportList.innerHTML = '<em>Aucune couche de support détectée.</em>';
            return;
        }

        aleaSupportList.innerHTML = aleaLayers.map((layer) => {
            const safeLayer = escapeHtml(layer);
            const safeTitle = escapeHtml(prettifyLayerName(layer));
            return `
                <div class="alea-chip">
                    <span class="chip-title">${safeTitle}</span>
                    <a href="#" class="chip-link" data-layer="${safeLayer}">Injecter</a>
                </div>
            `;
        }).join('');
    }

    function formatRunDate(isoString) {
        if (!isoString) return '-';
        const d = new Date(isoString);
        if (Number.isNaN(d.getTime())) return '-';
        return d.toLocaleString('fr-FR', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    function runStatusBadge(status) {
        const s = String(status || '').toLowerCase();
        if (s === 'done' || s === 'succes' || s === 'success') {
            return '<span class="bg-emerald-900/40 text-emerald-400 border border-emerald-800/50 px-2 py-1 rounded text-xs font-medium">Succès</span>';
        }
        if (s === 'error' || s === 'echec' || s === 'failed') {
            return '<span class="bg-red-900/40 text-red-400 border border-red-800/50 px-2 py-1 rounded text-xs font-medium">Erreur</span>';
        }
        return `<span class="bg-slate-800 border border-slate-700 text-slate-300 px-2 py-1 rounded text-xs font-medium">${escapeHtml(status || 'Inconnu')}</span>`;
    }

    function formatFileSize(bytes) {
        const value = Number(bytes || 0);
        if (!Number.isFinite(value) || value <= 0) return '0 octet';
        if (value < 1024) return `${value} octets`;
        if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} Ko`;
        return `${(value / (1024 * 1024)).toFixed(1)} Mo`;
    }

    function helpBodyToHtml(body) {
        const raw = String(body || '').trim();
        if (!raw) {
            return '<em class="text-slate-500 not-italic">Aucun contenu d\'aide disponible.</em>';
        }

        return raw
            .split(/\n\s*\n/)
            .map((block) => block.trim())
            .filter(Boolean)
            .map((block) => `<p>${escapeHtml(block).replace(/\n/g, '<br>')}</p>`)
            .join('');
    }

    function renderHelpContent(content) {
        const safeContent = content || {};
        if (helpPageTitle) {
            helpPageTitle.textContent = safeContent.title || 'Aide & Documentation';
        }
        if (helpPageBody) {
            helpPageBody.innerHTML = helpBodyToHtml(safeContent.body);
        }
    }

    function renderHelpDocument(documentInfo) {
        if (!helpDocumentPanel || !helpDocumentMeta) return;

        const doc = documentInfo || null;
        if (!doc) {
            helpDocumentMeta.innerHTML = '<em class="text-slate-500 not-italic">Aucun document de référence disponible.</em>';
            if (helpDocumentPreviewLink) {
                helpDocumentPreviewLink.href = '#';
                helpDocumentPreviewLink.classList.add('hidden-element');
            }
            if (helpDocumentDownloadLink) {
                helpDocumentDownloadLink.href = '#';
                helpDocumentDownloadLink.classList.add('hidden-element');
            }
            if (helpDocumentPreviewFrame) {
                helpDocumentPreviewFrame.removeAttribute('src');
            }
            if (helpDocumentPreviewShell) {
                helpDocumentPreviewShell.classList.add('hidden-element');
            }
            return;
        }

        const uploadedAt = formatRunDate(doc.uploaded_at);
        const previewMode = String(doc.preview_mode || 'none');
        let previewNote = 'Prévisualisation indisponible pour ce format.';
        if (previewMode === 'pdf') {
            previewNote = 'Prévisualisation PDF intégrée et téléchargement disponibles.';
        } else if (previewMode === 'word_pdf') {
            previewNote = 'Prévisualisation générée à partir du document Word via conversion PDF serveur.';
        }

        helpDocumentMeta.innerHTML = `
            <div class="space-y-2">
                <div><strong class="text-slate-100">${escapeHtml(doc.original_filename || 'Document sans nom')}</strong></div>
                <div class="text-slate-400">Format : ${escapeHtml(String(doc.file_ext || '').toUpperCase().replace('.', '')) || '-'}</div>
                <div class="text-slate-400">Taille : ${escapeHtml(formatFileSize(doc.file_size))}</div>
                <div class="text-slate-400">Dernière mise à jour : ${escapeHtml(uploadedAt)}</div>
                <div class="text-slate-400">${escapeHtml(previewNote)}</div>
            </div>
        `;

        if (helpDocumentDownloadLink) {
            helpDocumentDownloadLink.href = doc.download_url || '#';
            helpDocumentDownloadLink.classList.remove('hidden-element');
        }

        const previewHref = doc.preview_url
            ? `${doc.preview_url}${doc.preview_url.includes('?') ? '&' : '?'}ts=${encodeURIComponent(doc.uploaded_at || Date.now())}`
            : '#';
        if (helpDocumentPreviewLink) {
            if (doc.preview_available && doc.preview_url) {
                helpDocumentPreviewLink.href = previewHref;
                helpDocumentPreviewLink.classList.remove('hidden-element');
            } else {
                helpDocumentPreviewLink.href = '#';
                helpDocumentPreviewLink.classList.add('hidden-element');
            }
        }

        if (helpDocumentPreviewShell && helpDocumentPreviewFrame) {
            if (doc.preview_available && doc.preview_url) {
                helpDocumentPreviewFrame.src = previewHref;
                helpDocumentPreviewShell.classList.remove('hidden-element');
            } else {
                helpDocumentPreviewFrame.removeAttribute('src');
                helpDocumentPreviewShell.classList.add('hidden-element');
            }
        }
    }

    function renderAdminUserList(users) {
        if (!adminUserList) return;

        if (!Array.isArray(users) || !users.length) {
            adminUserList.innerHTML = '<em class="text-slate-500 not-italic">Aucun utilisateur trouvé.</em>';
            return;
        }

        adminUserList.innerHTML = `
            <div class="overflow-x-auto border border-slate-800 rounded-lg">
                <table class="w-full text-sm">
                    <thead class="bg-slate-950 text-slate-400">
                        <tr>
                            <th class="text-left px-4 py-3 font-medium">Utilisateur</th>
                            <th class="text-left px-4 py-3 font-medium">Rôle</th>
                            <th class="text-left px-4 py-3 font-medium">Admin</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-800">
                        ${users.map((user) => `
                            <tr class="bg-slate-900/70">
                                <td class="px-4 py-3 text-slate-200">
                                    <span class="font-medium">${escapeHtml(user.username || '')}</span>
                                    ${user.is_current_user ? '<span class="ml-2 inline-flex items-center px-2 py-1 rounded border border-brand-800/60 bg-brand-900/20 text-brand-300 text-[11px]">vous</span>' : ''}
                                </td>
                                <td class="px-4 py-3 text-slate-400">${user.is_admin ? 'Administrateur' : 'Utilisateur'}</td>
                                <td class="px-4 py-3 text-slate-300">
                                    <label class="inline-flex items-center gap-2">
                                        <input
                                            type="checkbox"
                                            class="admin-user-role-toggle accent-cyan-500"
                                            data-user-id="${escapeHtml(String(user.id || ''))}"
                                            ${user.is_admin ? 'checked' : ''}
                                            ${user.is_current_user ? 'disabled' : ''}
                                        >
                                        <span>${user.is_current_user ? 'Compte courant' : 'Accorder le rôle admin'}</span>
                                    </label>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;
    }

    function updateHistorySelectionUi() {
        const rowCheckboxes = historyList
            ? Array.from(historyList.querySelectorAll('input.history-select-run[type="checkbox"]'))
            : [];
        const checkedCount = rowCheckboxes.filter((cb) => cb.checked).length;
        const hasRows = rowCheckboxes.length > 0;

        if (historySelectAll) {
            historySelectAll.disabled = !hasRows;
            historySelectAll.checked = hasRows && checkedCount === rowCheckboxes.length;
            historySelectAll.indeterminate = hasRows && checkedCount > 0 && checkedCount < rowCheckboxes.length;
        }

        if (historyDeleteSelectedBtn) {
            historyDeleteSelectedBtn.disabled = selectedRunIds.size === 0;
        }

        if (historySelectionInfo) {
            if (selectedRunIds.size === 0) {
                historySelectionInfo.textContent = 'Aucun run sélectionné.';
            } else {
                const suffix = selectedRunIds.size > 1 ? 's' : '';
                historySelectionInfo.textContent = `${selectedRunIds.size} run${suffix} sélectionné${suffix}.`;
            }
        }
    }

    function renderHistoryRows(runs) {
        if (!historyList) return;
        if (!Array.isArray(runs) || runs.length === 0) {
            selectedRunIds.clear();
            historyList.innerHTML = `
                <tr>
                    <td class="py-3 px-4 text-slate-500" colspan="6">Aucun run trouvé.</td>
                </tr>
            `;
            updateHistorySelectionUi();
            return;
        }

        const visibleIds = new Set(
            runs
                .map((run) => String(run.run_id ?? '').trim())
                .filter((id) => id.length > 0)
        );
        Array.from(selectedRunIds).forEach((id) => {
            if (!visibleIds.has(id)) {
                selectedRunIds.delete(id);
            }
        });

        historyList.innerHTML = runs.map((run) => {
            const runIdRaw = String(run.run_id ?? '').trim();
            const runId = escapeHtml(runIdRaw);
            const isSelected = runIdRaw.length > 0 && selectedRunIds.has(runIdRaw);
            const checkedAttr = isSelected ? 'checked' : '';
            const mainLayer = escapeHtml(run.main_layer || '-');
            const viewName = escapeHtml(run.view_name || '');
            const stressRaw = Array.isArray(run.stress_layers)
                ? run.stress_layers
                : (typeof run.stress_layers === 'string' ? run.stress_layers.split(',') : []);
            const stressLayers = stressRaw
                .map((item) => String(item || '').trim())
                .filter((item) => item.length > 0);
            const stressText = stressLayers.length ? stressLayers.join(', ') : '-';
            const stressBadges = stressLayers.length
                ? stressLayers.map((layer) =>
                    `<span class="inline-flex items-center px-2 py-1 rounded border border-brand-800/60 bg-brand-900/20 text-brand-300 text-[11px]">${escapeHtml(layer)}</span>`
                ).join(' ')
                : '<span class="text-slate-500">-</span>';
            const safeStressTitle = escapeHtml(stressText);
            const createdAt = formatRunDate(run.created_at);
            const duration = run.duration_seconds ? `${Number(run.duration_seconds).toFixed(2)}s` : '';
            const csvHref = run.view_name ? `/download_resilience_layer/${encodeURIComponent(run.view_name)}?format=csv` : '#';
            const gpkgHref = run.view_name ? `/download_resilience_layer/${encodeURIComponent(run.view_name)}?format=gpkg` : '#';
            const shpHref = run.view_name ? `/download_resilience_layer/${encodeURIComponent(run.view_name)}?format=shp` : '#';
            const actions = run.view_name ? `
                <div class="flex justify-end gap-2">
                    <a class="bg-slate-800 border border-slate-700 hover:bg-slate-700 text-slate-200 px-2 py-1 rounded text-xs" href="${csvHref}" target="_blank" rel="noopener">CSV</a>
                    <a class="bg-slate-800 border border-slate-700 hover:bg-slate-700 text-slate-200 px-2 py-1 rounded text-xs" href="${gpkgHref}" target="_blank" rel="noopener">GPKG</a>
                    <a class="bg-slate-800 border border-slate-700 hover:bg-slate-700 text-slate-200 px-2 py-1 rounded text-xs" href="${shpHref}" target="_blank" rel="noopener">SHP</a>
                    <button type="button" class="history-open-table bg-brand-600/20 text-brand-400 border border-brand-500/30 hover:bg-brand-600 hover:text-white px-2 py-1 rounded text-xs font-medium transition-colors" data-view="${viewName}">Table</button>
                </div>
            ` : '<span class="text-slate-600 text-xs">-</span>';

            return `
                <tr class="hover:bg-slate-800/40 transition-colors">
                    <td class="py-3 px-4 text-center align-top">
                        <input type="checkbox" class="history-select-run accent-cyan-500" data-run-id="${runId}" ${checkedAttr}>
                    </td>
                    <td class="py-3 px-4">
                        <div class="font-mono text-brand-400">RUN-${runId}</div>
                        <div class="text-[11px] text-slate-500">${createdAt}${duration ? ` • ${duration}` : ''}</div>
                    </td>
                    <td class="py-3 px-4 text-slate-300">${mainLayer}</td>
                    <td class="py-3 px-4 text-slate-300 max-w-[520px] whitespace-normal break-words align-top leading-relaxed" title="${safeStressTitle}">${stressBadges}</td>
                    <td class="py-3 px-4">${runStatusBadge(run.status)}</td>
                    <td class="py-3 px-4 text-right">${actions}</td>
                </tr>
            `;
        }).join('');
        updateHistorySelectionUi();
    }

    function loadResilienceHistory() {
        if (!historyList) return;
        const q = historySearchInput ? historySearchInput.value.trim() : '';
        historyList.innerHTML = `
            <tr>
                <td class="py-3 px-4 text-slate-500" colspan="6">Chargement de l'historique...</td>
            </tr>
        `;
        if (historySelectAll) {
            historySelectAll.checked = false;
            historySelectAll.indeterminate = false;
            historySelectAll.disabled = true;
        }
        fetch(`/resilience_runs_history?q=${encodeURIComponent(q)}`)
            .then((r) => {
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return r.json();
            })
            .then((runs) => {
                renderHistoryRows(runs);
            })
            .catch((e) => {
                historyList.innerHTML = `
                    <tr>
                        <td class="py-3 px-4 text-red-400" colspan="6">Erreur de chargement de l'historique: ${escapeHtml(e.message)}</td>
                    </tr>
                `;
                updateHistorySelectionUi();
            });
    }

    window.loadResilienceHistory = loadResilienceHistory;

    function showFeedback(element, timerName, message, type = 'success', delay = 6000) {
        if (!element) return;

        if (timerName === 'import' && importFeedbackTimer) clearTimeout(importFeedbackTimer);
        if (timerName === 'analysis' && analysisImportFeedbackTimer) clearTimeout(analysisImportFeedbackTimer);
        if (timerName === 'layer' && layerActionFeedbackTimer) clearTimeout(layerActionFeedbackTimer);
        if (timerName === 'impact' && impactMatrixFeedbackTimer) clearTimeout(impactMatrixFeedbackTimer);
        if (timerName === 'admin' && adminUserFeedbackTimer) clearTimeout(adminUserFeedbackTimer);

        element.classList.remove('hidden-element', 'success', 'error');
        element.classList.add(type === 'error' ? 'error' : 'success');
        element.textContent = message;

        const timer = setTimeout(() => {
            element.classList.add('hidden-element');
        }, delay);

        if (timerName === 'import') importFeedbackTimer = timer;
        if (timerName === 'analysis') analysisImportFeedbackTimer = timer;
        if (timerName === 'layer') layerActionFeedbackTimer = timer;
        if (timerName === 'impact') impactMatrixFeedbackTimer = timer;
        if (timerName === 'admin') adminUserFeedbackTimer = timer;
    }

    function showImportFeedback(message, type = 'success') {
        showFeedback(importFeedback, 'import', message, type, 6000);
    }

    function showAnalysisImportFeedback(message, type = 'success') {
        showFeedback(analysisImportFeedback, 'analysis', message, type, 6000);
    }

    function showLayerActionFeedback(message, type = 'success') {
        showFeedback(layerActionFeedback, 'layer', message, type, 8000);
    }

    function showImpactMatrixFeedback(message, type = 'success') {
        showFeedback(impactMatrixFeedback, 'impact', message, type, 7000);
    }

    function showAdminUserFeedback(message, type = 'success') {
        showFeedback(adminUserFeedback, 'admin', message, type, 7000);
    }

    function showHelpDocumentFeedback(message, type = 'success') {
        if (helpDocumentFeedbackTimer) clearTimeout(helpDocumentFeedbackTimer);
        if (!helpDocumentFeedback) return;
        helpDocumentFeedback.classList.remove('hidden-element', 'success', 'error');
        helpDocumentFeedback.classList.add(type === 'error' ? 'error' : 'success');
        helpDocumentFeedback.textContent = message;
        helpDocumentFeedbackTimer = setTimeout(() => {
            helpDocumentFeedback.classList.add('hidden-element');
        }, 7000);
    }

    function loadResilienceAdminUsers() {
        if (!isAdminUser || !adminUserList) return Promise.resolve([]);

        adminUserList.innerHTML = '<em class="text-slate-500 not-italic">Chargement des utilisateurs...</em>';
        return fetch('/resilience_admin_users')
            .then(async (response) => {
                const data = await response.json().catch(() => ({}));
                if (!response.ok || data.status !== 'ok') {
                    throw new Error(data.message || `HTTP ${response.status}`);
                }
                const users = Array.isArray(data.users) ? data.users : [];
                renderAdminUserList(users);
                return users;
            })
            .catch((error) => {
                adminUserList.innerHTML = `<em class="text-red-400 not-italic">Erreur de chargement: ${escapeHtml(error.message)}</em>`;
                return [];
            });
    }

    function loadResilienceHelpContent() {
        return fetch('/resilience_help_content')
            .then(async (response) => {
                const data = await response.json().catch(() => ({}));
                if (!response.ok || data.status !== 'ok') {
                    throw new Error(data.message || `HTTP ${response.status}`);
                }
                renderHelpContent(data.content || {});
                renderHelpDocument(data.document || null);
                return data.content || {};
            })
            .catch((error) => {
                if (helpPageBody) {
                    helpPageBody.innerHTML = `<em class="text-red-400 not-italic">Erreur de chargement: ${escapeHtml(error.message)}</em>`;
                }
                renderHelpDocument(null);
                return null;
            });
    }

    window.loadResilienceAdminUsers = loadResilienceAdminUsers;
    window.loadResilienceHelpContent = loadResilienceHelpContent;

    function renderImpactMatrix(payload) {
        if (!impactMatrixContainer) return;

        const levels = Array.isArray(payload && payload.levels) ? payload.levels : [];
        const layers = Array.isArray(payload && payload.layers) ? payload.layers : [];

        if (!layers.length || !levels.length) {
            impactMatrixContainer.innerHTML = '<em>Aucune couche d\'aléa configurée pour la matrice.</em>';
            return;
        }

        const headerCells = levels.map((level) => `
            <th>Niveau ${escapeHtml(String(level))}</th>
        `).join('');

        const bodyRows = layers.map((layer) => {
            const layerName = String(layer.layer_name || '').trim();
            const safeLayer = escapeHtml(layerName);
            const title = escapeHtml(prettifyLayerName(layerName));
            const cells = levels.map((level) => {
                const rawValue = layer && layer.values ? layer.values[String(level)] : 0;
                const value = rawValue === null || rawValue === undefined ? 0 : rawValue;
                return `
                    <td>
                        <input
                            type="number"
                            step="any"
                            class="impact-matrix-input"
                            data-layer="${safeLayer}"
                            data-level="${escapeHtml(String(level))}"
                            value="${escapeHtml(String(value))}"
                        >
                    </td>
                `;
            }).join('');

            return `
                <tr>
                    <th class="impact-matrix-row-label">
                        <div class="impact-matrix-header">
                            <div class="impact-matrix-title">${title}</div>
                            <button type="button" class="impact-matrix-delete" data-layer="${safeLayer}">Supprimer</button>
                        </div>
                    </th>
                    ${cells}
                </tr>
            `;
        }).join('');

        impactMatrixContainer.innerHTML = `
            <table>
                <thead>
                    <tr>
                        <th>Couche d'aléa</th>
                        ${headerCells}
                    </tr>
                </thead>
                <tbody>
                    ${bodyRows}
                </tbody>
            </table>
        `;
    }

    function loadImpactMatrix() {
        if (!impactMatrixContainer) return;
        impactMatrixContainer.innerHTML = '<em>Chargement de la matrice des impacts...</em>';

        fetch('/resilience_impact_matrix')
            .then((r) => {
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return r.json();
            })
            .then((payload) => {
                if (payload.status === 'error') throw new Error(payload.message || 'Erreur matrice');
                renderImpactMatrix(payload);
            })
            .catch((err) => {
                impactMatrixContainer.innerHTML = `<em>Erreur de chargement: ${escapeHtml(err.message)}</em>`;
            });
    }

    async function saveImpactMatrix() {
        if (!impactMatrixContainer) return;

        const values = {};
        impactMatrixContainer.querySelectorAll('.impact-matrix-input[data-layer][data-level]').forEach((input) => {
            const layer = String(input.dataset.layer || '').trim();
            const level = String(input.dataset.level || '').trim();
            if (!layer || !level) return;
            if (!values[layer]) values[layer] = {};
            values[layer][level] = input.value;
        });

        if (!Object.keys(values).length) {
            showImpactMatrixFeedback("Aucune valeur à enregistrer dans la matrice.", 'error');
            return;
        }

        if (impactMatrixSaveBtn) impactMatrixSaveBtn.disabled = true;
        try {
            const response = await fetch('/resilience_impact_matrix', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ values })
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok || payload.status !== 'ok') {
                throw new Error(payload.message || `HTTP ${response.status}`);
            }

            showImpactMatrixFeedback("Matrice des impacts enregistrée.", 'success');
            loadImpactMatrix();
        } catch (err) {
            showImpactMatrixFeedback(`Enregistrement impossible: ${err.message}`, 'error');
        } finally {
            if (impactMatrixSaveBtn) impactMatrixSaveBtn.disabled = false;
        }
    }

    async function deleteResilienceLayer(layer, triggerButton = null) {
        const layerName = String(layer || '').trim();
        if (!layerName) return;

        let dependencyDetails = null;
        try {
            const dependencyResponse = await fetch(`/resilience_dependencies/${encodeURIComponent(layerName)}`);
            const dependencyPayload = await dependencyResponse.json().catch(() => ({}));
            if (!dependencyResponse.ok || dependencyPayload.status === 'error') {
                throw new Error(dependencyPayload.message || `HTTP ${dependencyResponse.status}`);
            }
            dependencyDetails = dependencyPayload;
        } catch (err) {
            const fallbackMessage = buildLayerDeleteFallbackMessage(layerName, err.message);
            if (!confirm(fallbackMessage)) {
                return;
            }
        }

        if (dependencyDetails && !confirm(buildLayerDeleteConfirmMessage(layerName, dependencyDetails))) {
            return;
        }

        let originalLabel = null;
        if (triggerButton) {
            triggerButton.disabled = true;
            originalLabel = triggerButton.textContent;
            triggerButton.textContent = 'Suppression...';
        }

        try {
            const response = await fetch('/delete_resilience_layer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ layer: layerName })
            });
            const result = await response.json().catch(() => ({}));
            if (!response.ok || result.status !== 'ok') {
                throw new Error(result.message || `HTTP ${response.status}`);
            }

            showLayerActionFeedback(buildLayerDeleteSuccessMessage(result, layerName), 'success');
            updateLayerList();
            if (layerStore[layerName]) {
                map.removeLayer(layerStore[layerName]);
                delete layerStore[layerName];
            }
        } catch (err) {
            showLayerActionFeedback(buildLayerDeleteErrorMessage(layerName, err.message), 'error');
        } finally {
            if (triggerButton) {
                triggerButton.disabled = false;
                triggerButton.textContent = originalLabel;
            }
        }
    }

    function buildDatasets(files) {
        const shapefileGroups = new Map();
        const gpkgFiles = [];

        files.forEach((file) => {
            const ext = getExt(file.name);
            if (ext === '.gpkg') {
                gpkgFiles.push(file);
                return;
            }
            if (SHP_EXTS.has(ext)) {
                const stem = file.name.slice(0, -ext.length);
                if (!shapefileGroups.has(stem)) {
                    shapefileGroups.set(stem, { exts: new Set() });
                }
                shapefileGroups.get(stem).exts.add(ext);
            }
        });

        const datasets = [];
        shapefileGroups.forEach((group, stem) => {
            if (!group.exts.has('.shp')) return;
            const missing = SHP_REQUIRED.filter((ext) => !group.exts.has(ext));
            datasets.push({
                key: `${stem}.shp`,
                type: 'shp',
                label: `${stem}.shp`,
                exts: Array.from(group.exts).sort(),
                missing
            });
        });

        gpkgFiles.forEach((file) => {
            datasets.push({
                key: file.name,
                type: 'gpkg',
                label: file.name,
                exts: ['.gpkg'],
                missing: []
            });
        });

        return datasets;
    }

    function getAllowedUploadFiles(fileInputEl) {
        return Array.from(fileInputEl ? fileInputEl.files : []).filter((file) => ALLOWED_EXTS.has(getExt(file.name)));
    }

    function renderDatasetInputs(fileInputEl, containerEl) {
        if (!containerEl) return [];

        containerEl.innerHTML = "";
        const allFiles = Array.from(fileInputEl ? fileInputEl.files : []);
        const files = allFiles.filter((file) => ALLOWED_EXTS.has(getExt(file.name)));
        const ignoredCount = allFiles.length - files.length;
        const datasets = buildDatasets(files);

        if (!datasets.length) {
            containerEl.innerHTML = "<em>Aucun fichier GPKG ou shapefile détecté.</em>";
            return [];
        }

        datasets.forEach((ds) => {
            const div = document.createElement('div');
            const extsInfo = ds.type === 'shp'
                ? `Extensions: ${ds.exts.join(', ')}`
                : 'Format: GPKG';
            const missingInfo = ds.missing.length
                ? `<div style="color:#b00; font-size:0.9em;">Manque: ${ds.missing.join(', ')}</div>`
                : '';
            div.innerHTML = `
                <label>Nom pour <strong>${ds.label}</strong> :</label>
                <input type="text" data-key="${ds.key}" placeholder="optionnel (sinon nom du fichier)">
                <div style="color:#666; font-size:0.9em;">${extsInfo}</div>
                <div style="color:#666; font-size:0.85em;">Laisser vide pour utiliser le nom du fichier.</div>
                ${missingInfo}
            `;
            containerEl.appendChild(div);
        });

        if (ignoredCount > 0) {
            const note = document.createElement('div');
            note.style.color = '#666';
            note.style.fontSize = '0.9em';
            note.textContent = `${ignoredCount} fichier(s) ignoré(s) (format non supporté).`;
            containerEl.appendChild(note);
        }

        return datasets;
    }

    function collectDatasetNames(containerEl) {
        const names = {};
        if (!containerEl) return names;

        containerEl.querySelectorAll('input[data-key]').forEach((input) => {
            const value = (input.value || '').trim();
            if (value) {
                names[input.dataset.key] = value;
            }
        });

        return names;
    }

    if (fileInput) {
        fileInput.addEventListener('change', () => {
            uploadDatasets = renderDatasetInputs(fileInput, fileNamesContainer);
        });
    }

    if (analysisFileInput) {
        analysisFileInput.addEventListener('change', () => {
            analysisUploadDatasets = renderDatasetInputs(analysisFileInput, analysisFileNamesContainer);
        });
    }

    if (uploadBtn) {
        uploadBtn.addEventListener('click', () => {
            const files = getAllowedUploadFiles(fileInput);
            if (importFeedback) importFeedback.classList.add('hidden-element');
            if (!files.length) return alert("Veuillez sélectionner des fichiers GPKG ou Shapefile.");

            const missingRequired = uploadDatasets
                .filter((ds) => ds.type === 'shp' && ds.missing.length)
                .map((ds) => `${ds.label} (${ds.missing.join(', ')})`);
            if (missingRequired.length) {
                alert("Shapefile incomplet : " + missingRequired.join(' | '));
                return;
            }

            const formData = new FormData();
            files.forEach((file) => {
                formData.append('files', file);
            });
            formData.append('names', JSON.stringify(collectDatasetNames(fileNamesContainer)));

            uploadBtn.disabled = true;
            const originalLabel = uploadBtn.dataset.label || uploadBtn.textContent;
            uploadBtn.dataset.label = originalLabel;
            uploadBtn.textContent = "Import en cours...";

            fetch('/upload_resilience', { method: 'POST', body: formData })
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'ok') {
                        const importedCount = Array.isArray(data.imported_layers) && data.imported_layers.length
                            ? data.imported_layers.length
                            : uploadDatasets.length;
                        showImportFeedback(`Importation réussie: ${importedCount} couche(s) aléa ajoutée(s).`, 'success');
                        updateLayerList();
                        fileInput.value = '';
                        fileNamesContainer.innerHTML = '';
                        uploadDatasets = [];
                    } else {
                        showImportFeedback("Erreur serveur: " + data.message, 'error');
                        alert("Erreur serveur : " + data.message);
                    }
                })
                .catch(err => {
                    showImportFeedback("Erreur réseau: " + err.message, 'error');
                    alert("Erreur réseau : " + err.message);
                })
                .finally(() => {
                    uploadBtn.disabled = false;
                    uploadBtn.textContent = uploadBtn.dataset.label || "Importer dans la Base";
                });
        });
    }

    if (analysisUploadBtn) {
        analysisUploadBtn.addEventListener('click', () => {
            const files = getAllowedUploadFiles(analysisFileInput);
            if (analysisImportFeedback) analysisImportFeedback.classList.add('hidden-element');
            if (!files.length) return alert("Veuillez sélectionner votre couche d'analyse (GPKG ou Shapefile).");

            const missingRequired = analysisUploadDatasets
                .filter((ds) => ds.type === 'shp' && ds.missing.length)
                .map((ds) => `${ds.label} (${ds.missing.join(', ')})`);
            if (missingRequired.length) {
                alert("Shapefile incomplet : " + missingRequired.join(' | '));
                return;
            }
            if (analysisUploadDatasets.length !== 1) {
                alert("Importez une seule couche principale à la fois pour l'analyse réseau.");
                return;
            }

            const formData = new FormData();
            files.forEach((file) => {
                formData.append('files', file);
            });
            formData.append('names', JSON.stringify(collectDatasetNames(analysisFileNamesContainer)));

            analysisUploadBtn.disabled = true;
            const originalLabel = analysisUploadBtn.dataset.label || analysisUploadBtn.textContent;
            analysisUploadBtn.dataset.label = originalLabel;
            analysisUploadBtn.textContent = "Import en cours...";

            fetch('/upload_resilience_analysis_layer', { method: 'POST', body: formData })
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'ok') {
                        const importedLayers = Array.isArray(data.imported_layers) ? data.imported_layers : [];
                        const importedCount = importedLayers.length || analysisUploadDatasets.length;
                        showAnalysisImportFeedback(`Importation réussie: ${importedCount} couche temporaire prête pour l'analyse.`, 'success');
                        updateLayerList(importedLayers[0] || null);
                        analysisFileInput.value = '';
                        analysisFileNamesContainer.innerHTML = '';
                        analysisUploadDatasets = [];
                    } else {
                        showAnalysisImportFeedback("Erreur serveur: " + data.message, 'error');
                        alert("Erreur serveur : " + data.message);
                    }
                })
                .catch(err => {
                    showAnalysisImportFeedback("Erreur réseau: " + err.message, 'error');
                    alert("Erreur réseau : " + err.message);
                })
                .finally(() => {
                    analysisUploadBtn.disabled = false;
                    analysisUploadBtn.textContent = analysisUploadBtn.dataset.label || "Importer ma couche d'analyse";
                });
        });
    }

    if (layerAlea) {
        layerAlea.addEventListener('change', () => {
            updateAleaSelectedCount();
        });
    }

    if (aleaAllCheckbox) {
        aleaAllCheckbox.addEventListener('change', () => {
            syncAleaSelectionMode();
        });
    }

    if (aleaMainLayer) {
        aleaMainLayer.addEventListener('change', () => {
            renderAnalysisMapLayerControls(getAnalysisMapLayerStateMap());
            scheduleAnalysisMapRefresh();
        });
    }

    if (aleaClearBtn) {
        aleaClearBtn.addEventListener('click', () => {
            if (!layerAlea) return;
            if (aleaAllCheckbox) aleaAllCheckbox.checked = false;
            Array.from(layerAlea.options).forEach((opt) => {
                opt.selected = false;
            });
            syncAleaSelectionMode();
            layerAlea.dispatchEvent(new Event('change'));
        });
    }

    if (analysisMapLayerControls) {
        analysisMapLayerControls.addEventListener('change', (event) => {
            const target = event.target;
            if (!target || (!target.classList.contains('analysis-map-layer-toggle') && !target.classList.contains('analysis-map-layer-color'))) {
                return;
            }
            scheduleAnalysisMapRefresh();
        });
    }

    if (aleaSupportList) {
        aleaSupportList.addEventListener('click', (event) => {
            const link = event.target.closest('.chip-link[data-layer]');
            if (!link || !layerAlea) return;
            event.preventDefault();

            const layer = link.dataset.layer;
            if (!layer) return;

            if (typeof window.switchTab === 'function') {
                window.switchTab('analyse');
            }

            if (aleaAllCheckbox) aleaAllCheckbox.checked = false;
            syncAleaSelectionMode();

            const targetOption = Array.from(layerAlea.options).find((opt) => opt.value === layer);
            if (targetOption) {
                targetOption.selected = true;
                layerAlea.dispatchEvent(new Event('change'));
            }

            layerAlea.focus();
        });
    }

    if (analysisMapFullscreenBtn) {
        analysisMapFullscreenBtn.addEventListener('click', () => {
            toggleAnalysisMapFullscreen();
        });
    }

    if (configMapFullscreenBtn) {
        configMapFullscreenBtn.addEventListener('click', () => {
            toggleConfigMapFullscreen();
        });
    }

    document.addEventListener('fullscreenchange', () => {
        syncAnalysisMapFullscreenButton();
        syncConfigMapFullscreenButton();
    });
    document.addEventListener('webkitfullscreenchange', () => {
        syncAnalysisMapFullscreenButton();
        syncConfigMapFullscreenButton();
    });

    if (adminUserForm) {
        adminUserForm.addEventListener('submit', (event) => {
            event.preventDefault();
            if (!isAdminUser) return;

            const username = String((adminUserUsername && adminUserUsername.value) || '').trim();
            const password = String((adminUserPassword && adminUserPassword.value) || '');
            const isAdmin = !!(adminUserIsAdmin && adminUserIsAdmin.checked);

            adminUserSubmit.disabled = true;
            fetch('/resilience_admin_users', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password, is_admin: isAdmin })
            })
                .then(async (response) => {
                    const data = await response.json().catch(() => ({}));
                    if (!response.ok || data.status !== 'ok') {
                        throw new Error(data.message || `HTTP ${response.status}`);
                    }
                    showAdminUserFeedback(data.message || 'Utilisateur créé.', 'success');
                    adminUserForm.reset();
                    return loadResilienceAdminUsers();
                })
                .catch((error) => {
                    showAdminUserFeedback(`Erreur: ${error.message}`, 'error');
                })
                .finally(() => {
                    adminUserSubmit.disabled = false;
                });
        });
    }

    if (adminUserList) {
        adminUserList.addEventListener('change', (event) => {
            const toggle = event.target.closest('.admin-user-role-toggle[data-user-id]');
            if (!toggle) return;

            const userId = String(toggle.dataset.userId || '').trim();
            if (!userId) return;

            toggle.disabled = true;
            fetch(`/resilience_admin_users/${encodeURIComponent(userId)}/role`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ is_admin: toggle.checked })
            })
                .then(async (response) => {
                    const data = await response.json().catch(() => ({}));
                    if (!response.ok || data.status !== 'ok') {
                        throw new Error(data.message || `HTTP ${response.status}`);
                    }
                    showAdminUserFeedback(data.message || 'Rôle mis à jour.', 'success');
                    return loadResilienceAdminUsers();
                })
                .catch((error) => {
                    showAdminUserFeedback(`Erreur: ${error.message}`, 'error');
                    loadResilienceAdminUsers();
                })
                .finally(() => {
                    toggle.disabled = false;
                });
        });
    }

    if (helpDocumentForm) {
        helpDocumentForm.addEventListener('submit', (event) => {
            event.preventDefault();
            if (!isAdminUser) return;

            const file = helpDocumentFileInput && helpDocumentFileInput.files ? helpDocumentFileInput.files[0] : null;
            if (!file) {
                showHelpDocumentFeedback('Sélectionnez un fichier PDF, DOC ou DOCX.', 'error');
                return;
            }

            const formData = new FormData();
            formData.append('file', file);
            helpDocumentUploadBtn.disabled = true;

            fetch('/resilience_help_document', {
                method: 'POST',
                body: formData,
            })
                .then(async (response) => {
                    const data = await response.json().catch(() => ({}));
                    if (!response.ok || data.status !== 'ok') {
                        throw new Error(data.message || `HTTP ${response.status}`);
                    }
                    renderHelpDocument(data.document || null);
                    if (helpDocumentFileInput) {
                        helpDocumentFileInput.value = '';
                    }
                    showHelpDocumentFeedback(data.message || 'Document importé.', 'success');
                })
                .catch((error) => {
                    showHelpDocumentFeedback(`Erreur: ${error.message}`, 'error');
                })
                .finally(() => {
                    helpDocumentUploadBtn.disabled = false;
                });
        });
    }

    if (helpDocumentDeleteBtn) {
        helpDocumentDeleteBtn.addEventListener('click', () => {
            if (!isAdminUser) return;
            if (!confirm("Supprimer le document de référence actuel ?")) {
                return;
            }

            helpDocumentDeleteBtn.disabled = true;
            fetch('/resilience_help_document', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            })
                .then(async (response) => {
                    const data = await response.json().catch(() => ({}));
                    if (!response.ok || data.status !== 'ok') {
                        throw new Error(data.message || `HTTP ${response.status}`);
                    }
                    renderHelpDocument(null);
                    showHelpDocumentFeedback(data.message || 'Document supprimé.', 'success');
                })
                .catch((error) => {
                    showHelpDocumentFeedback(`Erreur: ${error.message}`, 'error');
                })
                .finally(() => {
                    helpDocumentDeleteBtn.disabled = false;
                });
        });
    }

    if (historySearchInput) {
        historySearchInput.addEventListener('input', () => {
            if (historySearchTimer) clearTimeout(historySearchTimer);
            historySearchTimer = setTimeout(() => {
                loadResilienceHistory();
            }, 220);
        });
    }

    if (historyRefreshBtn) {
        historyRefreshBtn.addEventListener('click', () => {
            loadResilienceHistory();
        });
    }

    if (historySelectAll) {
        historySelectAll.addEventListener('change', () => {
            if (!historyList) return;
            const runCheckboxes = Array.from(historyList.querySelectorAll('input.history-select-run[type="checkbox"]'));
            runCheckboxes.forEach((cb) => {
                cb.checked = historySelectAll.checked;
                const runId = String(cb.dataset.runId || '').trim();
                if (!runId) return;
                if (cb.checked) {
                    selectedRunIds.add(runId);
                } else {
                    selectedRunIds.delete(runId);
                }
            });
            updateHistorySelectionUi();
        });
    }

    if (historyDeleteSelectedBtn) {
        historyDeleteSelectedBtn.addEventListener('click', () => {
            const runIds = Array.from(selectedRunIds)
                .map((id) => Number.parseInt(id, 10))
                .filter((id) => Number.isInteger(id) && id > 0);
            if (!runIds.length) {
                alert('Sélectionnez au moins un run à supprimer.');
                return;
            }

            if (!confirm(`Supprimer ${runIds.length} run(s) sélectionné(s) ? Cette action est irréversible.`)) {
                return;
            }

            historyDeleteSelectedBtn.disabled = true;
            fetch('/resilience_runs_delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ run_ids: runIds })
            })
                .then(async (r) => {
                    const data = await r.json().catch(() => ({}));
                    if (!r.ok || data.status !== 'ok') {
                        throw new Error(data.message || `HTTP ${r.status}`);
                    }
                    return data;
                })
                .then((data) => {
                    alert(`${data.deleted_count || 0} run(s) supprimé(s).`);
                    selectedRunIds.clear();
                    updateLayerList();
                    loadResilienceHistory();
                })
                .catch((e) => {
                    alert(`Erreur suppression: ${e.message}`);
                })
                .finally(() => {
                    historyDeleteSelectedBtn.disabled = selectedRunIds.size === 0;
                    updateHistorySelectionUi();
                });
        });
    }

    if (historyResetBtn) {
        historyResetBtn.addEventListener('click', () => {
            if (!confirm("Réinitialiser tout l'historique des runs ? Cette action est irréversible.")) {
                return;
            }

            historyResetBtn.disabled = true;
            fetch('/resilience_runs_reset', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            })
                .then(async (r) => {
                    const data = await r.json().catch(() => ({}));
                    if (!r.ok || data.status !== 'ok') {
                        throw new Error(data.message || `HTTP ${r.status}`);
                    }
                    return data;
                })
                .then(() => {
                    alert('Historique réinitialisé.');
                    selectedRunIds.clear();
                    updateLayerList();
                    loadResilienceHistory();
                })
                .catch((e) => {
                    alert(`Erreur réinitialisation: ${e.message}`);
                })
                .finally(() => {
                    historyResetBtn.disabled = false;
                    updateHistorySelectionUi();
                });
        });
    }

    if (historyList) {
        historyList.addEventListener('change', (event) => {
            const cb = event.target.closest('input.history-select-run[type="checkbox"]');
            if (!cb) return;
            const runId = String(cb.dataset.runId || '').trim();
            if (!runId) return;
            if (cb.checked) {
                selectedRunIds.add(runId);
            } else {
                selectedRunIds.delete(runId);
            }
            updateHistorySelectionUi();
        });

        historyList.addEventListener('click', (event) => {
            const btn = event.target.closest('.history-open-table[data-view]');
            if (!btn) return;
            const view = btn.dataset.view;
            if (!view) return;

            if (typeof window.switchTab === 'function') {
                window.switchTab('analyse');
            }
            updateLayerList();
            setTimeout(() => {
                const exists = Array.from(tableSelector.options).find((opt) => opt.value === view);
                if (!exists) {
                    const opt = document.createElement('option');
                    opt.value = view;
                    opt.textContent = view;
                    tableSelector.appendChild(opt);
                }
                tableSelector.value = view;
                loadAttributeTable(view);
            }, 350);
        });
    }

    // --- Création vue matérialisée aléas ---
    if (aleaRunBtn) {
        aleaRunBtn.addEventListener('click', () => {
            const main = aleaMainLayer && aleaMainLayer.value;
            if (!main) {
                alert("Sélectionnez une couche principale.");
                return;
            }
            const viewName = (aleaViewName && aleaViewName.value.trim()) || `${main}_alea_view`;
            const selectedAlea = Array.from(layerAlea ? layerAlea.selectedOptions : []).map(o => o.value);
            const useAll = aleaAllCheckbox ? aleaAllCheckbox.checked : true;

            if (!useAll && selectedAlea.length === 0) {
                alert("Sélectionnez au moins une couche aléa, ou activez l'option 'Prendre toutes les couches aléa'.");
                return;
            }

            aleaRunBtn.disabled = true;
            aleaProgress.textContent = "Création de la vue en cours...";
            aleaProgress.style.display = 'inline-block';
            aleaLog.innerHTML = "";
            if (aleaDownloadCsv) aleaDownloadCsv.style.display = 'none';
            if (aleaDownloadGpkg) aleaDownloadGpkg.style.display = 'none';
            if (aleaDownloadShp) aleaDownloadShp.style.display = 'none';

            const params = new URLSearchParams({ main_layer: main, view_name: viewName });
            if (!useAll && selectedAlea.length) {
                params.set('alea_tables', selectedAlea.join(','));
            }

            const es = new EventSource(`/alea_view_batch_stream?${params.toString()}`);
            es.onmessage = (evt) => {
                try {
                    const data = JSON.parse(evt.data);
                    if (data.status === 'progress') {
                        const line = `Couche ${data.step}/${data.total} : ${data.layer} — ${data.seconds}s`;
                        const div = document.createElement('div');
                        div.textContent = line;
                        aleaLog.appendChild(div);
                        aleaProgress.textContent = line;
                        aleaProgress.style.display = 'inline-block';
                    } else if (data.status === 'done') {
                        aleaProgress.textContent = `Vue "${data.view}" créée.`;
                        aleaProgress.style.display = 'inline-block';
                        if (aleaDownloadCsv && data.download_csv) {
                            aleaDownloadCsv.href = data.download_csv;
                            aleaDownloadCsv.textContent = "Télécharger CSV";
                            aleaDownloadCsv.style.display = 'inline';
                        }
                        if (aleaDownloadGpkg && data.download_gpkg) {
                            aleaDownloadGpkg.href = data.download_gpkg;
                            aleaDownloadGpkg.textContent = "Télécharger GPKG";
                            aleaDownloadGpkg.style.display = 'inline';
                        }
                        if (aleaDownloadShp && data.download_shp) {
                            aleaDownloadShp.href = data.download_shp;
                            aleaDownloadShp.textContent = "Télécharger Shapefile";
                            aleaDownloadShp.style.display = 'inline';
                        }
                        fetch('/resilience_analysis_layer_clear', { method: 'POST' })
                            .catch(() => null)
                            .finally(() => {
                                updateLayerList();
                            });
                        loadResilienceHistory();
                        es.close();
                        aleaRunBtn.disabled = false;
                    } else if (data.status === 'error') {
                        aleaProgress.textContent = "Erreur";
                        aleaProgress.style.display = 'inline-block';
                        alert(data.message || 'Erreur serveur');
                        loadResilienceHistory();
                        es.close();
                        aleaRunBtn.disabled = false;
                    }
                } catch (e) {
                    console.error(e);
                }
            };
            es.onerror = () => {
                aleaProgress.textContent = "Erreur";
                aleaProgress.style.display = 'inline-block';
                alert("Connexion interrompue.");
                es.close();
                aleaRunBtn.disabled = false;
            };
        });
    }

    // ========== Mise à jour des couches disponibles ========== //
    function updateLayerList(preferredAnalysisLayer = null) {
        const previousTableSelection = tableSelector ? tableSelector.value : '';
        const previousAnalysisSelection = preferredAnalysisLayer || (aleaMainLayer ? aleaMainLayer.value : '');
        const previousAnalysisMapState = getAnalysisMapLayerStateMap();
        const tableOptionValues = new Set();

        tableSelector.innerHTML = '';
        layerControls.innerHTML = '';
        if (layerAlea) layerAlea.innerHTML = '';
        if (aleaMainLayer) aleaMainLayer.innerHTML = '';
        if (analysisMapLayerControls) analysisMapLayerControls.innerHTML = '<em>Chargement des couches cartographiques d\'analyse...</em>';
        if (aleaSupportList) aleaSupportList.innerHTML = '<em>Chargement des couches de support...</em>';
        if (aleaSupportCount) aleaSupportCount.textContent = '...';
        if (impactMatrixContainer) impactMatrixContainer.innerHTML = '<em>Chargement de la matrice des impacts...</em>';

        layerStore = {};
        mainLayers = [];
        aleaLayers = [];
        analysisRunChoices = [];
        syncAleaSelectionMode();
        loadImpactMatrix();

        function appendTableOption(value, label = value) {
            if (!tableSelector || !value || tableOptionValues.has(value)) return;
            const opt = document.createElement('option');
            opt.value = value;
            opt.textContent = label;
            tableSelector.appendChild(opt);
            tableOptionValues.add(value);
        }

        function restoreSelections() {
            if (tableSelector && previousTableSelection) {
                const option = Array.from(tableSelector.options).find((opt) => opt.value === previousTableSelection);
                if (option) {
                    tableSelector.value = previousTableSelection;
                }
            }
        }

        // Charger les couches partagées pour la configuration cartographique.
        fetch('/resilience_layers')
            .then(r => r.json())
            .then(layers => {
                mainLayers = Array.isArray(layers) ? layers : [];

                mainLayers.forEach(layer => {
                    appendTableOption(layer, layer);

                    const wrapper = document.createElement('div');
                    wrapper.style.marginBottom = '10px';
                    wrapper.innerHTML = `
                        <input type="checkbox" id="toggle-${layer}" class="layer-toggle" data-layer="${layer}">
                        <label for="toggle-${layer}"><strong>${layer}</strong></label>
                        <input type="color" class="layer-color" data-layer="${layer}" value="#005aa3" style="margin-left:10px;">
                        <select class="download-format" data-layer="${layer}" style="margin-left:10px;">
                            <option value="">⬇ Format</option>
                            <option value="csv">CSV</option>
                            <option value="html">HTML</option>
                            <option value="gpkg">GPKG</option>
                            <option value="shp">Shapefile</option>
                        </select>
                        <button class="delete-layer-btn" data-layer="${layer}" style="margin-left:10px;">🗑 Supprimer</button>
                    `;
                    layerControls.appendChild(wrapper);
                });
                restoreSelections();
            });

        // Charger les couches support (aléas) pour l'injection de stress.
        fetch('/resilience_layers_support')
            .then(r => r.json())
            .then(supportLayers => {
                aleaLayers = Array.isArray(supportLayers) ? supportLayers : [];
                renderAleaSupportList();

                // Pour création de vue matérialisée (multi-select)
                if (layerAlea) {
                    aleaLayers.forEach(layer => {
                        const opt = document.createElement('option');
                        opt.value = layer;
                        opt.textContent = layer;
                        layerAlea.appendChild(opt);
                    });
                }

                syncAleaSelectionMode();
                scheduleAnalysisMapRefresh();
            })
            .catch(() => {
                aleaLayers = [];
                if (aleaSupportList) aleaSupportList.innerHTML = '<em>Erreur lors du chargement des couches support.</em>';
                if (aleaSupportCount) aleaSupportCount.textContent = 'Erreur';
                syncAleaSelectionMode();
                scheduleAnalysisMapRefresh();
            });

        // Charger les couches privées d'analyse pour l'utilisateur courant.
        fetch('/resilience_analysis_layers')
            .then(r => r.json())
            .then(privateLayers => {
                const analysisLayers = Array.isArray(privateLayers) ? privateLayers : [];

                if (aleaMainLayer) {
                    if (!analysisLayers.length) {
                        const placeholder = document.createElement('option');
                        placeholder.value = '';
                        placeholder.textContent = 'Importez votre couche réseau temporaire';
                        aleaMainLayer.appendChild(placeholder);
                    } else {
                        analysisLayers.forEach((layer) => {
                            appendTableOption(layer, `${layer} · Couche infra importée`);
                            const opt = document.createElement('option');
                            opt.value = layer;
                            opt.textContent = layer;
                            aleaMainLayer.appendChild(opt);
                        });
                        const targetValue = preferredAnalysisLayer || previousAnalysisSelection;
                        const targetOption = Array.from(aleaMainLayer.options).find((opt) => opt.value === targetValue);
                        if (targetOption) {
                            aleaMainLayer.value = targetValue;
                        }
                    }
                }
                renderAnalysisMapLayerControls(previousAnalysisMapState);
                restoreSelections();
                scheduleAnalysisMapRefresh();
            })
            .catch(() => {
                if (aleaMainLayer) {
                    const placeholder = document.createElement('option');
                    placeholder.value = '';
                    placeholder.textContent = 'Erreur chargement couche temporaire';
                    aleaMainLayer.appendChild(placeholder);
                }
                renderAnalysisMapLayerControls(previousAnalysisMapState);
                scheduleAnalysisMapRefresh();
            });

        fetch('/resilience_runs_history?limit=200')
            .then((r) => {
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return r.json();
            })
            .then((runs) => {
                analysisRunChoices = Array.isArray(runs) ? runs : [];
                analysisRunChoices
                    .filter((run) => String(run.status || '').toLowerCase() === 'done')
                    .forEach((run) => {
                        const layerName = String(run.view_name || run.layer_name || '').trim();
                        if (!layerName) return;
                        appendTableOption(layerName, `${layerName} · Run utilisateur`);
                    });
                renderAnalysisMapLayerControls(previousAnalysisMapState);
                restoreSelections();
                scheduleAnalysisMapRefresh();
            })
            .catch(() => {
                analysisRunChoices = [];
                renderAnalysisMapLayerControls(previousAnalysisMapState);
                scheduleAnalysisMapRefresh();
            });
    }



    // ========== Le reste de tes fonctionnalités Leaflet, download, suppression, table attributaire... ==========

    function displayLayer(layerName, color = "#005aa3") {
        // Supprime la couche si elle est déjà affichée
        if (layerStore[layerName]) {
            map.removeLayer(layerStore[layerName]);
            delete layerStore[layerName];
        }
        // Recharge la couche depuis le backend
        fetch(`/resilience_layer_data/${encodeURIComponent(layerName)}`)
            .then(r => r.json())
            .then(data => {
                if (data.status !== 'ok') throw new Error(data.message);

                const geo = L.geoJSON(data.features, {
                    style: { color },
                    pointToLayer: function (feature, latlng) {
                        return L.circleMarker(latlng, {
                            radius: 6,
                            color: color,
                            fillColor: color,
                            fillOpacity: 0.6
                        });
                    },
                    onEachFeature: (feature, layer) => {
                        const props = feature.properties || {};
                        const content = Object.entries(props)
                            .map(([k, v]) => `<strong>${k}</strong>: ${v}`)
                            .join('<br>');
                        layer.bindPopup(content);
                    }
                }).addTo(map);

                layerStore[layerName] = geo;
                map.fitBounds(geo.getBounds());
            })
            .catch(e => alert("Erreur : " + e.message));
    }

    function loadAttributeTable(layerName) {
        fetch(`/resilience_layer_data/${encodeURIComponent(layerName)}`)
            .then(r => r.json())
            .then(data => {
                if (data.status !== 'ok') throw new Error(data.message);

                const columns = data.columns.filter(c => c !== 'geometry');
                const rows = data.table;

                let html = `<table><thead><tr>${columns.map(c => `<th>${c}</th>`).join('')}</tr></thead><tbody>`;
                rows.forEach(row => {
                    html += `<tr>${columns.map(c => `<td>${row[c] ?? ''}</td>`).join('')}</tr>`;
                });
                html += '</tbody></table>';
                tableContainer.innerHTML = html;
            })
            .catch(e => {
                tableContainer.innerHTML = `<p style="color: red;">Erreur table : ${e.message}</p>`;
            });
    }

    tableSelector.addEventListener('change', () => {
        const selected = tableSelector.value;
        if (selected) loadAttributeTable(selected);
    });

    layerControls.addEventListener('change', function (e) {
        const layerName = e.target.dataset.layer;
        if (e.target.classList.contains('layer-toggle')) {
            const colorInput = document.querySelector(`input.layer-color[data-layer="${layerName}"]`);
            if (e.target.checked) displayLayer(layerName, colorInput.value);
            else if (layerStore[layerName]) map.removeLayer(layerStore[layerName]);
        }
        if (e.target.classList.contains('layer-color')) {
            const color = e.target.value;
            const checkbox = document.querySelector(`input.layer-toggle[data-layer="${layerName}"]`);
            if (checkbox.checked) {
                displayLayer(layerName, color);
            }
        }
        if (e.target.classList.contains('download-format')) {
            const layer = e.target.dataset.layer;
            const format = e.target.value;
            if (format) {
                window.open(`/download_resilience_layer/${layer}?format=${format}`, '_blank');
                e.target.value = '';
            }
        }
    });

    layerControls.addEventListener('click', async function (e) {
        const deleteBtn = e.target.closest('.delete-layer-btn');
        if (!deleteBtn) return;
        await deleteResilienceLayer(deleteBtn.dataset.layer, deleteBtn);
    });

    if (impactMatrixContainer) {
        impactMatrixContainer.addEventListener('click', async function (e) {
            const deleteBtn = e.target.closest('.impact-matrix-delete[data-layer]');
            if (!deleteBtn) return;
            await deleteResilienceLayer(deleteBtn.dataset.layer, deleteBtn);
        });
    }

    if (impactMatrixSaveBtn) {
        impactMatrixSaveBtn.addEventListener('click', () => {
            saveImpactMatrix();
        });
    }

    updateHistorySelectionUi();
    syncAnalysisMapFullscreenButton();
    syncConfigMapFullscreenButton();
    loadResilienceHelpContent();
    if (isAdminUser) {
        loadResilienceAdminUsers();
    }
    updateLayerList(); // démarrage
});
````

### Styles CSS

#### static/css/resilience.css

````css
:root {
    --sr-bg: #020617;
    --sr-surface: #0f172a;
    --sr-surface-2: #111827;
    --sr-border: #1e293b;
    --sr-text: #d1d5db;
    --sr-text-soft: #94a3b8;
    --sr-title: #e2e8f0;
    --sr-brand: #06b6d4;
    --sr-brand-strong: #0891b2;
    --sr-danger: #ef4444;
    --sr-success: #22c55e;
}

* {
    box-sizing: border-box;
}

html,
body {
    margin: 0;
    padding: 0;
}

body.sr-body {
    font-family: "Poppins", "Segoe UI", Tahoma, sans-serif;
    background: radial-gradient(circle at top, #0b1022 0%, var(--sr-bg) 48%);
    color: var(--sr-text);
    min-height: 100vh;
}

.sr-topbar {
    position: sticky;
    top: 0;
    z-index: 60;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 20px;
    padding: 14px 24px;
    background: rgba(15, 23, 42, 0.92);
    border-bottom: 1px solid var(--sr-border);
    backdrop-filter: blur(10px);
}

.sr-brand {
    display: flex;
    align-items: center;
    gap: 20px;
    min-width: 0;
}

.sr-logo {
    width: 80px;
    height: 80px;
    object-fit: contain;
    background: rgba(255, 255, 255, 0.95);
    border-radius: 50%;
    padding: 12px;
    box-shadow: 0 6px 16px rgba(6, 182, 212, 0.5);
}

.sr-brand-text {
    display: flex;
    flex-direction: column;
    min-width: 0;
}

.sr-title {
    font-size: 1.05rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    color: var(--sr-brand);
    white-space: nowrap;
}

.sr-subtitle {
    font-size: 0.78rem;
    color: var(--sr-text-soft);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.sr-nav {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    justify-content: center;
}

.sr-nav a {
    text-decoration: none;
    color: var(--sr-text-soft);
    border: 1px solid transparent;
    padding: 8px 11px;
    border-radius: 8px;
    font-size: 0.88rem;
    font-weight: 600;
    transition: 0.2s ease;
}

.sr-nav a:hover {
    color: var(--sr-title);
    border-color: var(--sr-border);
    background: #0b1220;
}

.sr-logout {
    text-decoration: none;
    color: #fca5a5;
    border: 1px solid #7f1d1d;
    background: rgba(127, 29, 29, 0.2);
    padding: 8px 12px;
    border-radius: 8px;
    font-size: 0.88rem;
    font-weight: 600;
    white-space: nowrap;
}

.sr-logout:hover {
    background: rgba(127, 29, 29, 0.35);
}

.sr-main {
    padding: 24px;
}

.sr-container {
    max-width: 1280px;
    margin: 0 auto;
    display: grid;
    gap: 18px;
}

.sr-card {
    background: linear-gradient(180deg, #0f172a 0%, #0b1220 100%);
    border: 1px solid var(--sr-border);
    border-radius: 14px;
    padding: 18px;
    box-shadow: 0 14px 30px rgba(2, 6, 23, 0.4);
}

.sr-card-head h2 {
    margin: 0 0 4px 0;
    color: var(--sr-title);
    font-size: 1.28rem;
    letter-spacing: 0.01em;
}

.sr-card-head p {
    margin: 0 0 14px 0;
    color: var(--sr-text-soft);
    font-size: 0.9rem;
}

.sr-form,
.sr-grid-2,
.sr-alea-grid {
    display: grid;
    gap: 14px;
}

.sr-upload-box {
    border: 1px dashed #334155;
    background: #0b1220;
    border-radius: 12px;
    padding: 14px;
}

.sr-upload-box label {
    display: block;
    color: var(--sr-brand);
    font-weight: 700;
    margin-bottom: 10px;
}

.sr-upload-box input[type="file"] {
    width: 100%;
    color: var(--sr-text);
}

.sr-listbox,
.sr-table-wrap {
    background: rgba(15, 23, 42, 0.78);
    border: 1px solid var(--sr-border);
    border-radius: 10px;
    padding: 12px;
    min-height: 44px;
}

#file-names-container > div {
    padding: 10px;
    background: #020617;
    border: 1px solid #1f2937;
    border-radius: 10px;
    margin-bottom: 8px;
}

#file-names-container label {
    font-size: 0.9rem;
    color: var(--sr-title);
}

#file-names-container input[type="text"] {
    width: 100%;
    margin-top: 8px;
    background: #0b1220;
    color: var(--sr-text);
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 10px;
}

.sr-actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
}

.sr-btn {
    border: none;
    border-radius: 10px;
    padding: 11px 16px;
    font-weight: 700;
    cursor: pointer;
    color: #fff;
}

.sr-btn-primary {
    background: linear-gradient(90deg, var(--sr-brand-strong), var(--sr-brand));
}

.sr-btn-primary:hover {
    filter: brightness(1.08);
}

.sr-toolbar {
    display: grid;
    grid-template-columns: auto 1fr auto auto;
    align-items: center;
    gap: 10px;
    margin-bottom: 12px;
}

.sr-toolbar label {
    color: var(--sr-text-soft);
    font-weight: 600;
    font-size: 0.9rem;
}

select,
input[type="text"] {
    background: #0b1220;
    color: var(--sr-text);
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 10px;
    min-height: 40px;
}

input[type="color"] {
    width: 44px;
    height: 40px;
    border: 1px solid #334155;
    border-radius: 8px;
    background: transparent;
    padding: 2px;
}

.sr-grid-2 {
    grid-template-columns: 2fr 1fr;
}

.sr-panel {
    background: #020617;
    border: 1px solid var(--sr-border);
    border-radius: 12px;
    padding: 12px;
}

.sr-panel h3 {
    margin: 0 0 10px 0;
    font-size: 1rem;
    color: var(--sr-title);
}

#layer-controls > div {
    display: grid;
    grid-template-columns: auto minmax(120px, 1fr) auto auto auto;
    align-items: center;
    gap: 8px;
    background: #0b1220;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 8px;
    margin-bottom: 8px;
}

#layer-controls label {
    color: var(--sr-text);
    font-size: 0.9rem;
}

#layer-controls select,
#layer-controls button,
#layer-controls input[type="color"] {
    min-height: 34px;
}

#layer-controls button {
    border: 1px solid #7f1d1d;
    background: rgba(127, 29, 29, 0.22);
    color: #fecaca;
    border-radius: 8px;
    padding: 6px 10px;
    cursor: pointer;
}

#layer-controls button:hover {
    background: rgba(127, 29, 29, 0.38);
}

.sr-support-list {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}

#resilience-map {
    height: 560px;
    border-radius: 12px;
    border: 1px solid var(--sr-border);
    margin-top: 14px;
}

.sr-alea-grid {
    grid-template-columns: repeat(3, minmax(180px, 1fr));
    align-items: end;
}

.sr-alea-grid label {
    display: flex;
    flex-direction: column;
    gap: 7px;
    color: var(--sr-text-soft);
    font-size: 0.88rem;
    font-weight: 600;
}

.sr-alea-grid select[multiple] {
    min-height: 120px;
}

.sr-inline-option {
    flex-direction: row !important;
    align-items: center;
    gap: 8px !important;
}

.sr-chip-row {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-top: 10px;
}

.sr-chip {
    background: rgba(8, 145, 178, 0.15);
    color: #67e8f9;
    border: 1px solid rgba(34, 211, 238, 0.35);
    border-radius: 999px;
    font-size: 0.82rem;
    padding: 6px 11px;
}

.sr-chip-link {
    text-decoration: none;
}

.sr-chip-link:hover {
    background: rgba(8, 145, 178, 0.3);
}

.sr-log-panel {
    margin-top: 12px;
    background: #020617;
    color: #cbd5e1;
    border: 1px solid #1e293b;
    border-radius: 10px;
    padding: 10px;
    min-height: 80px;
    max-height: 220px;
    overflow-y: auto;
    font-family: Consolas, "Courier New", monospace;
    font-size: 0.85rem;
}

.sr-log-panel div {
    margin-bottom: 4px;
}

.sr-table-wrap {
    overflow-x: auto;
}

.sr-table-wrap table,
#table-container table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.88rem;
}

.sr-table-wrap th,
.sr-table-wrap td,
#table-container th,
#table-container td {
    border: 1px solid #334155;
    padding: 8px 10px;
}

.sr-table-wrap thead,
#table-container thead {
    background: #0b1220;
}

.sr-table-wrap tbody tr:nth-child(even),
#table-container tbody tr:nth-child(even) {
    background: rgba(15, 23, 42, 0.65);
}

.sr-table-wrap tbody tr:hover,
#table-container tbody tr:hover {
    background: rgba(8, 145, 178, 0.15);
}

@media (max-width: 1100px) {
    .sr-toolbar {
        grid-template-columns: 1fr;
    }

    .sr-grid-2 {
        grid-template-columns: 1fr;
    }

    .sr-alea-grid {
        grid-template-columns: 1fr;
    }
}

@media (max-width: 820px) {
    .sr-topbar {
        flex-direction: column;
        align-items: flex-start;
    }

    .sr-nav {
        width: 100%;
        justify-content: flex-start;
    }

    #layer-controls > div {
        grid-template-columns: 1fr;
        justify-items: stretch;
    }

    .sr-main {
        padding: 14px;
    }
}
````

#### static/css/style.css

````css

/* Reset de base */
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: 'Poppins', sans-serif;
    background: linear-gradient(to right, #f6f8fb, #eef1f6);
    color: #2c3e50;
    line-height: 1.6;
    overflow-x: hidden;
}

/* Header */
header {
    background: linear-gradient(90deg, #003d6b, #005aa3);
    color: #fff;
    padding: 1.5rem 1rem;
    text-align: center;
    position: relative;
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
}

header img {
    position: absolute;
    top: 15px;
    left: 15px;
    height: 60px;
}

header h1 {
    font-size: 2.5rem;
    text-transform: uppercase;
    letter-spacing: 1.8px;
}

/* Main container */
main {
    padding: 2rem;
}

.container {
    max-width: 1180px;
    margin: 0 auto;
    background: #fff;
    border-radius: 18px;
    box-shadow: 0 14px 30px rgba(0, 0, 0, 0.08);
    padding: 32px;
    border: 1px solid #e5e9f2;
}

/* Titres */
h2 {
    color: #444;
    font-size: 2rem;
    text-align: center;
    margin-bottom: 1rem;
    text-transform: uppercase;
    letter-spacing: 1px;
}

/* Sections */
.section {
    background: #fdfefe;
    margin: 1.5rem 0;
    border-radius: 14px;
    padding: 22px;
    box-shadow: 0 8px 18px rgba(18, 38, 63, 0.08);
    border: 1px solid #eef2f7;
}

/* Layout spécifique à la section aléas */
.alea-card {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 14px 18px;
    align-items: center;
}

.alea-card label {
    font-weight: 600;
    color: #34495e;
}

.alea-actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    align-items: center;
    margin-top: 8px;
}

.chip {
    background: #eef5ff;
    color: #1f4b99;
    padding: 6px 12px;
    border-radius: 999px;
    font-size: 0.9rem;
    border: 1px solid #d8e6ff;
}

.log-panel {
    margin-top: 12px;
    background: #0f172a;
    color: #e5e7eb;
    border-radius: 12px;
    padding: 12px 14px;
    font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', monospace;
    max-height: 220px;
    overflow-y: auto;
    border: 1px solid #1e293b;
}

.log-panel div { margin-bottom: 4px; }

/* Input file style */
.file-input-container {
    text-align: center;
    margin-bottom: 1.5rem;
    padding: 1rem;
    border: 2px dashed #005aa3; /* Couleurs SIPPEREC */
    border-radius: 12px;
    transition: border-color 0.3s ease;
}

.file-input-container:hover {
    border-color: #006b0e; 
}

.file-input-container label {
    background: linear-gradient(90deg, #005aa3, #003d6b); /* Couleurs SIPPEREC */
    color: #fff;
    padding: 1rem;
    border-radius: 8px;
    font-size: 1rem;
    cursor: pointer;
    display: inline-block;
    transition: all 0.3s ease;
    margin-bottom: 10px;
    min-width: 300px; /* Taille minimale uniforme */
    text-align: center;
}

.file-input-container label:hover {
    background: linear-gradient(90deg, #003d6b, #002a4e); /* Couleurs SIPPEREC */
    transform: scale(1.05);
}

.selected-file {
    margin-top: 10px;
    font-style: italic;
    color: #666;
}

/* Boutons uniformes */
button {
    min-width: 180px;
    height: 44px;
    padding: 0 16px;
    border: none;
    border-radius: 10px;
    background: linear-gradient(135deg, #0b68ff, #004aad);
    color: #fff;
    font-size: 0.95rem;
    font-weight: 700;
    text-transform: none;
    cursor: pointer;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
    box-shadow: 0 8px 16px rgba(0, 74, 173, 0.25);
}

button:hover {
    transform: translateY(-1px);
    box-shadow: 0 12px 22px rgba(0, 74, 173, 0.28);
}

.button-container {
    display: flex;
    justify-content: center;
    gap: 15px;
    flex-wrap: wrap;
}

/* Dropdown for file list */
.file-list {
    max-height: 150px;
    overflow-y: auto;
    background: #fff;
    border: 1px solid #ddd;
    border-radius: 8px;
    padding: 10px;
    text-align: left;
    margin-top: 1rem;
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
}

.file-list li {
    list-style: none;
    padding: 8px;
    font-size: 1rem;
    border-bottom: 1px solid #eee;
}

.file-list li:last-child {
    border-bottom: none;
}

/* Résultats */
.result-container {
    margin-top: 2rem;
    text-align: center;
    padding: 1.5rem;
    background: #f9f9f9;
    border-radius: 12px;
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
}

.result-container h3 {
    font-size: 1.8rem;
    color: #444;
    margin-bottom: 1rem;
    text-transform: uppercase;
}

.result-container .file-list {
    max-height: 200px;
    overflow-y: auto;
    border: 1px solid #ddd;
    padding: 15px;
    border-radius: 8px;
    text-align: left;
    box-shadow: 0 6px 12px rgba(0, 0, 0, 0.1);
}

.result-container .file-list li {
    list-style: none;
    border-bottom: 1px solid #eee;
    padding: 8px;
    font-size: 1rem;
}

.result-container .file-list li:last-child {
    border-bottom: none;
}

/* Download button */
.btn-download {
    display: inline-block;
    margin-top: 15px;
    padding: 12px 20px;
    background: linear-gradient(90deg, #005aa3, #003d6b); 
    color: #fff;
    border-radius: 8px;
    font-size: 1rem;
    font-weight: bold;
    text-transform: uppercase;
    text-decoration: none;
    transition: all 0.3s ease;
}

.btn-download:hover {
    background: linear-gradient(90deg, #003d6b, #002a4e); /* Couleurs SIPPEREC */
    transform: scale(1.05);
}

/* Responsive design */
@media (max-width: 768px) {
    button {
        width: 100%;
        font-size: 0.9rem;
    }
}


/* Styles pour les boutons Importer et Importer les Deux Exports */
.btn-import-green {
    display: block; /* S'assure qu'ils sont affichés en tant que blocs pour un centrage facile */
    margin: 20px auto; /* Centre horizontalement et ajoute un espacement vertical */
    width: 400px; /* Largeur fixe pour uniformité */
    height: 50px; /* Hauteur fixe */
    padding: 0;
    border: none;
    border-radius: 8px;
    background: linear-gradient(90deg, #28a745, #218838); /* Dégradé vert */
    color: #fff; /* Texte en blanc */
    font-size: 1rem;
    font-weight: bold;
    text-transform: uppercase;
    cursor: pointer;
    transition: all 0.3s ease; /* Douce transition sur l'effet hover */
    text-align: center;
}

.btn-import-green:hover {
    background: linear-gradient(90deg, #218838, #1e7e34); /* Vert plus foncé au survol */
    transform: scale(1.05); /* Légère mise en avant */
}


/* Styles pour les boutons Télécharger */
.btn-download-green {
    background: linear-gradient(90deg, #28a745, #218838); /* Dégradé vert */
    color: #fff; /* Texte en blanc */
    border-radius: 8px;
    font-size: 1rem;
    font-weight: bold;
    text-transform: uppercase;
    text-decoration: none;
    padding: 12px 20px; /* Espacement interne */
    display: inline-block;
    text-align: center;
    transition: all 0.3s ease; /* Transition douce pour l'effet hover */
    margin-top: 15px; /* Espacement supérieur */
}

.btn-download-green:hover {
    background: linear-gradient(90deg, #218838, #1e7e34); /* Vert plus foncé au survol */
    transform: scale(1.05); /* Effet de zoom léger */
}

/* Styles pour les tableaux */
table {
    width: 100%; /* Le tableau occupe toute la largeur du conteneur */
    border-collapse: collapse; /* Fusion des bordures pour un look propre */
    margin: 20px 0; /* Espacement au-dessus et au-dessous */
    font-size: 1rem; /* Taille de police */
    text-align: left; /* Texte aligné à gauche */
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1); /* Ombre pour un effet 3D */
}

table thead {
    background-color: #28a745; /* Couleur d'en-tête verte */
    color: #fff; /* Texte en blanc */
}

table th, table td {
    padding: 12px 15px; /* Espacement interne pour un tableau aéré */
    border: 1px solid #ddd; /* Bordure légère entre les cellules */
}

table tbody tr:nth-child(even) {
    background-color: #f9f9f9; /* Couleur de fond alternée pour les lignes paires */
}

table tbody tr:hover {
    background-color: #eafbea; /* Surlignage léger au survol */
}

/* Boutons Télécharger */
a.download-btn {
    display: inline-block;
    background: linear-gradient(90deg, #28a745, #218838); /* Dégradé vert */
    color: #fff; /* Texte blanc */
    padding: 10px 20px; /* Espacement interne */
    border-radius: 8px; /* Coins arrondis */
    font-size: 1rem; /* Taille de police */
    font-weight: bold; /* Texte en gras */
    text-transform: uppercase; /* Texte en majuscules */
    text-decoration: none; /* Pas de soulignement */
    margin-right: 10px; /* Espacement horizontal */
    transition: all 0.3s ease; /* Transition douce pour l'effet hover */
}

a.download-btn:hover {
    background: linear-gradient(90deg, #218838, #1e7e34); /* Dégradé plus sombre au survol */
    transform: scale(1.05); /* Zoom léger */
}

/* Style pour les cases de date (type month) */
.export-date-input {
    width: 250px; /* Largeur personnalisée */
    padding: 10px 15px; /* Espacement interne */
    font-size: 1rem; /* Taille de la police */
    align-items: center;
    color: #333; /* Couleur du texte */
    border: 1px solid #ddd; /* Bordure légère */
    border-radius: 8px; /* Coins arrondis */
    background: #f9f9f9; /* Couleur de fond */
    transition: all 0.3s ease; /* Transition pour les effets */
}

/* Focus : mettre en avant la case sélectionnée */
.export-date-input:focus {
    outline: none; /* Retire le contour par défaut */
    border-color: #28a745; /* Bordure verte */
    box-shadow: 0 0 5px rgba(40, 167, 69, 0.5); /* Effet lumineux */
    background: #fff; /* Fond blanc pour la case active */
}

/* Pour s'assurer qu'il est aligné avec les labels */
.date-selector label {
    font-size: 1rem; /* Taille de police uniforme */
    margin-bottom: 5px; /* Espacement avec l'input */
    display: block; /* Forcer un alignement vertical */
    color: #444; /* Couleur du texte */
}


/* Conteneur pour le logo */
.logo-container {
    background-color: #fff; /* Fond blanc */
    padding: 20px; /* Espacement interne */
    border-radius: 12px; /* Coins arrondis */
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2); /* Ombre légère */
    display: flex;
    width: 100px; 
    height: 40px; 
    margin: 12 auto; 
}

/* Image à l'intérieur du conteneur */
.logo-container img {
    max-width: 100%; 
    max-height: 100%; 
    object-fit: contain; 
   
}


.drop-zone {
    border: 2px dashed #005aa3;
    border-radius: 8px;
    padding: 20px;
    text-align: center;
    font-size: 1rem;
    color: #005aa3;
    cursor: pointer;
    transition: background-color 0.3s ease, border-color 0.3s ease;
}

.drop-zone.dragover {
    background-color: #e6f7ff;
    border-color: #003d6b;
    color: #003d6b;
}

.logout-container {
    position: absolute;
    top: 20px;
    right: 20px;
}

.btn-logout {
    background: #ff4d4d;
    color: white;
    padding: 10px 15px;
    border-radius: 5px;
    text-decoration: none;
    font-weight: bold;
    transition: 0.3s ease;
}

.btn-logout:hover {
    background: #cc0000;
}

/* Nouveau style pour le bouton "Analyser Tout" */
.btn-export-analysis-green {
    width: 250px;
    height: 50px;
    padding: 0;
    border: none;
    border-radius: 8px;
    background: linear-gradient(90deg, #a79a28, #887021); 
    color: #fff;
    font-size: 1rem;
    font-weight: bold;
    text-transform: uppercase;
    cursor: pointer;
    transition: all 0.3s ease;
    text-align: center;
}

.btn-export-analysis-green:hover {
    background: linear-gradient(90deg, #888121, #1e7e34);
    transform: translateY(-2px) scale(1.05);
}

/* Bouton history export */
.export-history {
    margin-bottom: 1rem;
}

.accordion-toggle {
    background: linear-gradient(90deg, #005aa3, #003d6b);
    color: white;
    font-weight: bold;
    padding: 10px 15px;
    border: none;
    border-radius: 8px;
    width: 100%;
    text-align: left;
    font-size: 1rem;
    cursor: pointer;
    transition: background 0.3s ease;
    
}

.accordion-toggle:hover {
    background: linear-gradient(90deg, #003d6b, #002a4e);
}

.export-history-panel {
    max-height: 0;
    overflow: hidden;
    transition: max-height 0.4s ease;
    background-color: #f9f9f9;
    padding: 0 10px;
    border-radius: 0 0 8px 8px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.1);
}
.export-history-panel.open {
    max-height: 300px;
    padding: 10px;
}

/* Styles pour les icônes d'information */
.info-icon {
    display: inline-block;
    margin-left: 8px;
    width: 18px;
    height: 18px;
    background-color: #005aa3;
    color: white;
    border-radius: 50%;
    text-align: center;
    font-style: normal;
    font-size: 12px;
    line-height: 18px;
    font-weight: bold;
    cursor: help;
    transition: all 0.3s ease;
}

button:hover .info-icon {
    background-color: white;
    color: #005aa3;
}

.btn-with-tooltip::after {
  /* structure + position */
  content: attr(data-tooltip);
  position: absolute;
  left: 50%;
  bottom: calc(100% + 0.5em);
  transform: translateX(-50%);
  display: block;
  width: 550px;
  max-height: 200px;
  overflow-y: auto;
  
  /* pré‐servations des espaces et retours */
  white-space: pre-wrap;
  word-break: break-word;
  
  /* style */
  background: rgba(0,0,0,0.85);
  color: #fff;
  padding: 0.6em 0.8em;
  border-radius: 4px;
  font-size: 0.9rem;
  line-height: 1.4;
  text-align: left;      /* aligné à gauche */
  font-weight: normal;
  text-transform: none;  /* conserve la casse */
  
  /* apparition */
  opacity: 0;
  visibility: hidden;
  transition: opacity .2s, visibility .2s;
  z-index: 1000;
  pointer-events: auto;
  overscroll-behavior: contain;
}

/* petit triangle */
.btn-with-tooltip::before {
  content: "";
  position: absolute;
  left: 50%;
  bottom: 100%;
  transform: translateX(-50%);
  border: 6px solid transparent;
  border-top-color: rgba(0,0,0,0.85);
  opacity: 0;
  visibility: hidden;
  transition: opacity .2s, visibility .2s;
  z-index: 1000;
}

.btn-with-tooltip:hover::after,
.btn-with-tooltip:hover::before {
  opacity: 1;
  visibility: visible;
}
````

### Backend Flask

#### app.py

````python
from flask import Flask, request, jsonify, render_template, redirect, send_from_directory, url_for, session, flash, send_file, Response, stream_with_context
from werkzeug.utils import secure_filename
import geopandas as gpd
from geoalchemy2 import Geometry
from flask_sqlalchemy import SQLAlchemy
import os
import pandas as pd
import chardet
import urllib.parse
from sqlalchemy import create_engine
import json
import logging
import hashlib
from dbfread import DBF
import base64
import csv
from sqlalchemy import inspect
from io import StringIO  
from shapely.geometry import shape, Polygon, MultiPolygon, LineString, MultiLineString, Point, MultiPoint
from shapely.geometry.base import BaseGeometry
from shapely.validation import make_valid
import fiona
import time
from shapely import wkt as shapely_wkt
from shapely import wkb as shapely_wkb
from sqlalchemy import text
import numpy as np
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from dotenv import load_dotenv
import traceback
from datetime import datetime
import zipfile
import io
from zipfile import ZipFile
import tempfile, requests
from flask import jsonify, request
import re
import shutil
import subprocess
import html
from pathlib import Path
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from dotenv import load_dotenv
from sqlalchemy.sql.elements import quoted_name as sa_quoted_name
from pyproj import CRS
load_dotenv() 

from sqlalchemy import create_engine, text

app = Flask(__name__)

SIDE_CAR_EXTS = {'.dbf', '.shx', '.prj', '.cpg', '.sbn', '.sbx'}
RESILIENCE_ANALYSIS_SESSION_KEY = "resilience_analysis_upload"
RESILIENCE_ANALYSIS_STAGE_DIRNAME = "resilience_analysis_stage"
RESILIENCE_IMPACT_LEVELS = (0, 1, 2, 3)
RESILIENCE_HELP_PAGE_KEY = "resilience_manual"
ADMIN_SUPPORT_INIT_LOCK_KEY = 8201001
RUN_HISTORY_INIT_LOCK_KEY = 8201002
DEFAULT_RESILIENCE_HELP_TITLE = "Manuel d'utilisation SippeRésiste"
DEFAULT_RESILIENCE_HELP_BODY = (
    "1. Configuration: importer les couches et contrôler leur affichage cartographique.\n\n"
    "2. Analyse Réseau: importer une couche infra temporaire, sélectionner les aléas à injecter "
    "et lancer le calcul de résilience.\n\n"
    "3. Historique runs: consulter les exécutions passées, leurs exports et la table attributaire.\n\n"
    "4. Admin. & Accès: créer des comptes et définir les droits administrateur.\n\n"
    "5. Aide & Doc: maintenir la documentation visible par les utilisateurs."
)
RESILIENCE_HELP_DOCUMENT_EXTS = {".pdf", ".doc", ".docx"}
RESILIENCE_HELP_DOCUMENT_MAX_BYTES = 25 * 1024 * 1024

# --- Options app ---
app.config['RESET_LINK_VIA_UI'] = os.getenv('RESET_LINK_VIA_UI', '0') == '1'
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "change-me-in-prod")
LOGIN_TEMPLATE = os.getenv("LOGIN_TEMPLATE", "login_resilience.html")
AUTH_SCHEMA = os.getenv("AUTH_SCHEMA", "resilience")

# --- Logging simple et lisible ---
logging.basicConfig(
    level=logging.DEBUG if os.getenv("FLASK_DEBUG", "0") == "1" else logging.INFO,
    format="%(asctime)s %(levelname)s:%(message)s"
)

# --- Connexion PostgreSQL ---
username = urllib.parse.quote_plus(os.getenv("DB_USERNAME", "postgres"))
password = urllib.parse.quote_plus(os.getenv("DB_PASSWORD", ""))
host     = os.getenv("DB_HOST", "db")
dbname   = os.getenv("DB_NAME", "postgres")
port     = os.getenv("DB_PORT", "5432")  # <- IMPORTANT : 5432 dans le réseau Docker

search_path = os.getenv("DB_SEARCH_PATH", "resilience,public")

app.config['SQLALCHEMY_DATABASE_URI'] = (
    f'postgresql://{username}:{password}@{host}:{port}/{dbname}'
    f'?options=-csearch_path%3D{search_path}'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Evite les connexions mortes si Postgres redémarre
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}

# --- DB objects ---
db = SQLAlchemy(app)
engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI'], pool_pre_ping=True)

# --- Base URL pour appels HTTP internes (à la place de 127.0.0.1:5000 en dev) ---
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")
_KEY_COLUMN_CACHE: dict[tuple[str, str], str | None] = {}
_ADMIN_SUPPORT_READY = False
_RUN_HISTORY_READY = False
PUBLIC_EXACT_PATHS = {
    "/healthz",
    "/login",
    "/logout",
    "/forgot",
}
PUBLIC_PREFIX_PATHS = (
    "/reset/",
    "/image/",
)
PUBLIC_STATIC_PREFIX_PATHS = (
    "/static/css/",
    "/static/js/",
)

def _quote_ident(identifier: str) -> str:
    """
    Quote un identifiant SQL (schema/table/colonne/index) en échappant les guillemets.
    """
    ident = str(identifier or "")
    if not ident or "\x00" in ident:
        raise ValueError("Identifiant SQL invalide.")
    return '"' + ident.replace('"', '""') + '"'


def _qualified_ident(schema: str, name: str) -> str:
    return f"{_quote_ident(schema)}.{_quote_ident(name)}"


def _is_public_path(path: str) -> bool:
    if path in PUBLIC_EXACT_PATHS:
        return True
    if any(path.startswith(prefix) for prefix in PUBLIC_PREFIX_PATHS):
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_STATIC_PREFIX_PATHS)


def _wants_json_auth_response() -> bool:
    if request.is_json:
        return True
    best = request.accept_mimetypes.best
    return best == "application/json" and (
        request.accept_mimetypes["application/json"]
        >= request.accept_mimetypes["text/html"]
    )


@app.before_request
def require_authenticated_user():
    if _is_public_path(request.path):
        return None
    if _current_user_id() is not None:
        return None
    if _wants_json_auth_response():
        return jsonify({"status": "error", "message": "Utilisateur non authentifié."}), 401
    return redirect(url_for("login"))


@app.get("/healthz")
def healthz():
    """Petite sonde pour vérifier l'app et la DB."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return jsonify({"status": "ok", "db": db_ok}), 200 if db_ok else 500


@app.cli.command("init-db")
def init_db_cli():
    """Créer les tables (à lancer manuellement si besoin) :
       docker compose exec web flask --app app init-db
    """
    with app.app_context():
        db.create_all()
    print("Database tables created.")

# Modèle utilisateur
class User(db.Model):
    __tablename__ = 'users'
    __table_args__ = {'schema': AUTH_SCHEMA}
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False, server_default=text('false'))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

def _serializer():
    # Le SECRET_KEY existe déjà dans ta config (env). On ajoute un "salt" dédié.
    return URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='password-reset')

def make_reset_token(user):
    # On inclut le hash courant: si le mdp change, l'ancien jeton ne marchera plus
    payload = {'uid': user.id, 'ph': user.password_hash}
    return _serializer().dumps(payload)

def load_user_from_token(token, max_age_seconds=3600):
    _ensure_admin_support_tables()
    data = _serializer().loads(token, max_age=max_age_seconds)
    user = User.query.get(data.get('uid'))
    if not user or user.password_hash != data.get('ph'):
        # Jeton forgé / expiré / mdp déjà changé
        raise BadSignature("Invalid token")
    return user


# Middleware pour vérifier si l'utilisateur est connecté
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if _current_user_id() is None:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Route de connexion
@app.route('/login', methods=['GET', 'POST'])
def login():
    _ensure_admin_support_tables()
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            flash("Connexion réussie.", "success")
            return redirect(url_for('resilience'))
        else:
            flash('Identifiants incorrects', 'danger')

    return render_template(LOGIN_TEMPLATE)

# Route de déconnexion
@app.route('/logout')
def logout():
    _clear_resilience_analysis_upload_for_user(_current_user_id(), clear_files=True)
    session.pop('user_id', None)
    flash("Déconnexion réussie.", "success")
    return redirect(url_for('login'))


def _current_user_id() -> int | None:
    raw_user_id = session.get("user_id")
    try:
        user_id = int(raw_user_id)
    except (TypeError, ValueError):
        return None
    return user_id if user_id > 0 else None


def _current_user() -> User | None:
    _ensure_admin_support_tables()
    user_id = _current_user_id()
    if user_id is None:
        return None
    return db.session.get(User, user_id)


def _ensure_admin_support_tables():
    global _ADMIN_SUPPORT_READY
    if _ADMIN_SUPPORT_READY:
        return

    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": ADMIN_SUPPORT_INIT_LOCK_KEY})
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_quote_ident(AUTH_SCHEMA)}"))

        q_users = _qualified_ident(AUTH_SCHEMA, "users")
        q_help = _qualified_ident(AUTH_SCHEMA, "help_content")
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {q_users} (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL
            )
        """))
        conn.execute(text(f"""
            ALTER TABLE {q_users}
            ADD COLUMN IF NOT EXISTS is_admin BOOLEAN
        """))
        conn.execute(text(f"""
            UPDATE {q_users}
            SET is_admin = TRUE
            WHERE is_admin IS NULL
        """))
        conn.execute(text(f"""
            ALTER TABLE {q_users}
            ALTER COLUMN is_admin SET DEFAULT FALSE
        """))
        conn.execute(text(f"""
            ALTER TABLE {q_users}
            ALTER COLUMN is_admin SET NOT NULL
        """))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {q_help} (
                page_key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                updated_by INTEGER,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {_help_documents_table_ident()} (
                page_key TEXT PRIMARY KEY,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_ext TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                file_size BIGINT NOT NULL DEFAULT 0,
                preview_text TEXT,
                uploaded_by INTEGER,
                uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        conn.execute(text(f"""
            INSERT INTO {q_help} (page_key, title, body, updated_at)
            VALUES (:page_key, :title, :body, now())
            ON CONFLICT (page_key) DO NOTHING
        """), {
            "page_key": RESILIENCE_HELP_PAGE_KEY,
            "title": DEFAULT_RESILIENCE_HELP_TITLE,
            "body": DEFAULT_RESILIENCE_HELP_BODY,
        })
    _ADMIN_SUPPORT_READY = True


def _require_admin_user() -> User:
    _ensure_admin_support_tables()
    user = _current_user()
    if not user:
        raise PermissionError("Utilisateur non authentifié.")
    if not bool(user.is_admin):
        raise PermissionError("Accès administrateur requis.")
    return user


def _resilience_help_content(conn):
    q_help = _qualified_ident(AUTH_SCHEMA, "help_content")
    row = conn.execute(text(f"""
        SELECT page_key, title, body, updated_by, updated_at
        FROM {q_help}
        WHERE page_key = :page_key
    """), {"page_key": RESILIENCE_HELP_PAGE_KEY}).mappings().first()

    if row:
        return {
            "page_key": row["page_key"],
            "title": row["title"],
            "body": row["body"],
            "updated_by": row["updated_by"],
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        }

    return {
        "page_key": RESILIENCE_HELP_PAGE_KEY,
        "title": DEFAULT_RESILIENCE_HELP_TITLE,
        "body": DEFAULT_RESILIENCE_HELP_BODY,
        "updated_by": None,
        "updated_at": None,
    }


def _resilience_help_document_root() -> str:
    root = os.path.join(os.getcwd(), "uploads", "resilience_help_docs")
    os.makedirs(root, exist_ok=True)
    return root


def _help_documents_table_ident() -> str:
    return _qualified_ident(AUTH_SCHEMA, "help_documents")


def _normalize_resilience_help_document_ext(filename: str) -> str:
    ext = os.path.splitext(str(filename or ""))[1].lower().strip()
    if ext not in RESILIENCE_HELP_DOCUMENT_EXTS:
        raise ValueError("Formats acceptés : PDF, DOC ou DOCX.")
    return ext


def _resilience_help_document_mimetype(ext: str) -> str:
    if ext == ".pdf":
        return "application/pdf"
    if ext == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if ext == ".doc":
        return "application/msword"
    return "application/octet-stream"


def _resilience_help_preview_root() -> str:
    root = os.path.join(_resilience_help_document_root(), "_previews")
    os.makedirs(root, exist_ok=True)
    return root


def _resilience_help_preview_pdf_path(document: dict | None) -> str:
    stored_filename = str((document or {}).get("stored_filename") or "").strip()
    if not stored_filename:
        file_path = str((document or {}).get("file_path") or "").strip()
        stored_filename = os.path.basename(file_path)
    base_name = os.path.splitext(stored_filename)[0]
    return os.path.join(_resilience_help_preview_root(), f"{base_name}.pdf")


def _resilience_help_office_converter_bin() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def _resilience_help_word_preview_supported() -> bool:
    return bool(_resilience_help_office_converter_bin())


def _generate_resilience_help_preview_pdf(source_path: str, output_pdf_path: str):
    soffice_bin = _resilience_help_office_converter_bin()
    if not soffice_bin:
        raise RuntimeError("Le convertisseur LibreOffice n'est pas disponible sur le serveur.")

    out_dir = tempfile.mkdtemp(prefix="resilience_help_pdf_")
    profile_dir = tempfile.mkdtemp(prefix="resilience_help_lo_")
    generated_pdf = os.path.join(
        out_dir,
        f"{os.path.splitext(os.path.basename(source_path))[0]}.pdf",
    )
    try:
        subprocess.run(
            [
                soffice_bin,
                "--headless",
                f"-env:UserInstallation={Path(profile_dir).resolve().as_uri()}",
                "--convert-to",
                "pdf:writer_pdf_Export",
                "--outdir",
                out_dir,
                source_path,
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        if not os.path.isfile(generated_pdf):
            raise RuntimeError("Le PDF de prévisualisation n'a pas été généré.")
        os.makedirs(os.path.dirname(output_pdf_path), exist_ok=True)
        shutil.move(generated_pdf, output_pdf_path)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("La conversion Word vers PDF a dépassé le délai autorisé.") from exc
    except subprocess.CalledProcessError as exc:
        stderr_text = (exc.stderr or b"").decode("utf-8", errors="ignore").strip()
        stdout_text = (exc.stdout or b"").decode("utf-8", errors="ignore").strip()
        detail = stderr_text or stdout_text or "erreur LibreOffice inconnue"
        raise RuntimeError(f"Conversion Word vers PDF impossible : {detail}") from exc
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
        shutil.rmtree(profile_dir, ignore_errors=True)


def _ensure_resilience_help_preview_pdf(document: dict | None, force_refresh: bool = False) -> str:
    source_path = str((document or {}).get("file_path") or "").strip()
    ext = str((document or {}).get("file_ext") or "").lower().strip()
    if not source_path or ext not in {".doc", ".docx"}:
        raise RuntimeError("Le document fourni n'est pas un fichier Word convertible.")

    output_pdf_path = _resilience_help_preview_pdf_path(document)
    if not force_refresh and os.path.isfile(output_pdf_path):
        return output_pdf_path

    _generate_resilience_help_preview_pdf(source_path, output_pdf_path)
    return output_pdf_path


def _store_resilience_help_document(uploaded_file, uploaded_by: int | None) -> dict:
    original_filename = os.path.basename(uploaded_file.filename or "").strip()
    if not original_filename:
        raise ValueError("Aucun document fourni.")

    safe_name = secure_filename(original_filename)
    if not safe_name:
        raise ValueError("Nom de fichier invalide.")

    ext = _normalize_resilience_help_document_ext(safe_name)
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    stored_filename = f"resilience_manual_{timestamp}{ext}"
    target_dir = _resilience_help_document_root()
    target_path = os.path.join(target_dir, stored_filename)
    uploaded_file.save(target_path)

    file_size = os.path.getsize(target_path)
    if file_size <= 0:
        _delete_resilience_help_document_file({"file_path": target_path})
        raise ValueError("Le document importé est vide.")
    if file_size > RESILIENCE_HELP_DOCUMENT_MAX_BYTES:
        _delete_resilience_help_document_file({"file_path": target_path})
        raise ValueError("Le document dépasse la taille maximale autorisée (25 Mo).")

    document_meta = {
        "stored_filename": stored_filename,
        "file_path": target_path,
        "file_ext": ext,
    }
    if ext in {".doc", ".docx"}:
        try:
            _ensure_resilience_help_preview_pdf(document_meta, force_refresh=True)
        except Exception as exc:
            _delete_resilience_help_document_file(document_meta)
            raise ValueError(
                "Impossible de générer une prévisualisation fidèle du document Word. "
                "Essayez d'importer un PDF ou réexportez votre document Word."
            ) from exc

    return {
        "page_key": RESILIENCE_HELP_PAGE_KEY,
        "original_filename": original_filename,
        "stored_filename": stored_filename,
        "file_path": target_path,
        "file_ext": ext,
        "mime_type": _resilience_help_document_mimetype(ext),
        "file_size": file_size,
        "preview_text": "",
        "uploaded_by": uploaded_by,
        "uploaded_at": datetime.utcnow().isoformat(),
    }


def _delete_resilience_help_document_file(document: dict | None):
    path = str((document or {}).get("file_path") or "").strip()
    preview_pdf_path = ""
    try:
        preview_pdf_path = _resilience_help_preview_pdf_path(document)
    except Exception:
        preview_pdf_path = ""
    try:
        if path and os.path.isfile(path):
            os.remove(path)
        if preview_pdf_path and os.path.isfile(preview_pdf_path):
            os.remove(preview_pdf_path)
    except Exception:
        logging.exception("Suppression impossible du document d'aide %s.", path)


def _resilience_help_document(conn):
    q_docs = _help_documents_table_ident()
    row = conn.execute(text(f"""
        SELECT page_key, original_filename, stored_filename, file_path, file_ext, mime_type, file_size, preview_text, uploaded_by, uploaded_at
        FROM {q_docs}
        WHERE page_key = :page_key
    """), {"page_key": RESILIENCE_HELP_PAGE_KEY}).mappings().first()

    if not row:
        return None

    document = {
        "page_key": row["page_key"],
        "original_filename": row["original_filename"],
        "stored_filename": row["stored_filename"],
        "file_path": row["file_path"],
        "file_ext": row["file_ext"],
        "mime_type": row["mime_type"],
        "file_size": int(row["file_size"] or 0),
        "preview_text": row["preview_text"] or "",
        "uploaded_by": row["uploaded_by"],
        "uploaded_at": row["uploaded_at"].isoformat() if row["uploaded_at"] else None,
    }

    if document["file_path"] and os.path.isfile(document["file_path"]):
        return document

    conn.execute(text(f"""
        DELETE FROM {q_docs}
        WHERE page_key = :page_key
    """), {"page_key": RESILIENCE_HELP_PAGE_KEY})
    return None


def _upsert_resilience_help_document(conn, document: dict):
    q_docs = _help_documents_table_ident()
    conn.execute(text(f"""
        INSERT INTO {q_docs}
        (page_key, original_filename, stored_filename, file_path, file_ext, mime_type, file_size, preview_text, uploaded_by, uploaded_at)
        VALUES (:page_key, :original_filename, :stored_filename, :file_path, :file_ext, :mime_type, :file_size, :preview_text, :uploaded_by, now())
        ON CONFLICT (page_key) DO UPDATE
        SET original_filename = EXCLUDED.original_filename,
            stored_filename = EXCLUDED.stored_filename,
            file_path = EXCLUDED.file_path,
            file_ext = EXCLUDED.file_ext,
            mime_type = EXCLUDED.mime_type,
            file_size = EXCLUDED.file_size,
            preview_text = EXCLUDED.preview_text,
            uploaded_by = EXCLUDED.uploaded_by,
            uploaded_at = now()
    """), {
        "page_key": RESILIENCE_HELP_PAGE_KEY,
        "original_filename": document["original_filename"],
        "stored_filename": document["stored_filename"],
        "file_path": document["file_path"],
        "file_ext": document["file_ext"],
        "mime_type": document["mime_type"],
        "file_size": int(document["file_size"] or 0),
        "preview_text": document.get("preview_text") or "",
        "uploaded_by": document.get("uploaded_by"),
    })


def _delete_resilience_help_document_row(conn):
    q_docs = _help_documents_table_ident()
    document = _resilience_help_document(conn)
    conn.execute(text(f"""
        DELETE FROM {q_docs}
        WHERE page_key = :page_key
    """), {"page_key": RESILIENCE_HELP_PAGE_KEY})
    return document


def _serialize_resilience_help_document(document: dict | None) -> dict | None:
    if not document:
        return None

    ext = str(document.get("file_ext") or "").lower()
    preview_mode = "none"
    preview_available = False
    if ext == ".pdf":
        preview_mode = "pdf"
        preview_available = True
    elif ext in {".doc", ".docx"}:
        preview_mode = "word_pdf"
        preview_available = _resilience_help_word_preview_supported()

    return {
        "original_filename": document.get("original_filename"),
        "file_ext": ext,
        "mime_type": document.get("mime_type"),
        "file_size": int(document.get("file_size") or 0),
        "uploaded_by": document.get("uploaded_by"),
        "uploaded_at": document.get("uploaded_at"),
        "preview_available": preview_available,
        "preview_mode": preview_mode,
        "download_url": url_for("resilience_help_document_download"),
        "preview_url": url_for("resilience_help_document_preview"),
    }


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "oui"}


def _normalize_alea_layer_name(name: str) -> str:
    normalized = re.sub(r'[^A-Za-z0-9_]+', '_', str(name or '').strip()).strip('_').lower()
    if not normalized:
        raise ValueError("Nom de couche aléa invalide.")
    if not normalized.startswith("alea_"):
        normalized = f"alea_{normalized}"
    return normalized[:63]


def _resilience_analysis_stage_root() -> str:
    root = os.path.join(tempfile.gettempdir(), RESILIENCE_ANALYSIS_STAGE_DIRNAME)
    os.makedirs(root, exist_ok=True)
    return root


def _clear_resilience_analysis_upload_files(upload: dict | None):
    if not isinstance(upload, dict):
        return
    staging_dir = str(upload.get("staging_dir") or "").strip()
    if staging_dir and os.path.isdir(staging_dir):
        shutil.rmtree(staging_dir, ignore_errors=True)


def _pop_session_resilience_analysis_upload(clear_files: bool = True):
    upload = session.pop(RESILIENCE_ANALYSIS_SESSION_KEY, None)
    if clear_files:
        _clear_resilience_analysis_upload_files(upload)
    session.modified = True
    return upload


def _sanitize_session_resilience_analysis_upload(raw_upload) -> dict | None:
    if not isinstance(raw_upload, dict):
        return None
    display_name = str(raw_upload.get("display_name") or "").strip()
    dataset_path = str(raw_upload.get("dataset_path") or "").strip()
    staging_dir = str(raw_upload.get("staging_dir") or "").strip()
    if not display_name or not dataset_path or not staging_dir:
        return None
    return {
        "display_name": display_name,
        "dataset_path": dataset_path,
        "staging_dir": staging_dir,
    }


def _get_session_resilience_analysis_upload() -> dict | None:
    upload = _sanitize_session_resilience_analysis_upload(session.get(RESILIENCE_ANALYSIS_SESSION_KEY))
    if not upload:
        return None
    if not os.path.exists(upload["dataset_path"]):
        _pop_session_resilience_analysis_upload(clear_files=True)
        return None
    return upload


def _set_session_resilience_analysis_upload(display_name: str, dataset_path: str, staging_dir: str):
    _pop_session_resilience_analysis_upload(clear_files=True)
    session[RESILIENCE_ANALYSIS_SESSION_KEY] = {
        "display_name": str(display_name or "").strip(),
        "dataset_path": str(dataset_path or "").strip(),
        "staging_dir": str(staging_dir or "").strip(),
    }
    session.modified = True


def _analysis_upload_registry_row_to_payload(row) -> dict | None:
    if not row:
        return None
    return _sanitize_session_resilience_analysis_upload({
        "display_name": row.get("display_name"),
        "dataset_path": row.get("dataset_path"),
        "staging_dir": row.get("staging_dir"),
    })


def _analysis_upload_registry_by_user(conn, owner_user_id: int):
    return conn.execute(text("""
        SELECT owner_user_id, display_name, dataset_path, staging_dir, created_at
        FROM resilience.analysis_upload_registry
        WHERE owner_user_id = :owner_user_id
        LIMIT 1
    """), {"owner_user_id": owner_user_id}).mappings().first()


def _register_analysis_upload_registry(conn, owner_user_id: int, display_name: str, dataset_path: str, staging_dir: str):
    previous_row = _analysis_upload_registry_by_user(conn, owner_user_id)
    previous_upload = _analysis_upload_registry_row_to_payload(previous_row)
    if previous_upload and previous_upload["staging_dir"] != str(staging_dir or "").strip():
        _clear_resilience_analysis_upload_files(previous_upload)

    conn.execute(text("""
        INSERT INTO resilience.analysis_upload_registry
            (owner_user_id, display_name, dataset_path, staging_dir, created_at)
        VALUES
            (:owner_user_id, :display_name, :dataset_path, :staging_dir, now())
        ON CONFLICT (owner_user_id) DO UPDATE
        SET display_name = EXCLUDED.display_name,
            dataset_path = EXCLUDED.dataset_path,
            staging_dir = EXCLUDED.staging_dir,
            created_at = now()
    """), {
        "owner_user_id": owner_user_id,
        "display_name": str(display_name or "").strip(),
        "dataset_path": str(dataset_path or "").strip(),
        "staging_dir": str(staging_dir or "").strip(),
    })


def _pop_analysis_upload_registry(conn, owner_user_id: int, clear_files: bool = True) -> dict | None:
    row = _analysis_upload_registry_by_user(conn, owner_user_id)
    upload = _analysis_upload_registry_row_to_payload(row)
    conn.execute(text("""
        DELETE FROM resilience.analysis_upload_registry
        WHERE owner_user_id = :owner_user_id
    """), {"owner_user_id": owner_user_id})
    if clear_files:
        _clear_resilience_analysis_upload_files(upload)
    return upload


def _clear_resilience_analysis_upload_for_user(owner_user_id: int | None, clear_files: bool = True):
    session_upload = _pop_session_resilience_analysis_upload(clear_files=False)
    registry_upload = None
    if owner_user_id is not None:
        _ensure_resilience_run_history_table()
        with engine.begin() as conn:
            registry_upload = _pop_analysis_upload_registry(conn, owner_user_id, clear_files=False)

    if clear_files:
        _clear_resilience_analysis_upload_files(registry_upload or session_upload)
    return registry_upload or session_upload


def _get_resilience_analysis_upload_for_user(owner_user_id: int | None) -> dict | None:
    upload = _get_session_resilience_analysis_upload()
    if upload:
        return upload
    if owner_user_id is None:
        return None

    _ensure_resilience_run_history_table()
    with engine.begin() as conn:
        row = _analysis_upload_registry_by_user(conn, owner_user_id)
        upload = _analysis_upload_registry_row_to_payload(row)
        if not upload:
            return None
        if not os.path.exists(upload["dataset_path"]):
            _pop_analysis_upload_registry(conn, owner_user_id, clear_files=True)
            return None

    session[RESILIENCE_ANALYSIS_SESSION_KEY] = upload
    session.modified = True
    return upload

@app.route('/forgot', methods=['GET', 'POST'])
def forgot_password():
    _ensure_admin_support_tables()
    # Ne pas divulguer si le compte existe ou non -> anti-enumération.
    if request.method == 'POST':
        username = (request.form.get('username') or "").strip()
        if username:
            user = User.query.filter_by(username=username).first()
            if user:
                token = make_reset_token(user)
                reset_link = url_for('reset_password', token=token, _external=True)
                # En prod: envoyer par email (non présent ici). 
                # En dev: on l'affiche (flash) et on log pour faciliter.
                app.logger.info(f"[RESET] Lien pour {username}: {reset_link}")
                flash("Si un compte existe pour cet identifiant, un lien de réinitialisation a été généré.", "info")
                # Option DEV : afficher le lien si app.debug
                show_link_in_ui = app.debug or app.config.get('RESET_LINK_VIA_UI')
                if show_link_in_ui:
                    # Génère un token réel si l'utilisateur existe, sinon un token "dummy"
                    if user:
                        token = make_reset_token(user)
                    else:
                        # Token signé mais qui échouera à la validation -> évite de révéler si le compte existe
                        token = _serializer().dumps({'uid': 0, 'ph': 'x'})

                    reset_link = url_for('reset_password', token=token, _external=True)
                    flash(
                        f'''Lien de réinitialisation :
                            <a class="btn btn-primary" href="{reset_link}">
                            Changer mon mot de passe
                            </a>''',
                        "warning"
                    )

            else:
                flash("Si un compte existe pour cet identifiant, un lien de réinitialisation a été généré.", "info")
        else:
            flash("Merci de saisir votre identifiant.", "warning")
        return redirect(url_for('forgot_password'))
    return render_template('forgot_password.html')


@app.route('/reset/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        # Ne valide pas encore: on vérifie uniquement l’expiration à l’envoi du formulaire.
        if request.method == 'POST':
            new_password = request.form.get('password') or ""
            confirm      = request.form.get('confirm') or ""
            if not new_password or len(new_password) < 8:
                flash("Mot de passe trop court (min. 8 caractères).", "danger")
                return redirect(request.url)
            if new_password != confirm:
                flash("Les mots de passe ne correspondent pas.", "danger")
                return redirect(request.url)

            # Validation définitive du jeton (max_age 1h ici)
            user = load_user_from_token(token, max_age_seconds=3600)
            user.set_password(new_password)
            db.session.commit()
            flash("Votre mot de passe a été réinitialisé. Vous pouvez vous connecter.", "success")
            return redirect(url_for('login'))

        # GET => simple formulaire
        return render_template('reset_password.html')

    except SignatureExpired:
        flash("Le lien de réinitialisation a expiré. Recommencez l’opération.", "danger")
        return redirect(url_for('forgot_password'))
    except BadSignature:
        flash("Lien invalide.", "danger")
        return redirect(url_for('forgot_password'))

@app.route('/')
@login_required
def home():
    return redirect(url_for('resilience'))



@app.route('/image/<path:filename>')
def serve_image(filename):
    return send_from_directory('image', filename)

DEFAULT_SRID = 2154  # Lambert-93
SIDE_CAR_EXTS = {'.dbf', '.shx', '.prj', '.cpg', '.sbn', '.sbx'}


def _source_label(path: str, layer: str | None = None) -> str:
    base = os.path.basename(path)
    return f"{base}::{layer}" if layer else base


def _is_safe_ogr_identifier(identifier: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_]+", str(identifier or "")))


def _escape_ogr_pg_value(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def _build_ogr_pg_dsn(schema: str | None = None) -> str:
    params = {
        "host": os.getenv("DB_HOST", "db"),
        "port": os.getenv("DB_PORT", "5432"),
        "dbname": os.getenv("DB_NAME", "postgres"),
        "user": os.getenv("DB_USERNAME", "postgres"),
        "password": os.getenv("DB_PASSWORD", ""),
    }
    parts = [f"{key}='{_escape_ogr_pg_value(value)}'" for key, value in params.items() if value is not None]
    if schema:
        parts.append(f"active_schema='{_escape_ogr_pg_value(schema)}'")
    return "PG:" + " ".join(parts)


def _pick_vector_source_layer(path: str) -> str | None:
    lower_path = str(path).lower()
    if not lower_path.endswith(".gpkg"):
        return None
    layers = list(fiona.listlayers(path) or [])
    if not layers:
        return None
    for layer in layers:
        try:
            with fiona.open(path, layer=layer) as src:
                geom_name = ((src.schema or {}).get("geometry") or "").strip()
                if geom_name:
                    return layer
        except Exception:
            continue
    return layers[0]


def _inspect_vector_source(path: str, layer: str | None = None) -> dict:
    open_kwargs = {"layer": layer} if layer else {}
    with fiona.open(path, **open_kwargs) as src:
        crs_input = src.crs_wkt or src.crs
        crs_obj = None
        if crs_input:
            try:
                crs_obj = CRS.from_user_input(crs_input)
            except Exception as exc:
                raise ValueError(f"CRS invalide pour {_source_label(path, layer)} : {exc}") from exc

        feature_count = 0
        null_geometry_count = 0
        for feat in src:
            feature_count += 1
            if not feat.get("geometry"):
                null_geometry_count += 1

    return {
        "layer": layer,
        "feature_count": feature_count,
        "null_geometry_count": null_geometry_count,
        "crs": crs_obj,
    }


def _resolve_actual_table_name(conn, schema: str, table_name: str) -> str:
    row = conn.execute(text("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = :schema
          AND lower(table_name) = lower(:table_name)
        ORDER BY table_name
        LIMIT 1
    """), {"schema": schema, "table_name": table_name}).first()
    if not row:
        raise RuntimeError(
            f"Table importée introuvable après chargement: {schema}.{table_name}"
        )
    return str(row[0])


def _collect_postgis_geometry_stats(
    conn,
    schema: str,
    table_name: str,
    geom_column: str = "geometry",
) -> dict:
    qualified_name = _qualified_ident(schema, table_name)
    quoted_geom = _quote_ident(geom_column)
    stats = conn.execute(text(f"""
        SELECT
            COUNT(*)::bigint AS row_count,
            COUNT(*) FILTER (WHERE {quoted_geom} IS NULL)::bigint AS null_geometry_count,
            COUNT(*) FILTER (
                WHERE {quoted_geom} IS NOT NULL
                  AND ST_IsEmpty({quoted_geom})
            )::bigint AS empty_geometry_count,
            COUNT(*) FILTER (
                WHERE {quoted_geom} IS NOT NULL
                  AND NOT ST_IsEmpty({quoted_geom})
                  AND NOT ST_IsValid({quoted_geom})
            )::bigint AS invalid_geometry_count
        FROM {qualified_name}
    """)).mappings().first() or {}
    return {
        "row_count": int(stats.get("row_count") or 0),
        "null_geometry_count": int(stats.get("null_geometry_count") or 0),
        "empty_geometry_count": int(stats.get("empty_geometry_count") or 0),
        "invalid_geometry_count": int(stats.get("invalid_geometry_count") or 0),
    }


def _repair_invalid_postgis_geometries(
    conn,
    schema: str,
    table_name: str,
    geom_column: str = "geometry",
) -> int:
    qualified_name = _qualified_ident(schema, table_name)
    quoted_geom = _quote_ident(geom_column)
    result = conn.execute(text(f"""
        UPDATE {qualified_name}
        SET {quoted_geom} = ST_MakeValid({quoted_geom})
        WHERE {quoted_geom} IS NOT NULL
          AND NOT ST_IsEmpty({quoted_geom})
          AND NOT ST_IsValid({quoted_geom})
    """))
    return max(int(result.rowcount or 0), 0)


def _prepare_resilience_gdf_for_import(
    gdf: gpd.GeoDataFrame,
    source_label: str,
    source_null_geometry_count: int,
) -> gpd.GeoDataFrame:
    if gdf.geometry.name != 'geometry':
        if 'geometry' in gdf.columns:
            new_col = 'geometry_attr'
            i = 1
            while new_col in gdf.columns:
                new_col = f'geometry_attr{i}'
                i += 1
            gdf = gdf.rename(columns={'geometry': new_col})
        gdf = gdf.rename_geometry('geometry')
    if 'geometry' not in gdf.columns:
        raise ValueError(f'Géométrie introuvable pour {source_label}')

    geom_series = gpd.GeoSeries(
        gdf['geometry'].apply(_repair_geometry_preserve_family),
        crs=gdf.crs
    ).reset_index(drop=True)

    gdf = gdf.reset_index(drop=True).copy()
    gdf["geometry"] = geom_series
    gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs=geom_series.crs or gdf.crs)

    if gdf.empty:
        raise ValueError(f'Couche vide pour {source_label}')

    final_null_geometry_count = int(gdf["geometry"].isna().sum())
    lost_geometry_count = max(final_null_geometry_count - int(source_null_geometry_count or 0), 0)
    if lost_geometry_count > 0:
        raise ValueError(
            f"{source_label}: {lost_geometry_count} géométrie(s) non nulles ont été perdues "
            "dans le fallback Python. L'import est refusé pour éviter des traitements spatiaux faux."
        )

    if gdf.crs is None:
        raise ValueError(
            f"Projection introuvable pour {source_label}. "
            "Ajoutez le CRS au fichier source pour un import fidèle."
        )

    try:
        source_crs = CRS.from_user_input(gdf.crs)
    except Exception as exc:
        raise ValueError(f"CRS invalide pour {source_label} : {exc}") from exc

    if not source_crs.equals(CRS.from_epsg(DEFAULT_SRID)):
        gdf = gdf.to_crs(epsg=DEFAULT_SRID)

    return gdf


def _import_vector_dataset_via_geopandas(path: str, table_name: str, schema: str = "resilience") -> dict:
    layer = _pick_vector_source_layer(path)
    source_info = _inspect_vector_source(path, layer)
    source_name = _source_label(path, layer)
    gdf = _read_geofile(path, layer=layer)
    gdf = _prepare_resilience_gdf_for_import(gdf, source_name, source_info["null_geometry_count"])

    with engine.begin() as conn:
        gdf.to_postgis(
            table_name,
            conn,
            schema=schema,
            if_exists="replace",
            index=False,
            dtype={"geometry": Geometry("GEOMETRY", srid=DEFAULT_SRID)}
        )
        conn.execute(text(f'ANALYZE {_qualified_ident(schema, table_name)}'))

    return {
        "driver": "geopandas",
        "layer": layer,
        "source_rows": int(source_info["feature_count"] or 0),
        "source_null_geometry_count": int(source_info["null_geometry_count"] or 0),
    }


def _import_vector_dataset_via_ogr(path: str, table_name: str, schema: str = "resilience") -> dict:
    if shutil.which("ogr2ogr") is None:
        raise RuntimeError("ogr2ogr indisponible dans l'environnement courant.")
    if not _is_safe_ogr_identifier(schema) or not _is_safe_ogr_identifier(table_name):
        raise ValueError(
            f"Nom de table incompatible avec l'import GDAL direct : {table_name}. "
            "Utilisez uniquement lettres, chiffres et underscore."
        )

    layer = _pick_vector_source_layer(path)
    source_info = _inspect_vector_source(path, layer)
    source_name = _source_label(path, layer)
    source_crs = source_info["crs"]
    if source_crs is None:
        raise ValueError(
            f"Projection introuvable pour {source_name}. "
            "Ajoutez le CRS au fichier source pour un import fidèle."
        )

    cmd = [
        "ogr2ogr",
        "-f", "PostgreSQL",
        _build_ogr_pg_dsn(schema),
        path,
    ]
    if layer:
        cmd.append(layer)
    cmd.extend([
        "-overwrite",
        "-nln", table_name,
        "-nlt", "GEOMETRY",
        "-makevalid",
        "-lco", f"SCHEMA={schema}",
        "-lco", "GEOMETRY_NAME=geometry",
        "--config", "PG_USE_COPY", "YES",
    ])

    target_crs = CRS.from_epsg(DEFAULT_SRID)
    if not source_crs.equals(target_crs):
        cmd.extend(["-t_srs", f"EPSG:{DEFAULT_SRID}"])

    completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(
            f"Import GDAL impossible pour {source_name}: {detail or 'erreur inconnue'}"
        )

    with engine.begin() as conn:
        actual_table_name = _resolve_actual_table_name(conn, schema, table_name)
        stats_before_repair = _collect_postgis_geometry_stats(conn, schema, actual_table_name)
        repaired_invalid_count = 0
        if int(stats_before_repair["invalid_geometry_count"] or 0) > 0:
            repaired_invalid_count = _repair_invalid_postgis_geometries(conn, schema, actual_table_name)
        stats = _collect_postgis_geometry_stats(conn, schema, actual_table_name)
        conn.execute(text(f'ANALYZE {_qualified_ident(schema, actual_table_name)}'))

    imported_rows = int(stats.get("row_count") or 0)
    imported_nulls = int(stats.get("null_geometry_count") or 0)
    imported_empties = int(stats.get("empty_geometry_count") or 0)
    imported_invalids = int(stats.get("invalid_geometry_count") or 0)
    expected_rows = int(source_info["feature_count"] or 0)
    expected_nulls = int(source_info["null_geometry_count"] or 0)
    if imported_rows != expected_rows:
        raise RuntimeError(
            f"Import GDAL incomplet pour {source_name}: {imported_rows} ligne(s) importée(s) "
            f"au lieu de {expected_rows}."
        )
    effective_missing = imported_nulls + imported_empties
    if effective_missing != expected_nulls:
        raise RuntimeError(
            f"Import GDAL incohérent pour {source_name}: {effective_missing} géométrie(s) "
            f"NULL/vides en base alors que la source en contient {expected_nulls}."
        )
    if imported_invalids > 0:
        raise RuntimeError(
            f"Import GDAL incompletement réparé pour {source_name}: "
            f"{imported_invalids} géométrie(s) invalide(s) subsistent après correction."
        )

    return {
        "driver": "ogr2ogr",
        "layer": layer,
        "actual_table_name": actual_table_name,
        "source_rows": expected_rows,
        "source_null_geometry_count": expected_nulls,
        "imported_null_geometry_count": imported_nulls,
        "imported_empty_geometry_count": imported_empties,
        "imported_invalid_geometry_count": imported_invalids,
        "repaired_invalid_geometry_count": repaired_invalid_count,
    }


def _import_vector_dataset_to_postgis(path: str, table_name: str, schema: str = "resilience") -> dict:
    if shutil.which("ogr2ogr") is None:
        logging.warning(
            "Import GDAL indisponible pour %s -> %s. Bascule vers le fallback GeoPandas strict.",
            path,
            table_name,
        )
        return _import_vector_dataset_via_geopandas(path, table_name, schema=schema)
    return _import_vector_dataset_via_ogr(path, table_name, schema=schema)

def prepare_gdf_for_postgis(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    - Reprojette en L93 (2154)
    - Réutilise la géométrie existante
    - Renomme tout attribut parasite nommé 'geometry' / 'geom'
    - Normalise le nom de la géo en 'geom'
    - Déduplique tous les noms de colonnes
    """
    # 0) CRS -> L93
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)
    gdf = gdf.to_crs(epsg=DEFAULT_SRID)

    # 1) Nom de la colonne géométrique ACTUELLE
    current_geom = gdf.geometry.name  # souvent 'geometry'

    # 2) Si un attribut porte le même nom (ex. 'geometry' dans le DBF), on le renomme
    rename_map = {}
    for c in gdf.columns:
        if c == current_geom:
            continue  # c'est la vraie géo
        if c.lower() in ("geometry", "geom"):
            # évite toutes collisions avec le futur nom 'geom'
            newc = f"{c}_attr"
            i = 1
            while newc in gdf.columns:
                newc = f"{c}_attr{i}"
                i += 1
            rename_map[c] = newc
    if rename_map:
        gdf = gdf.rename(columns=rename_map)

    # 3) Renommer la géométrie en 'geom' (standard PostGIS)
    if current_geom != 'geom':
        gdf = gdf.rename_geometry('geom')
        current_geom = 'geom'

    # 4) Dédupliquer proprement tous les noms (sécurité)
    new_cols, seen = [], set()
    for c in gdf.columns:
        name = str(c).strip()
        base = name
        k = 1
        # réserve 'geom' pour la géométrie
        if name == 'geom' and c != 'geom':
            name = f"{base}_{k}"; k += 1
        while name in seen:
            name = f"{base}_{k}"
            k += 1
        new_cols.append(name)
        seen.add(name)
    gdf.columns = new_cols
    gdf = gdf.set_geometry('geom')

    return gdf


def _coerce_geometry_value(val):
    if val is None:
        return None
    if isinstance(val, BaseGeometry) or hasattr(val, "geom_type"):
        return val
    if isinstance(val, (bytes, bytearray, memoryview)):
        try:
            return shapely_wkb.loads(bytes(val))
        except Exception:
            return None
    if isinstance(val, str):
        try:
            return shapely_wkt.loads(val)
        except Exception:
            return None
    if isinstance(val, (dict, list, tuple)):
        try:
            return shape(val)
        except Exception:
            return None
    return None


def _geom_family(geom):
    if geom is None or not hasattr(geom, "geom_type"):
        return None
    gtype = str(geom.geom_type).upper()
    if "LINE" in gtype:
        return "LINE"
    if "POLYGON" in gtype:
        return "POLYGON"
    if "POINT" in gtype:
        return "POINT"
    return None


def _pick_family_geom(geom, family):
    if geom is None:
        return None
    if family is None:
        return geom
    fam = _geom_family(geom)
    if fam == family:
        return geom
    if str(getattr(geom, "geom_type", "")).upper() != "GEOMETRYCOLLECTION":
        return None
    candidates = [g for g in getattr(geom, "geoms", []) if g is not None and not g.is_empty and _geom_family(g) == family]
    if not candidates:
        return None
    if family == "POLYGON":
        return max(candidates, key=lambda g: float(getattr(g, "area", 0.0) or 0.0))
    if family == "LINE":
        return max(candidates, key=lambda g: float(getattr(g, "length", 0.0) or 0.0))
    return candidates[0]


def _repair_geometry_preserve_family(geom):
    """
    Répare une géométrie sans changer sa famille d'origine.
    Exemple: une LINESTRING reste ligne (LINESTRING/MULTILINESTRING), pas point.
    """
    original = _coerce_geometry_value(geom)
    if original is None:
        return None

    family = _geom_family(original)
    repaired = original

    try:
        candidate = make_valid(original)
        if candidate is not None:
            picked = _pick_family_geom(candidate, family)
            if picked is not None:
                repaired = picked
    except Exception:
        repaired = original

    try:
        if repaired is None or repaired.is_empty:
            return None
    except Exception:
        return None
    return _coerce_geometry_value(repaired)


def _read_geofile(path: str, layer: str | None = None):
    def _read_with_fiona_manual(fp: str):
        records = []
        geoms = []
        crs_val = None

        def add_row(props, geom_obj):
            records.append(dict(props))
            geoms.append(geom_obj)

        with fiona.open(fp) as src:
            crs_val = src.crs_wkt or src.crs
            for feat in src:
                props = feat.get("properties") or {}
                geom = feat.get("geometry")
                if geom is None:
                    add_row(props, None)
                    continue
                try:
                    gi = geom.__geo_interface__ if hasattr(geom, "__geo_interface__") else geom
                    g = _repair_geometry_preserve_family(shape(gi))
                    add_row(props, g)
                except Exception:
                    add_row(props, None)
                    continue

        if not records:
            return gpd.GeoDataFrame(columns=[], geometry=gpd.GeoSeries([], crs=crs_val))
        return gpd.GeoDataFrame(records, geometry=gpd.GeoSeries(geoms, crs=crs_val))

    # GPKG / GeoJSON : on laisse geopandas gérer, sinon fallback sûr
    lower_path = str(path).lower()
    if lower_path.endswith((".gpkg", ".geojson", ".json", ".geojsonl")):
        if lower_path.endswith(".gpkg"):
            return _read_gpkg_safe(path, layer=layer)
        read_kwargs = {"layer": layer} if layer else {}
        return gpd.read_file(path, **read_kwargs)

    # Shapefile et assimilés : lecteur manuel robuste
    return _read_with_fiona_manual(path)



@app.route('/resilience')
def resilience():
    user = _current_user()
    if not user:
        return redirect(url_for('login'))

    _ensure_admin_support_tables()
    return render_template('resilience.html', resilience_context={
        "user_id": user.id,
        "username": user.username,
        "is_admin": bool(user.is_admin),
    })


@app.route('/resilience_admin_users', methods=['GET', 'POST'])
def resilience_admin_users():
    try:
        admin_user = _require_admin_user()
    except PermissionError as exc:
        status_code = 401 if _current_user_id() is None else 403
        return jsonify({"status": "error", "message": str(exc)}), status_code

    _ensure_admin_support_tables()

    if request.method == 'GET':
        q_users = _qualified_ident(AUTH_SCHEMA, "users")
        with engine.begin() as conn:
            rows = conn.execute(text(f"""
                SELECT id, username, is_admin
                FROM {q_users}
                ORDER BY LOWER(username), id
            """)).mappings().all()

        return jsonify({
            "status": "ok",
            "users": [
                {
                    "id": row["id"],
                    "username": row["username"],
                    "is_admin": bool(row["is_admin"]),
                    "is_current_user": int(row["id"]) == int(admin_user.id),
                }
                for row in rows
            ],
        })

    payload = request.get_json(silent=True) or request.form or {}
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    is_admin = _coerce_bool(payload.get("is_admin"))

    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,50}", username):
        return jsonify({
            "status": "error",
            "message": "Nom d'utilisateur invalide. Utilisez 3 à 50 caractères alphanumériques, ., _ ou -.",
        }), 400
    if len(password) < 8:
        return jsonify({
            "status": "error",
            "message": "Le mot de passe doit contenir au moins 8 caractères.",
        }), 400
    if User.query.filter_by(username=username).first():
        return jsonify({"status": "error", "message": "Ce nom d'utilisateur existe déjà."}), 409

    new_user = User(username=username, is_admin=is_admin)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()

    return jsonify({
        "status": "ok",
        "message": f'Utilisateur "{username}" créé.',
        "user": {
            "id": new_user.id,
            "username": new_user.username,
            "is_admin": bool(new_user.is_admin),
            "is_current_user": False,
        }
    })


@app.route('/resilience_admin_users/<int:user_id>/role', methods=['POST'])
def resilience_admin_user_role(user_id: int):
    try:
        admin_user = _require_admin_user()
    except PermissionError as exc:
        status_code = 401 if _current_user_id() is None else 403
        return jsonify({"status": "error", "message": str(exc)}), status_code

    payload = request.get_json(silent=True) or request.form or {}
    is_admin = _coerce_bool(payload.get("is_admin"))

    target_user = db.session.get(User, user_id)
    if not target_user:
        return jsonify({"status": "error", "message": "Utilisateur introuvable."}), 404
    if int(target_user.id) == int(admin_user.id):
        return jsonify({
            "status": "error",
            "message": "Vous ne pouvez pas modifier votre propre rôle administrateur depuis cette page.",
        }), 400

    if not is_admin and bool(target_user.is_admin):
        admin_count = User.query.filter_by(is_admin=True).count()
        if admin_count <= 1:
            return jsonify({
                "status": "error",
                "message": "Impossible de retirer le dernier administrateur.",
            }), 400

    target_user.is_admin = is_admin
    db.session.commit()

    return jsonify({
        "status": "ok",
        "message": f'Rôle mis à jour pour "{target_user.username}".',
        "user": {
            "id": target_user.id,
            "username": target_user.username,
            "is_admin": bool(target_user.is_admin),
            "is_current_user": False,
        }
    })


@app.route('/resilience_help_content', methods=['GET'])
def resilience_help_content():
    _ensure_admin_support_tables()

    current_user = _current_user()
    with engine.begin() as conn:
        content = _resilience_help_content(conn)
        document = _resilience_help_document(conn)
    return jsonify({
        "status": "ok",
        "content": content,
        "document": _serialize_resilience_help_document(document),
        "can_edit": bool(current_user and current_user.is_admin),
    })


@app.route('/resilience_help_document', methods=['POST', 'DELETE'], strict_slashes=False)
def resilience_help_document():
    _ensure_admin_support_tables()

    try:
        admin_user = _require_admin_user()
    except PermissionError as exc:
        status_code = 401 if _current_user_id() is None else 403
        return jsonify({"status": "error", "message": str(exc)}), status_code

    if request.method == 'DELETE':
        with engine.begin() as conn:
            previous_document = _delete_resilience_help_document_row(conn)
        _delete_resilience_help_document_file(previous_document)
        return jsonify({
            "status": "ok",
            "message": "Document de référence supprimé.",
            "document": None,
        })

    uploaded_file = request.files.get("file")
    if not uploaded_file or not str(uploaded_file.filename or "").strip():
        return jsonify({"status": "error", "message": "Sélectionnez un fichier PDF, DOC ou DOCX."}), 400

    stored_document = None
    previous_document = None
    try:
        stored_document = _store_resilience_help_document(uploaded_file, admin_user.id)
        with engine.begin() as conn:
            previous_document = _resilience_help_document(conn)
            _upsert_resilience_help_document(conn, stored_document)
        if previous_document and previous_document.get("file_path") != stored_document.get("file_path"):
            _delete_resilience_help_document_file(previous_document)
    except ValueError as exc:
        if stored_document:
            _delete_resilience_help_document_file(stored_document)
        return jsonify({"status": "error", "message": str(exc)}), 400
    except Exception as exc:
        if stored_document:
            _delete_resilience_help_document_file(stored_document)
        logging.exception("Import du document d'aide impossible.")
        return jsonify({"status": "error", "message": str(exc)}), 500

    return jsonify({
        "status": "ok",
        "message": "Document de référence importé.",
        "document": _serialize_resilience_help_document(stored_document),
    })


@app.route('/resilience_help_document_download', strict_slashes=False)
def resilience_help_document_download():
    current_user = _current_user()
    if not current_user:
        return redirect(url_for('login'))

    _ensure_admin_support_tables()
    with engine.begin() as conn:
        document = _resilience_help_document(conn)
    if not document:
        return jsonify({"status": "error", "message": "Aucun document de référence disponible."}), 404

    return send_file(
        document["file_path"],
        mimetype=document["mime_type"],
        as_attachment=True,
        download_name=document["original_filename"],
    )


@app.route('/resilience_help_document_preview', strict_slashes=False)
def resilience_help_document_preview():
    current_user = _current_user()
    if not current_user:
        return redirect(url_for('login'))

    _ensure_admin_support_tables()
    with engine.begin() as conn:
        document = _resilience_help_document(conn)
    if not document:
        return Response("<p>Aucun document de référence disponible.</p>", mimetype="text/html"), 404

    ext = str(document.get("file_ext") or "").lower()
    if ext == ".pdf":
        return send_file(
            document["file_path"],
            mimetype=document["mime_type"],
            as_attachment=False,
            download_name=document["original_filename"],
        )

    if ext in {".doc", ".docx"}:
        try:
            preview_pdf_path = _ensure_resilience_help_preview_pdf(document)
            return send_file(
                preview_pdf_path,
                mimetype="application/pdf",
                as_attachment=False,
                download_name=f"{os.path.splitext(document['original_filename'])[0]}.pdf",
            )
        except Exception as exc:
            logging.exception("Prévisualisation PDF Word impossible pour %s.", document.get("file_path"))
            fallback_html = f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Prévisualisation indisponible</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; background: #020617; color: #e2e8f0; }}
    main {{ max-width: 760px; margin: 0 auto; padding: 24px; }}
    .card {{ background: #0f172a; border: 1px solid #1e293b; border-radius: 14px; padding: 24px; }}
    a {{ color: #67e8f9; }}
  </style>
</head>
<body>
  <main>
    <div class="card">
      <h1>Prévisualisation Word indisponible</h1>
      <p>La conversion du document Word vers PDF a échoué sur le serveur.</p>
      <p>Détail technique : {html.escape(str(exc))}</p>
      <p><a href="{html.escape(url_for('resilience_help_document_download'))}">Télécharger le document original</a></p>
    </div>
  </main>
</body>
</html>"""
            return Response(fallback_html, mimetype="text/html"), 500

    fallback_html = f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Prévisualisation indisponible</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; background: #020617; color: #e2e8f0; }}
    main {{ max-width: 760px; margin: 0 auto; padding: 24px; }}
    .card {{ background: #0f172a; border: 1px solid #1e293b; border-radius: 14px; padding: 24px; }}
    a {{ color: #67e8f9; }}
  </style>
</head>
<body>
  <main>
    <div class="card">
      <h1>Prévisualisation indisponible</h1>
      <p>Le format {html.escape(ext or 'inconnu')} ne peut pas être prévisualisé directement dans l'application.</p>
      <p><a href="{html.escape(url_for('resilience_help_document_download'))}">Télécharger le document</a></p>
    </div>
  </main>
</body>
</html>"""
    return Response(fallback_html, mimetype="text/html")


@app.route('/upload_resilience', methods=['POST'])
def upload_resilience():
    current_user_id = _current_user_id()
    if current_user_id is None:
        return jsonify({'status': 'error', 'message': 'Utilisateur non authentifié.'}), 401

    _ensure_resilience_run_history_table()
    files = request.files.getlist('files')
    names = {}
    legacy_names = []
    names_raw = request.form.get('names')
    if names_raw:
        try:
            names = json.loads(names_raw)
            if not isinstance(names, dict):
                return jsonify({'status': 'error', 'message': 'Format de noms invalide (attendu: objet JSON).'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Noms invalides : {str(e)}'})
    else:
        legacy_items = [(k, request.form[k]) for k in request.form if k.startswith('name-')]
        legacy_items.sort(key=lambda kv: int(kv[0].split('-')[1]) if kv[0].split('-')[1].isdigit() else 0)
        legacy_names = [v for _, v in legacy_items if v]

    from werkzeug.utils import secure_filename
    import tempfile

    SHP_EXTS = {'.shp', '.shx', '.dbf', '.prj', '.cpg', '.sbn', '.sbx'}
    SHP_REQUIRED = {'.shp', '.shx', '.dbf'}

    with tempfile.TemporaryDirectory() as tmpdir:
        saved_files = []
        seen_names = set()
        for file in files:
            orig_name = os.path.basename(file.filename or "")
            if not orig_name:
                continue
            safe_name = secure_filename(orig_name)
            if not safe_name:
                continue
            if safe_name in seen_names:
                return jsonify({'status': 'error', 'message': f'Fichier en double : {orig_name}'})
            seen_names.add(safe_name)
            filepath = os.path.join(tmpdir, safe_name)
            file.save(filepath)
            saved_files.append(filepath)

        if not saved_files:
            return jsonify({'status': 'error', 'message': 'Aucun fichier reçu.'})

        stems = {}
        gpkg_files = []
        for p in saved_files:
            fname = os.path.basename(p)
            stem, ext = os.path.splitext(fname)
            ext = ext.lower()
            if ext == '.gpkg':
                gpkg_files.append(p)
                continue
            if ext in SHP_EXTS:
                stems.setdefault(stem, set()).add(ext)

        shapefile_stems = [s for s, exts in stems.items() if '.shp' in exts]
        missing_required = {
            stem: sorted(SHP_REQUIRED - exts)
            for stem, exts in stems.items()
            if '.shp' in exts and not SHP_REQUIRED.issubset(exts)
        }
        if missing_required:
            details = "; ".join([f"{stem}: manque {', '.join(m)}" for stem, m in missing_required.items()])
            return jsonify({'status': 'error', 'message': f'Shapefile incomplet ({details})'})

        datasets = []
        for stem in sorted(shapefile_stems):
            shp_path = os.path.join(tmpdir, f"{stem}.shp")
            if not os.path.exists(shp_path):
                continue
            datasets.append({
                "path": shp_path,
                "key": f"{stem}.shp",
                "default_name": stem
            })

        for p in sorted(gpkg_files):
            base = os.path.basename(p)
            datasets.append({
                "path": p,
                "key": base,
                "default_name": os.path.splitext(base)[0]
            })

        if not datasets:
            return jsonify({'status': 'error', 'message': 'Aucun fichier GPKG ou shapefile détecté.'})

        target_names = set()
        imported_layers = []
        for ds in datasets:
            name = (names.get(ds["key"]) or names.get(ds["default_name"]) or "")
            if not name and legacy_names:
                name = legacy_names.pop(0)
            name = (name or "").strip()
            if not name:
                # Fallback: si aucun nom saisi, on prend le nom du fichier/couche.
                name = ds["default_name"]
            try:
                alea_name = _normalize_alea_layer_name(name)
            except ValueError as e:
                return jsonify({'status': 'error', 'message': str(e)}), 400
            if alea_name in target_names:
                return jsonify({'status': 'error', 'message': f'Nom de couche dupliqué dans l’import : {alea_name}'}), 400
            target_names.add(alea_name)
            try:
                with engine.begin() as conn:
                    _purge_missing_private_resilience_layers(conn)
                    _ensure_public_layer_name_available(conn, alea_name)
                import_meta = _import_vector_dataset_to_postgis(ds["path"], alea_name, schema="resilience")
                logging.info(
                    "Import résilience %s -> %s via %s (%s lignes, %s géométrie(s) NULL source).",
                    ds["key"],
                    alea_name,
                    import_meta.get("driver", "unknown"),
                    import_meta.get("source_rows", "?"),
                    import_meta.get("source_null_geometry_count", "?"),
                )
                imported_layers.append(alea_name)
            except Exception as e:
                return jsonify({'status': 'error', 'message': f'Erreur traitement {os.path.basename(ds["path"])} : {str(e)}'})

    return jsonify({"status": "ok", "imported_layers": imported_layers})


@app.route('/upload_resilience_analysis_layer', methods=['POST'])
def upload_resilience_analysis_layer():
    current_user_id = _current_user_id()
    if current_user_id is None:
        return jsonify({'status': 'error', 'message': 'Utilisateur non authentifié.'}), 401

    files = request.files.getlist('files')
    names = {}
    legacy_names = []
    names_raw = request.form.get('names')
    if names_raw:
        try:
            names = json.loads(names_raw)
            if not isinstance(names, dict):
                return jsonify({'status': 'error', 'message': 'Format de noms invalide (attendu: objet JSON).'}), 400
        except Exception as e:
            return jsonify({'status': 'error', 'message': f'Noms invalides : {str(e)}'}), 400
    else:
        legacy_items = [(k, request.form[k]) for k in request.form if k.startswith('name-')]
        legacy_items.sort(key=lambda kv: int(kv[0].split('-')[1]) if kv[0].split('-')[1].isdigit() else 0)
        legacy_names = [v for _, v in legacy_items if v]

    shp_exts = {'.shp', '.shx', '.dbf', '.prj', '.cpg', '.sbn', '.sbx'}
    shp_required = {'.shp', '.shx', '.dbf'}
    stage_dir = None
    try:
        stage_dir = tempfile.mkdtemp(
            prefix=f"resilience_analysis_u{current_user_id}_",
            dir=_resilience_analysis_stage_root(),
        )

        saved_files = []
        seen_names = set()
        for file in files:
            orig_name = os.path.basename(file.filename or "")
            if not orig_name:
                continue
            safe_name = secure_filename(orig_name)
            if not safe_name:
                continue
            if safe_name in seen_names:
                return jsonify({'status': 'error', 'message': f'Fichier en double : {orig_name}'}), 400
            seen_names.add(safe_name)
            filepath = os.path.join(stage_dir, safe_name)
            file.save(filepath)
            saved_files.append(filepath)

        if not saved_files:
            return jsonify({'status': 'error', 'message': 'Aucun fichier reçu.'}), 400

        stems = {}
        gpkg_files = []
        for path in saved_files:
            fname = os.path.basename(path)
            stem, ext = os.path.splitext(fname)
            ext = ext.lower()
            if ext == '.gpkg':
                gpkg_files.append(path)
                continue
            if ext in shp_exts:
                stems.setdefault(stem, set()).add(ext)

        shapefile_stems = [stem for stem, exts in stems.items() if '.shp' in exts]
        missing_required = {
            stem: sorted(shp_required - exts)
            for stem, exts in stems.items()
            if '.shp' in exts and not shp_required.issubset(exts)
        }
        if missing_required:
            details = "; ".join([f"{stem}: manque {', '.join(m)}" for stem, m in missing_required.items()])
            return jsonify({'status': 'error', 'message': f'Shapefile incomplet ({details})'}), 400

        datasets = []
        for stem in sorted(shapefile_stems):
            shp_path = os.path.join(stage_dir, f"{stem}.shp")
            if not os.path.exists(shp_path):
                continue
            datasets.append({
                "path": shp_path,
                "key": f"{stem}.shp",
                "default_name": stem,
            })

        for path in sorted(gpkg_files):
            base = os.path.basename(path)
            datasets.append({
                "path": path,
                "key": base,
                "default_name": os.path.splitext(base)[0],
            })

        if not datasets:
            return jsonify({'status': 'error', 'message': 'Aucun fichier GPKG ou shapefile détecté.'}), 400
        if len(datasets) != 1:
            return jsonify({
                'status': 'error',
                'message': "Importez une seule couche principale à la fois pour l'analyse réseau."
            }), 400

        ds = datasets[0]
        name = (names.get(ds["key"]) or names.get(ds["default_name"]) or "")
        if not name and legacy_names:
            name = legacy_names.pop(0)
        display_name = (name or ds["default_name"] or "").strip()
        if not display_name:
            return jsonify({'status': 'error', 'message': "Nom de couche d'analyse invalide."}), 400

        _ensure_resilience_run_history_table()
        with engine.begin() as conn:
            _register_analysis_upload_registry(conn, current_user_id, display_name, ds["path"], stage_dir)
        _set_session_resilience_analysis_upload(display_name, ds["path"], stage_dir)
        stage_dir = None
        logging.info(
            "Couche d'analyse temporaire chargée pour user=%s : %s (%s).",
            current_user_id,
            display_name,
            ds["path"],
        )
        return jsonify({"status": "ok", "imported_layers": [display_name]})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Erreur import analyse : {str(e)}'}), 500
    finally:
        if stage_dir and os.path.isdir(stage_dir):
            shutil.rmtree(stage_dir, ignore_errors=True)


# Route pour lister les couches dans le schéma resilience
@app.route('/resilience_layers')
def get_resilience_layers():
    current_user_id = _current_user_id()
    if current_user_id is None:
        return jsonify({'status': 'error', 'message': 'Utilisateur non authentifié.'}), 401

    _ensure_resilience_run_history_table()
    with engine.begin() as conn:
        _purge_missing_private_resilience_layers(conn)
        private_rows = conn.execute(text("""
            SELECT layer_name, display_name, owner_user_id
            FROM resilience.private_run_layers
        """)).mappings().all()
        private_by_layer = {row["layer_name"]: row for row in private_rows}

        # Tables et vues partagées, y compris les couches aléa.
        result1 = conn.execute(text("""
            SELECT table_name 
            FROM information_schema.tables
            WHERE table_schema = 'resilience'
              AND table_type IN ('BASE TABLE', 'VIEW')
              AND table_name <> 'users'
              AND EXISTS (
                  SELECT 1
                  FROM information_schema.columns c
                  WHERE c.table_schema = 'resilience'
                    AND c.table_name = information_schema.tables.table_name
                    AND c.column_name = 'geometry'
              );
        """))
        tables = [row[0] for row in result1]

        # Vues matérialisées avec géométrie uniquement
        result2 = conn.execute(text("""
            SELECT matviewname 
            FROM pg_matviews
            WHERE schemaname = 'resilience'
              AND matviewname <> 'users';
        """))
        matviews = [row[0] for row in result2 if _has_column(conn, 'resilience', row[0], 'geometry')]

    shared_layers = []
    for layer in sorted(set(tables + matviews)):
        if layer in private_by_layer:
            continue
        shared_layers.append(layer)

    return jsonify(sorted(set(shared_layers)))


# Route pour charger une couche spécifique partagée ou privée autorisée pour l'utilisateur courant.
@app.route('/resilience_layer_data/<layer_name>')
def get_resilience_layer_data(layer_name):
    current_user_id = _current_user_id()
    if current_user_id is None:
        return jsonify({'status': 'error', 'message': 'Utilisateur non authentifié.'}), 401

    try:
        requested_layer_name = str(layer_name or "").strip()
        analysis_upload = _get_resilience_analysis_upload_for_user(current_user_id)
        if analysis_upload and requested_layer_name == analysis_upload["display_name"]:
            source_layer = _pick_vector_source_layer(analysis_upload["dataset_path"])
            source_info = _inspect_vector_source(analysis_upload["dataset_path"], source_layer)
            gdf = _read_geofile(analysis_upload["dataset_path"], layer=source_layer)
            gdf = _prepare_resilience_gdf_for_import(
                gdf,
                analysis_upload["display_name"],
                source_info["null_geometry_count"],
            )
            gdf = gdf.to_crs(epsg=4326)

            gdf_clean = gdf.copy()
            attr_df = gdf_clean.drop(columns='geometry').replace({pd.NA: None})
            attr_df = attr_df.where(pd.notna(attr_df), None)
            table_data = attr_df.fillna('').to_dict(orient='records')
            gdf_clean[attr_df.columns] = attr_df
            geojson = gdf_clean.__geo_interface__

            return jsonify({
                'status': 'ok',
                'features': geojson['features'],
                'table': table_data,
                'columns': list(gdf_clean.columns)
            })

        _ensure_resilience_run_history_table()
        with engine.begin() as conn:
            _purge_missing_private_resilience_layers(conn)
            resolved_layer = _resolve_resilience_layer_for_user(conn, layer_name, current_user_id)
            if not resolved_layer or not resolved_layer["allowed"]:
                return jsonify({'status': 'error', 'message': f'Couche {layer_name} introuvable.'}), 404
            db_layer_name = resolved_layer["layer_name"]
            if not _object_exists('resilience', db_layer_name):
                return jsonify({'status': 'error', 'message': f'Couche {layer_name} introuvable.'}), 404
            if not _has_column(conn, 'resilience', db_layer_name, 'geometry'):
                return jsonify({'status': 'error', 'message': f"{layer_name} n'est pas une couche cartographique."}), 400

            q_layer = _quote_ident(db_layer_name)
            gdf = gpd.read_postgis(f'SELECT * FROM "resilience".{q_layer}', con=conn, geom_col='geometry')
            gdf = gdf.to_crs(epsg=4326)
        
        # Nettoyage des attributs uniquement (ne jamais convertir geometry en string).
        gdf_clean = gdf.copy()
        attr_df = gdf_clean.drop(columns='geometry').replace({pd.NA: None})
        attr_df = attr_df.where(pd.notna(attr_df), None)
        table_data = attr_df.fillna('').to_dict(orient='records')
        gdf_clean[attr_df.columns] = attr_df
        geojson = gdf_clean.__geo_interface__

        return jsonify({
            'status': 'ok',
            'features': geojson['features'],
            'table': table_data,
            'columns': list(gdf_clean.columns)
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


# Couches supports (prefixe alea)
@app.route('/resilience_layers_support')
def get_resilience_layers_support():
    with engine.begin() as conn:
        alea_tables = _list_resilience_support_layers(conn)
    return jsonify(sorted(alea_tables))


@app.route('/resilience_impact_matrix')
def get_resilience_impact_matrix():
    current_user_id = _current_user_id()
    if current_user_id is None:
        return jsonify({'status': 'error', 'message': 'Utilisateur non authentifié.'}), 401

    _ensure_resilience_run_history_table()
    with engine.begin() as conn:
        support_layers = _ensure_resilience_impact_matrix_defaults(conn)
        matrix = _get_resilience_impact_matrix_map(conn, support_layers)

    payload = {
        "levels": list(RESILIENCE_IMPACT_LEVELS),
        "layers": [
            {
                "layer_name": layer_name,
                "values": {str(level): matrix.get(layer_name, {}).get(level, 0.0) for level in RESILIENCE_IMPACT_LEVELS},
            }
            for layer_name in support_layers
        ],
    }
    return jsonify(payload)


@app.route('/resilience_impact_matrix', methods=['POST'])
def save_resilience_impact_matrix():
    current_user_id = _current_user_id()
    if current_user_id is None:
        return jsonify({'status': 'error', 'message': 'Utilisateur non authentifié.'}), 401

    _ensure_resilience_run_history_table()
    data = request.get_json(silent=True) or {}
    values = data.get("values")

    try:
        with engine.begin() as conn:
            _save_resilience_impact_matrix(conn, values)
        return jsonify({"status": "ok"})
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        logging.exception("Sauvegarde de la matrice d'impacts impossible.")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/resilience_analysis_layers')
def get_resilience_analysis_layers():
    current_user_id = _current_user_id()
    if current_user_id is None:
        return jsonify({'status': 'error', 'message': 'Utilisateur non authentifié.'}), 401

    upload = _get_resilience_analysis_upload_for_user(current_user_id)
    if not upload:
        return jsonify([])
    return jsonify([upload["display_name"]])


@app.route('/resilience_analysis_layer_clear', methods=['POST'])
def clear_resilience_analysis_layer():
    current_user_id = _current_user_id()
    if current_user_id is None:
        return jsonify({'status': 'error', 'message': 'Utilisateur non authentifié.'}), 401

    _clear_resilience_analysis_upload_for_user(current_user_id, clear_files=True)
    return jsonify({"status": "ok"})


#dependance    
@app.route('/resilience_dependencies/<layer>')
def resilience_dependencies(layer):
    current_user_id = _current_user_id()
    if current_user_id is None:
        return jsonify({'status': 'error', 'message': 'Utilisateur non authentifié.'}), 401

    _ensure_resilience_run_history_table()
    with engine.begin() as conn:
        _purge_missing_private_resilience_layers(conn)
        resolved_layer = _resolve_resilience_layer_for_user(conn, layer, current_user_id)
        if not resolved_layer or not resolved_layer["allowed"]:
            return jsonify({
                "status": "error",
                "message": f'Couche "{layer}" introuvable.'
            }), 404

        db_layer_name = resolved_layer["layer_name"]
        layer_type = _get_resilience_object_kind(conn, db_layer_name)
        if layer_type is None:
            return jsonify({
                "status": "error",
                "message": f'Couche "{layer}" introuvable.'
            }), 404
        if not _has_column(conn, 'resilience', db_layer_name, 'geometry'):
            return jsonify({
                "status": "error",
                "message": f'"{layer}" n\'est pas une couche cartographique.'
            }), 400
        deps = _list_resilience_dependencies(conn, db_layer_name)
        for dep in deps:
            resolved_dep = _resolve_resilience_layer_for_user(conn, dep["name"], current_user_id)
            if resolved_dep and resolved_dep["allowed"]:
                dep["name"] = resolved_dep["display_name"]
    return jsonify({
        "status": "ok",
        "layer": layer,
        "layer_type": layer_type,
        "layer_type_label": _resilience_object_kind_label(layer_type),
        "dependency_count": len(deps),
        "dependencies": deps
    })


# route de suppression d'une couche
@app.route('/delete_resilience_layer', methods=['POST'])
def delete_resilience_layer():
    current_user_id = _current_user_id()
    if current_user_id is None:
        return jsonify({'status': 'error', 'message': 'Utilisateur non authentifié.'}), 401

    data = request.json
    layer = (data or {}).get('layer')
    if not layer:
        return jsonify({"status": "error", "message": "Couche manquante."}), 400

    try:
        _ensure_resilience_run_history_table()
        with engine.begin() as conn:
            _purge_missing_private_resilience_layers(conn)
            resolved_layer = _resolve_resilience_layer_for_user(conn, layer, current_user_id)
            if not resolved_layer or not resolved_layer["allowed"]:
                return jsonify({
                    "status": "error",
                    "message": f'Couche "{layer}" introuvable.'
                }), 404

            db_layer_name = resolved_layer["layer_name"]
            layer_type = _get_resilience_object_kind(conn, db_layer_name)
            if layer_type is None:
                return jsonify({
                    "status": "error",
                    "message": f'Couche "{layer}" introuvable.'
                }), 404
            if not _has_column(conn, 'resilience', db_layer_name, 'geometry'):
                return jsonify({
                    "status": "error",
                    "message": f'"{layer}" n\'est pas une couche cartographique.'
                }), 400

            deps = _list_resilience_dependencies(conn, db_layer_name)
            for dep in deps:
                resolved_dep = _resolve_resilience_layer_for_user(conn, dep["name"], current_user_id)
                if resolved_dep and resolved_dep["allowed"]:
                    dep["name"] = resolved_dep["display_name"]

            q_layer = _quote_ident(db_layer_name)
            if layer_type == 'materialized_view':
                conn.execute(text(f'DROP MATERIALIZED VIEW IF EXISTS "resilience".{q_layer} CASCADE'))
            elif layer_type == 'view':
                conn.execute(text(f'DROP VIEW IF EXISTS "resilience".{q_layer} CASCADE'))
            else:
                conn.execute(text(f'DROP TABLE IF EXISTS "resilience".{q_layer} CASCADE'))
            _delete_resilience_impact_matrix_for_layer(conn, db_layer_name)
            _unregister_private_run_layer(conn, db_layer_name)
            _unregister_private_analysis_layer(conn, db_layer_name)

        message = f'Couche "{layer}" supprimee de la base Resilience.'
        if deps:
            message += f" {len(deps)} dependance(s) ont aussi ete supprimee(s) en cascade."

        return jsonify({
            "status": "ok",
            "message": message,
            "layer": layer,
            "layer_type": layer_type,
            "layer_type_label": _resilience_object_kind_label(layer_type),
            "dependency_count": len(deps),
            "dependencies": deps
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# route de téléchargement d'une couche
@app.route('/download_resilience_layer/<layer>')
def download_resilience_layer(layer):
    current_user_id = _current_user_id()
    if current_user_id is None:
        return jsonify({'status': 'error', 'message': 'Utilisateur non authentifié.'}), 401

    format = request.args.get('format', 'csv')
    try:
        _ensure_resilience_run_history_table()
        with engine.begin() as conn:
            _purge_missing_private_resilience_layers(conn)
            resolved_layer = _resolve_resilience_layer_for_user(conn, layer, current_user_id)
            if not resolved_layer or not resolved_layer["allowed"]:
                return jsonify({'status': 'error', 'message': f'Couche {layer} introuvable.'}), 404

            db_layer_name = resolved_layer["layer_name"]
            download_layer_name = resolved_layer["display_name"] or layer
            if not _object_exists('resilience', db_layer_name):
                return jsonify({'status': 'error', 'message': f'Couche {layer} introuvable.'}), 404

            q_layer = _quote_ident(db_layer_name)
            gdf = gpd.read_postgis(f'SELECT * FROM "resilience".{q_layer}', con=conn, geom_col='geometry')
            gdf = gdf.to_crs(epsg=4326)
        df = gdf.drop(columns='geometry')

        tmp = tempfile.TemporaryDirectory()

        if format == 'csv':
            path = os.path.join(tmp.name, f"{download_layer_name}.csv")
            df.to_csv(path, index=False, sep=';', encoding='utf-8')
            return send_file(path, as_attachment=True, download_name=f"{download_layer_name}.csv")

        elif format == 'html':
            path = os.path.join(tmp.name, f"{download_layer_name}.html")
            df.to_html(path, index=False)
            return send_file(path, as_attachment=True, download_name=f"{download_layer_name}.html")

        elif format == 'gpkg':
            path = os.path.join(tmp.name, f"{download_layer_name}.gpkg")
            gdf.to_file(path, driver="GPKG")
            return send_file(path, as_attachment=True, download_name=f"{download_layer_name}.gpkg")

        elif format == 'shp':
            # écrire un shapefile dans un dossier temporaire puis zipper
            shp_path = os.path.join(tmp.name, f"{download_layer_name}.shp")
            gdf.to_file(shp_path, driver="ESRI Shapefile")
            zip_path = os.path.join(tmp.name, f"{download_layer_name}_shp.zip")
            shp_exts = {'.shp', '.shx', '.dbf', '.prj', '.cpg', '.sbn', '.sbx'}
            with ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for fname in os.listdir(tmp.name):
                    ext = os.path.splitext(fname)[1].lower()
                    if fname.startswith(download_layer_name + '.') and ext in shp_exts:
                        full = os.path.join(tmp.name, fname)
                        zf.write(full, arcname=fname)
            return send_file(zip_path, as_attachment=True, download_name=f"{download_layer_name}.zip")

        else:
            return jsonify({'status': 'error', 'message': 'Format non supporté'}), 400

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ==================== Batch croisement aléas ==================== #

def _list_alea_tables():
    with engine.connect() as conn:
        res = conn.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema='resilience' AND table_name LIKE 'alea_%'
            ORDER BY table_name
        """))
        return [r[0] for r in res]


def _has_column(conn, schema, table, col):
    q = text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema=:schema AND table_name=:table AND column_name=:col
    """)
    return conn.execute(q, {"schema": schema, "table": table, "col": col}).first() is not None


def _get_resilience_object_kind(conn, name: str) -> str | None:
    row = conn.execute(text("""
        SELECT 'materialized_view' AS kind
        FROM pg_matviews
        WHERE schemaname = 'resilience' AND matviewname = :name
        UNION ALL
        SELECT CASE
            WHEN table_type = 'VIEW' THEN 'view'
            ELSE 'table'
        END AS kind
        FROM information_schema.tables
        WHERE table_schema = 'resilience' AND table_name = :name
        LIMIT 1
    """), {"name": name}).first()
    return row[0] if row else None


def _resilience_object_kind_label(kind: str | None) -> str:
    return {
        "table": "table",
        "view": "vue",
        "materialized_view": "vue materialisee",
    }.get(kind, "objet")


def _list_resilience_dependencies(conn, layer: str) -> list[dict[str, str]]:
    rows = conn.execute(text("""
        SELECT DISTINCT
            dependent_view.relname AS name,
            CASE dependent_view.relkind
                WHEN 'm' THEN 'materialized_view'
                WHEN 'v' THEN 'view'
                ELSE 'object'
            END AS kind
        FROM pg_depend dep
        JOIN pg_rewrite rw
          ON rw.oid = dep.objid
        JOIN pg_class dependent_view
          ON dependent_view.oid = rw.ev_class
        JOIN pg_namespace dependent_ns
          ON dependent_ns.oid = dependent_view.relnamespace
        JOIN pg_class source_rel
          ON source_rel.oid = dep.refobjid
        JOIN pg_namespace source_ns
          ON source_ns.oid = source_rel.relnamespace
        WHERE source_ns.nspname = 'resilience'
          AND source_rel.relname = :layer
          AND dependent_ns.nspname = 'resilience'
          AND dependent_view.relkind IN ('m', 'v')
          AND dependent_view.relname <> :layer
        ORDER BY dependent_view.relname
    """), {"layer": layer}).mappings().all()
    return [
        {
            "name": row["name"],
            "type": row["kind"],
            "label": _resilience_object_kind_label(row["kind"]),
        }
        for row in rows
    ]


def _object_exists(schema: str, name: str) -> bool:
    """
    Retourne True si une table, vue ou vue matérialisée existe.
    Ouvre une connexion AUTOCOMMIT dédiée pour éviter les états 'InFailedSqlTransaction'.
    """
    q = text("""
        SELECT 1
        FROM (
            SELECT table_name AS name FROM information_schema.tables
             WHERE table_schema=:s
            UNION
            SELECT viewname FROM pg_views WHERE schemaname=:s
            UNION
            SELECT matviewname FROM pg_matviews WHERE schemaname=:s
        ) AS t
        WHERE name=:n
        LIMIT 1
    """)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        return conn.execute(q, {"s": schema, "n": name}).first() is not None


def _read_gpkg_safe(path: str, layer: str | None = None) -> gpd.GeoDataFrame:
    """
    Lecture robuste d'un GPKG : essaie geopandas, sinon fiona layer par layer en filtrant les géométries invalides.
    """
    try:
        return gpd.read_file(path)
    except Exception as exc:
        layers = [layer] if layer else fiona.listlayers(path)
        if not layers:
            raise exc
        last_err = exc
        accepted = {"Polygon", "MultiPolygon", "LineString", "MultiLineString", "Point", "MultiPoint"}

        def _geom_rank(g):
            gtype = g.geom_type
            if "Polygon" in gtype:
                return (3, float(getattr(g, "area", 0.0) or 0.0))
            if "LineString" in gtype:
                return (2, float(getattr(g, "length", 0.0) or 0.0))
            if "Point" in gtype:
                return (1, 0.0)
            return (0, 0.0)

        def _pick_single_geom(g):
            if g is None or g.is_empty:
                return None
            if g.geom_type in accepted:
                return g
            if g.geom_type == "GeometryCollection":
                candidates = [sub for sub in getattr(g, "geoms", []) if sub is not None and not sub.is_empty]
                candidates = [sub for sub in candidates if sub.geom_type in accepted]
                if not candidates:
                    return None
                return max(candidates, key=_geom_rank)
            return None

        for layer in layers:
            try:
                geoms = []
                props = []
                crs_val = None
                with fiona.open(path, layer=layer) as src:
                    crs_val = src.crs_wkt or src.crs
                    for feat in src:
                        props_base = feat.get("properties") or {}
                        geom = feat.get("geometry")
                        if not geom:
                            geoms.append(None)
                            props.append(dict(props_base))
                            continue
                        gi = geom.__geo_interface__ if hasattr(geom, "__geo_interface__") else geom
                        gtype = (gi.get("type") or "").upper() if isinstance(gi, dict) else ""
                        coords = gi.get("coordinates") if isinstance(gi, dict) else None
                        try:
                            g = None
                            if gtype == "MULTIPOLYGON":
                                polys = []
                                for poly_coords in (coords or []):
                                    if not poly_coords:
                                        continue
                                    exterior = poly_coords[0] if len(poly_coords) > 0 else []
                                    holes = poly_coords[1:] if len(poly_coords) > 1 else []
                                    p = Polygon(exterior, holes)
                                    if p is not None and not p.is_empty:
                                        polys.append(p)
                                if not polys:
                                    geoms.append(None)
                                    props.append(dict(props_base))
                                    continue
                                g = polys[0] if len(polys) == 1 else MultiPolygon(polys)
                            elif gtype == "MULTILINESTRING":
                                lines = []
                                for line_coords in (coords or []):
                                    if not line_coords:
                                        continue
                                    ln = LineString(line_coords)
                                    if ln is not None and not ln.is_empty:
                                        lines.append(ln)
                                if not lines:
                                    geoms.append(None)
                                    props.append(dict(props_base))
                                    continue
                                g = lines[0] if len(lines) == 1 else MultiLineString(lines)
                            elif gtype == "MULTIPOINT":
                                pts = []
                                for pt_coords in (coords or []):
                                    p = Point(pt_coords)
                                    if p is not None and not p.is_empty:
                                        pts.append(p)
                                if not pts:
                                    geoms.append(None)
                                    props.append(dict(props_base))
                                    continue
                                g = pts[0] if len(pts) == 1 else MultiPoint(pts)
                            else:
                                g = shape(gi)

                            g = _repair_geometry_preserve_family(g)

                            final_geom = _pick_single_geom(g)
                            geoms.append(final_geom)
                            props.append(dict(props_base))
                        except Exception as e:
                            last_err = e
                            geoms.append(None)
                            props.append(dict(props_base))
                            continue
                if props:
                    return gpd.GeoDataFrame(props, geometry=gpd.GeoSeries(geoms, crs=crs_val))
            except Exception as e:
                last_err = e
                continue
        if last_err is not None:
            raise last_err
        raise ValueError("GPKG sans géométrie valide (types supportés: POINT/LINESTRING/POLYGON).")


def _pick_alea_value_col(conn, table):
    """
    Retourne la colonne à utiliser comme valeur d'aléa pour une table donnée.
    Priorité : 'alea' si présente, sinon première colonne non-geometry, sinon 'id'.
    """
    if _has_column(conn, 'resilience', table, 'alea'):
        return 'alea'
    alt = conn.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema='resilience' AND table_name=:t AND column_name <> 'geometry'
        ORDER BY ordinal_position LIMIT 1
    """), {"t": table}).scalar()
    return alt or 'id'


def _pick_pk_column(conn, schema: str, table: str) -> str | None:
    """
    Retourne une clé stable pour les jointures, sans heuristique sur des noms de colonnes:
    1) clé primaire déclarée
    2) contrainte / index UNIQUE mono-colonne
    3) fallback data-driven: colonne non géométrique unique et non nulle
       (candidats ordonnés via pg_stats, puis vérification exacte)
    Résultat mis en cache par table pour éviter des scans répétés.
    """
    cache_key = (schema, table)
    if cache_key in _KEY_COLUMN_CACHE:
        return _KEY_COLUMN_CACHE[cache_key]

    pk_q = text("""
        SELECT a.attname
        FROM pg_constraint c
        JOIN pg_class t ON c.conrelid = t.oid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(c.conkey)
        WHERE c.contype = 'p' AND n.nspname = :schema AND t.relname = :table
        ORDER BY a.attnum
        LIMIT 1
    """)
    row = conn.execute(pk_q, {"schema": schema, "table": table}).first()
    if row:
        _KEY_COLUMN_CACHE[cache_key] = row[0]
        return row[0]

    uq_q = text("""
        SELECT a.attname
        FROM pg_constraint c
        JOIN pg_class t ON c.conrelid = t.oid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(c.conkey)
        WHERE c.contype = 'u'
          AND n.nspname = :schema
          AND t.relname = :table
          AND array_length(c.conkey, 1) = 1
        ORDER BY a.attnum
        LIMIT 1
    """)
    row = conn.execute(uq_q, {"schema": schema, "table": table}).first()
    if row:
        candidate = row[0]
        if candidate and candidate != "geometry":
            _KEY_COLUMN_CACHE[cache_key] = candidate
            return candidate

    idx_uq_q = text("""
        SELECT a.attname
        FROM pg_index i
        JOIN pg_class t ON t.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = i.indkey[0]
        WHERE n.nspname = :schema
          AND t.relname = :table
          AND i.indisunique = true
          AND array_length(i.indkey, 1) = 1
        LIMIT 1
    """)
    row = conn.execute(idx_uq_q, {"schema": schema, "table": table}).first()
    if row:
        candidate = row[0]
        if candidate and candidate != "geometry":
            _KEY_COLUMN_CACHE[cache_key] = candidate
            return candidate

    candidates_q = text("""
        SELECT a.attname
        FROM pg_attribute a
        JOIN pg_class t ON t.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        LEFT JOIN pg_stats s
          ON s.schemaname = n.nspname
         AND s.tablename = t.relname
         AND s.attname = a.attname
        WHERE n.nspname = :schema
          AND t.relname = :table
          AND a.attnum > 0
          AND NOT a.attisdropped
          AND a.attname <> 'geometry'
        ORDER BY
          CASE WHEN s.n_distinct = -1 THEN 0 ELSE 1 END,
          COALESCE(s.null_frac, 1),
          a.attnum
        LIMIT 12
    """)
    candidates = [r[0] for r in conn.execute(candidates_q, {"schema": schema, "table": table})]
    q_table = _qualified_ident(schema, table)
    for col in candidates:
        q_col = _quote_ident(col)
        uniq_sql = text(f"""
            SELECT
                COUNT(*)::bigint AS total_rows,
                COUNT({q_col})::bigint AS non_null_rows,
                COUNT(DISTINCT {q_col})::bigint AS distinct_rows
            FROM {q_table}
        """)
        stats = conn.execute(uniq_sql).mappings().first()
        if not stats:
            continue
        total_rows = int(stats["total_rows"] or 0)
        non_null_rows = int(stats["non_null_rows"] or 0)
        distinct_rows = int(stats["distinct_rows"] or 0)
        if total_rows > 0 and non_null_rows == total_rows and distinct_rows == total_rows:
            _KEY_COLUMN_CACHE[cache_key] = col
            return col

    _KEY_COLUMN_CACHE[cache_key] = None
    return None


def _ensure_resilience_run_history_table():
    """
    Crée les tables de persistance des runs résilience si elles n'existent pas.
    """
    global _RUN_HISTORY_READY
    if _RUN_HISTORY_READY:
        return

    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": RUN_HISTORY_INIT_LOCK_KEY})
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS resilience.run_history (
                run_id BIGSERIAL PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                owner_user_id INTEGER,
                main_layer TEXT NOT NULL,
                view_name TEXT NOT NULL,
                layer_name TEXT,
                stress_layers TEXT NOT NULL,
                status TEXT NOT NULL,
                duration_seconds DOUBLE PRECISION,
                message TEXT
            )
        """))
        conn.execute(text("""
            ALTER TABLE resilience.run_history
            ADD COLUMN IF NOT EXISTS owner_user_id INTEGER
        """))
        conn.execute(text("""
            ALTER TABLE resilience.run_history
            ADD COLUMN IF NOT EXISTS layer_name TEXT
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS run_history_created_at_idx
            ON resilience.run_history (created_at DESC)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS run_history_owner_user_id_idx
            ON resilience.run_history (owner_user_id, created_at DESC)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS resilience.private_run_layers (
                layer_name TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                owner_user_id INTEGER NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS private_run_layers_owner_idx
            ON resilience.private_run_layers (owner_user_id, created_at DESC)
        """))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS private_run_layers_owner_display_uidx
            ON resilience.private_run_layers (owner_user_id, display_name)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS resilience.private_analysis_layers (
                layer_name TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                owner_user_id INTEGER NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS private_analysis_layers_owner_idx
            ON resilience.private_analysis_layers (owner_user_id, created_at DESC)
        """))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS private_analysis_layers_owner_display_uidx
            ON resilience.private_analysis_layers (owner_user_id, display_name)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS resilience.analysis_upload_registry (
                owner_user_id INTEGER PRIMARY KEY,
                display_name TEXT NOT NULL,
                dataset_path TEXT NOT NULL,
                staging_dir TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS analysis_upload_registry_created_at_idx
            ON resilience.analysis_upload_registry (created_at DESC)
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS resilience.impact_matrix (
                layer_name TEXT NOT NULL,
                alea_level SMALLINT NOT NULL,
                impact_value DOUBLE PRECISION NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (layer_name, alea_level)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS impact_matrix_layer_idx
            ON resilience.impact_matrix (layer_name)
        """))
        legacy_analysis_layers = [
            str(row[0]).strip()
            for row in conn.execute(text("""
                SELECT layer_name
                FROM resilience.private_analysis_layers
            """)).all()
            if row and row[0]
        ]
        for layer_name in legacy_analysis_layers:
            layer_type = _get_resilience_object_kind(conn, layer_name)
            if layer_type is None:
                continue
            q_layer = _quote_ident(layer_name)
            if layer_type == 'materialized_view':
                conn.execute(text(f'DROP MATERIALIZED VIEW IF EXISTS "resilience".{q_layer} CASCADE'))
            elif layer_type == 'view':
                conn.execute(text(f'DROP VIEW IF EXISTS "resilience".{q_layer} CASCADE'))
            else:
                conn.execute(text(f'DROP TABLE IF EXISTS "resilience".{q_layer} CASCADE'))
        if legacy_analysis_layers:
            conn.execute(text("DELETE FROM resilience.private_analysis_layers"))
            logging.info(
                "Nettoyage des anciennes couches d'analyse persistées: %s objet(s) supprimé(s).",
                len(legacy_analysis_layers),
            )
    _RUN_HISTORY_READY = True


def _purge_missing_private_run_layers(conn):
    conn.execute(text("""
        DELETE FROM resilience.private_run_layers pr
        WHERE NOT EXISTS (
            SELECT 1
            FROM (
                SELECT table_name AS object_name
                FROM information_schema.tables
                WHERE table_schema = 'resilience'
                UNION
                SELECT viewname AS object_name
                FROM pg_views
                WHERE schemaname = 'resilience'
                UNION
                SELECT matviewname AS object_name
                FROM pg_matviews
                WHERE schemaname = 'resilience'
            ) objects
            WHERE objects.object_name = pr.layer_name
        )
    """))


def _purge_missing_private_analysis_layers(conn):
    conn.execute(text("""
        DELETE FROM resilience.private_analysis_layers pr
        WHERE NOT EXISTS (
            SELECT 1
            FROM (
                SELECT table_name AS object_name
                FROM information_schema.tables
                WHERE table_schema = 'resilience'
                UNION
                SELECT viewname AS object_name
                FROM pg_views
                WHERE schemaname = 'resilience'
                UNION
                SELECT matviewname AS object_name
                FROM pg_matviews
                WHERE schemaname = 'resilience'
            ) objects
            WHERE objects.object_name = pr.layer_name
        )
    """))


def _purge_missing_private_resilience_layers(conn):
    _purge_missing_private_run_layers(conn)
    _purge_missing_private_analysis_layers(conn)


def _list_resilience_support_layers(conn) -> list[str]:
    result = conn.execute(text("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'resilience'
          AND table_type IN ('BASE TABLE', 'VIEW')
          AND table_name LIKE 'alea%'
          AND EXISTS (
              SELECT 1
              FROM information_schema.columns c
              WHERE c.table_schema = 'resilience'
                AND c.table_name = information_schema.tables.table_name
                AND c.column_name = 'geometry'
          )
        ORDER BY table_name
    """))
    layers = [row[0] for row in result if row and row[0]]

    matviews = [
        row[0]
        for row in conn.execute(text("""
            SELECT matviewname
            FROM pg_matviews
            WHERE schemaname = 'resilience'
              AND matviewname LIKE 'alea%'
            ORDER BY matviewname
        """))
        if row and row[0] and _has_column(conn, 'resilience', row[0], 'geometry')
    ]

    return sorted(set(layers + matviews))


def _delete_resilience_impact_matrix_for_layer(conn, layer_name: str):
    conn.execute(text("""
        DELETE FROM resilience.impact_matrix
        WHERE layer_name = :layer_name
    """), {"layer_name": layer_name})


def _ensure_resilience_impact_matrix_defaults(conn) -> list[str]:
    support_layers = _list_resilience_support_layers(conn)
    support_set = set(support_layers)

    existing_layers = {
        str(row[0]).strip()
        for row in conn.execute(text("""
            SELECT DISTINCT layer_name
            FROM resilience.impact_matrix
        """)).all()
        if row and row[0]
    }

    for stale_layer in sorted(existing_layers - support_set):
        _delete_resilience_impact_matrix_for_layer(conn, stale_layer)

    for layer_name in support_layers:
        for alea_level in RESILIENCE_IMPACT_LEVELS:
            conn.execute(text("""
                INSERT INTO resilience.impact_matrix (layer_name, alea_level, impact_value)
                VALUES (:layer_name, :alea_level, 0)
                ON CONFLICT (layer_name, alea_level) DO NOTHING
            """), {
                "layer_name": layer_name,
                "alea_level": alea_level,
            })

    return support_layers


def _normalize_resilience_impact_value(raw_value) -> float:
    if raw_value is None:
        return 0.0
    if isinstance(raw_value, (int, float, np.integer, np.floating)):
        value = float(raw_value)
        if not np.isfinite(value):
            raise ValueError("Valeur d'impact invalide.")
        return value

    text_value = str(raw_value).strip().replace(",", ".")
    if not text_value:
        return 0.0

    value = float(text_value)
    if not np.isfinite(value):
        raise ValueError("Valeur d'impact invalide.")
    return value


def _get_resilience_impact_matrix_map(conn, layer_names: list[str] | None = None) -> dict[str, dict[int, float]]:
    support_layers = _ensure_resilience_impact_matrix_defaults(conn)
    target_layers = [layer for layer in (layer_names or support_layers) if layer]
    matrix = {
        layer_name: {level: 0.0 for level in RESILIENCE_IMPACT_LEVELS}
        for layer_name in target_layers
    }
    if not matrix:
        return matrix

    rows = conn.execute(text("""
        SELECT layer_name, alea_level, impact_value
        FROM resilience.impact_matrix
        ORDER BY layer_name, alea_level
    """)).mappings().all()

    for row in rows:
        layer_name = str(row["layer_name"] or "").strip()
        alea_level = int(row["alea_level"])
        if layer_name not in matrix or alea_level not in RESILIENCE_IMPACT_LEVELS:
            continue
        matrix[layer_name][alea_level] = float(row["impact_value"] or 0.0)

    return matrix


def _save_resilience_impact_matrix(conn, values: dict):
    if not isinstance(values, dict):
        raise ValueError("Format de matrice invalide.")

    support_layers = set(_ensure_resilience_impact_matrix_defaults(conn))
    for layer_name, raw_levels in values.items():
        layer_name = str(layer_name or "").strip()
        if not layer_name:
            continue
        if layer_name not in support_layers:
            raise ValueError(f'La couche "{layer_name}" n\'est pas disponible dans la configuration.')
        if not isinstance(raw_levels, dict):
            raise ValueError(f'Valeurs invalides pour la couche "{layer_name}".')

        for alea_level in RESILIENCE_IMPACT_LEVELS:
            impact_value = _normalize_resilience_impact_value(
                raw_levels.get(str(alea_level), raw_levels.get(alea_level, 0))
            )
            conn.execute(text("""
                INSERT INTO resilience.impact_matrix (layer_name, alea_level, impact_value, updated_at)
                VALUES (:layer_name, :alea_level, :impact_value, now())
                ON CONFLICT (layer_name, alea_level) DO UPDATE
                SET impact_value = EXCLUDED.impact_value,
                    updated_at = now()
            """), {
                "layer_name": layer_name,
                "alea_level": alea_level,
                "impact_value": impact_value,
            })


def _build_resilience_output_columns(alea_tables: list[str]) -> dict[str, dict[str, str]]:
    mapping: dict[str, dict[str, str]] = {}
    used_suffixes: set[str] = set()
    max_suffix_len = 63 - len("impact_")

    for layer_name in alea_tables:
        raw_suffix = str(layer_name or "").strip()
        if raw_suffix.startswith("alea_"):
            raw_suffix = raw_suffix[5:]
        normalized = re.sub(r'[^A-Za-z0-9_]+', '_', raw_suffix).strip('_').lower() or "layer"
        suffix = normalized[:max_suffix_len].rstrip('_') or "layer"
        if suffix in used_suffixes:
            digest = hashlib.sha1(str(layer_name).encode("utf-8")).hexdigest()[:6]
            base_len = max(1, max_suffix_len - len(digest) - 1)
            suffix = f"{normalized[:base_len].rstrip('_') or 'layer'}_{digest}"
        while suffix in used_suffixes:
            suffix = f"{suffix[:max(1, max_suffix_len - 2)]}_{len(used_suffixes)}"
            suffix = suffix[:max_suffix_len].rstrip('_') or "layer"

        used_suffixes.add(suffix)
        mapping[layer_name] = {
            "suffix": suffix,
            "alea_col": f"alea_{suffix}",
            "impact_col": f"impact_{suffix}",
        }

    return mapping


def _private_run_layer_by_name(conn, layer_name: str):
    return conn.execute(text("""
        SELECT layer_name, display_name, owner_user_id, created_at
        FROM resilience.private_run_layers
        WHERE layer_name = :layer_name
        LIMIT 1
    """), {"layer_name": layer_name}).mappings().first()


def _private_run_layer_by_display_name(conn, owner_user_id: int, display_name: str):
    return conn.execute(text("""
        SELECT layer_name, display_name, owner_user_id, created_at
        FROM resilience.private_run_layers
        WHERE owner_user_id = :owner_user_id
          AND display_name = :display_name
        LIMIT 1
    """), {
        "owner_user_id": owner_user_id,
        "display_name": display_name,
    }).mappings().first()


def _private_analysis_layer_by_name(conn, layer_name: str):
    return conn.execute(text("""
        SELECT layer_name, display_name, owner_user_id, created_at
        FROM resilience.private_analysis_layers
        WHERE layer_name = :layer_name
        LIMIT 1
    """), {"layer_name": layer_name}).mappings().first()


def _private_analysis_layer_by_display_name(conn, owner_user_id: int, display_name: str):
    return conn.execute(text("""
        SELECT layer_name, display_name, owner_user_id, created_at
        FROM resilience.private_analysis_layers
        WHERE owner_user_id = :owner_user_id
          AND display_name = :display_name
        LIMIT 1
    """), {
        "owner_user_id": owner_user_id,
        "display_name": display_name,
    }).mappings().first()


def _register_private_run_layer(conn, layer_name: str, display_name: str, owner_user_id: int):
    conn.execute(text("""
        INSERT INTO resilience.private_run_layers (layer_name, display_name, owner_user_id)
        VALUES (:layer_name, :display_name, :owner_user_id)
        ON CONFLICT (layer_name) DO UPDATE
        SET display_name = EXCLUDED.display_name,
            owner_user_id = EXCLUDED.owner_user_id
    """), {
        "layer_name": layer_name,
        "display_name": display_name,
        "owner_user_id": owner_user_id,
    })


def _unregister_private_run_layer(conn, layer_name: str):
    conn.execute(text("""
        DELETE FROM resilience.private_run_layers
        WHERE layer_name = :layer_name
    """), {"layer_name": layer_name})


def _register_private_analysis_layer(conn, layer_name: str, display_name: str, owner_user_id: int):
    conn.execute(text("""
        INSERT INTO resilience.private_analysis_layers (layer_name, display_name, owner_user_id)
        VALUES (:layer_name, :display_name, :owner_user_id)
        ON CONFLICT (layer_name) DO UPDATE
        SET display_name = EXCLUDED.display_name,
            owner_user_id = EXCLUDED.owner_user_id
    """), {
        "layer_name": layer_name,
        "display_name": display_name,
        "owner_user_id": owner_user_id,
    })


def _unregister_private_analysis_layer(conn, layer_name: str):
    conn.execute(text("""
        DELETE FROM resilience.private_analysis_layers
        WHERE layer_name = :layer_name
    """), {"layer_name": layer_name})


def _make_private_run_layer_name(display_name: str, owner_user_id: int) -> str:
    normalized = re.sub(r'[^A-Za-z0-9_]+', '_', str(display_name or "")).strip('_').lower() or "run"
    digest = hashlib.sha1(f"{owner_user_id}:{display_name}".encode("utf-8")).hexdigest()[:12]
    prefix = f"run_u{owner_user_id}_"
    max_base_len = max(1, 63 - len(prefix) - len(digest) - 1)
    base = normalized[:max_base_len].rstrip('_') or "run"
    return f"{prefix}{base}_{digest}"


def _make_private_analysis_layer_name(display_name: str, owner_user_id: int) -> str:
    normalized = re.sub(r'[^A-Za-z0-9_]+', '_', str(display_name or "")).strip('_').lower() or "analyse"
    digest = hashlib.sha1(f"analysis:{owner_user_id}:{display_name}".encode("utf-8")).hexdigest()[:12]
    prefix = f"analysis_u{owner_user_id}_"
    max_base_len = max(1, 63 - len(prefix) - len(digest) - 1)
    base = normalized[:max_base_len].rstrip('_') or "analyse"
    return f"{prefix}{base}_{digest}"


def _resolve_resilience_layer_for_user(conn, requested_name: str, owner_user_id: int | None):
    requested_name = str(requested_name or "").strip()
    if not requested_name:
        return None

    if owner_user_id is not None:
        row = _private_run_layer_by_display_name(conn, owner_user_id, requested_name)
        if row:
            if _get_resilience_object_kind(conn, row["layer_name"]) is None:
                _unregister_private_run_layer(conn, row["layer_name"])
            else:
                return {
                    "requested_name": requested_name,
                    "layer_name": row["layer_name"],
                    "display_name": row["display_name"],
                    "owner_user_id": row["owner_user_id"],
                    "scope": "private_run",
                    "allowed": True,
                }

    row = _private_run_layer_by_name(conn, requested_name)
    if row:
        if _get_resilience_object_kind(conn, row["layer_name"]) is None:
            _unregister_private_run_layer(conn, row["layer_name"])
        else:
            allowed = owner_user_id is not None and int(row["owner_user_id"]) == int(owner_user_id)
            return {
                "requested_name": requested_name,
                "layer_name": row["layer_name"],
                "display_name": row["display_name"],
                "owner_user_id": row["owner_user_id"],
                "scope": "private_run",
                "allowed": allowed,
            }

    if _get_resilience_object_kind(conn, requested_name) is not None:
        return {
            "requested_name": requested_name,
            "layer_name": requested_name,
            "display_name": requested_name,
            "owner_user_id": None,
            "scope": "public",
            "allowed": True,
        }

    return None


def _plan_private_run_target(conn, display_name: str, owner_user_id: int):
    existing = _private_run_layer_by_display_name(conn, owner_user_id, display_name)
    if existing:
        return {
            "layer_name": existing["layer_name"],
            "display_name": existing["display_name"],
        }

    # Un nom logique de run ne doit pas masquer une couche publique existante.
    existing_public = _resolve_resilience_layer_for_user(conn, display_name, owner_user_id=None)
    if existing_public and existing_public["scope"] == "public":
        raise ValueError(f'Le nom "{display_name}" est déjà utilisé par une couche partagée.')

    layer_name = _make_private_run_layer_name(display_name, owner_user_id)
    collision = _resolve_resilience_layer_for_user(conn, layer_name, owner_user_id=None)
    if collision and collision["scope"] == "public":
        raise ValueError(f'Le nom interne "{layer_name}" est déjà utilisé. Choisissez un autre nom de run.')

    return {
        "layer_name": layer_name,
        "display_name": display_name,
    }


def _plan_private_analysis_target(conn, display_name: str, owner_user_id: int):
    existing = _private_analysis_layer_by_display_name(conn, owner_user_id, display_name)
    if existing:
        return {
            "layer_name": existing["layer_name"],
            "display_name": existing["display_name"],
        }

    existing_run = _private_run_layer_by_display_name(conn, owner_user_id, display_name)
    if existing_run:
        raise ValueError(
            f'Le nom "{display_name}" est déjà utilisé par un résultat de run privé.'
        )

    existing_public = _resolve_resilience_layer_for_user(conn, display_name, owner_user_id=None)
    if existing_public and existing_public["scope"] == "public":
        raise ValueError(f'Le nom "{display_name}" est déjà utilisé par une couche partagée.')

    layer_name = _make_private_analysis_layer_name(display_name, owner_user_id)
    collision = _resolve_resilience_layer_for_user(conn, layer_name, owner_user_id=None)
    if collision and collision["scope"] == "public":
        raise ValueError(
            f'Le nom interne "{layer_name}" est déjà utilisé. Choisissez un autre nom de couche.'
        )

    return {
        "layer_name": layer_name,
        "display_name": display_name,
    }


def _ensure_public_layer_name_available(conn, display_name: str):
    collision = conn.execute(text("""
        SELECT 1
        FROM resilience.private_run_layers reserved
        WHERE display_name = :display_name
           OR layer_name = :display_name
        LIMIT 1
    """), {"display_name": display_name}).first()
    if collision:
        raise ValueError(
            f'Le nom "{display_name}" est déjà réservé par une couche privée. '
            "Utilisez un autre nom pour la couche partagée."
        )


def _log_resilience_run(
    main_layer,
    view_name,
    stress_layers,
    status,
    duration_seconds=None,
    message=None,
    owner_user_id=None,
    layer_name=None,
):
    """
    Enregistre un run résilience (succès/erreur) dans l'historique.
    """
    try:
        _ensure_resilience_run_history_table()
        stress_list = [str(s).strip() for s in (stress_layers or []) if str(s).strip()]
        stress_text = json.dumps(stress_list, ensure_ascii=False)
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO resilience.run_history
                (owner_user_id, main_layer, view_name, layer_name, stress_layers, status, duration_seconds, message)
                VALUES (:owner_user_id, :main_layer, :view_name, :layer_name, :stress_layers, :status, :duration_seconds, :message)
            """), {
                "owner_user_id": owner_user_id,
                "main_layer": main_layer or "",
                "view_name": view_name or "",
                "layer_name": layer_name or None,
                "stress_layers": stress_text,
                "status": status or "unknown",
                "duration_seconds": duration_seconds,
                "message": message or ""
            })
    except Exception:
        logging.exception("Impossible d'enregistrer l'historique du run résilience.")


@app.route('/resilience_runs_history')
def resilience_runs_history():
    """
    Retourne l'historique des runs de résilience, avec filtre texte optionnel.
    """
    current_user_id = _current_user_id()
    if current_user_id is None:
        return jsonify({"status": "error", "message": "Utilisateur non authentifié."}), 401

    q = (request.args.get("q") or "").strip()
    limit_raw = request.args.get("limit", "200")
    try:
        limit = int(limit_raw)
    except ValueError:
        limit = 200
    limit = max(1, min(limit, 500))

    _ensure_resilience_run_history_table()
    like = f"%{q}%"

    with engine.begin() as conn:
        _purge_missing_private_resilience_layers(conn)
        rows = conn.execute(text("""
            SELECT run_id, created_at, main_layer, view_name, COALESCE(layer_name, view_name) AS layer_name, stress_layers, status, duration_seconds, message
            FROM resilience.run_history
            WHERE owner_user_id = :owner_user_id
              AND (:q = ''
               OR run_id::text ILIKE :like
               OR main_layer ILIKE :like
               OR view_name ILIKE :like
               OR stress_layers ILIKE :like
               OR status ILIKE :like)
            ORDER BY run_id DESC
            LIMIT :limit
        """), {
            "owner_user_id": current_user_id,
            "q": q,
            "like": like,
            "limit": limit,
        }).mappings().all()

    payload = []
    for row in rows:
        stress_raw = (row["stress_layers"] or "").strip()
        stress_layers = []
        if stress_raw:
            if stress_raw.startswith("["):
                try:
                    parsed = json.loads(stress_raw)
                    if isinstance(parsed, list):
                        stress_layers = [str(s).strip() for s in parsed if str(s).strip()]
                except Exception:
                    stress_layers = []
            if not stress_layers:
                stress_layers = [s.strip() for s in stress_raw.split(",") if s.strip()]
        payload.append({
            "run_id": row["run_id"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "main_layer": row["main_layer"],
            "view_name": row["view_name"],
            "layer_name": row["layer_name"],
            "stress_layers": stress_layers,
            "status": row["status"],
            "duration_seconds": row["duration_seconds"],
            "message": row["message"] or ""
        })
    return jsonify(payload)


@app.route('/resilience_runs_delete', methods=['POST'])
def resilience_runs_delete():
    """
    Supprime une sélection de runs (par run_id).
    """
    current_user_id = _current_user_id()
    if current_user_id is None:
        return jsonify({"status": "error", "message": "Utilisateur non authentifié."}), 401

    _ensure_resilience_run_history_table()
    data = request.get_json(silent=True) or {}
    raw_ids = data.get("run_ids")
    if not isinstance(raw_ids, list):
        return jsonify({"status": "error", "message": "run_ids doit être une liste."}), 400

    run_ids = []
    for raw in raw_ids:
        try:
            rid = int(raw)
        except (TypeError, ValueError):
            continue
        if rid > 0:
            run_ids.append(rid)
    run_ids = sorted(set(run_ids))

    if not run_ids:
        return jsonify({"status": "error", "message": "Aucun run_id valide fourni."}), 400

    placeholders = ", ".join(f":id_{idx}" for idx in range(len(run_ids)))
    params = {f"id_{idx}": rid for idx, rid in enumerate(run_ids)}

    try:
        with engine.begin() as conn:
            result = conn.execute(
                text(f"""
                    DELETE FROM resilience.run_history
                    WHERE owner_user_id = :owner_user_id
                      AND run_id IN ({placeholders})
                """),
                {"owner_user_id": current_user_id, **params},
            )
        return jsonify({
            "status": "ok",
            "requested_count": len(run_ids),
            "deleted_count": int(result.rowcount or 0),
        })
    except Exception as e:
        logging.exception("Suppression des runs de résilience impossible.")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/resilience_runs_reset', methods=['POST'])
def resilience_runs_reset():
    """
    Réinitialise entièrement l'historique des runs.
    """
    current_user_id = _current_user_id()
    if current_user_id is None:
        return jsonify({"status": "error", "message": "Utilisateur non authentifié."}), 401

    _ensure_resilience_run_history_table()
    try:
        with engine.begin() as conn:
            result = conn.execute(text("""
                DELETE FROM resilience.run_history
                WHERE owner_user_id = :owner_user_id
            """), {"owner_user_id": current_user_id})
        return jsonify({"status": "ok", "deleted_count": int(result.rowcount or 0)})
    except Exception as e:
        logging.exception("Réinitialisation de l'historique des runs impossible.")
        return jsonify({"status": "error", "message": str(e)}), 500


# --- SSE : création vue matérialisée aléas avec logs en temps réel ---
@app.route('/alea_view_batch_stream')
def alea_view_batch_stream():
    current_user_id = _current_user_id()
    if current_user_id is None:
        return jsonify({'status': 'error', 'message': 'Utilisateur non authentifié.'}), 401

    main = request.args.get('main_layer')
    view_name = request.args.get('view_name') or (f"{main}_alea_view" if main else None)
    selected_raw = request.args.get('alea_tables') or ""
    selected_alea = [a for a in selected_raw.split(',') if a]

    if not main:
        return jsonify({'status': 'error', 'message': 'Couche principale manquante'}), 400
    if not view_name or not re.match(r'^[A-Za-z0-9_]+$', view_name):
        return jsonify({'status': 'error', 'message': 'Nom de vue invalide (lettres, chiffres, underscore).'}), 400

    def gen():
        run_started = time.time()
        planned_target = None
        analysis_upload = None
        analysis_input_table = None
        temp_table = None
        try:
            _ensure_resilience_run_history_table()
            analysis_upload = _get_resilience_analysis_upload_for_user(current_user_id)
            if not analysis_upload:
                message = (
                    "Importez d'abord votre couche réseau temporaire depuis la page Analyse Réseau."
                )
                _log_resilience_run(
                    main,
                    view_name,
                    selected_alea,
                    "error",
                    message=message,
                    owner_user_id=current_user_id,
                )
                yield f"data: {json.dumps({'status':'error','message': message})}\n\n"
                return
            if analysis_upload["display_name"] != main:
                message = (
                    "La couche principale sélectionnée n'est plus disponible. "
                    "Rechargez votre couche réseau temporaire avant de relancer l'analyse."
                )
                _log_resilience_run(
                    main,
                    view_name,
                    selected_alea,
                    "error",
                    message=message,
                    owner_user_id=current_user_id,
                )
                yield f"data: {json.dumps({'status':'error','message': message})}\n\n"
                return

            with engine.begin() as conn:
                _purge_missing_private_resilience_layers(conn)

                planned_target = _plan_private_run_target(conn, view_name, current_user_id)
                all_alea = _list_resilience_support_layers(conn)
                if not all_alea:
                    _log_resilience_run(
                        main,
                        view_name,
                        [],
                        "error",
                        message="Aucune couche aléa trouvée.",
                        owner_user_id=current_user_id,
                        layer_name=planned_target["layer_name"],
                    )
                    yield f"data: {json.dumps({'status':'error','message':'Aucune couche aléa trouvée.'})}\n\n"
                    return

                alea_tables = selected_alea if selected_alea else all_alea
                missing = [a for a in alea_tables if a not in all_alea]
                if missing:
                    _log_resilience_run(
                        main,
                        view_name,
                        alea_tables,
                        "error",
                        message='Couches aléa introuvables: ' + ', '.join(missing),
                        owner_user_id=current_user_id,
                        layer_name=planned_target["layer_name"],
                    )
                    yield f"data: {json.dumps({'status':'error','message':'Couches aléa introuvables: ' + ', '.join(missing)})}\n\n"
                    return

                impact_matrix = _get_resilience_impact_matrix_map(conn, alea_tables)
                output_columns = _build_resilience_output_columns(alea_tables)
                analysis_input_table = f"analysis_input_u{current_user_id}_{time.time_ns()}"
                temp_table = f"tmp_run_u{current_user_id}_{time.time_ns()}"

                # Pas de limite SQL pour les couches volumineuses.
                conn.execute(text("SET LOCAL statement_timeout = 0"))
                _import_vector_dataset_to_postgis(
                    analysis_upload["dataset_path"],
                    analysis_input_table,
                    schema="resilience",
                )
                db_main = analysis_input_table
                if _get_resilience_object_kind(conn, db_main) is None:
                    _log_resilience_run(
                        main,
                        view_name,
                        alea_tables,
                        "error",
                        message=f'Couche principale {main} introuvable.',
                        owner_user_id=current_user_id,
                        layer_name=planned_target["layer_name"],
                    )
                    yield f"data: {json.dumps({'status':'error','message':f'Couche principale {main} introuvable.'})}\n\n"
                    return

                pk_col = _pick_pk_column(conn, 'resilience', db_main)
                key_col = _quote_ident(pk_col) if pk_col else _quote_ident('__rowid')
                q_temp_table = _quote_ident(temp_table)
                q_main = _quote_ident(db_main)
                q_view = _quote_ident(planned_target["layer_name"])

                if pk_col:
                    conn.execute(text(f'''
                        DROP TABLE IF EXISTS "resilience".{q_temp_table};
                        CREATE TABLE "resilience".{q_temp_table} AS
                        SELECT * FROM "resilience".{q_main};
                    '''))
                else:
                    conn.execute(text(f'''
                        DROP TABLE IF EXISTS "resilience".{q_temp_table};
                        CREATE TABLE "resilience".{q_temp_table} AS
                        SELECT *, row_number() OVER () AS __rowid
                        FROM "resilience".{q_main};
                    '''))

                conn.execute(text(f'''
                    CREATE INDEX IF NOT EXISTS {_quote_ident(f"{temp_table}_geom_idx")}
                    ON "resilience".{q_temp_table} USING GIST(geometry)
                '''))
                if pk_col:
                    conn.execute(text(f'''
                        CREATE INDEX IF NOT EXISTS {_quote_ident(f"{temp_table}_{pk_col}_idx")}
                        ON "resilience".{q_temp_table} ({key_col})
                    '''))
                else:
                    conn.execute(text(f'''
                        CREATE INDEX IF NOT EXISTS {_quote_ident(f"{temp_table}__rowid_idx")}
                        ON "resilience".{q_temp_table} (__rowid)
                    '''))

                total = len(alea_tables)
                for idx, alea in enumerate(alea_tables, 1):
                    start = time.time()
                    val_col = _pick_alea_value_col(conn, alea)
                    q_alea = _quote_ident(alea)
                    q_val_col = _quote_ident(val_col)
                    output_meta = output_columns[alea]
                    alea_col = output_meta["alea_col"]
                    impact_col = output_meta["impact_col"]
                    q_alea_col = _quote_ident(alea_col)
                    q_impact_col = _quote_ident(impact_col)
                    impact_values = impact_matrix.get(alea, {})
                    conn.execute(text(f'''
                        ALTER TABLE "resilience".{q_temp_table}
                        ADD COLUMN IF NOT EXISTS {q_alea_col} INTEGER
                    '''))
                    conn.execute(text(f'''
                        ALTER TABLE "resilience".{q_temp_table}
                        ADD COLUMN IF NOT EXISTS {q_impact_col} DOUBLE PRECISION DEFAULT 0
                    '''))
                    conn.execute(text(f'''
                        CREATE INDEX IF NOT EXISTS {_quote_ident(f"{alea}_geom_idx")}
                        ON "resilience".{q_alea} USING GIST(geometry)
                    '''))
                    conn.execute(text(f'''
                        WITH intersects AS (
                            SELECT
                                v.{key_col} AS k,
                                btrim(a.{q_val_col}::text) AS raw_val
                            FROM "resilience".{q_temp_table} v
                            JOIN "resilience".{q_alea} a
                              ON ST_Intersects(a.geometry, v.geometry)
                            WHERE a.{q_val_col} IS NOT NULL
                        ),
                        agg AS (
                            SELECT
                                k,
                                MAX(
                                    CASE
                                        WHEN raw_val ~ '^-?[0-9]+(\\.[0-9]+)?$'
                                            THEN floor(raw_val::numeric)::int
                                        ELSE NULL
                                    END
                                ) AS alea_level
                            FROM intersects
                            WHERE raw_val <> ''
                            GROUP BY k
                        )
                        UPDATE "resilience".{q_temp_table} v
                        SET {q_alea_col} = agg.alea_level
                        FROM agg
                        WHERE v.{key_col} = agg.k;
                    '''))
                    conn.execute(text(f'''
                        UPDATE "resilience".{q_temp_table} v
                        SET {q_impact_col} = CASE
                            WHEN v.{q_alea_col} = 0 THEN :impact_0
                            WHEN v.{q_alea_col} = 1 THEN :impact_1
                            WHEN v.{q_alea_col} = 2 THEN :impact_2
                            WHEN v.{q_alea_col} = 3 THEN :impact_3
                            ELSE 0
                        END
                    '''), {
                        "impact_0": float(impact_values.get(0, 0.0)),
                        "impact_1": float(impact_values.get(1, 0.0)),
                        "impact_2": float(impact_values.get(2, 0.0)),
                        "impact_3": float(impact_values.get(3, 0.0)),
                    })
                    elapsed = round(time.time() - start, 2)
                    payload = {'status': 'progress', 'layer': alea, 'seconds': elapsed, 'step': idx, 'total': total}
                    yield f"data: {json.dumps(payload)}\n\n"

                impact_cols = [output_columns[layer]["impact_col"] for layer in alea_tables]
                conn.execute(text(f'''
                    ALTER TABLE "resilience".{q_temp_table}
                    ADD COLUMN IF NOT EXISTS "somme" DOUBLE PRECISION DEFAULT 0
                '''))
                if impact_cols:
                    somme_expr = " + ".join([f'COALESCE({_quote_ident(col)}, 0)' for col in impact_cols])
                    conn.execute(text(f'''
                        UPDATE "resilience".{q_temp_table}
                        SET "somme" = {somme_expr}
                    '''))

                # Table finale (pas de MV) + indexes
                conn.execute(text(f'''
                    DROP TABLE IF EXISTS "resilience".{q_view} CASCADE;
                    CREATE TABLE "resilience".{q_view} AS
                    SELECT * FROM "resilience".{q_temp_table};
                '''))
                conn.execute(text(f'''
                    CREATE INDEX IF NOT EXISTS {_quote_ident(f"{planned_target['layer_name']}_geom_idx")}
                    ON "resilience".{q_view} USING GIST(geometry)
                '''))
                if pk_col:
                    conn.execute(text(f'''
                        CREATE INDEX IF NOT EXISTS {_quote_ident(f"{planned_target['layer_name']}_{pk_col}_idx")}
                        ON "resilience".{q_view} ({key_col})
                    '''))
                else:
                    conn.execute(text(f'''
                        CREATE INDEX IF NOT EXISTS {_quote_ident(f"{planned_target['layer_name']}__rowid_idx")}
                        ON "resilience".{q_view} (__rowid)
                    '''))
                    # Ne pas exposer la colonne technique dans la sortie finale.
                    conn.execute(text(f'''
                        ALTER TABLE "resilience".{q_view}
                        DROP COLUMN IF EXISTS "__rowid"
                    '''))
                conn.execute(text(f'''DROP TABLE IF EXISTS "resilience".{q_temp_table} CASCADE;'''))
                conn.execute(text(f'''DROP TABLE IF EXISTS "resilience".{_quote_ident(db_main)} CASCADE;'''))
                _register_private_run_layer(conn, planned_target["layer_name"], view_name, current_user_id)

            done = {
                'status': 'done',
                'view': view_name,
                'dependencies': [main] + alea_tables,
                'download_csv': f'/download_resilience_layer/{view_name}?format=csv',
                'download_gpkg': f'/download_resilience_layer/{view_name}?format=gpkg',
                'download_shp': f'/download_resilience_layer/{view_name}?format=shp'
            }
            _log_resilience_run(
                main,
                view_name,
                alea_tables,
                "done",
                round(time.time() - run_started, 2),
                owner_user_id=current_user_id,
                layer_name=planned_target["layer_name"],
            )
            yield f"data: {json.dumps(done)}\n\n"
        except Exception as e:
            for transient_layer in (temp_table, analysis_input_table):
                if not transient_layer:
                    continue
                try:
                    with engine.begin() as cleanup_conn:
                        cleanup_conn.execute(text(
                            f'DROP TABLE IF EXISTS "resilience".{_quote_ident(transient_layer)} CASCADE'
                        ))
                except Exception:
                    logging.exception("Nettoyage impossible pour la couche temporaire %s.", transient_layer)
            _log_resilience_run(
                main,
                view_name,
                selected_alea,
                "error",
                round(time.time() - run_started, 2),
                str(e),
                owner_user_id=current_user_id,
                layer_name=(planned_target or {}).get("layer_name"),
            )
            yield f"data: {json.dumps({'status':'error','message':str(e)})}\n\n"

    return Response(stream_with_context(gen()), mimetype='text/event-stream')
````

#### app_resilience.py

````python
from flask import jsonify, redirect, request, session, url_for

from app import app as app


AUTH_EXACT_PATHS = {
    "/healthz",
    "/login",
    "/logout",
    "/forgot",
}
AUTH_PREFIX_PATHS = (
    "/reset/",
    "/static/",
    "/image/",
)

RESILIENCE_EXACT_PATHS = {
    "/resilience",
    "/resilience_admin_users",
    "/resilience_help_content",
    "/resilience_help_document",
    "/resilience_help_document_preview",
    "/resilience_help_document_download",
    "/upload_resilience",
    "/upload_resilience_analysis_layer",
    "/resilience_layers",
    "/resilience_layers_support",
    "/resilience_impact_matrix",
    "/resilience_analysis_layers",
    "/resilience_analysis_layer_clear",
    "/resilience_runs_history",
    "/resilience_runs_delete",
    "/resilience_runs_reset",
    "/delete_resilience_layer",
    "/alea_view_batch_stream",
}
RESILIENCE_PREFIX_PATHS = (
    "/resilience_admin_users/",
    "/resilience_help_document/",
    "/resilience_help_document_preview/",
    "/resilience_help_document_download/",
    "/resilience_layer_data/",
    "/resilience_dependencies/",
    "/download_resilience_layer/",
)

def _is_resilience_path(path: str) -> bool:
    if path in RESILIENCE_EXACT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in RESILIENCE_PREFIX_PATHS)


def _is_allowed_on_resilience_app(path: str) -> bool:
    if path in AUTH_EXACT_PATHS or path in RESILIENCE_EXACT_PATHS:
        return True
    if any(path.startswith(prefix) for prefix in AUTH_PREFIX_PATHS):
        return True
    if any(path.startswith(prefix) for prefix in RESILIENCE_PREFIX_PATHS):
        return True
    return False


@app.before_request
def isolate_resilience_application():
    if request.path == "/":
        return redirect("/resilience", code=302)

    if _is_resilience_path(request.path) and "user_id" not in session:
        return redirect(url_for("login"), code=302)

    if _is_allowed_on_resilience_app(request.path):
        return None

    return jsonify(
        {
            "status": "error",
            "message": "Route indisponible sur l'application Résilience.",
        }
    ), 404
````

#### create_user.py

````python
from app import db, User, app  # Importer app pour gérer le contexte Flask
import sys

def create_user(username, password):
    """Créer un utilisateur et l'ajouter dans la base de données"""
    with app.app_context():  # Assurer l'utilisation du contexte Flask
        # Crée la table users dans le schéma resilience si absente.
        User.__table__.create(bind=db.engine, checkfirst=True)

        # Vérifier si l'utilisateur existe déjà
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            print(f" L'utilisateur '{username}' existe déjà !")
            return

        # Création et hachage du mot de passe
        new_user = User(username=username)
        new_user.set_password(password)

        # Ajout et validation
        db.session.add(new_user)
        db.session.commit()
        print(f" Utilisateur '{username}' créé avec succès !")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Utilisation : python create_user.py <username> <password>")
        sys.exit(1)

    username = sys.argv[1]
    password = sys.argv[2]

    create_user(username, password)
````

### Deploiement

#### Dockerfile

````dockerfile
FROM python:3.11-slim

# 1) Dépendances système
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc g++ \
    gdal-bin libgdal-dev \
    libspatialindex-dev \
    proj-bin proj-data libproj-dev \
    libgeos-dev \
    libpq-dev \
    libreoffice-writer \
    fonts-dejavu-core \
    ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app



# 3) Rend pip/requests plus calmes et utilise la trust store système
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# 4) Copie un requirements UTF-8 dédié au build Docker.
COPY requirements.docker.txt ./requirements.docker.txt

# 5) Installe les deps Python.
#    - Pas d'upgrade pip (ça forcerait un accès à PyPI tout de suite).
#    - Ajout de --trusted-host aussi ici (plan B si ton CA n'est pas installé).
RUN pip install --no-cache-dir \
      --trusted-host pypi.org --trusted-host files.pythonhosted.org \
      -r requirements.docker.txt \
  && pip install --no-cache-dir \
      --trusted-host pypi.org --trusted-host files.pythonhosted.org \
      GeoAlchemy2==0.14.7 geopandas==0.14.4 shapely==2.0.5 pyproj==3.6.1 rtree==1.3.0 requests==2.32.3 gunicorn==22.0.0

# 6) Copie du code après l'install (meilleur cache Docker)
COPY . /app

EXPOSE 8000
CMD ["sh", "-c", "gunicorn -w 2 -b 0.0.0.0:${PORT:-8000} --timeout 0 --graceful-timeout 300 app_resilience:app"]
````

#### docker-compose.yml

````yaml
services:
  db_resilience:
    image: postgis/postgis:16-3.4
    container_name: telecom_db_resilience
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${DB_USERNAME_RESILIENCE:-app}
      POSTGRES_PASSWORD: ${DB_PASSWORD_RESILIENCE:-app}
      POSTGRES_DB: ${DB_NAME_RESILIENCE:-telecom_resilience_db}
    ports:
      - "5433:5432"
    volumes:
      - db_resilience_data:/var/lib/postgresql/data
      - ./db/init_resilience:/docker-entrypoint-initdb.d
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 10s
      timeout: 5s
      retries: 10

  web_resilience:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: telecom_web_resilience
    env_file:
      - .env
    environment:
      DB_HOST: db_resilience
      DB_PORT: 5432
      DB_USERNAME: ${DB_USERNAME_RESILIENCE:-app}
      DB_PASSWORD: ${DB_PASSWORD_RESILIENCE:-app}
      DB_NAME: ${DB_NAME_RESILIENCE:-telecom_resilience_db}
      DB_SEARCH_PATH: resilience,public
      AUTH_SCHEMA: resilience
      LOGIN_TEMPLATE: login_resilience.html
      RESET_LINK_VIA_UI: ${RESET_LINK_VIA_UI:-1}
    depends_on:
      db_resilience:
        condition: service_healthy
    ports:
      - "8001:8000"
    volumes:
      - ./uploads:/app/uploads
      - ./temp_shapefiles:/app/temp_shapefiles
      - ./static:/app/static
      - ./templates:/app/templates
    command: gunicorn -w 2 -b 0.0.0.0:8000 --timeout 0 --graceful-timeout 300 app_resilience:app
    restart: unless-stopped

volumes:
  db_resilience_data:
````

#### render.yaml

````yaml
services:
  - type: web
    name: sipperesiste-resilience
    runtime: docker
    plan: free
    dockerfilePath: ./Dockerfile
    dockerCommand: gunicorn -w 2 -b 0.0.0.0:$PORT --timeout 0 --graceful-timeout 300 app_resilience:app
    envVars:
      - key: SECRET_KEY
        generateValue: true
      - key: DB_HOST
        fromDatabase:
          name: sipperesiste-resilience-db
          property: host
      - key: DB_PORT
        value: 5432
      - key: DB_USERNAME
        fromDatabase:
          name: sipperesiste-resilience-db
          property: user
      - key: DB_PASSWORD
        fromDatabase:
          name: sipperesiste-resilience-db
          property: password
      - key: DB_NAME
        fromDatabase:
          name: sipperesiste-resilience-db
          property: database
      - key: DB_SEARCH_PATH
        value: resilience,public
      - key: AUTH_SCHEMA
        value: resilience
      - key: LOGIN_TEMPLATE
        value: login_resilience.html
      - key: RESET_LINK_VIA_UI
        value: 0

databases:
  - name: sipperesiste-resilience-db
    plan: free
    databaseName: sipperesiste_resilience
    postgresMajorVersion: "16"
````

### Dependances

#### requirements.txt

````text
blinker==1.9.0
chardet==5.2.0
click==8.1.8
colorama==0.4.6
dbfread==2.0.7
Flask==3.1.0
Flask-SQLAlchemy==3.1.1
greenlet==3.2.2
itsdangerous==2.2.0
Jinja2==3.1.6
MarkupSafe==3.0.2
numpy==2.3.1
pandas==2.3.0
psycopg2==2.9.10
python-dateutil==2.9.0.post0
python-dotenv==1.1.1
pytz==2025.2
six==1.17.0
SQLAlchemy==2.0.41
typing_extensions==4.13.2
tzdata==2025.2
Werkzeug==3.1.3
````

#### requirements.docker.txt

````text
blinker==1.9.0
chardet==5.2.0
click==8.1.8
colorama==0.4.6
dbfread==2.0.7
Flask==3.1.0
Flask-SQLAlchemy==3.1.1
greenlet==3.2.2
itsdangerous==2.2.0
Jinja2==3.1.6
MarkupSafe==3.0.2
numpy==2.3.1
pandas==2.3.0
psycopg2==2.9.10
python-dateutil==2.9.0.post0
python-dotenv==1.1.1
pytz==2025.2
six==1.17.0
SQLAlchemy==2.0.41
typing_extensions==4.13.2
tzdata==2025.2
Werkzeug==3.1.3
````

### Base de donnees

#### db/init_resilience/00_init_postgis.sql

````sql
-- Init DB Résilience
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA IF NOT EXISTS resilience;
````
