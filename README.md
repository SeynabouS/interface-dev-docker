# Resilience Reseau

Application Flask dediee a la partie Resilience uniquement.

- Web local : `http://localhost:8001/resilience`
- Base locale : service PostGIS `db_resilience`, port hote `5433`
- Schema d'authentification et de donnees : `resilience`
- Page de connexion : `login_resilience.html`
- Imports applicatifs : fichiers `.gpkg` uniquement pour les couches alea et les couches infra temporaires

## Premier lancement local

Copier l'exemple d'environnement uniquement pour une nouvelle installation :

```bash
cp .env.docker.example .env
```

Renseigner ensuite les variables suivantes :

- `DB_USERNAME_RESILIENCE` : utilisateur PostgreSQL, `app` par defaut ;
- `DB_PASSWORD_RESILIENCE` : mot de passe PostgreSQL robuste et obligatoire ;
- `DB_NAME_RESILIENCE` : base PostgreSQL, `telecom_resilience_db` par defaut ;
- `SECRET_KEY` : secret Flask long et aleatoire ;
- `RESET_LINK_VIA_UI` : utiliser `0` en production.

Demarrer l'application :

```bash
docker compose up -d --build
```

Verifier le lancement :

```bash
docker compose ps
curl -fsS http://localhost:8001/healthz
```

## Compte administrateur initial

Creer le premier compte avec le role administrateur :

```bash
docker compose exec web_resilience python create_user.py admin_resilience "<MOT_DE_PASSE_ADMIN_ROBUSTE>" --admin
```

Si le compte existe deja sans les droits administrateur, la meme commande avec `--admin` le promeut sans modifier son mot de passe.

Les autres comptes peuvent ensuite etre crees et geres depuis l'onglet `Admin. & Acces`.

## Redeploiement du serveur existant sans perte de donnees

Cette procedure doit etre utilisee lorsque PostgreSQL contient deja des couches, des analyses ou des comptes utilisateurs.

### Regles importantes

- Ne jamais lancer `docker compose down -v`.
- Ne jamais supprimer le volume PostgreSQL `db_resilience_data`.
- Ne jamais utiliser `docker volume rm` ou `docker system prune --volumes` pour ce projet.
- Ne pas recopier `.env.docker.example` sur le fichier `.env` existant.
- Conserver les valeurs actuelles de `DB_USERNAME_RESILIENCE`, `DB_NAME_RESILIENCE` et `SECRET_KEY`.
- Utiliser `docker compose up -d --build` : cette commande reconstruit les conteneurs sans supprimer le volume.

### 1. Verifier l'etat actuel

Depuis le dossier du projet sur le serveur :

```bash
git status --short
docker compose ps
```

Si `git status --short` affiche des modifications sur des fichiers suivis, ne pas continuer avant de les avoir sauvegardees.

### 2. Sauvegarder PostgreSQL avant toute modification

La sauvegarde est placee en dehors du depot Git :

```bash
mkdir -p ../backups_sipperesiste
BACKUP_FILE="../backups_sipperesiste/resilience_$(date +%Y%m%d_%H%M%S).dump"
docker compose exec -T db_resilience sh -lc 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$BACKUP_FILE"
test -s "$BACKUP_FILE" && ls -lh "$BACKUP_FILE"
```

Ne poursuivre que si la derniere commande affiche un fichier de sauvegarde non vide.

### 3. Recuperer la derniere version

```bash
git fetch origin
git checkout romain-test-nouvelle-version
git pull --ff-only origin romain-test-nouvelle-version
```

### 4. Preparer le nouveau mot de passe PostgreSQL

Generer un secret robuste :

```bash
NEW_DB_PASSWORD="$(openssl rand -base64 32)"
printf '%s\n' "$NEW_DB_PASSWORD"
```

Modifier le fichier `.env` existant et renseigner exactement la valeur affichee :

```env
DB_USERNAME_RESILIENCE=app
DB_PASSWORD_RESILIENCE=<COLLER_ICI_LE_NOUVEAU_MOT_DE_PASSE>
DB_NAME_RESILIENCE=telecom_resilience_db
RESET_LINK_VIA_UI=0
```

Ne pas modifier `DB_USERNAME_RESILIENCE` ni `DB_NAME_RESILIENCE` si la base existante utilise deja ces valeurs. Ne pas publier le mot de passe et ne pas commiter `.env`.

### 5. Appliquer le meme mot de passe au role PostgreSQL existant

La valeur utilisee ici doit etre strictement identique a celle placee dans `.env` :

```bash
docker compose up -d db_resilience
docker compose exec -T db_resilience psql \
  -v ON_ERROR_STOP=1 \
  -U app \
  -d telecom_resilience_db \
  -v new_password="$NEW_DB_PASSWORD" \
  -c "ALTER ROLE app WITH PASSWORD :'new_password';"
unset NEW_DB_PASSWORD
```

Si `DB_USERNAME_RESILIENCE` ou `DB_NAME_RESILIENCE` ne valent pas respectivement `app` et `telecom_resilience_db` dans le `.env` existant, remplacer ces valeurs dans la commande avant de l'executer.

### 6. Reconstruire et relancer sans supprimer le volume

```bash
docker compose up -d --build
```

Ne pas lancer de commande `down -v` avant ou apres cette etape.

### 7. Verifier le redeploiement

```bash
docker compose ps
docker compose logs --tail=100 web_resilience
curl -fsS https://sipperesiste.srv.comptoirdessignaux.com/healthz
```

Verifier ensuite la connexion sur :

`https://sipperesiste.srv.comptoirdessignaux.com/login`

Les comptes utilisateurs, les couches et les analyses deja enregistres doivent toujours etre presents. Il n'est pas necessaire de recreer les comptes apres un redeploiement normal.

## Imports de donnees

L'application accepte uniquement des fichiers `.gpkg` pour :

- les couches alea partagees ;
- la couche infra temporaire utilisee dans une analyse reseau.

Les composants Shapefile (`.shp`, `.shx`, `.dbf`, `.prj`, `.cpg`, etc.) ne sont plus acceptes a l'import.
