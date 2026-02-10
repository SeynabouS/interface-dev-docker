from flask import Flask, request, jsonify, render_template, redirect, send_from_directory, url_for, session, flash, send_file, Response
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
from dbfread import DBF
import base64
import csv
from sqlalchemy import inspect
from io import StringIO  
from shapely.geometry import shape, Polygon, MultiPolygon
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
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from dotenv import load_dotenv
from sqlalchemy.sql.elements import quoted_name as sa_quoted_name
load_dotenv() 

from sqlalchemy import create_engine, text

app = Flask(__name__)

SIDE_CAR_EXTS = {'.dbf', '.shx', '.prj', '.cpg', '.sbn', '.sbx'}

# --- Options app ---
app.config['RESET_LINK_VIA_UI'] = os.getenv('RESET_LINK_VIA_UI', '0') == '1'
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "change-me-in-prod")

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

search_path = os.getenv("DB_SEARCH_PATH", "gracethd,resilience,public")

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
    __table_args__ = {'schema': 'gracethd'}
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

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
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Route de connexion
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            flash("Connexion réussie.", "success")
            return redirect(url_for('interface'))
        else:
            flash('Identifiants incorrects', 'danger')

    return render_template('login.html')

# Route de déconnexion
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash("Déconnexion réussie.", "success")
    return redirect(url_for('login'))

@app.route('/forgot', methods=['GET', 'POST'])
def forgot_password():
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

# Route protégée pour accéder à `interface.html`
@app.route('/')
@login_required
def interface():
    return render_template('interface.html')


class Export(db.Model):
    __tablename__ = 'exports'
    __table_args__ = {'schema': 'gracethd'}
    id = db.Column(db.Integer, primary_key=True)
    export_date = db.Column(db.String(255), nullable=False)
    file_name = db.Column(db.String(255), nullable=False)
    table_name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT','8000')), debug=os.getenv('FLASK_DEBUG','0')=='1')



# Fonction pour créer les tables
def create_tables():
    with app.app_context():
        db.create_all()
        logging.info("Toutes les tables ont été créées avec succès.")

def detect_encoding(file_path):
    """
    Détecte l'encodage d'un fichier en lisant une partie du fichier.
    """
    with open(file_path, 'rb') as f:
        rawdata = f.read(10000)  # Lire une partie du fichier pour détecter l'encodage
        result = chardet.detect(rawdata)
    return result.get('encoding', 'utf-8')

def detect_separator(file_path, encoding):
    """
    Détecte le séparateur d'un fichier CSV en analysant la première ligne.
    """
    with open(file_path, 'r', encoding=encoding) as f:
        first_line = f.readline()
        if ';' in first_line:
            return ';'
        elif ',' in first_line:
            return ','
        else:
            return ','  # Par défaut

def read_file_generic(file_path):
    """
    Essaye de lire un fichier quel que soit son format avec Pandas.
    """
    possible_encodings = ['ISO-8859-1', 'utf-8', 'utf-8-sig', 'latin1', 'cp1252', 'ansi']
    encoding = detect_encoding(file_path)
    possible_encodings.insert(0, encoding)  # Ajouter l'encodage détecté en premier

    for enc in possible_encodings:
        try:
            if file_path.endswith('.csv'):
                sep = detect_separator(file_path, enc)
                return pd.read_csv(file_path, encoding=enc, low_memory=False, on_bad_lines='skip', quoting=csv.QUOTE_NONE, sep=sep, escapechar='\\')
            elif file_path.endswith('.xlsx'):
                return pd.read_excel(file_path, engine='openpyxl')
            elif file_path.endswith('.json'):
                with open(file_path, 'r', encoding=enc) as f:
                    data = json.load(f)
                return pd.json_normalize(data)
            elif file_path.endswith('.dbf'):
                table = DBF(file_path, encoding=enc)
                return pd.DataFrame(iter(table))
            else:
                # Pour les fichiers binaires ou non tabulaires, lire le contenu brut
                with open(file_path, 'rb') as f:
                    content = f.read()
                    return pd.DataFrame({'file_name': [os.path.basename(file_path)], 'content': [base64.b64encode(content).decode('utf-8')]})
        except UnicodeDecodeError:
            logging.warning(f"Erreur d'encodage avec {enc}, tentative avec un autre encodage...")
        except Exception as e:
            logging.error(f"Erreur lors de la lecture du fichier {file_path} avec encodage {enc}: {str(e)}")

    # Si aucun encodage ne fonctionne
    raise ValueError(f"Erreur lors de la lecture du fichier {file_path}: Aucun encodage valide trouvé.")


    """
    Essaye de lire un fichier quel que soit son format avec Pandas.
    """
    possible_encodings = ['ISO-8859-1', 'utf-8', 'utf-8-sig', 'latin1', 'cp1252', 'ansi']
    encoding = detect_encoding(file_path)
    possible_encodings.insert(0, encoding)  # Ajouter l'encodage détecté en premier

    for enc in possible_encodings:
        try:
            if file_path.endswith('.csv'):
                sep = detect_separator(file_path, enc)
                return pd.read_csv(file_path, encoding=enc, low_memory=False, on_bad_lines='skip', quoting=csv.QUOTE_NONE, sep=sep, escapechar='\\')
            elif file_path.endswith('.xlsx'):
                return pd.read_excel(file_path, engine='openpyxl')
            elif file_path.endswith('.json'):
                with open(file_path, 'r', encoding=enc) as f:
                    data = json.load(f)
                return pd.json_normalize(data)
            elif file_path.endswith('.dbf'):
                table = DBF(file_path, encoding=enc)
                return pd.DataFrame(iter(table))
            else:
                # Pour les fichiers binaires ou non tabulaires, lire le contenu brut
                with open(file_path, 'rb') as f:
                    content = f.read()
                    return pd.DataFrame({'file_name': [os.path.basename(file_path)], 'content': [base64.b64encode(content).decode('utf-8')]})
        except UnicodeDecodeError:
            logging.warning(f"Erreur d'encodage avec {enc}, tentative avec un autre encodage...")
        except Exception as e:
            logging.error(f"Erreur lors de la lecture du fichier {file_path} avec encodage {enc}: {str(e)}")

    # Si aucun encodage ne fonctionne
    raise ValueError(f"Erreur lors de la lecture du fichier {file_path}: Aucun encodage valide trouvé.")

def read_table(export_date: str, suffix_with_ext: str) -> pd.DataFrame:
    """
    Charge la table dont le nom est f"{export_date}_{suffix_with_ext}".
    Si cette table n'existe pas, bascule sur l'autre extension (.csv ↔ .dbf).
    """
    table1 = f"{export_date}_{suffix_with_ext}"
    if suffix_with_ext.lower().endswith('.csv'):
        table2 = table1[:-4] + '.dbf'
    else:
        table2 = table1[:-4] + '.csv'

    try:
        return pd.read_sql(f'SELECT * FROM "{table1}"', engine)
    except Exception:
        return pd.read_sql(f'SELECT * FROM "{table2}"', engine)

def load_table_any(export_date: str, base_name: str, prefer: str = '.csv') -> pd.DataFrame:
    """
    Charge la table pour base_name (ex: 't_cable'), en privilégiant prefer ('.csv' par défaut),
    et bascule automatiquement sur l'autre extension si besoin, grâce à read_table().
    """
    return read_table(export_date, f'{base_name}{prefer}')

@app.route('/image/<path:filename>')
def serve_image(filename):
    return send_from_directory('image', filename)

DEFAULT_SRID = 2154  # Lambert-93
SIDE_CAR_EXTS = {'.dbf', '.shx', '.prj', '.cpg', '.sbn', '.sbx'}

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


def _read_geofile(path: str):
    def _read_with_fiona_manual(fp: str):
        records = []
        geoms = []
        crs_val = None

        def add_geom(props, geom_obj):
            if geom_obj is None:
                return
            records.append(dict(props))
            geoms.append(geom_obj)

        with fiona.open(fp) as src:
            crs_val = src.crs_wkt or src.crs
            for feat in src:
                props = feat.get("properties") or {}
                geom = feat.get("geometry")
                if geom is None:
                    continue
                try:
                    gi = geom.__geo_interface__ if hasattr(geom, "__geo_interface__") else geom
                    gtype = gi.get("type")
                    coords = gi.get("coordinates")
                    if gtype == "Polygon":
                        if coords:
                            exterior = coords[0] if len(coords) > 0 else []
                            holes = coords[1:] if len(coords) > 1 else []
                            add_geom(props, Polygon(exterior, holes))
                    elif gtype == "MultiPolygon":
                        for poly_coords in coords or []:
                            if not poly_coords:
                                continue
                            exterior = poly_coords[0] if len(poly_coords) > 0 else []
                            holes = poly_coords[1:] if len(poly_coords) > 1 else []
                            try:
                                add_geom(props, Polygon(exterior, holes))
                            except Exception:
                                continue
                    else:
                        add_geom(props, shape(gi))
                except Exception:
                    continue

        if not geoms:
            return gpd.GeoDataFrame(columns=list(records[0].keys()) if records else [], geometry=gpd.GeoSeries([], crs=crs_val))
        return gpd.GeoDataFrame(records, geometry=gpd.GeoSeries(geoms, crs=crs_val))

    # GPKG / GeoJSON : on laisse geopandas gérer
    lower_path = str(path).lower()
    if lower_path.endswith((".gpkg", ".geojson", ".json", ".geojsonl")):
        return gpd.read_file(path)

    # Shapefile et assimilés : lecteur manuel robuste
    return _read_with_fiona_manual(path)


def import_shapefile_to_postgis(shp_path: str, table_name: str, schema: str = "gracethd"):
    """
    Lit un SHP, normalise, et pousse en PostGIS dans gracethd.
    - Réutilise la géométrie existante (renommée en 'geom')
    - dtype explicite pour 'geom' (SRID 2154)
    - Quote le nom de table (contient un point)
    """
    gdf = gpd.read_file(shp_path)
    gdf = prepare_gdf_for_postgis(gdf)

    qname = sa_quoted_name(table_name, True)  # ex: "2025-10_t_noeud.shp"

    with engine.begin() as conn:
        conn.execute(text("SET LOCAL search_path TO gracethd, public"))
        # if_exists='replace' suffit, mais on ajoute un DROP défensif pour les reliquats
        conn.execute(text(f'DROP TABLE IF EXISTS "{schema}"."{table_name}" CASCADE'))

        gdf.to_postgis(
            name=qname,
            con=conn,
            schema=schema,
            if_exists="fail",        # après le DROP, la création doit passer
            index=False,
            dtype={"geom": Geometry("GEOMETRY", srid=DEFAULT_SRID)}
        )

@app.route('/upload', methods=['POST'])
def upload_files():
    try:
        export_date = request.form.get('export_date')
        files = request.files.getlist('file')

        upload_dir = os.path.join(os.getcwd(), 'uploads', export_date)
        os.makedirs(upload_dir, exist_ok=True)

        saved_files = []
        for f in files:
            fname = os.path.basename(f.filename)
            fpath = os.path.normpath(os.path.join(upload_dir, fname))
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            f.save(fpath)
            saved_files.append(fpath)

        # Regroupe par stem
        stems = {}
        for p in saved_files:
            stem, ext = os.path.splitext(os.path.basename(p))
            stems.setdefault(stem, set()).add(ext.lower())
        shapefile_stems = {s for s, exts in stems.items() if '.shp' in exts}

        # 1) SHP -> PostGIS EPSG:2154, nom "<date>_<file>.shp"
        for stem in sorted(shapefile_stems):
            shp_path = os.path.join(upload_dir, f"{stem}.shp")
            if not os.path.exists(shp_path):
                continue
            table_name = f"{export_date}_{stem}.shp"
            import_shapefile_to_postgis(shp_path, table_name, schema="gracethd")
            db.session.add(Export(export_date=export_date, file_name=f"{stem}.shp", table_name=table_name))

        # 2) Le reste (CSV/XLSX/JSON/DBF...) en tabulaire, en sautant les sidecars des SHP
        for p in saved_files:
            fname = os.path.basename(p)
            stem, ext = os.path.splitext(fname)
            ext = ext.lower()

            if stem in shapefile_stems and (ext == '.shp' or ext in SIDE_CAR_EXTS):
                continue  # sidecars ignorés (déjà pris en charge via SHP)

            table_name = f"{export_date}_{fname}"
            df = read_file_generic(p)  # ta fonction existante
            if df.empty:
                df = pd.DataFrame(columns=df.columns)
            df.columns = df.columns.astype(str)

            qname = sa_quoted_name(table_name, True)
            df.to_sql(qname, engine, schema='gracethd', index=False, if_exists='replace')
            db.session.add(Export(export_date=export_date, file_name=fname, table_name=table_name))

        db.session.commit()
        return jsonify({"message": "Fichiers importés avec succès"}), 200

    except Exception as e:
        db.session.rollback()
        logging.exception("Erreur serveur")
        return jsonify({"message": f"Erreur serveur: {e}"}), 500


if __name__ == '__main__':
    create_tables()  # Assurer que les tables sont créées avant de lancer l'application
    app.run(debug=True)


@app.route('/arborescence_livrable', methods=['POST'])
def arborescence_livrable():
    try:
        # Récupération de la date d'export
        export_date = request.form.get('export_date')
        logging.debug(f"Export date received: {export_date}")

        if not export_date:
            return "Erreur: Date d'export non spécifiée", 400

        # Rechercher les exports dans la base pour la date donnée
        exports = Export.query.filter(Export.export_date == export_date).all()
        if not exports:
            logging.warning(f"No exports found for date: {export_date}")
            return f"Aucun export trouvé pour la date {export_date}", 404

        # Normalisation des noms de fichiers pour éviter les problèmes de casse et de chemins
        fichiers_disponibles = {os.path.basename(e.file_name).lower(): e for e in exports}

        # Liste des fichiers à vérifier (noms en minuscule pour la comparaison)
        fichiers_a_verifier = [
            "t_adresse.dbf", "t_adresse.shp", "t_adresse.shx", "t_baie.csv",
            "t_cab_cond.csv", "t_cable.csv", "t_cableline.dbf", "t_cableline.shp",
            "t_cableline.shx", "t_cheminement.dbf", "t_cheminement.shp", "t_cheminement.shx",
            "t_cond_chem.csv", "t_conduite.csv", "t_docobj.csv", "t_document.csv",
            "t_ebp.csv", "t_empreinte.dbf", "t_empreinte.shp", "t_empreinte.shx",
            "t_equipement.csv", "t_fibre.csv", "t_love.csv", "t_ltech.csv",
            "t_masque.csv", "t_noeud.dbf", "t_noeud.shp", "t_noeud.shx",
            "t_organisme.csv", "t_position.csv", "t_ptech.csv", "t_reference.csv",
            "t_ropt.csv", "t_siteemission.csv", "t_sitetech.csv", "t_suf.csv",
            "t_tiroir.csv", "t_zdep.dbf", "t_zdep.shp", "t_zdep.shx",
            "t_znro.dbf", "t_znro.shp", "t_znro.shx", "t_zpbo.dbf", "t_zpbo.shp",
            "t_zpbo.shx", "t_zsro.dbf", "t_zsro.shp", "t_zsro.shx"
        ]

        # Création du tableau de résultats
        resultats = []
        for fichier in fichiers_a_verifier:
            fichier_lower = fichier.lower()
            present = fichier_lower in fichiers_disponibles
            resultats.append({
                "file_name": fichier,
                "status": "OK" if present else "Non trouvé"
            })

        # Retourner les résultats dans le template
        return render_template('arborescence_livrable.html', export_date=export_date, resultats=resultats)

    except Exception as e:
        logging.error(f"Error in arborescence_livrable: {str(e)}")
        return "Erreur lors de la génération de l'arborescence livrable.", 500

    
@app.route('/presence_champ_csv', methods=['POST'])
def presence_champ_csv():
    try:
        # Récupération de la date d'export
        export_date = request.form.get('export_date')
        logging.debug(f"Export date received: {export_date}")

        if not export_date:
            return "Erreur: Date d'export non spécifiée", 400

        # Liste des champs attendus pour chaque fichier CSV
        champs_attendus = {
        "t_baie.csv": ["ba_code", "ba_codeext", "ba_etiquet", "ba_lt_code", "ba_prop", "ba_gest", "ba_user", "ba_proptyp", "ba_statut", "ba_etat", "ba_rf_code", "ba_type", "ba_nb_u", "ba_haut", "ba_larg", "ba_prof", "ba_comment", "ba_creadat", "ba_majdate", "ba_majsrc", "ba_abddate", "ba_abdsrc"],
        "t_cable.csv": ["cb_avct", "cb_capafo", "cb_code", "cb_creadat", "cb_diam", "cb_etat", "cb_etiquet", "cb_fo_disp", "cb_fo_util", "cb_gest", "cb_lgreel", "cb_modulo", "cb_nd1", "cb_nd2", "cb_prop", "cb_proptyp", "cb_r1_code", "cb_r2_code", "cb_rf_code", "cb_statut", "cb_tech", "cb_typelog", "cb_typephy"],
        "t_cab_cond.csv": ["cc_cb_code", "cc_cd_code", "cc_creadat", "cc_majdate", "cc_majsrc", "cc_abddate", "cc_abdsrc"],
        "t_cassette.csv": ["cs_code", "cs_nb_pas", "cs_bp_code", "cs_num", "cs_type", "cs_face", "cs_rf_code", "cs_comment", "cs_creadat", "cs_majdate", "cs_majsrc", "cs_abddate", "cs_abdsrc"],
        "t_cheminement.csv": ["CM_CODE", "CM_CODEEXT", "CM_NDCODE1", "CM_NDCODE2", "CM_CM1", "CM_CM2", "CM_R1_CODE", "CM_R2_CODE", "CM_R3_CODE", "CM_R4_CODE", "CM_VOIE", "CM_GEST_DO", "CM_PROP_DO", "CM_STATUT", "CM_ETAT", "CM_DATCONS", "CM_DATEMES", "CM_AVCT", "CM_TYPELOG", "CM_TYP_IMP", "CM_NATURE", "CM_COMPO", "CM_CDDISPO", "CM_FO_UTIL", "CM_MOD_POS", "CM_PASSAGE", "CM_REVET", "CM_REMBLAI", "CM_CHARGE", "CM_LARG", "CM_FILDTEC", "CM_MUT_ORG", "CM_LONG", "CM_LGREEL", "CM_COMMENT", "CM_DTCLASS", "CM_GEOLQLT", "CM_GEOLMOD", "CM_GEOLSRC", "CM_CREADAT", "CM_MAJDATE", "CM_MAJSRC", "CM_ABDDATE", "CM_ABDSRC"],
        "t_conduite.csv": ["cd_code", "cd_codeext", "cd_etiquet", "cd_cd_code", "cd_r1_code", "cd_r2_code", "cd_r3_code", "cd_r4_code", "cd_prop", "cd_gest", "cd_user", "cd_proptyp", "cd_statut", "cd_etat", "cd_dateaig", "cd_dateman", "cd_datemes", "cd_avct", "cd_type", "cd_dia_int", "cd_dia_ext", "cd_color", "cd_long", "cd_nbcable", "cd_occup", "cd_comment", "cd_creadat", "cd_majdate", "cd_majsrc", "cd_abddate", "cd_abdsrc"],
        "t_cond_chem.csv": ["dm_cd_code", "dm_cm_code", "dm_creadat", "dm_majdate", "dm_majsrc", "dm_abddate", "dm_abdsrc"],
        "t_docobj.csv": ["od_id", "od_do_code", "od_tbltype", "od_codeobj", "od_creadat", "od_majdate", "od_majsrc", "od_abddate", "od_abdsrc"],
        "t_document.csv": ["do_code", "do_ref", "do_reftier", "do_r1_code", "do_r2_code", "do_r3_code", "do_r4_code", "do_type", "do_indice", "do_date", "do_classe", "do_url1", "do_url2", "do_comment", "do_creadat", "do_majdate", "do_majsrc", "do_abddate", "do_abdsrc"],
        "t_equipement.csv": ["eq_code", "eq_codeext", "eq_etiquet", "eq_ba_code", "eq_prop", "eq_rf_code", "eq_dateins", "eq_datemes", "eq_comment", "eq_creadat", "eq_majdate", "eq_majsrc", "eq_abddate", "eq_abdsrc"],
        "t_fibre.csv": ["fo_code", "fo_code_ext", "fo_cb_code", "fo_nincab", "fo_numtub", "fo_nintub", "fo_type", "fo_etat", "fo_color", "fo_reper", "fo_proptyp", "fo_comment", "fo_creadat", "fo_majdate", "fo_majsrc", "fo_abddate", "fo_abdsrc"],
        "t_love.csv": ["lv_id", "lv_cb_code", "lv_nd_code", "lv_long", "lv_creadat", "lv_majdate", "lv_majsrc", "lv_abddate", "lv_abdsrc"],
        "t_ltech.csv": "Error: 'ascii' codec can't decode byte 0xc3 in position 13902",
        "t_masque.csv": ["mq_id", "mq_nd_code", "mq_face", "mq_col", "mq_ligne", "mq_cd_code", "mq_qualinf", "mq_comment", "mq_creadat", "mq_majdate", "mq_majsrc", "mq_abddate", "mq_abdsrc"],
        "t_organisme.csv": ["or_code", "or_nom", "or_siren", "or_type", "or_activ", "or_l331", "or_siret", "or_nometab", "or_ad_code", "or_nomvoie", "or_numero", "or_rep", "or_local", "or_postal", "or_commune", "or_telfixe", "or_mail", "or_comment", "or_creadat", "or_majdate", "or_majsrc", "or_abddate", "or_abdsrc"],
        "t_position.csv": ["ps_code", "ps_numero", "ps_1", "ps_2", "ps_cs_code", "ps_ti_code", "ps_type", "ps_fonct", "ps_etat", "ps_preaff", "ps_comment", "ps_creadat", "ps_majdate", "ps_majsrc", "ps_abddate", "ps_abdsrc"],
        "t_reference.csv": ["rf_code", "rf_type", "rf_fabric", "rf_design", "rf_etat", "rf_comment", "rf_creadat", "rf_majdate", "rf_majsrc", "rf_abddate", "rf_abdsrc"],
        "t_ropt.csv": ["rt_id", "rt_code", "rt_code_ext", "rt_fo_code", "rt_fo_ordr", "rt_comment", "rt_creadat", "rt_majdate", "rt_majsrc", "rt_abddate", "rt_abdsrc"],
        "t_siteemission.csv": ["se_code", "se_nd_code", "se_anfr", "se_prop", "se_gest", "se_user", "se_proptyp", "se_statut", "se_etat", "se_occp", "se_dateins", "se_datemes", "se_type", "se_haut", "se_ad_code", "se_comment", "se_creadat", "se_majdate", "se_majsrc", "se_abddate", "se_abdsrc"],
        "t_suf.csv": ["sf_code", "sf_nd_code", "sf_ad_code", "sf_zp_code", "sf_escal", "sf_etage", "sf_oper", "sf_type", "sf_prop", "sf_resid", "sf_local", "sf_racco", "sf_comment", "sf_creadat", "sf_majdate", "sf_majsrc", "sf_abddate", "sf_abdsrc"],
        "t_tiroir.csv": ["ti_code", "ti_codeext", "ti_etiquet", "ti_ba_code", "ti_prop", "ti_etat", "ti_type", "ti_rf_code", "ti_taille", "ti_placemt", "ti_localis", "ti_comment", "ti_creadat", "ti_majdate", "ti_majsrc", "ti_abddate", "ti_abdsrc"],
        "t_ebp.csv": ["bp_avct", "bp_code", "bp_codeext", "bp_creadat", "bp_etiquet", "bp_gest", "bp_prop", "bp_proptyp", "bp_rf_code", "bp_statut", "bp_typelog", "bp_typephy"],
        "t_sitetech.csv": ["st_avct", "st_code", "st_codeext", "st_creadat", "st_dateins", "st_gest", "st_nblines", "st_nd_code", "st_nom", "st_prop", "st_proptyp", "st_statut", "st_typelog", "st_typephy"],
        "t_ltech.csv":["lt_code", "lt_codeext", "lt_etiquet", "lt_st_code", "lt_prop", "lt_gest", "lt_user", "lt_proptyp", "lt_statut", "lt_etat", "lt_dateins", "lt_datemes", "lt_local", "lt_elec", "lt_clim", "lt_occp", "lt_idmajic", "lt_comment", "lt_creadat", "lt_majdate", "lt_majsrc", "lt_abddate", "lt_abdsrc"]
        
    }
        # Recherche des fichiers pour la date donnée
        exports = Export.query.filter(Export.export_date == export_date).all()
        if not exports:
            logging.warning(f"No exports found for date: {export_date}")
            return f"Aucun export trouvé pour la date {export_date}", 404

        # Normalisation des noms de fichiers dans la base
        fichiers_disponibles = {os.path.basename(e.file_name).lower(): e for e in exports}

        resultats = []

        for fichier, champs in champs_attendus.items():
            fichier_lower = fichier.lower()
            export = fichiers_disponibles.get(fichier_lower)

            if export:
                try:
                    # Charger le fichier depuis la base
                    table_name = export.table_name
                    logging.debug(f"Checking table: {table_name} for file: {fichier}")
                    df = pd.read_sql(f"SELECT * FROM \"{table_name}\"", engine)

                    # Normaliser les noms de colonnes à la casse insensible
                    df.columns = df.columns.str.lower()
                    champs_normalises = [col.lower() for col in champs]

                    # Vérifier si les colonnes attendues sont présentes
                    colonnes_manquantes = [col for col in champs_normalises if col not in df.columns]
                    if colonnes_manquantes:
                        resultats.append({
                            "file_name": fichier,
                            "status": f"Colonnes manquantes: {', '.join(colonnes_manquantes)}"
                        })
                    else:
                        resultats.append({"file_name": fichier, "status": "OK"})
                except Exception as e:
                    logging.error(f"Error processing table {table_name} for file {fichier}: {str(e)}")
                    resultats.append({
                        "file_name": fichier,
                        "status": f"Erreur lors du traitement: {str(e)}"
                    })
            else:
                resultats.append({"file_name": fichier, "status": "Fichier non trouvé"})

        # Rendre la page HTML avec les résultats
        return render_template('presence_champ_csv.html', export_date=export_date, resultats=resultats)

    except Exception as e:
        logging.error(f"Erreur dans presence_champ_csv: {str(e)}")
        return "Erreur lors de la vérification des fichiers CSV.", 500


@app.route('/analyze_bpe', methods=['POST'])
def analyze_bpe():
    try:
        logging.info("Requête reçue pour l'analyse des BPE")

        # Vérifiez que la requête contient un JSON valide
        if not request.is_json:
            logging.error("Requête invalide : JSON attendu")
            return jsonify({"error": "Requête invalide, JSON attendu"}), 400

        # Récupérez la date d'export
        data = request.get_json()
        export_date = data.get('export_date')
        if not export_date:
            logging.error("Date d'export non spécifiée")
            return jsonify({"error": "Date d'export non spécifiée"}), 400

        logging.info(f"Date d'export reçue : {export_date}")

        # Rechercher la table correspondant au fichier t_ebp
        inspector = inspect(engine)
        table_name = None
        for table in inspector.get_table_names():
            if table.startswith(f"{export_date}_t_ebp"):
                table_name = table
                break

        if not table_name:
            logging.error(f"Table pour t_ebp introuvable pour l'export {export_date}")
            return jsonify({"error": f"Table pour t_ebp introuvable pour l'export {export_date}"}), 404

        logging.info(f"Nom complet de la table : {table_name}")

        # Charger les données de la table trouvée
        ebp_data = pd.read_sql(f"SELECT * FROM \"{table_name}\"", engine)

        # Analyse des données
        logging.info("Début de l'analyse des données")

        # Créez une liste pour stocker les résultats sous forme de dictionnaires
        results_list = []

        grouped_ebp = ebp_data.groupby('bp_rf_code')
        for bp_rf_code, group in grouped_ebp:
            nombre_territoire = len(group[group['bp_codeext'] == 'TERRITOIRE'])
            nombre_hors_territoire = len(group[(group['bp_codeext'] == 'H TERRITOIRE') | (group['bp_codeext'] == 'HORS TERRITOIRE')])
            nombre_indt = len(group[group['bp_codeext'] == 'INDT'])

            # Ajoutez un dictionnaire avec les résultats dans la liste
            results_list.append({
                'Type de BPE': bp_rf_code,
                'Nombre sur le perimetre de la DSP (Territoire)': nombre_territoire, 
                'Nombre en dehors du perimetre de la DSP (Hors Territoire)': nombre_hors_territoire, 
                'Nombre en dehors du perimetre de la DSP (INDT)': nombre_indt
            })

        # Créez le DataFrame à partir de la liste
        results = pd.DataFrame(results_list)

        # Vérifiez et créez le répertoire `static/exports` s'il n'existe pas
        export_dir = os.path.join('static', 'exports')
        if not os.path.exists(export_dir):
            os.makedirs(export_dir)
            logging.info(f"Répertoire créé : {export_dir}")

        # Sauvegarde des résultats
        csv_path = os.path.join(export_dir, f"BPEGraceTHD_{export_date}.csv")
        html_path = os.path.join(export_dir, f"BPEGraceTHD_{export_date}.html")
        results.to_csv(csv_path, index=False, sep=';')
        with open(html_path, 'w') as file:
            file.write(results.to_html(index=False))

        logging.info("Analyse terminée avec succès")
        return jsonify({
            "results": results.to_dict(orient='records'),
            "csv_path": f"/{csv_path}", 
            "html_path": f"/{html_path}"  
        })

    except Exception as e:
        logging.error(f"Erreur lors de l'analyse des BPE : {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/analyze_cable', methods=['POST'])
def analyze_cable():
    try:
        logging.info("Requête reçue pour l'analyse des câbles")

        # Récupérer la date d'export depuis la requête JSON
        if not request.is_json:
            logging.error("Requête invalide : JSON attendu")
            return jsonify({"error": "Requête invalide, JSON attendu"}), 400

        data = request.get_json()
        export_date = data.get('export_date')
        if not export_date:
            logging.error("Date d'export non spécifiée")
            return jsonify({"error": "Date d'export non spécifiée"}), 400

        logging.info(f"Date d'export reçue : {export_date}")

        # Rechercher la table correspondant au fichier t_cable
        inspector = inspect(engine)
        table_name = None
        for table in inspector.get_table_names():
            if table.startswith(f"{export_date}_t_cable"):
                table_name = table
                break

        if not table_name:
            logging.error(f"Table pour t_cable introuvable pour l'export {export_date}")
            return jsonify({"error": f"Table pour t_cable introuvable pour l'export {export_date}"}), 404

        logging.info(f"Nom complet de la table : {table_name}")

        # Charger les données de la table trouvée
        cable_data = pd.read_sql(f"SELECT * FROM \"{table_name}\"", engine)

        # Nettoyage et préparation des données
        cable_data['cb_lgreel'] = cable_data['cb_lgreel'].astype(str).str.replace(',', '.').astype(float)
        cable_data['cb_capafo'] = cable_data['cb_capafo'].fillna('Vide').replace('', 'Vide')

        # Analyse des données
        logging.info("Début de l'analyse des données")
        results_list = []

        grouped_cable = cable_data.groupby('cb_capafo')
        for cb_capafo, group in grouped_cable:
            nombre_total = len(group)
            somme_longueur = group['cb_lgreel'].sum()
            proprietaire = len(group[~group['cb_prop'].isna()])
            territoire = len(group[group['cb_codeext'] == 'TERRITOIRE'])
            hors_territoire = len(group[(group['cb_codeext'] == 'H TERRITOIRE') | (group['cb_codeext'] == 'HORS TERRITOIRE')])
            indt = len(group[group['cb_codeext'] == 'INDT'])

            results_list.append({
                'cb_capafo': cb_capafo,
                'Nombre_Total': nombre_total,
                'Somme_Longueur': somme_longueur,
                'Proprietaire': proprietaire,
                'Territoire': territoire,
                'Hors_Territoire': hors_territoire,
                'INDT': indt
            })

        # Créer un DataFrame à partir de la liste
        results = pd.DataFrame(results_list)

        # Vérifiez et créez le répertoire `static/exports` s'il n'existe pas
        export_dir = os.path.join('static', 'exports')
        if not os.path.exists(export_dir):
            os.makedirs(export_dir)
            logging.info(f"Répertoire créé : {export_dir}")

        # Sauvegarde des résultats
        csv_path = os.path.join(export_dir, f"CABLEGraceTHD_{export_date}.csv")
        html_path = os.path.join(export_dir, f"CABLEGraceTHD_{export_date}.html")
        results.to_csv(csv_path, index=False, sep=';')
        with open(html_path, 'w') as file:
            file.write(results.to_html(index=False))

        logging.info("Analyse des câbles terminée avec succès")

        # Retourner les résultats sous forme de JSON
        return jsonify({
            "results": results.to_dict(orient='records'),
            "csv_path": f"/{csv_path}",
            "html_path": f"/{html_path}"
        })

    except Exception as e:
        logging.error(f"Erreur lors de l'analyse des câbles : {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/analyze_chambre', methods=['POST'])
def analyze_chambre():
    try:
        logging.info("Requête reçue pour l'analyse des Chambres Techniques")

        # Vérifiez que la requête contient un JSON valide
        if not request.is_json:
            logging.error("Requête invalide : JSON attendu")
            return jsonify({"error": "Requête invalide, JSON attendu"}), 400

        # Récupérez la date d'export
        data = request.get_json()
        export_date = data.get('export_date')
        if not export_date:
            logging.error("Date d'export non spécifiée")
            return jsonify({"error": "Date d'export non spécifiée"}), 400

        logging.info(f"Date d'export reçue : {export_date}")

        # Vérifiez si la table correspondante existe
        inspector = inspect(engine)
        table_name = None
        for table in inspector.get_table_names():
            if table.startswith(f"{export_date}_t_ptech"):
                table_name = table
                break

        if not table_name:
            logging.error(f"Table pour t_ptech introuvable pour l'export {export_date}")
            return jsonify({"error": f"Table pour t_ptech introuvable pour l'export {export_date}"}), 404

        logging.info(f"Nom complet de la table : {table_name}")

        # Charger les données depuis la table
        ptech_data = pd.read_sql(f"SELECT * FROM \"{table_name}\"", engine)

        # Nettoyage et préparation des données
        ptech_data['pt_nature'] = ptech_data['pt_nature'].fillna('Vide')

        # Analyse des données
        logging.info("Début de l'analyse des données")
        results_list = []

        grouped_ptech = ptech_data.groupby('pt_nature')
        for pt_nature, group in grouped_ptech:
            nombre_dsp_irise = len(group[group['pt_gest'] == 'OR21'])
            nombre_location = len(group[group['pt_gest'] != 'OR21'])
            nombre_total = nombre_dsp_irise + nombre_location
            territoire = len(group[group['pt_codeext'] == 'TERRITOIRE'])
            hors_territoire = len(group[(group['pt_codeext'] == 'H TERRITOIRE') | (group['pt_codeext'] == 'HORS TERRITOIRE')])
            indt = len(group[group['pt_codeext'] == 'INDT'])

            results_list.append({
                'Nature de chambre': pt_nature,
                'Nombre de chambres DSP Irise': nombre_dsp_irise,
                'Nombre de chambres (location)': nombre_location,
                'Nombre total': nombre_total,
                'Territoire': territoire,
                'Hors Territoire': hors_territoire,
                'INDT': indt
            })

        # Créer un DataFrame avec les résultats
        results = pd.DataFrame(results_list)

        # Vérifiez et créez le répertoire `static/exports` s'il n'existe pas
        export_dir = os.path.join('static', 'exports')
        if not os.path.exists(export_dir):
            os.makedirs(export_dir)
            logging.info(f"Répertoire créé : {export_dir}")

        # Sauvegarde des résultats
        csv_path = os.path.join(export_dir, f"CHAMBREGraceTHD_{export_date}.csv")
        html_path = os.path.join(export_dir, f"CHAMBREGraceTHD_{export_date}.html")
        results.to_csv(csv_path, index=False, sep=';')
        with open(html_path, 'w') as file:
            file.write(results.to_html(index=False))

        logging.info("Analyse des chambres techniques terminée avec succès")

        # Retourner les résultats en JSON
        return jsonify({
            "results": results.to_dict(orient='records'),
            "csv_path": f"/{csv_path}",
            "html_path": f"/{html_path}"
        })

    except Exception as e:
        logging.error(f"Erreur lors de l'analyse des chambres techniques : {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/analyze_fourreaux', methods=['POST'])
def analyze_fourreaux():
    try:
        logging.info("Requête reçue pour l'analyse des fourreaux")

        if not request.is_json:
            return jsonify({"error": "Requête invalide, JSON attendu"}), 400

        export_date = request.get_json().get('export_date')
        if not export_date:
            return jsonify({"error": "Date d'export non spécifiée"}), 400

        # ---- helper local : charge CSV sinon DBF, puis normalise les colonnes
        def load_and_normalize(date_, base_name_):
            df = load_table_any(date_, base_name_)  # essaie .csv puis .dbf
            if df is None or df.empty:
                raise FileNotFoundError(
                    f"Aucun fichier trouvé pour {base_name_} à la date {date_} (.csv ou .dbf)"
                )
            df.columns = df.columns.str.strip().str.lower()
            return df

        # ---- chargement (plus d'inspector.has_table sur .csv)
        conduite_data = load_and_normalize(export_date, 't_conduite')
        cheminement_data = load_and_normalize(export_date, 't_cheminement')

        logging.info(f"Colonnes t_conduite : {conduite_data.columns.tolist()}")
        logging.info(f"Colonnes t_cheminement : {cheminement_data.columns.tolist()}")

        # ---- garde-fous colonnes attendues
        if 'cm_long' not in cheminement_data.columns:
            return jsonify({"error": "La colonne 'cm_long' est introuvable dans t_cheminement"}), 400
        if 'cm_codeext' not in cheminement_data.columns:
            return jsonify({"error": "La colonne 'cm_codeext' est introuvable dans t_cheminement"}), 400
        if 'cd_prop' not in conduite_data.columns:
            return jsonify({"error": "La colonne 'cd_prop' est introuvable dans t_conduite"}), 400

        # ---- normalisations de valeurs
        cheminement_data['cm_long'] = (
            cheminement_data['cm_long'].astype(str).str.replace(',', '.', regex=False)
        )
        cheminement_data['cm_long'] = pd.to_numeric(cheminement_data['cm_long'], errors='coerce').fillna(0)
        cheminement_data['cm_codeext'] = cheminement_data['cm_codeext'].astype(str).str.strip().str.upper()

        # ---- analyses
        results_conduite = pd.DataFrame({
            'Proprietaire': ['DSP Irise', 'Location', 'Total'],
            'Nombre de fourreaux': [
                (conduite_data['cd_prop'] == 'OR21').sum(),
                (conduite_data['cd_prop'] != 'OR21').sum(),
                len(conduite_data)
            ]
        })

        territoire = (cheminement_data['cm_codeext'] == 'TERRITOIRE')
        hors_territoire = ~territoire
        results_cheminement = pd.DataFrame({
            'Proprietaire': ['Territoire', 'Hors Territoire', 'Total'],
            'Nombre de tronçons': [territoire.sum(), hors_territoire.sum(), len(cheminement_data)],
            'Longueur GC en m': [
                cheminement_data.loc[territoire, 'cm_long'].sum(),
                cheminement_data.loc[hors_territoire, 'cm_long'].sum(),
                cheminement_data['cm_long'].sum()
            ]
        })

        # ---- sauvegardes
        export_dir = os.path.join('static', 'exports')
        os.makedirs(export_dir, exist_ok=True)
        csv_path = os.path.join(export_dir, f"FourreauxGraceTHD_{export_date}.csv")
        html_path = os.path.join(export_dir, f"FourreauxGraceTHD_{export_date}.html")

        with open(csv_path, 'w', newline='') as f:
            results_conduite.to_csv(f, index=False, sep=';')
            f.write('\n\n')
            results_cheminement.to_csv(f, index=False, sep=';', mode='a')

        with open(html_path, 'w') as f:
            f.write("<h3>Analyse des Fourreaux - Résultats Conduite</h3>")
            f.write(results_conduite.to_html(index=False))
            f.write("<h3>Analyse des Fourreaux - Résultats Cheminement</h3>")
            f.write(results_cheminement.to_html(index=False))

        logging.info("Analyse des fourreaux terminée avec succès")

        return jsonify({
            "results_conduite": results_conduite.to_dict(orient='records'),
            "results_cheminement": results_cheminement.to_dict(orient='records'),
            "csv_path": f"/{csv_path}",
            "html_path": f"/{html_path}"
        })

    except FileNotFoundError as e:
        # 404 seulement si ni CSV ni DBF
        logging.error(str(e))
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logging.error(f"Erreur lors de l'analyse des fourreaux : {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/upload_different_version', methods=['POST'])
def upload_different_version():
    try:
        # Récupération des dates d'export et des fichiers
        old_date = request.form.get('old_date')
        new_date = request.form.get('new_date')
        old_files = request.files.getlist('old_files')
        new_files = request.files.getlist('new_files')

        if not old_date or not new_date:
            logging.error("Dates d'exportation manquantes")
            return jsonify({"message": "Dates d'exportation manquantes"}), 400

        logging.info(f"Ancien export : {old_date}, Nombre de fichiers : {len(old_files)}")
        logging.info(f"Nouveau export : {new_date}, Nombre de fichiers : {len(new_files)}")

        # Sauvegarde et traitement des fichiers pour les deux exports
        for file_group, export_date in [(old_files, old_date), (new_files, new_date)]:
            upload_dir = os.path.normpath(os.path.join(os.getcwd(), 'uploads', export_date))
            os.makedirs(upload_dir, exist_ok=True)
            logging.info(f"Répertoire créé ou existant : {upload_dir}")

            for f in file_group:
                # Extraire le chemin relatif complet du fichier
                relative_path = os.path.normpath(f.filename)
                save_path = os.path.join(upload_dir, relative_path)

                # Créer les sous-dossiers nécessaires
                os.makedirs(os.path.dirname(save_path), exist_ok=True)

                try:
                    # Sauvegarder le fichier
                    f.save(save_path)
                    logging.info(f"Fichier sauvegardé avec succès : {save_path}")

                    # Lecture et traitement du fichier avec `read_file_generic`
                    try:
                        df = read_file_generic_with_ansi(save_path)
                    except ValueError as e:
                        logging.error(f"Erreur de lecture du fichier {save_path}: {str(e)}")
                        return jsonify({"message": f"Erreur de lecture du fichier {relative_path}: {str(e)}"}), 500

                    # Conversion explicite des colonnes texte en UTF-8
                    for col in df.columns:
                        if df[col].dtype == object:  # Vérifier si la colonne est de type texte
                            df[col] = df[col].apply(
                                lambda x: str(x).encode('utf-8', 'ignore').decode('utf-8') if isinstance(x, str) else x
                            )

                    # Définir le nom de la table en conservant l'extension
                    table_name = f"{export_date}_{os.path.basename(relative_path)}"

                    # Insertion dans PostgreSQL
                    df.columns = df.columns.astype(str)  # S'assurer que les colonnes sont des chaînes
                    df.to_sql(table_name, engine, schema='gracethd', index=False, if_exists='replace')

                    logging.info(f"Table {table_name} créée ou mise à jour dans la base de données.")

                    # Enregistrer l'information sur l'export dans la base de données
                    new_export = Export(export_date=export_date, file_name=relative_path, table_name=table_name)
                    db.session.add(new_export)

                except FileNotFoundError as e:
                    logging.error(f"Erreur lors de la sauvegarde du fichier {f.filename} : {str(e)}")
                    return jsonify({"message": f"Erreur lors de la sauvegarde du fichier {f.filename} : {str(e)}"}), 500
                except Exception as e:
                    logging.error(f"Erreur générale pour le fichier {f.filename} : {str(e)}")
                    return jsonify({"message": f"Erreur générale pour le fichier {f.filename} : {str(e)}"}), 500

        # Validation finale
        db.session.commit()
        logging.info("Tous les fichiers ont été importés avec succès.")
        return jsonify({"message": "Fichiers importés avec succès"}), 200

    except Exception as e:
        logging.error(f"Erreur serveur : {str(e)}")
        return jsonify({"message": f"Erreur serveur : {str(e)}"}), 500


def read_file_generic_with_ansi(file_path):
    """
    Essaye de lire un fichier quel que soit son format avec Pandas, y compris l'encodage ANSI.
    """
    possible_encodings = ['utf-8', 'utf-8-sig', 'ISO-8859-1', 'latin1', 'cp1252', 'ansi']
    encoding = detect_encoding(file_path)
    if encoding:
        possible_encodings.insert(0, encoding)  # Ajouter l'encodage détecté en premier

    for enc in possible_encodings:
        try:
            logging.info(f"Tentative de lecture du fichier {file_path} avec encodage {enc}")

            # Lecture des fichiers CSV
            if file_path.endswith('.csv'):
                sep = detect_separator(file_path, enc)
                return pd.read_csv(
                    file_path, 
                    encoding=enc, 
                    low_memory=False, 
                    on_bad_lines='skip', 
                    quoting=csv.QUOTE_NONE, 
                    sep=sep, 
                    escapechar='\\'
                )

            # Lecture des fichiers Excel
            elif file_path.endswith('.xlsx'):
                return pd.read_excel(file_path, engine='openpyxl')

            # Lecture des fichiers JSON
            elif file_path.endswith('.json'):
                with open(file_path, 'r', encoding=enc) as f:
                    data = json.load(f)
                return pd.json_normalize(data)

            # Lecture des fichiers DBF
            elif file_path.endswith('.dbf'):
                for dbf_enc in possible_encodings:
                    try:
                        table = DBF(file_path, encoding=dbf_enc)
                        return pd.DataFrame(iter(table))
                    except UnicodeDecodeError:
                        logging.warning(f"Erreur d'encodage pour {file_path} avec {dbf_enc}.")
                    except Exception as dbf_err:
                        logging.error(f"Erreur avec l'encodage {dbf_enc}: {str(dbf_err)}")
                raise ValueError(f"Erreur lors de la lecture du fichier {file_path}: Aucun encodage valide trouvé.")

            # Lecture des fichiers binaires ou non tabulaires
            else:
                with open(file_path, 'rb') as f:
                    content = f.read()
                    return pd.DataFrame({'file_name': [os.path.basename(file_path)], 'content': [base64.b64encode(content).decode('utf-8')]})
        
        except UnicodeDecodeError:
            logging.warning(f"Erreur d'encodage pour {file_path} avec {enc}.")
        except Exception as e:
            logging.error(f"Erreur avec l'encodage {enc}: {str(e)}")

    # Si aucun encodage ne fonctionne
    raise ValueError(f"Erreur lors de la lecture du fichier {file_path}: Aucun encodage valide trouvé.")


@app.route('/compare_ebp', methods=['POST'])
def compare_ebp():
    try:
        logging.info("Requête reçue pour comparer les EBP")

        # Lire les données JSON de la requête
        data = request.get_json()
        old_date = data.get('old_date')
        new_date = data.get('new_date')

        if not old_date or not new_date:
            logging.error("Les deux dates d'export doivent être spécifiées.")
            return jsonify({"error": "Les deux dates d'export doivent être spécifiées."}), 400

        logging.info(f"Dates d'export reçues : Ancien - {old_date}, Nouveau - {new_date}")

        # Rechercher les fichiers CSV dans la base
        old_export = Export.query.filter(Export.export_date == old_date, Export.file_name.ilike('%t_ebp%.csv')).first()
        new_export = Export.query.filter(Export.export_date == new_date, Export.file_name.ilike('%t_ebp%.csv')).first()

        if not old_export or not new_export:
            logging.error("Fichiers d'export non trouvés pour les dates fournies.")
            return jsonify({"error": "Fichiers d'export non trouvés pour les dates fournies."}), 404

        logging.info(f"Tables trouvées : {old_export.table_name}, {new_export.table_name}")

        # Charger les tables correspondantes
        old_table_name = old_export.table_name
        new_table_name = new_export.table_name

        try:
            old_df = pd.read_sql(f"SELECT * FROM \"{old_table_name}\"", engine)
            new_df = pd.read_sql(f"SELECT * FROM \"{new_table_name}\"", engine)
        except Exception as e:
            logging.error(f"Erreur lors du chargement des données SQL : {str(e)}")
            return jsonify({"error": f"Erreur lors du chargement des données : {str(e)}"}), 500

        # Normaliser les colonnes
        old_df.columns = old_df.columns.str.strip().str.lower()
        new_df.columns = new_df.columns.str.strip().str.lower()

        # Journalisation des colonnes disponibles
        logging.info(f"Colonnes dans l'ancien export : {old_df.columns.tolist()}")
        logging.info(f"Colonnes dans le nouvel export : {new_df.columns.tolist()}")

        # Journaliser les deux premières lignes des DataFrames
        logging.info("Aperçu des deux premières lignes de l'ancien export :")
        logging.info(f"\n{old_df[['bp_code']].head(2)}")

        logging.info("Aperçu des deux premières lignes du nouvel export :")
        logging.info(f"\n{new_df[['bp_code']].head(2)}")

        if 'bp_code' not in old_df.columns or 'bp_code' not in new_df.columns:
            logging.error("La colonne 'bp_code' est introuvable dans les exports.")
            return jsonify({"error": "La colonne 'bp_code' est introuvable dans les exports."}), 400

        # Normaliser les données
        def normalize_value(value):
            try:
                if isinstance(value, str):
                    value = value.replace(",", ".").strip()
                if float(value) == int(float(value)):
                    return int(float(value))
                return float(value)
            except (ValueError, TypeError):
                return value

        old_df['bp_code'] = old_df['bp_code'].apply(normalize_value).astype(str).str.strip()
        new_df['bp_code'] = new_df['bp_code'].apply(normalize_value).astype(str).str.strip()

        # Vérification des valeurs de bp_code
        logging.info(f"Exemples de bp_code dans l'ancien export : {old_df['bp_code'].head().tolist()}")
        logging.info(f"Exemples de bp_code dans le nouvel export : {new_df['bp_code'].head().tolist()}")

        # Identifier les bp_code communs
        common_ids = set(old_df['bp_code']).intersection(set(new_df['bp_code']))
        logging.info(f"Nombre de bp_code communs : {len(common_ids)}")

        # Comparer les colonnes pour les bp_code communs
        colonnes_interessantes = ['bp_prop', 'bp_codeext', 'bp_rf_code']
        diffs = []
        for oid in common_ids:
            row_old = old_df.loc[old_df['bp_code'] == oid, colonnes_interessantes].iloc[0]
            row_new = new_df.loc[new_df['bp_code'] == oid, colonnes_interessantes].iloc[0]

            for col in colonnes_interessantes:
                val_old = normalize_value(row_old[col])
                val_new = normalize_value(row_new[col])

                if pd.isna(val_old) and pd.isna(val_new):
                    continue

                if val_old != val_new:
                    diffs.append({
                        'bp_code': oid,
                        'Attribut': col,
                        'Valeur N-1': val_old,
                        'Valeur N': val_new
                    })

        # Identifier les ajouts et suppressions
        ajouts = [{'bp_code': code, 'Type': 'Ajout'} for code in set(new_df['bp_code']) - set(old_df['bp_code'])]
        suppressions = [{'bp_code': code, 'Type': 'Suppression'} for code in set(old_df['bp_code']) - set(new_df['bp_code'])]

        # Fusionner toutes les informations
        all_results = diffs + ajouts + suppressions

        # Chemins de sauvegarde
        export_dir = os.path.join('static', 'exports')
        os.makedirs(export_dir, exist_ok=True)

        csv_path = os.path.join(export_dir, f"CompareEBP_{old_date}_vs_{new_date}.csv")
        html_path = os.path.join(export_dir, f"CompareEBP_{old_date}_vs_{new_date}.html")

        pd.DataFrame(all_results).to_csv(csv_path, index=False, sep=';')

        with open(html_path, 'w') as file:
            file.write("<h3>Résultats de la Comparaison</h3>")
            pd.DataFrame(all_results).to_html(file, index=False)

        logging.info("Analyse terminée avec succès")

        return render_template(
            'compare_result_ebp.html',
            results=all_results,
            csv_path=f"/{csv_path}",
            html_path=f"/{html_path}"
        )
    except Exception as e:
        logging.error(f"Erreur lors de la comparaison des EBP : {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/compare_cable', methods=['POST'])
def compare_cable():
    try:
        logging.info("Requête reçue pour comparer les câbles")

        # Lire les données JSON de la requête
        data = request.get_json()
        old_date = data.get('old_date')
        new_date = data.get('new_date')

        if not old_date or not new_date:
            return jsonify({"error": "Les deux dates d'export doivent être spécifiées."}), 400

        logging.info(f"Dates d'export reçues : Ancien - {old_date}, Nouveau - {new_date}")

        # Rechercher les fichiers CSV dans la base
        old_export = Export.query.filter(Export.export_date == old_date, Export.file_name.ilike('%t_cable.csv')).first()
        new_export = Export.query.filter(Export.export_date == new_date, Export.file_name.ilike('%t_cable.csv')).first()

        if not old_export or not new_export:
            return jsonify({"error": "Fichiers d'export non trouvés pour les dates fournies."}), 404

        # Charger les tables correspondantes
        old_table_name = old_export.table_name
        new_table_name = new_export.table_name

        old_df = pd.read_sql(f"SELECT * FROM \"{old_table_name}\"", engine)
        new_df = pd.read_sql(f"SELECT * FROM \"{new_table_name}\"", engine)

        # Normaliser les colonnes
        old_df.columns = old_df.columns.str.lower()
        new_df.columns = new_df.columns.str.lower()

        if 'cb_code' not in old_df.columns or 'cb_code' not in new_df.columns:
            return jsonify({"error": "'cb_code' est absent dans l'un des exports."}), 400

        # Identifier les différences
        diffs = []
        for oid in set(old_df['cb_code']).intersection(set(new_df['cb_code'])):
            row_old = old_df.loc[old_df['cb_code'] == oid].iloc[0]
            row_new = new_df.loc[new_df['cb_code'] == oid].iloc[0]

            cb_lgreel_old = float(str(row_old.get('cb_lgreel', 0)).replace(',', '.'))
            cb_lgreel_new = float(str(row_new.get('cb_lgreel', 0)).replace(',', '.'))

            # Différence si cb_lgreel change de plus de 1
            if abs(cb_lgreel_old - cb_lgreel_new) > 1:
                diffs.append({
                    'cb_code': oid,
                    'Type': 'Modification',
                    'Attribut': 'cb_lgreel',
                    'Valeur N-1': cb_lgreel_old,
                    'Valeur N': cb_lgreel_new
                })

        # Identifier les ajouts et suppressions
        ajouts = [{'cb_code': code, 'Type': 'Ajout', 'Attribut': None, 'Valeur N-1': None, 'Valeur N': None} for code in set(new_df['cb_code']) - set(old_df['cb_code'])]
        suppressions = [{'cb_code': code, 'Type': 'Suppression', 'Attribut': None, 'Valeur N-1': None, 'Valeur N': None} for code in set(old_df['cb_code']) - set(new_df['cb_code'])]

        # Fusionner toutes les informations
        all_results = diffs + ajouts + suppressions

        # Chemins de sauvegarde
        export_dir = os.path.join('static', 'exports')
        os.makedirs(export_dir, exist_ok=True)

        csv_path = os.path.join(export_dir, f"CompareCables_{old_date}_vs_{new_date}.csv")
        html_path = os.path.join(export_dir, f"CompareCables_{old_date}_vs_{new_date}.html")

        # Sauvegarde CSV
        pd.DataFrame(all_results).to_csv(csv_path, index=False, sep=';')

        # Sauvegarde HTML
        with open(html_path, 'w') as file:
            file.write("<h3>Résultats de la Comparaison</h3>")
            pd.DataFrame(all_results).to_html(file, index=False)

        # Retourner les résultats au client
        return render_template(
            'compare_result_cable.html',
            results=all_results,
            csv_path=f"/{csv_path}",
            html_path=f"/{html_path}"
        )
    except Exception as e:
        logging.error(f"Erreur lors de la comparaison des câbles : {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/compare_PointTechnique', methods=['POST'])
def compare_PointTechnique():
    try:
        logging.info("Requête reçue pour comparer les Points Techniques")

        # Lire les données JSON de la requête
        data = request.get_json()
        logging.info(f"Données reçues : {data}")
        old_date = data.get('old_date')
        new_date = data.get('new_date')

        if not old_date or not new_date:
            logging.error("Les dates ne sont pas fournies dans la requête.")
            return jsonify({"error": "Les deux dates d'export doivent être spécifiées."}), 400

        logging.info(f"Dates d'export reçues : Ancien - {old_date}, Nouveau - {new_date}")

        # Rechercher les fichiers CSV dans la base
        old_export = Export.query.filter(Export.export_date == old_date, Export.file_name.ilike('%t_ptech.csv')).first()
        new_export = Export.query.filter(Export.export_date == new_date, Export.file_name.ilike('%t_ptech.csv')).first()

        if not old_export or not new_export:
            logging.error("Fichiers CSV introuvables dans la base de données.")
            return jsonify({"error": "Fichiers d'export non trouvés pour les dates fournies."}), 404

        logging.info(f"Tables trouvées : {old_export.table_name}, {new_export.table_name}")

        # Charger les tables correspondantes
        old_table_name = old_export.table_name
        new_table_name = new_export.table_name

        old_df = pd.read_sql(f"SELECT * FROM \"{old_table_name}\"", engine)
        new_df = pd.read_sql(f"SELECT * FROM \"{new_table_name}\"", engine)

        logging.info(f"Ancien export : {len(old_df)} lignes, Nouveau export : {len(new_df)} lignes")

        # Normaliser les colonnes
        old_df.columns = old_df.columns.str.lower()
        new_df.columns = new_df.columns.str.lower()

        if 'pt_code' not in old_df.columns or 'pt_code' not in new_df.columns:
            logging.error("'pt_code' est absent dans les colonnes des exports.")
            return jsonify({"error": "'pt_code' est absent dans l'un des exports."}), 400

        # Identifier les pt_code communs
        common_ids = set(old_df['pt_code']).intersection(set(new_df['pt_code']))
        logging.info(f"Nombre de pt_code communs : {len(common_ids)}")

        # Comparer les colonnes pour les pt_code communs
        colonnes_interessantes = ['pt_gest', 'pt_codeext', 'pt_nature']

        def normalize_value(value):
            try:
                if isinstance(value, str):
                    value = value.replace(",", ".")
                if float(value) == int(float(value)):
                    return int(float(value))
                return float(value)
            except (ValueError, TypeError):
                return value

        diffs = []
        for oid in common_ids:
            row_old = old_df.loc[old_df['pt_code'] == oid, colonnes_interessantes].iloc[0]
            row_new = new_df.loc[new_df['pt_code'] == oid, colonnes_interessantes].iloc[0]

            for col in colonnes_interessantes:
                val_old = normalize_value(row_old[col])
                val_new = normalize_value(row_new[col])

                # Vérifier si les deux valeurs sont NaN
                if pd.isna(val_old) and pd.isna(val_new):
                    continue

                if val_old != val_new:
                    diffs.append({
                        'pt_code': oid,
                        'Attribut': col,
                        'Valeur N-1': val_old,
                        'Valeur N': val_new
                    })

        # Identifier les ajouts et suppressions
        ajouts = [{'pt_code': code, 'Type': 'Ajout'} for code in set(new_df['pt_code']) - set(old_df['pt_code'])]
        suppressions = [{'pt_code': code, 'Type': 'Suppression'} for code in set(old_df['pt_code']) - set(new_df['pt_code'])]

        # Fusionner toutes les informations
        all_results = diffs + ajouts + suppressions

        logging.info(f"Résultats totaux : {len(all_results)} entrées")

        # Chemins de sauvegarde
        export_dir = os.path.join('static', 'exports')
        os.makedirs(export_dir, exist_ok=True)

        csv_path = os.path.join(export_dir, f"ComparePointTechnique_{old_date}_vs_{new_date}.csv")
        html_path = os.path.join(export_dir, f"ComparePointTechnique_{old_date}_vs_{new_date}.html")

        # Sauvegarde CSV
        pd.DataFrame(all_results).to_csv(csv_path, index=False, sep=';')

        # Sauvegarde HTML
        with open(html_path, 'w') as file:
            file.write("<h3>Résultats de la Comparaison</h3>")
            pd.DataFrame(all_results).to_html(file, index=False)

        logging.info("Analyse terminée avec succès")

        # Retourner les résultats au client
        return render_template(
            'compare_result_point_technique.html',
            results=all_results,
            csv_path=f"/{csv_path}",
            html_path=f"/{html_path}"
        )
    except Exception as e:
        logging.error(f"Erreur lors de la comparaison des points techniques : {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/compare_cheminement', methods=['POST'])
def compare_cheminement():
    try:
        logging.info("Requête reçue pour comparer les Cheminements")

        data = request.get_json()
        old_date = data.get('old_date')
        new_date = data.get('new_date')
        if not old_date or not new_date:
            return jsonify({"error": "Les deux dates d'export doivent être spécifiées."}), 400

        # --- Chargement avec fallback CSV/DBF
        old_df = load_table_any(old_date, 't_cheminement')   # essaie .csv, sinon .dbf
        new_df = load_table_any(new_date, 't_cheminement')   # essaie .csv, sinon .dbf

        # --- Normalisation colonnes
        old_df.columns = old_df.columns.str.strip().str.lower()
        new_df.columns = new_df.columns.str.strip().str.lower()

        # --- Garde-fous colonnes attendues
        needed = ['cm_code', 'cm_prop_do', 'cm_codeext', 'cm_long']
        for col in needed:
            if col not in old_df.columns or col not in new_df.columns:
                return jsonify({"error": f"La colonne '{col}' est absente dans l'un des exports."}), 400

        # --- Normalisation valeurs
        def normalize_value(value):
            try:
                if isinstance(value, str):
                    # nettoie éventuels guillemets/espaces et virgules décimales
                    v = value.strip().strip('"').strip("'")
                    v = v.replace(",", ".")
                    # tente conversion numérique si possible
                    if v != "":
                        f = float(v)
                        return int(f) if f.is_integer() else f
                    return ""
                return value
            except Exception:
                return value

        old_df['cm_code'] = old_df['cm_code'].astype(str).str.strip()
        new_df['cm_code'] = new_df['cm_code'].astype(str).str.strip()

        # Colonnes à comparer (seuil de 1 m pour cm_long)
        colonnes_interessantes = ['cm_prop_do', 'cm_codeext', 'cm_long']

        # Comparaison
        common_ids = set(old_df['cm_code']).intersection(set(new_df['cm_code']))
        diffs = []
        for oid in common_ids:
            row_old = old_df.loc[old_df['cm_code'] == oid, colonnes_interessantes].iloc[0]
            row_new = new_df.loc[new_df['cm_code'] == oid, colonnes_interessantes].iloc[0]

            for col in colonnes_interessantes:
                val_old = normalize_value(row_old[col])
                val_new = normalize_value(row_new[col])

                if pd.isna(val_old) and pd.isna(val_new):
                    continue

                if col == 'cm_long' and isinstance(val_old, (int, float)) and isinstance(val_new, (int, float)):
                    if abs(val_old - val_new) > 1:
                        diffs.append({
                            'cm_code': oid, 'Type': 'Modification',
                            'Attribut': col, 'Valeur N-1': val_old, 'Valeur N': val_new
                        })
                elif col != 'cm_long' and val_old != val_new:
                    diffs.append({
                        'cm_code': oid, 'Type': 'Modification',
                        'Attribut': col, 'Valeur N-1': val_old, 'Valeur N': val_new
                    })

        # Ajouts / suppressions
        ajouts = [{'cm_code': normalize_value(code), 'Type': 'Ajout'} for code in set(new_df['cm_code']) - set(old_df['cm_code'])]
        suppressions = [{'cm_code': normalize_value(code), 'Type': 'Suppression'} for code in set(old_df['cm_code']) - set(new_df['cm_code'])]

        # Sorties
        all_results = diffs + ajouts + suppressions

        export_dir = os.path.join('static', 'exports')
        os.makedirs(export_dir, exist_ok=True)
        csv_path = os.path.join(export_dir, f"CompareCheminement_{old_date}_vs_{new_date}.csv")
        html_path = os.path.join(export_dir, f"CompareCheminement_{old_date}_vs_{new_date}.html")

        pd.DataFrame(all_results).to_csv(csv_path, index=False, sep=';')
        with open(html_path, 'w') as f:
            f.write("<h3>Résultats de la Comparaison</h3>")
            pd.DataFrame(all_results).to_html(f, index=False)

        return render_template(
            'compare_result_cheminement.html',
            results=all_results,
            csv_path=f"/{csv_path}",
            html_path=f"/{html_path}"
        )
    except Exception as e:
        logging.error(f"Erreur compare_cheminement : {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/compare_site_technique', methods=['POST'])
def compare_site_technique():
    try:
        logging.info("Requête reçue pour comparer les Sites Techniques")

        # Lire les données JSON de la requête
        data = request.get_json()
        old_date = data.get('old_date')
        new_date = data.get('new_date')

        if not old_date or not new_date:
            logging.error("Les deux dates d'export doivent être spécifiées.")
            return jsonify({"error": "Les deux dates d'export doivent être spécifiées."}), 400

        logging.info(f"Dates d'export reçues : Ancien - {old_date}, Nouveau - {new_date}")

        # Rechercher les fichiers CSV dans la base
        old_export = Export.query.filter(Export.export_date == old_date, Export.file_name.ilike('%t_sitetech%.csv')).first()
        new_export = Export.query.filter(Export.export_date == new_date, Export.file_name.ilike('%t_sitetech%.csv')).first()

        if not old_export or not new_export:
            logging.error("Fichiers d'export non trouvés pour les dates fournies.")
            return jsonify({"error": "Fichiers d'export non trouvés pour les dates fournies."}), 404

        # Charger les tables correspondantes
        old_table_name = old_export.table_name
        new_table_name = new_export.table_name

        old_df = pd.read_sql(f"SELECT * FROM \"{old_table_name}\"", engine)
        new_df = pd.read_sql(f"SELECT * FROM \"{new_table_name}\"", engine)

        # Normaliser les colonnes
        old_df.columns = old_df.columns.str.strip().str.lower()
        new_df.columns = new_df.columns.str.strip().str.lower()

        if 'st_code' not in old_df.columns or 'st_code' not in new_df.columns:
            logging.error("La colonne 'st_code' est introuvable dans les exports.")
            return jsonify({"error": "La colonne 'st_code' est introuvable dans les exports."}), 400

        # Identifier les st_code communs
        common_ids = set(old_df['st_code']).intersection(set(new_df['st_code']))
        logging.info(f"Nombre de st_code communs : {len(common_ids)}")

        # Comparer les colonnes pour les st_code communs
        colonnes_interessantes = ['st_nom', 'st_prop']
        diffs = []
        for oid in common_ids:
            row_old = old_df.loc[old_df['st_code'] == oid, colonnes_interessantes].iloc[0]
            row_new = new_df.loc[new_df['st_code'] == oid, colonnes_interessantes].iloc[0]

            for col in colonnes_interessantes:
                val_old = row_old[col]
                val_new = row_new[col]

                if val_old != val_new:
                    diffs.append({
                        'st_code': oid,
                        'Attribut': col,
                        'Valeur N-1': val_old,
                        'Valeur N': val_new
                    })

        # Identifier les ajouts et suppressions
        ajouts = [{'st_code': code, 'Type': 'Ajout'} for code in set(new_df['st_code']) - set(old_df['st_code'])]
        suppressions = [{'st_code': code, 'Type': 'Suppression'} for code in set(old_df['st_code']) - set(new_df['st_code'])]

        # Fusionner toutes les informations
        all_results = diffs + ajouts + suppressions

        # Chemins de sauvegarde
        export_dir = os.path.join('static', 'exports')
        os.makedirs(export_dir, exist_ok=True)

        csv_path = os.path.join(export_dir, f"CompareSiteTech_{old_date}_vs_{new_date}.csv")
        html_path = os.path.join(export_dir, f"CompareSiteTech_{old_date}_vs_{new_date}.html")

        pd.DataFrame(all_results).to_csv(csv_path, index=False, sep=';')

        with open(html_path, 'w') as file:
            file.write("<h3>Résultats de la Comparaison</h3>")
            pd.DataFrame(all_results).to_html(file, index=False)

        # Retourner les résultats au client
        return render_template(
            'compare_result_site_technique.html',
            results=all_results,
            csv_path=f"/{csv_path}",
            html_path=f"/{html_path}"
        )
    except Exception as e:
        logging.error(f"Erreur lors de la comparaison des Sites Techniques : {str(e)}")
        return jsonify({"error": str(e)}), 500


#nouvelles fonctionnalités logiques terrains

@app.route('/analyze_t_baie', methods=['POST'])
def analyze_t_baie():
    try:
        #  Récupération de la date d'export depuis le JSON
        data = request.get_json()
        export_date = data.get('export_date')
        if not export_date:
            return jsonify({"error": "Date d'export non spécifiée"}), 400

        #  Construction des noms des tables
        table_t_baie = f"{export_date}_t_baie.csv"
        table_t_ltech = f"{export_date}_t_ltech.csv"
        table_t_reference = f"{export_date}_t_reference.csv"

        #  Chargement des données
        df_baie = pd.read_sql(f'SELECT * FROM "{table_t_baie}"', engine)
        total = len(df_baie)
        if total == 0:
            return jsonify({"error": "La table t_baie est vide."}), 400

        #  Calcul des statistiques d'unicité des ba_code
        unique_ba_codes = df_baie['ba_code'].nunique()
        unique_percentage = round(unique_ba_codes / total * 100, 2)
        duplicate_percentage = round(100 - unique_percentage, 2)
        duplicated_ba_codes = df_baie['ba_code'].value_counts()[df_baie['ba_code'].value_counts() > 1].index.tolist()

        #  Vérification de la correspondance avec t_ltech
        try:
            df_ltech = pd.read_sql(f'SELECT * FROM "{table_t_ltech}"', engine)
            lt_codes = set(df_ltech['lt_code'].astype(str).str.strip())
        except:
            lt_codes = set()

        total_checked_lt = df_baie.shape[0]
        success_lt = df_baie['ba_lt_code'].apply(lambda x: str(x).strip() in lt_codes).sum()
        failure_lt = total_checked_lt - success_lt
        success_rate_lt = round(success_lt / total_checked_lt * 100, 2)
        failure_rate_lt = round(failure_lt / total_checked_lt * 100, 2)
        missing_lt = df_baie.loc[~df_baie['ba_lt_code'].apply(lambda x: str(x).strip() in lt_codes), 'ba_lt_code'].unique().tolist()

        #  Vérification de la correspondance avec t_reference
        try:
            df_reference = pd.read_sql(f'SELECT * FROM "{table_t_reference}"', engine)
            rf_codes = set(df_reference['rf_code'].astype(str).str.strip())
        except:
            rf_codes = set()

        total_checked_rf = df_baie.shape[0]
        success_rf = df_baie['ba_rf_code'].apply(lambda x: str(x).strip() in rf_codes).sum()
        failure_rf = total_checked_rf - success_rf
        success_rate_rf = round(success_rf / total_checked_rf * 100, 2)
        failure_rate_rf = round(failure_rf / total_checked_rf * 100, 2)
        missing_rf = df_baie.loc[~df_baie['ba_rf_code'].apply(lambda x: str(x).strip() in rf_codes), 'ba_rf_code'].unique().tolist()

        #  Création des fichiers HTML et CSV
        export_dir = os.path.join('static', 'exports')
        os.makedirs(export_dir, exist_ok=True)
        csv_path = os.path.join(export_dir, f"Analyse_t_baie_{export_date}.csv")
        html_path = os.path.join(export_dir, f"Analyse_t_baie_{export_date}.html")

        #  Génération du fichier CSV
        with open(csv_path, 'w', newline='') as file:
            writer = csv.writer(file, delimiter=';')

            writer.writerow([f"Analyse de t_baie - {export_date}"])
            writer.writerow([])

            #  Unicité des ba_code
            writer.writerow(["Unicité des ba_code"])
            writer.writerow(["Critère", "Valeur"])
            writer.writerow(["Unicité de ba_code (%)", unique_percentage])
            writer.writerow(["Duplicated ba_code (%)", duplicate_percentage])
            writer.writerow([])
            
            #  Ba Codes dupliqués
            writer.writerow(["Ba Codes dupliqués"])
            writer.writerow(["ba_code"])
            for code in duplicated_ba_codes:
                writer.writerow([code])
            writer.writerow([])

            # Correspondance ba_lt_code
            writer.writerow(["Correspondance ba_lt_code avec t_ltech"])
            writer.writerow(["Total Vérifié", "Succès (%)", "Échec (%)", "Valeurs Manquantes"])
            writer.writerow([total_checked_lt, success_rate_lt, failure_rate_lt, ", ".join(missing_lt)])
            writer.writerow([])

            #  Correspondance ba_rf_code
            writer.writerow(["Correspondance ba_rf_code avec t_reference"])
            writer.writerow(["Total Vérifié", "Succès (%)", "Échec (%)", "Valeurs Manquantes"])
            writer.writerow([total_checked_rf, success_rate_rf, failure_rate_rf, ", ".join(missing_rf)])

        #  Génération du fichier HTML
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(f"<h2>Analyse de t_baie - {export_date}</h2>")

            f.write("<section class='section'><h3>Unicité des ba_code</h3>")
            f.write("<table border='1'><thead><tr><th>Critère</th><th>Valeur</th></tr></thead><tbody>")
            f.write(f"<tr><td>Unicité de ba_code (%)</td><td>{unique_percentage}%</td></tr>")
            f.write(f"<tr><td>Duplicated ba_code (%)</td><td>{duplicate_percentage}%</td></tr>")
            f.write("</tbody></table></section>")

            f.write("<section class='section'><h3>Ba Codes dupliqués</h3><ul>")
            for code in duplicated_ba_codes:
                f.write(f"<li>{code}</li>")
            f.write("</ul></section>")

            f.write("<section class='section'><h3>Correspondance ba_lt_code avec t_ltech</h3>")
            f.write("<table border='1'><thead><tr><th>Total Vérifié</th><th>Succès (%)</th><th>Échec (%)</th><th>Valeurs Manquantes</th></tr></thead><tbody>")
            f.write(f"<tr><td>{total_checked_lt}</td><td>{success_rate_lt}%</td><td>{failure_rate_lt}%</td><td>{', '.join(missing_lt)}</td></tr>")
            f.write("</tbody></table></section>")

            f.write("<section class='section'><h3>Correspondance ba_rf_code avec t_reference</h3>")
            f.write("<table border='1'><thead><tr><th>Total Vérifié</th><th>Succès (%)</th><th>Échec (%)</th><th>Valeurs Manquantes</th></tr></thead><tbody>")
            f.write(f"<tr><td>{total_checked_rf}</td><td>{success_rate_rf}%</td><td>{failure_rate_rf}%</td><td>{', '.join(missing_rf)}</td></tr>")
            f.write("</tbody></table></section>")

        #  Retour des résultats en JSON
        return jsonify({
            "unique_percentage": unique_percentage,
            "duplicate_percentage": duplicate_percentage,
            "duplicated_ba_codes": duplicated_ba_codes if duplicated_ba_codes else [],
            "ba_lt_total_checked": total_checked_lt,
            "ba_lt_success_rate": success_rate_lt,
            "ba_lt_failure_rate": failure_rate_lt,
            "ba_lt_missing_values": missing_lt if missing_lt else [],
            "ba_rf_total_checked": total_checked_rf,
            "ba_rf_success_rate": success_rate_rf,
            "ba_rf_failure_rate": failure_rate_rf,
            "ba_rf_missing_values": missing_rf if missing_rf else [],
            "csv_path": f"/{csv_path}",
            "html_path": f"/{html_path}"
        })


    except Exception as e:
        logging.error(f"Erreur lors de l'analyse de t_baie: {str(e)}")
        return jsonify({"error": str(e)}), 500

#route t_cab_cond
def normalize_dataframe(df):
    return df.apply(lambda col: col.map(lambda x: str(x).strip().upper() if isinstance(x, str) else x) if col.dtype == "object" else col)
@app.route('/analyze_t_cab_cond', methods=['POST'])
def analyze_t_cab_cond():
    try:
        # Récupération de la date d'export
        data = request.get_json()
        export_date = data.get('export_date')
        if not export_date:
            return jsonify({"error": "Date d'export non spécifiée"}), 400

        # Définition des noms des fichiers CSV
        table_cab_cond = f"{export_date}_t_cab_cond.csv"
        table_cable = f"{export_date}_t_cable.csv"
        table_conduite = f"{export_date}_t_conduite.csv"

        # Chargement des données
        df_cab_cond = pd.read_sql(f'SELECT * FROM "{table_cab_cond}"', engine)
        df_cable = None
        df_conduite = None

        try:
            df_cable = pd.read_sql(f'SELECT * FROM "{table_cable}"', engine)
        except Exception as e:
            print(f"Pas de table câble trouvée : {e}")

        try:
            df_conduite = pd.read_sql(f'SELECT * FROM "{table_conduite}"', engine)
            df_conduite = normalize_dataframe(df_conduite)
        except Exception as e:
            print(f"Pas de table conduite trouvée : {e}")
        
        # Normalisation des noms de colonnes
        df_cab_cond = normalize_dataframe(df_cab_cond)
        if df_cable is not None:
            df_cable = normalize_dataframe(df_cable)
        if df_conduite is not None:
            df_conduite = normalize_dataframe(df_conduite)

        # Calcul des taux d'unicité
        total_cc_cb = len(df_cab_cond)
        duplicated_cc_cb = df_cab_cond[df_cab_cond.duplicated(subset=['cc_cb_code'], keep=False)]['cc_cb_code'].dropna().unique().tolist()
        duplicated_cc_cd = df_cab_cond[df_cab_cond.duplicated(subset=['cc_cd_code'], keep=False)]['cc_cd_code'].dropna().unique().tolist()

        cc_cb_unique_rate = round(((total_cc_cb - len(duplicated_cc_cb)) / total_cc_cb) * 100, 2) if total_cc_cb > 0 else 100
        cc_cd_unique_rate = round(((total_cc_cb - len(duplicated_cc_cd)) / total_cc_cb) * 100, 2) if total_cc_cb > 0 else 100

        # Vérification des correspondances
        valeurs_non_trouvees_cb = []
        valeurs_non_trouvees_cd = []
        codes_orphelins_cable = []
        codes_orphelins_conduite = []

        if df_cable is not None:
            valeurs_non_trouvees_cb = df_cab_cond[~df_cab_cond['cc_cb_code'].isin(df_cable['cb_code'])]['cc_cb_code'].dropna().unique().tolist()
            codes_orphelins_cable = df_cable[~df_cable['cb_code'].isin(df_cab_cond['cc_cb_code'])]['cb_code'].dropna().unique().tolist()

        if df_conduite is not None:
            valeurs_non_trouvees_cd = df_cab_cond[~df_cab_cond['cc_cd_code'].isin(df_conduite['cd_code'])]['cc_cd_code'].dropna().unique().tolist()
            codes_orphelins_conduite = df_conduite[~df_conduite['cd_code'].isin(df_cab_cond['cc_cd_code'])]['cd_code'].dropna().unique().tolist()

        # Calcul des taux de réussite
        total_checked_cb = len(df_cab_cond['cc_cb_code'].dropna())
        total_checked_cd = len(df_cab_cond['cc_cd_code'].dropna())

        success_cb = total_checked_cb - len(valeurs_non_trouvees_cb) if df_cable is not None else total_checked_cb
        success_cd = total_checked_cd - len(valeurs_non_trouvees_cd) if df_conduite is not None else total_checked_cd

        success_rate_cb = round((success_cb / total_checked_cb) * 100, 2) if total_checked_cb > 0 else 100
        failure_rate_cb = 100 - success_rate_cb

        success_rate_cd = round((success_cd / total_checked_cd) * 100, 2) if total_checked_cd > 0 else 100
        failure_rate_cd = 100 - success_rate_cd

        # Préparation des résultats
        result = {
            "status": "success",
            "export_date": export_date,
            "cc_cb_unique_rate": cc_cb_unique_rate,
            "cc_cd_unique_rate": cc_cd_unique_rate,
            "duplicated_cc_cb": duplicated_cc_cb,
            "duplicated_cc_cd": duplicated_cc_cd,
            "valeurs_non_trouvees_cb": valeurs_non_trouvees_cb,
            "valeurs_non_trouvees_cd": valeurs_non_trouvees_cd,
            "codes_orphelins_cable": codes_orphelins_cable,
            "codes_orphelins_conduite": codes_orphelins_conduite,
            "total_checked_cb": total_checked_cb,
            "total_checked_cd": total_checked_cd,
            "success_rate_cb": success_rate_cb,
            "failure_rate_cb": failure_rate_cb,
            "success_rate_cd": success_rate_cd,
            "failure_rate_cd": failure_rate_cd
        }

        # Génération des fichiers de rapport
        export_dir = os.path.join('static', 'exports')
        os.makedirs(export_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Fichier CSV
        csv_filename = f"Analyse_CabCond_{export_date}_{timestamp}.csv"
        csv_path = os.path.join(export_dir, csv_filename)
        
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow(["Analyse de t_cab_cond", export_date])
            writer.writerow([])
            writer.writerow(["Unicité", "cc_cb_code", "cc_cd_code"])
            writer.writerow(["Taux d'unicité", f"{cc_cb_unique_rate}%", f"{cc_cd_unique_rate}%"])
            writer.writerow(["Valeurs dupliquées", ", ".join(map(str,duplicated_cc_cb)) or "Aucune", ", ".join(map(str,duplicated_cc_cd)) or "Aucune"])
            writer.writerow([])
            writer.writerow(["Correspondances", "cc_cb_code → t_cable", "cc_cd_code → t_conduite"])
            writer.writerow(["Taux de succès", f"{success_rate_cb}%", f"{success_rate_cd}%"])
            writer.writerow(["Valeurs non trouvées", ", ".join(map(str,valeurs_non_trouvees_cb)) or "Aucune", ", ".join(map(str,valeurs_non_trouvees_cd)) or "Aucune"])
            writer.writerow([])
            writer.writerow(["Codes orphelins", "t_cable", "t_conduite"])
            writer.writerow(["Codes", ", ".join(map(str,codes_orphelins_cable)) or "Aucun", ", ".join(map(str,codes_orphelins_conduite)) or "Aucun"])

        # Fichier HTML
        html_filename = f"Analyse_CabCond_{export_date}_{timestamp}.html"
        html_path = os.path.join(export_dir, html_filename)
        
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <title>Analyse t_cab_cond - {export_date}</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 20px; }}
                    h1 {{ color: #2c3e50; }}
                    table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
                    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                    th {{ background-color: #f2f2f2; }}
                    tr:nth-child(even) {{ background-color: #f9f9f9; }}
                    .section {{ margin-bottom: 30px; }}
                    .section-title {{ color: #3498db; }}
                </style>
            </head>
            <body>
                <h1>Analyse de t_cab_cond - {export_date}</h1>
                
                <div class="section">
                    <h2 class="section-title">Unicité des codes</h2>
                    <table>
                        <tr><th>Colonne</th><th>Taux d'unicité</th><th>Valeurs dupliquées</th></tr>
                        <tr><td>cc_cb_code</td><td>{cc_cb_unique_rate}%</td><td>{", ".join(map(str,duplicated_cc_cb)) if duplicated_cc_cb else "Aucune"}</td></tr>
                        <tr><td>cc_cd_code</td><td>{cc_cd_unique_rate}%</td><td>{", ".join(map(str,duplicated_cc_cd)) if duplicated_cc_cd else "Aucune"}</td></tr>
                    </table>
                </div>
                
                <div class="section">
                    <h2 class="section-title">Correspondances</h2>
                    <table>
                        <tr><th>Relation</th><th>Taux de succès</th><th>Valeurs non trouvées</th></tr>
                        <tr><td>cc_cb_code → t_cable.cb_code</td><td>{success_rate_cb}%</td><td>{", ".join(map(str,valeurs_non_trouvees_cb)) if valeurs_non_trouvees_cb else "Aucune"}</td></tr>
                        <tr><td>cc_cd_code → t_conduite.cd_code</td><td>{success_rate_cd}%</td><td>{", ".join(map(str,valeurs_non_trouvees_cd)) if valeurs_non_trouvees_cd else "Aucune"}</td></tr>
                    </table>
                </div>
                
                <div class="section">
                    <h2 class="section-title">Codes orphelins</h2>
                    <table>
                        <tr><th>Table</th><th>Codes orphelins</th></tr>
                        <tr><td>t_cable</td><td>{", ".join(map(str,codes_orphelins_cable)) if codes_orphelins_cable else "Aucun"}</td></tr>
                        <tr><td>t_conduite</td><td>{", ".join(map(str,codes_orphelins_conduite)) if codes_orphelins_conduite else "Aucun"}</td></tr>
                    </table>
                </div>
            </body>
            </html>
            """)

        result["csv_path"] = f"/static/exports/{csv_filename}"
        result["html_path"] = f"/static/exports/{html_filename}"

        return jsonify(result)

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }), 500
    
#cohérence t_cassette
@app.route('/analyze_t_cassette', methods=['POST'])
def analyze_t_cassette():
    try:
        # utilitaire "Voir plus / Voir moins"
        def render_list_with_toggle(lst):
            # (inchangé, utilisé pour le HTML exporté)
            if not lst:
                return "Aucune"
            first10 = lst[:10]
            rest = lst[10:]
            s = ", ".join(map(str, first10))
            if rest:
                s += (
                    " <span class='toggle-more' onclick=\""
                    "this.style.display='none';"
                    "this.nextElementSibling.style.display='inline';"
                    "\">... Voir plus</span>"
                    f"<span class='toggle-less' style='display:none' onclick=\""
                    "this.style.display='none';"
                    "this.previousElementSibling.style.display='inline';"
                    "\">, {', '.join(map(str,rest))} <u>Voir moins</u></span>"
                )
            return s

        data = request.get_json()
        export_date = data.get('export_date')
        if not export_date:
            return jsonify({"error": "Date d'export non spécifiée"}), 400

        # noms de tables
        tbl_cassette  = f"{export_date}_t_cassette.csv"
        tbl_ebp       = f"{export_date}_t_ebp.csv"
        tbl_reference = f"{export_date}_t_reference.csv"

        # chargement
        df_cassette  = read_table(export_date, 't_cassette.csv')
        df_cassette  = normalize_dataframe(df_cassette)

        df_ebp       = read_table(export_date, 't_ebp.csv')
        df_ebp       = normalize_dataframe(df_ebp) if not df_ebp.empty else pd.DataFrame()

        df_reference = read_table(export_date, 't_reference.csv')
        df_reference = normalize_dataframe(df_reference) if not df_reference.empty else pd.DataFrame()


        # unicité
        total_bp = df_cassette['cs_code'].dropna().shape[0]
        total_rf = df_cassette['cs_rf_code'].dropna().shape[0]

        dup_bp = df_cassette[df_cassette.duplicated('cs_code', keep=False)]
        dup_rf = df_cassette[df_cassette.duplicated('cs_rf_code', keep=False)]

        duplicated_cs_bp = dup_bp['cs_code'].dropna().unique().tolist()
        duplicated_cs_rf = dup_rf['cs_rf_code'].dropna().unique().tolist()

        cs_bp_unique_rate = round((total_bp - len(duplicated_cs_bp)) / total_bp * 100, 2) if total_bp else 100
        cs_rf_unique_rate = round((total_rf - len(duplicated_cs_rf)) / total_rf * 100, 2) if total_rf else 100

        # correspondances
        if not df_ebp.empty:
            mask_bp = df_cassette['cs_bp_code'].dropna().isin(df_ebp['bp_code'])
            orphelins_bp = df_cassette.loc[~mask_bp, 'cs_bp_code'].dropna().unique().tolist()
            success_bp   = round(mask_bp.sum() / total_bp * 100, 2) if total_bp else 100
        else:
            orphelins_bp = []
            success_bp   = 0.0

        if not df_reference.empty:
            mask_rf = df_cassette['cs_rf_code'].dropna().isin(df_reference['rf_code'])
            orphelins_rf = df_cassette.loc[~mask_rf, 'cs_rf_code'].dropna().unique().tolist()
            success_rf   = round(mask_rf.sum() / total_rf * 100, 2) if total_rf else 100
        else:
            orphelins_rf = []
            success_rf   = 0.0

        # codes vides
        cs_bp_vide = int(df_cassette['cs_bp_code'].isna().sum())
        cs_rf_vide = int(df_cassette['cs_rf_code'].isna().sum())

        # exemples de vides (ici vide car NaN → dropna())
        exemples_bp_vide = df_cassette.loc[df_cassette['cs_bp_code'].isna(), 'cs_bp_code'].dropna().unique().tolist()
        exemples_rf_vide = df_cassette.loc[df_cassette['cs_rf_code'].isna(), 'cs_rf_code'].dropna().unique().tolist()

        # export CSV (identique à avant) …
        export_dir = os.path.join('static', 'exports')
        os.makedirs(export_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_fn = f"Analyse_Cassette_{export_date}_{timestamp}.csv"
        csv_path = os.path.join(export_dir, csv_fn)
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f, delimiter=';')
            w.writerow([f"Analyse t_cassette", export_date]); w.writerow([])
            w.writerow(["Unicité", "cs_code", "cs_rf_code"])
            w.writerow(["Taux (%)", f"{cs_bp_unique_rate}%", f"{cs_rf_unique_rate}%"])
            w.writerow([
                "Doublons",
                ", ".join(map(str, duplicated_cs_bp)) or "Aucune",
                ", ".join(map(str, duplicated_cs_rf)) or "Aucune"
            ])
            w.writerow([])
            w.writerow(["Correspondances", "→ t_ebp", "→ t_reference"])
            w.writerow(["Succès (%)", f"{success_bp}%", f"{success_rf}%"])
            w.writerow([
                "Orphelins",
                ", ".join(map(str, orphelins_bp)) or "Aucune",
                ", ".join(map(str, orphelins_rf)) or "Aucune"
            ])
            w.writerow([])
            w.writerow(["Codes vides", cs_bp_vide, cs_rf_vide])
            w.writerow([
                "Exemples vides",
                ", ".join(map(str, exemples_bp_vide)) or "Aucune",
                ", ".join(map(str, exemples_rf_vide)) or "Aucune"
            ])

        # export HTML avec toggles
        html = f"""
<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Analyse t_cassette – {export_date}</title>
<style>
  body{{font-family:Arial;margin:20px}}
  table{{border-collapse:collapse;width:100%;margin-bottom:20px}}
  th,td{{border:1px solid #ddd;padding:8px;text-align:left}}
  th{{background:#f2f2f2}}
  .toggle-more,.toggle-less{{color:blue;cursor:pointer;text-decoration:underline}}
</style></head><body>
  <h1>Analyse t_cassette – {export_date}</h1>

  <h2>Unicité des codes</h2>
  <table>
    <tr><th>Colonne</th><th>Taux (%)</th><th>Doublons</th></tr>
    <tr>
      <td>cs_code</td><td>{cs_bp_unique_rate}%</td>
      <td>{render_list_with_toggle(duplicated_cs_bp)}</td>
    </tr>
    <tr>
      <td>cs_rf_code</td><td>{cs_rf_unique_rate}%</td>
      <td>{render_list_with_toggle(duplicated_cs_rf)}</td>
    </tr>
  </table>

  <h2>Correspondances</h2>
  <table>
    <tr><th>Relation</th><th>Succès (%)</th><th>Orphelins</th></tr>
    <tr>
      <td>cs_bp_code → t_ebp</td><td>{success_bp}%</td>
      <td>{render_list_with_toggle(orphelins_bp)}</td>
    </tr>
    <tr>
      <td>cs_rf_code → t_reference</td><td>{success_rf}%</td>
      <td>{render_list_with_toggle(orphelins_rf)}</td>
    </tr>
  </table>

  <h2>Codes vides</h2>
  <table>
    <tr><th>Colonne</th><th>Nombre de vides</th><th>Exemples</th></tr>
    <tr>
      <td>cs_bp_code</td><td>{cs_bp_vide}</td>
      <td>{render_list_with_toggle(exemples_bp_vide)}</td>
    </tr>
    <tr>
      <td>cs_rf_code</td><td>{cs_rf_vide}</td>
      <td>{render_list_with_toggle(exemples_rf_vide)}</td>
    </tr>
  </table>
</body></html>
"""
        html_fn = f"Analyse_Cassette_{export_date}_{timestamp}.html"
        html_path = os.path.join(export_dir, html_fn)
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)

        # on inclut **toutes** les listes dans le JSON
        result = {
            "status":               "success",
            "export_date":          export_date,
            "total_cs_bp":          total_bp,
            "total_cs_rf":          total_rf,
            "cs_bp_unique_rate":    cs_bp_unique_rate,
            "cs_rf_unique_rate":    cs_rf_unique_rate,
            "duplicated_cs_bp":     duplicated_cs_bp,
            "duplicated_cs_rf":     duplicated_cs_rf,
            "success_rate_bp":      success_bp,
            "success_rate_rf":      success_rf,
            "non_trouve_bp":        orphelins_bp,
            "non_trouve_rf":        orphelins_rf,
            "cs_bp_vide":           cs_bp_vide,
            "cs_rf_vide":           cs_rf_vide,
            "csv_path":             f"/static/exports/{csv_fn}",
            "html_path":            f"/static/exports/{html_fn}"
        }

        return jsonify(result)

    except Exception as e:
        return jsonify({
            "status":    "error",
            "message":   str(e),
            "traceback": traceback.format_exc()
        }), 500


#cohérence t_cheminement
@app.route('/analyze_cheminement', methods=['POST'])
def analyze_cheminement():
    try:
        data        = request.get_json()
        export_date = data.get('export_date')
        if not export_date:
            return jsonify({"error": "Date d'export non spécifiée"}), 400

        # 1) Chargement (fallback .csv ↔ .dbf)
        df_ch   = read_table(export_date, 't_cheminement.csv')
        df_nd   = read_table(export_date, 't_noeud.csv')
        df_org  = read_table(export_date, 't_organisme.csv')

        # 2) Normalisation noms de colonnes
        for df in (df_ch, df_nd, df_org):
            df.columns = df.columns.str.lower().str.strip()

        # 3) Normalisation valeurs
        # ndcode1 & ndcode2 en lower pour existence & calcul remplissage
        for c in ['cm_ndcode1','cm_ndcode2']:
            df_ch[c] = df_ch[c].astype(str).str.strip().replace({'nan':'','none':''}).str.lower()
        # gest/prop org
        df_ch['cm_gest_do'] = df_ch['cm_gest_do'].astype(str).str.strip().str.lower()
        df_ch['cm_prop_do'] = df_ch['cm_prop_do'].astype(str).str.strip().str.lower()
        # codeext en upper
        df_ch['cm_codeext'] = df_ch['cm_codeext'].astype(str).str.strip().str.upper()

        df_nd['nd_code']    = df_nd['nd_code'].astype(str).str.strip().str.lower()
        df_org['or_code']   = df_org['or_code'].astype(str).str.strip().str.lower()

        total = len(df_ch)

        # Analyse d'unicité pour cm_code
        df_ch['cm_code'] = df_ch['cm_code'].astype(str).str.strip().replace({'nan':'','none':''})
        total_cm = df_ch['cm_code'].dropna().shape[0]
        dup_cm = df_ch[df_ch.duplicated('cm_code', keep=False)]
        duplicated_cm_code = dup_cm['cm_code'].dropna().unique().tolist()
        cm_code_unique_rate = round((total_cm - len(duplicated_cm_code)) / total_cm * 100, 2) if total_cm else 100

        # 4) Remplissage cm_ndcode1 & cm_ndcode2
        def fill_stats(col):
            filled = df_ch[col].map(bool).sum()
            pct_f  = round(filled/total*100, 2) if total else 0
            # existence parmi les remplis
            mask_exist = df_ch[col].isin(df_nd['nd_code'])
            missing    = df_ch.loc[df_ch[col].map(bool) & ~mask_exist, col].unique().tolist()
            miss_cnt   = int((df_ch[col].map(bool) & ~mask_exist).sum())
            miss_pct   = round(miss_cnt/total*100, 2) if total else 0
            return filled, pct_f, missing, miss_cnt, miss_pct

        f1, p1, m1, c1, q1 = fill_stats('cm_ndcode1')
        f2, p2, m2, c2, q2 = fill_stats('cm_ndcode2')

        # 5) Existence cm_gest_do & cm_prop_do
        def org_stats(col):
            mask = df_ch[col].isin(df_org['or_code'])
            missing = df_ch.loc[~mask, col].dropna().unique().tolist()
            cnt     = int((~mask).sum())
            pct     = round(cnt/total*100, 2) if total else 0
            return missing, cnt, pct

        mg, cg, pg = org_stats('cm_gest_do')
        mp, cp, pp = org_stats('cm_prop_do')

        # 6) CM_CODEEXT validité
        valid_ext = {"TERRITOIRE","HORS TERRITOIRE"}
        mask_ce   = df_ch['cm_codeext'].isin(valid_ext)
        missing_ce= df_ch.loc[~mask_ce, 'cm_codeext'].dropna().unique().tolist()
        cnt_ce    = int((~mask_ce).sum())
        pct_ce    = round(cnt_ce/total*100, 2) if total else 0

        # 7) Préparer JSON
        result = {
            "status":           "success",
            "export_date":      export_date,
            "total_rows":       total,

            "total_cm": total_cm,
            "cm_code_unique_rate": cm_code_unique_rate,
            "duplicated_cm_code": duplicated_cm_code,

            "f1":                f1, "p1": p1, "m1": m1, "c1": c1, "q1": q1,
            "f2":                f2, "p2": p2, "m2": m2, "c2": c2, "q2": q2,

            "mg":               mg, "cg": cg, "pg": pg,
            "mp":               mp, "cp": cp, "pp": pp,

            "missing_ce":       missing_ce,
            "cnt_ce":           cnt_ce,
            "pct_ce":           pct_ce

        }

        # 8) numpy → natifs
        import numpy as np
        for k,v in list(result.items()):
            if isinstance(v, np.integer):    result[k]=int(v)
            elif isinstance(v, np.floating): result[k]=float(v)
            elif isinstance(v, np.ndarray):  result[k]=v.tolist()

        # 9) Export CSV
        export_dir = os.path.join('static','exports'); os.makedirs(export_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_fn = f"Analyse_Cheminement_{export_date}_{ts}.csv"
        csv_p  = os.path.join(export_dir, csv_fn)
        with open(csv_p,'w', newline='', encoding='utf-8') as f:
            w=csv.writer(f,delimiter=';')
            w.writerow([f"Analyse t_cheminement", export_date]); w.writerow([])
            w.writerow(["Test","Remplis/Total (%)","Invalids/Total (%)"])
            w.writerow(["cm_ndcode1", f"{f1}/{total} ({p1}%)", f"{c1}/{total} ({q1}%)"])
            w.writerow(["cm_ndcode2", f"{f2}/{total} ({p2}%)", f"{c2}/{total} ({q2}%)"])
            w.writerow(["cm_gest_do invalides", "", f"{cg}/{total} ({pg}%)"])
            w.writerow(["cm_prop_do invalides", "", f"{cp}/{total} ({pp}%)"])
            w.writerow(["cm_codeext invalides", "", f"{cnt_ce}/{total} ({pct_ce}%)"])
            w.writerow([]); w.writerow(["Détail (max 10)"])
            w.writerow(["cm_ndcode1",    ", ".join(m1[:10])    or "Aucun"])
            w.writerow(["cm_ndcode2",    ", ".join(m2[:10])    or "Aucun"])
            w.writerow(["cm_gest_do",    ", ".join(mg[:10])    or "Aucun"])
            w.writerow(["cm_prop_do",    ", ".join(mp[:10])    or "Aucun"])
            w.writerow(["cm_codeext",    ", ".join(missing_ce[:10]) or "Aucun"])
            w.writerow(["cm_code unicité (%)", f"{total_cm} codes", f"{cm_code_unique_rate}% uniques – doublons: {', '.join(duplicated_cm_code[:10]) or 'Aucun'}"])

        result["csv_path"] = f"/static/exports/{csv_fn}"

        # 10) Export HTML
        def render_list(lst):
            if not lst: return "Aucun"
            v, m = lst[:10], lst[10:]
            s = ", ".join(v)
            if m:
                s += ("<span class='voir-plus' onclick=\"this.nextElementSibling.style.display='inline';"
                      "this.style.display='none';\">... Voir plus</span>")
                s += f"<span style='display:none'>, {', '.join(m)}</span>"
            return s

        html_fn = f"Analyse_Cheminement_{export_date}_{ts}.html"
        html_p  = os.path.join(export_dir, html_fn)
        with open(html_p,'w', encoding='utf-8') as f:
            f.write(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Analyse t_cheminement – {export_date}</title>
<style>body{{font-family:Arial;margin:20px}}
table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:8px}}
th{{background:#f2f2f2}}.voir-plus{{color:blue;cursor:pointer;text-decoration:underline}}
</style></head><body>
  <h1>Analyse t_cheminement – {export_date}</h1>
  <table>

    <tr><th>Test</th><th>Remplis/Total (%)</th><th>Invalids/Total (%)</th></tr>
    <tr><td>cm_ndcode1</td><td>{f1}/{total} ({p1}%)</td><td>{c1}/{total} ({q1}%)</td></tr>
    <tr><td>cm_ndcode2</td><td>{f2}/{total} ({p2}%)</td><td>{c2}/{total} ({q2}%)</td></tr>
    <tr><td>cm_gest_do</td><td>–</td><td>{cg}/{total} ({pg}%)</td></tr>
    <tr><td>cm_prop_do</td><td>–</td><td>{cp}/{total} ({pp}%)</td></tr>
    <tr><td>cm_codeext</td><td>–</td><td>{cnt_ce}/{total} ({pct_ce}%)</td></tr>
  </table>
  <h2>Détails des valeurs invalides</h2>
  <table>
    <tr><th>Champ</th><th>Valeurs</th></tr>
    <tr><td>cm_ndcode1</td><td>{render_list(m1)}</td></tr>
    <tr><td>cm_ndcode2</td><td>{render_list(m2)}</td></tr>
    <tr><td>cm_gest_do</td><td>{render_list(mg)}</td></tr>
    <tr><td>cm_prop_do</td><td>{render_list(mp)}</td></tr>
    <tr><td>cm_codeext</td><td>{render_list(missing_ce)}</td></tr>
  </table>
  <h2>Unicité de cm_code</h2>
  <table>
    <tr><th>Total</th><th>Taux (%)</th><th>Doublons</th></tr>
    <tr>
      <td>{total_cm}</td>
      <td>{cm_code_unique_rate}%</td>
      <td>{render_list(duplicated_cm_code)}</td>
    </tr>
  </table>
</body></html>""")
        result["html_path"] = f"/static/exports/{html_fn}"

        return jsonify(result)

    except Exception as e:
        return jsonify({
            "status":    "error",
            "message":   str(e),
            "traceback": traceback.format_exc()
        }), 500


@app.route('/analyze_t_cond_chem', methods=['POST'])
def analyze_t_cond_chem():
    try:
        # Récupération de la date
        data = request.get_json()
        export_date = data.get('export_date')
        if not export_date:
            return jsonify({"error": "Date d'export non spécifiée"}), 400

        # Construction des noms des tables
        table_cond_chem = f"{export_date}_t_cond_chem.csv"
        table_conduite = f"{export_date}_t_conduite.csv"
        table_cheminement = f"{export_date}_t_cheminement.csv"

        # Chargement des données
        df_cond_chem = pd.read_sql(f'SELECT * FROM "{table_cond_chem}"', engine)
        df_cond_chem.columns = df_cond_chem.columns.str.lower().str.strip()

        try:
            df_conduite = pd.read_sql(f'SELECT * FROM "{table_conduite}"', engine)
            df_conduite.columns = df_conduite.columns.str.lower().str.strip()
        except:
            df_conduite = pd.DataFrame()

        try:
            df_cheminement = pd.read_sql(f'SELECT * FROM "{table_cheminement}"', engine)
            df_cheminement.columns = df_cheminement.columns.str.lower().str.strip()
        except:
            df_cheminement = pd.DataFrame()

        # Fonction de nettoyage spécifique pour les codes
        def clean_code(series):
            # Convertir en string, supprimer les guillemets et espaces
            return series.astype(str).str.replace('"', '').str.strip()
        
        # Nettoyage des codes dans tous les dataframes
        if 'dm_cd_code' in df_cond_chem.columns:
            df_cond_chem['dm_cd_code'] = clean_code(df_cond_chem['dm_cd_code'])
        if 'dm_cm_code' in df_cond_chem.columns:
            df_cond_chem['dm_cm_code'] = clean_code(df_cond_chem['dm_cm_code'])
        
        if not df_conduite.empty and 'cd_code' in df_conduite.columns:
            df_conduite['cd_code'] = clean_code(df_conduite['cd_code'])
        
        if not df_cheminement.empty and 'cm_code' in df_cheminement.columns:
            df_cheminement['cm_code'] = clean_code(df_cheminement['cm_code'])

        # Vérification des colonnes
        for col in ['dm_cd_code', 'dm_cm_code']:
            if col not in df_cond_chem.columns:
                df_cond_chem[col] = pd.NA

        # Conversion des valeurs vides en NaN
        df_cond_chem['dm_cd_code'] = df_cond_chem['dm_cd_code'].replace(['', 'nan', 'None'], pd.NA)
        df_cond_chem['dm_cm_code'] = df_cond_chem['dm_cm_code'].replace(['', 'nan', 'None'], pd.NA)

        # Analyse unicité
        total_dm_cd = df_cond_chem['dm_cd_code'].dropna().shape[0]
        total_dm_cm = df_cond_chem['dm_cm_code'].dropna().shape[0]

        duplicated_dm_cd = df_cond_chem[
            df_cond_chem.duplicated(subset=['dm_cd_code'], keep=False) & 
            df_cond_chem['dm_cd_code'].notna()
        ]['dm_cd_code'].dropna().unique().tolist()

        duplicated_dm_cm = df_cond_chem[
            df_cond_chem.duplicated(subset=['dm_cm_code'], keep=False) & 
            df_cond_chem['dm_cm_code'].notna()
        ]['dm_cm_code'].dropna().unique().tolist()

        dm_cd_unique_rate = round((total_dm_cd - len(duplicated_dm_cd)) / total_dm_cd * 100, 2) if total_dm_cd else 100
        dm_cm_unique_rate = round((total_dm_cm - len(duplicated_dm_cm)) / total_dm_cm * 100, 2) if total_dm_cm else 100

        # Correspondances
        if not df_conduite.empty and 'cd_code' in df_conduite.columns:
            correspondances_cd = df_cond_chem[
                df_cond_chem['dm_cd_code'].isin(df_conduite['cd_code'])
            ].shape[0]

            non_trouve_cd = df_cond_chem[
                ~df_cond_chem['dm_cd_code'].isin(df_conduite['cd_code'])
            ]['dm_cd_code'].dropna().unique().tolist()
        else:
            correspondances_cd = 0
            non_trouve_cd = []


        if not df_cheminement.empty and 'cm_code' in df_cheminement.columns:
            # Comparaison ligne à ligne (pas uniquement les valeurs uniques)
            correspondances_cm = df_cond_chem[
                df_cond_chem['dm_cm_code'].isin(df_cheminement['cm_code'])
            ].shape[0]

            non_trouve_cm = df_cond_chem[
                ~df_cond_chem['dm_cm_code'].isin(df_cheminement['cm_code'])
            ]['dm_cm_code'].dropna().unique().tolist()
        else:
            correspondances_cm = 0
            non_trouve_cm = []


        # Calcul des taux de succès basés sur les occurrences dans le dataframe original
        success_rate_cd = round(correspondances_cd / total_dm_cd * 100, 2) if total_dm_cd else 100
        success_rate_cm = round(correspondances_cm / total_dm_cm * 100, 2) if total_dm_cm else 100

        # Codes vides
        dm_cd_vide = df_cond_chem['dm_cd_code'].isna().sum()
        dm_cm_vide = df_cond_chem['dm_cm_code'].isna().sum()

        # Résultat
        result = {
            "status": "success",
            "export_date": export_date,
            "total_dm_cd": total_dm_cd,
            "total_dm_cm": total_dm_cm,
            "dm_cd_unique_rate": dm_cd_unique_rate,
            "dm_cm_unique_rate": dm_cm_unique_rate,
            "duplicated_dm_cd": duplicated_dm_cd,
            "duplicated_dm_cm": duplicated_dm_cm,
            "success_rate_cd": success_rate_cd,
            "success_rate_cm": success_rate_cm,
            "non_trouve_cd": non_trouve_cd,
            "non_trouve_cm": non_trouve_cm,
            "dm_cd_vide": dm_cd_vide,
            "dm_cm_vide": dm_cm_vide
        }

        # Conversion des types numpy en types Python natifs
        for key, value in result.items():
            if isinstance(value, (np.integer, np.floating)):
                result[key] = int(value) if isinstance(value, np.integer) else float(value)
            elif isinstance(value, (list, np.ndarray)):
                result[key] = [str(x) for x in value]

        # Export CSV + HTML (identique à votre version originale)
        export_dir = os.path.join('static', 'exports')
        os.makedirs(export_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # CSV
        csv_filename = f"Analyse_CondChem_{export_date}_{timestamp}.csv"
        csv_path = os.path.join(export_dir, csv_filename)

        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow(["Analyse de t_cond_chem", export_date])
            writer.writerow([])
            writer.writerow(["Unicité", "dm_cd_code", "dm_cm_code"])
            writer.writerow(["Taux d'unicité", f"{dm_cd_unique_rate}%", f"{dm_cm_unique_rate}%"])
            writer.writerow(["Valeurs dupliquées", ", ".join(result["duplicated_dm_cd"]) or "Aucune", ", ".join(result["duplicated_dm_cm"]) or "Aucune"])
            writer.writerow([])
            writer.writerow(["Correspondances", "dm_cd_code → t_conduite", "dm_cm_code → t_cheminement"])
            writer.writerow(["Taux de succès", f"{success_rate_cd}%", f"{success_rate_cm}%"])
            print("NON TROUVÉS CM :", non_trouve_cm)

            writer.writerow(["Valeurs non trouvées", ", ".join(result["non_trouve_cd"]) or "Aucune", ", ".join(result["non_trouve_cm"]) or "Aucune"])
            writer.writerow([])
            writer.writerow(["Codes vides", dm_cd_vide, dm_cm_vide])

        # HTML
        html_filename = f"Analyse_CondChem_{export_date}_{timestamp}.html"
        html_path = os.path.join(export_dir, html_filename)

        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Analyse t_cond_chem - {export_date}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #2c3e50; }}
        table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        tr:nth-child(even) {{ background-color: #f9f9f9; }}
        .section {{ margin-bottom: 30px; }}
        .section-title {{ color: #3498db; }}
    </style>
</head>
<body>
    <h1>Analyse de t_cond_chem - {export_date}</h1>
    
    <div class="section">
        <h2 class="section-title">Unicité des codes</h2>
        <table>
            <tr><th>Colonne</th><th>Taux d'unicité</th><th>Valeurs dupliquées</th></tr>
            <tr><td>dm_cd_code</td><td>{dm_cd_unique_rate}%</td><td>{", ".join(result["duplicated_dm_cd"]) or "Aucune"}</td></tr>
            <tr><td>dm_cm_code</td><td>{dm_cm_unique_rate}%</td><td>{", ".join(result["duplicated_dm_cm"]) or "Aucune"}</td></tr>
        </table>
    </div>
    
    <div class="section">
        <h2 class="section-title">Correspondances</h2>
        <table>
            <tr><th>Relation</th><th>Taux de succès</th><th>Valeurs non trouvées</th></tr>
            <tr><td>dm_cd_code → t_conduite</td><td>{success_rate_cd}%</td><td>{", ".join(result["non_trouve_cd"]) or "Aucune"}</td></tr>
            <tr><td>dm_cm_code → t_cheminement</td><td>{success_rate_cm}%</td><td>{", ".join(result["non_trouve_cm"]) or "Aucune"}</td></tr>
        </table>
    </div>
    
    <div class="section">
        <h2 class="section-title">Codes vides</h2>
        <table>
            <tr><th>Colonne</th><th>Nombre de vides</th></tr>
            <tr><td>dm_cd_code</td><td>{dm_cd_vide}</td></tr>
            <tr><td>dm_cm_code</td><td>{dm_cm_vide}</td></tr>
        </table>
    </div>
</body>
</html>""")

        result["csv_path"] = f"/static/exports/{csv_filename}"
        result["html_path"] = f"/static/exports/{html_filename}"

        return jsonify(result)

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }), 500


#logique cohérence table cable
@app.route('/analyze_coherence_cable', methods=['POST'])
def analyze_coherence_cable():
    try:
        data = request.get_json()
        export_date = data.get('export_date')
        if not export_date:
            return jsonify({"error": "Date d'export non spécifiée"}), 400

        # --- Chargement avec fallback CSV/DBF
        df_cable = load_table_any(export_date, 't_cable')
        df_organisme = load_table_any(export_date, 't_organisme')

        # --- Normalisation colonnes
        df_cable.columns = df_cable.columns.str.lower().str.strip()
        df_organisme.columns = df_organisme.columns.str.lower().str.strip()

        # --- Nettoyage valeurs
        def clean(val): return str(val).strip().lower()
        df_cable = df_cable.applymap(clean)
        df_organisme = df_organisme.applymap(clean)

        # --- Vérif 1 : cb_prop / cb_gest / cb_user ∈ or_code
        if 'or_code' not in df_organisme.columns:
            return jsonify({"error": "Colonne or_code absente de t_organisme"}), 400
        for needed in ['cb_prop','cb_gest','cb_user']:
            if needed not in df_cable.columns:
                return jsonify({"error": f"Colonne {needed} absente de t_cable"}), 400

        or_codes = df_organisme['or_code'].dropna().unique()
        non_trouve_cb_prop = df_cable[~df_cable['cb_prop'].isin(or_codes)]['cb_prop'].dropna().unique().tolist()
        non_trouve_cb_gest = df_cable[~df_cable['cb_gest'].isin(or_codes)]['cb_gest'].dropna().unique().tolist()
        non_trouve_cb_user = df_cable[~df_cable['cb_user'].isin(or_codes)]['cb_user'].dropna().unique().tolist()

        # --- Vérif 2 : cb_fo_disp + cb_fo_util == cb_capafo
        for needed in ['cb_fo_disp','cb_fo_util','cb_capafo']:
            if needed not in df_cable.columns:
                return jsonify({"error": f"Colonne {needed} absente de t_cable"}), 400

        df_test_fo = df_cable.copy()
        df_test_fo[['cb_fo_disp','cb_fo_util','cb_capafo']] = df_test_fo[['cb_fo_disp','cb_fo_util','cb_capafo']].apply(pd.to_numeric, errors='coerce')
        df_test_fo['sum_disp_util'] = df_test_fo['cb_fo_disp'] + df_test_fo['cb_fo_util']
        incoherents_fo = df_test_fo[df_test_fo['sum_disp_util'] != df_test_fo['cb_capafo']]

        # HTML rows pour les incohérences
        incoherents_fo_html = ""
        if not incoherents_fo.empty:
            for _, row in incoherents_fo.iterrows():
                cb_code = row.get('cb_code', 'inconnu')
                incoherents_fo_html += (
                    f"<tr><td>{cb_code}</td>"
                    f"<td>{row['cb_fo_disp']}</td><td>{row['cb_fo_util']}</td>"
                    f"<td>{row['cb_capafo']}</td><td>{row['sum_disp_util']}</td></tr>"
                )

        # --- Vérif 3 : cb_codeext ∈ {territoire, hors territoire}
        if 'cb_codeext' in df_cable.columns:
            valid_values = {"territoire", "hors territoire"}
            cb_codeext_invalides = df_cable[~df_cable['cb_codeext'].isin(valid_values)]
        else:
            cb_codeext_invalides = pd.DataFrame()

        # --- Vérif 4 : unicité de cb_code
        if 'cb_code' not in df_cable.columns:
            return jsonify({"error": "Colonne cb_code absente de t_cable"}), 400
        df_cable['cb_code'] = df_cable['cb_code'].astype(str).str.strip().replace({'nan':'','none':''})
        total_cb_code = df_cable['cb_code'].dropna().shape[0]
        dup_cb_code = df_cable[df_cable.duplicated('cb_code', keep=False)]
        duplicated_cb_code = dup_cb_code['cb_code'].dropna().unique().tolist()
        cb_code_unique_rate = round((total_cb_code - len(duplicated_cb_code)) / total_cb_code * 100, 2) if total_cb_code else 100

        # --- Résultat JSON (+ fichiers)
        result = {
            "status": "success",
            "export_date": export_date,
            "cb_prop_non_trouve": list(map(str, non_trouve_cb_prop)),
            "cb_gest_non_trouve": list(map(str, non_trouve_cb_gest)),
            "cb_user_non_trouve": list(map(str, non_trouve_cb_user)),
            "nb_incoherents_fo": int(len(incoherents_fo)),
            "nb_cb_codeext_invalides": int(cb_codeext_invalides.shape[0]),
            "incoherents_fo_html": incoherents_fo_html,
            "total_cb_code": int(total_cb_code),
            "cb_code_unique_rate": cb_code_unique_rate,
            "duplicated_cb_code": duplicated_cb_code
        }

        export_dir = os.path.join("static", "exports")
        os.makedirs(export_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_filename = f"Analyse_Cable_{export_date}_{timestamp}.csv"
        html_filename = f"Analyse_Cable_{export_date}_{timestamp}.html"
        csv_path = os.path.join(export_dir, csv_filename)
        html_path = os.path.join(export_dir, html_filename)

        # CSV
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow(["Analyse de coherence du câble", export_date])
            writer.writerow([])
            writer.writerow(["Vérification cb_prop / cb_gest / cb_user présents dans or_code"])
            writer.writerow(["cb_prop non trouvés", ", ".join(result["cb_prop_non_trouve"][:10])])
            writer.writerow(["cb_gest non trouvés", ", ".join(result["cb_gest_non_trouve"][:10])])
            writer.writerow(["cb_user non trouvés", ", ".join(result["cb_user_non_trouve"][:10])])
            writer.writerow([])
            writer.writerow(["Vérification cb_fo_disp + cb_fo_util = cb_capafo"])
            writer.writerow(["Nombre d'incohérences", result["nb_incoherents_fo"]])
            writer.writerow(["cb_code", "cb_fo_disp", "cb_fo_util", "cb_capafo", "Somme disp+util"])
            for _, row in incoherents_fo.iterrows():
                cb_code = row.get("cb_code", "Inconnu")
                writer.writerow([cb_code, row['cb_fo_disp'], row['cb_fo_util'], row['cb_capafo'], row['sum_disp_util']])
            writer.writerow([])
            writer.writerow(["Vérification cb_codeext"])
            writer.writerow(["Nombre de valeurs invalides", result["nb_cb_codeext_invalides"]])
            writer.writerow([])
            writer.writerow(["Unicité de cb_code"])
            writer.writerow(["Total", total_cb_code])
            writer.writerow(["Taux unique (%)", f"{cb_code_unique_rate}%"])
            writer.writerow(["Doublons (max 10)", ", ".join(duplicated_cb_code[:10]) or "Aucun"])

        # HTML
        def html_voir_plus(liste):
            if not liste:
                return "Aucune"
            html = ", ".join(liste[:10])
            if len(liste) > 10:
                html += (
                    "<span class=\"voir-plus\" onclick=\"this.nextElementSibling.style.display='inline'; this.style.display='none';\">... Voir plus</span>"
                    f"<span style=\"display:none;\">, {', '.join(liste[10:])}</span>"
                )
            return html

        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Analyse câble - {export_date}</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 20px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ddd; padding: 8px; }}
th {{ background-color: #f2f2f2; }}
tr:nth-child(even) {{ background-color: #f9f9f9; }}
.voir-plus {{ color: blue; cursor: pointer; text-decoration: underline; }}
</style></head><body>
<h1>Analyse de la table câble – {export_date}</h1>

<h2>1. cb_prop / cb_gest / cb_user non trouvés dans or_code</h2>
<table>
<tr><th>Champ</th><th>Codes non trouvés</th></tr>
<tr><td>cb_prop</td><td>{html_voir_plus(result["cb_prop_non_trouve"])}</td></tr>
<tr><td>cb_gest</td><td>{html_voir_plus(result["cb_gest_non_trouve"])}</td></tr>
<tr><td>cb_user</td><td>{html_voir_plus(result["cb_user_non_trouve"])}</td></tr>
</table>

<h2>2. Incohérences cb_fo_disp + cb_fo_util ≠ cb_capafo</h2>
<p>Nombre de lignes incohérentes : <strong>{result["nb_incoherents_fo"]}</strong></p>
<table>
<thead><tr>
<th>cb_code</th><th>cb_fo_disp</th><th>cb_fo_util</th><th>cb_capafo</th><th>Somme disp+util</th>
</tr></thead><tbody>{result["incoherents_fo_html"]}</tbody></table>

<h2>3. Valeurs incorrectes dans cb_codeext</h2>
<p>Nombre de lignes avec cb_codeext invalide : <strong>{result["nb_cb_codeext_invalides"]}</strong></p>

<h2>4. Unicité de cb_code</h2>
<table>
<tr><th>Total</th><th>Taux (%)</th><th>Doublons</th></tr>
<tr><td>{total_cb_code}</td><td>{cb_code_unique_rate}%</td><td>{html_voir_plus(duplicated_cb_code)}</td></tr>
</table>
</body></html>""")

        result["csv_path"] = f"/static/exports/{csv_filename}"
        result["html_path"] = f"/static/exports/{html_filename}"
        return jsonify(result)

    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "traceback": traceback.format_exc()}), 500


#cohérence table t_conduite
@app.route('/analyze_conduite_organisme', methods=['POST'])
def analyze_conduite_organisme():
    try:
        data = request.get_json()
        export_date = data.get('export_date')
        if not export_date:
            return jsonify({"error": "Date d'export non spécifiée"}), 400

        # Construction des noms
        table_conduite = f"{export_date}_t_conduite.csv"
        table_organisme = f"{export_date}_t_organisme.csv"

        # Chargement des tables
        df_conduite = pd.read_sql(f'SELECT * FROM "{table_conduite}"', engine)
        df_organisme = pd.read_sql(f'SELECT * FROM "{table_organisme}"', engine)

        # Analyse unicité cd_code
        df_conduite['cd_code'] = df_conduite['cd_code'].astype(str).str.strip().replace({'nan':'', 'none':''})
        total_cd_code = df_conduite['cd_code'].dropna().shape[0]
        dup_cd_code = df_conduite[df_conduite.duplicated('cd_code', keep=False)]
        duplicated_cd_code = dup_cd_code['cd_code'].dropna().unique().tolist()
        cd_code_unique_rate = round((total_cd_code - len(duplicated_cd_code)) / total_cd_code * 100, 2) if total_cd_code else 100

        # Analyse unicité or_code
        df_organisme['or_code'] = df_organisme['or_code'].astype(str).str.strip().replace({'nan':'', 'none':''})
        total_or_code = df_organisme['or_code'].dropna().shape[0]
        dup_or_code = df_organisme[df_organisme.duplicated('or_code', keep=False)]
        duplicated_or_code = dup_or_code['or_code'].dropna().unique().tolist()
        or_code_unique_rate = round((total_or_code - len(duplicated_or_code)) / total_or_code * 100, 2) if total_or_code else 100


        # Normalisation des noms de colonnes et des valeurs
        df_conduite.columns = df_conduite.columns.str.lower().str.strip()
        df_organisme.columns = df_organisme.columns.str.lower().str.strip()

        def clean(val): return str(val).strip().lower()

        df_conduite = df_conduite.applymap(clean)
        df_organisme = df_organisme.applymap(clean)

        # Liste des codes OR existants
        or_codes = df_organisme['or_code'].dropna().unique()

        # Vérifications
        non_trouve_cd_prop = df_conduite[~df_conduite['cd_prop'].isin(or_codes)]['cd_prop'].dropna().unique().tolist()
        non_trouve_cd_gest = df_conduite[~df_conduite['cd_gest'].isin(or_codes)]['cd_gest'].dropna().unique().tolist()
        non_trouve_cd_user = df_conduite[~df_conduite['cd_user'].isin(or_codes)]['cd_user'].dropna().unique().tolist()

        result = {
            "status": "success",
            "export_date": export_date,
            "cd_prop_non_trouve": non_trouve_cd_prop,
            "cd_gest_non_trouve": non_trouve_cd_gest,
            "cd_user_non_trouve": non_trouve_cd_user,
            "total_cd_code": total_cd_code,
            "cd_code_unique_rate": cd_code_unique_rate,
            "duplicated_cd_code": duplicated_cd_code,
            "total_or_code": total_or_code,
            "or_code_unique_rate": or_code_unique_rate,
            "duplicated_or_code": duplicated_or_code

        }

        # Export CSV + HTML
        export_dir = os.path.join("static", "exports")
        os.makedirs(export_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        csv_filename = f"Analyse_Conduite_Organisme_{export_date}_{timestamp}.csv"
        csv_path = os.path.join(export_dir, csv_filename)

        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow(["Analyse des cb_* dans t_conduite", export_date])
            writer.writerow([])
            writer.writerow(["Champ", "Valeurs non trouvées"])
            writer.writerow(["cd_prop", ", ".join(non_trouve_cd_prop[:10]) or "Aucune"])
            writer.writerow(["cd_gest", ", ".join(non_trouve_cd_gest[:10]) or "Aucune"])
            writer.writerow(["cd_user", ", ".join(non_trouve_cd_user[:10]) or "Aucune"])
            writer.writerow([])
            writer.writerow(["Unicité des codes"])
            writer.writerow(["Champ", "Total", "Taux unique (%)", "Doublons (max 10)"])
            writer.writerow(["cd_code", total_cd_code, f"{cd_code_unique_rate}%", ", ".join(duplicated_cd_code[:10]) or "Aucun"])
            writer.writerow(["or_code", total_or_code, f"{or_code_unique_rate}%", ", ".join(duplicated_or_code[:10]) or "Aucun"])


        # HTML
        html_filename = f"Analyse_Conduite_Organisme_{export_date}_{timestamp}.html"
        html_path = os.path.join(export_dir, html_filename)

        def html_voir_plus(liste):
            if not liste:
                return "Aucune"
            html = ", ".join(liste[:10])
            if len(liste) > 10:
                html += f"""<span class="voir-plus" onclick="this.nextElementSibling.style.display='inline'; this.style.display='none';">... Voir plus</span>
                <span style="display:none;">, {', '.join(liste[10:])}</span>"""
            return html

        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Analyse t_conduite → t_organisme - {export_date}</title>
    <style>
        body {{ font-family: Arial; margin: 20px; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; }}
        th {{ background-color: #f2f2f2; }}
        .voir-plus {{ color: blue; cursor: pointer; text-decoration: underline; }}
    </style>
</head>
<body>
    <h1>Analyse t_conduite → t_organisme – {export_date}</h1>
    <table>
        <tr><th>Champ</th><th>Codes non trouvés</th></tr>
        <tr><td>cd_prop</td><td>{html_voir_plus(non_trouve_cd_prop)}</td></tr>
        <tr><td>cd_gest</td><td>{html_voir_plus(non_trouve_cd_gest)}</td></tr>
        <tr><td>cd_user</td><td>{html_voir_plus(non_trouve_cd_user)}</td></tr>
    </table>
    <table>
  <thead><tr><th>Champ</th><th>Total</th><th>Taux unique (%)</th><th>Doublons</th></tr></thead>
  <tbody>
    <tr><td>cd_code</td><td>{total_cd_code}</td><td>{cd_code_unique_rate}%</td><td>{html_voir_plus(duplicated_cd_code)}</td></tr>
    <tr><td>or_code</td><td>{total_or_code}</td><td>{or_code_unique_rate}%</td><td>{html_voir_plus(duplicated_or_code)}</td></tr>
  </tbody>
</table>
</body>
</html>""")

        result["csv_path"] = f"/static/exports/{csv_filename}"
        result["html_path"] = f"/static/exports/{html_filename}"

        return jsonify(result)

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }), 500


#cohérence table ebp/baie
@app.route('/analyze_ebp', methods=['POST'])
def analyze_ebp():
    try:
        data = request.get_json()
        export_date = data.get('export_date')
        if not export_date:
            return jsonify({"error": "Date d'export non spécifiée"}), 400

        # Construction des noms de fichiers
        table_ebp = f"{export_date}_t_ebp.csv"
        table_organisme = f"{export_date}_t_organisme.csv"
        table_ptech = f"{export_date}_t_ptech.csv"
        table_reference = f"{export_date}_t_reference.csv"
        table_cassette = f"{export_date}_t_cassette.csv"

        # Chargement des tables
        df_ebp = pd.read_sql(f'SELECT * FROM "{table_ebp}"', engine)
        # Vérification d’unicité de bp_code
        duplicated_bp_code = df_ebp[df_ebp.duplicated(subset='bp_code', keep=False)]['bp_code'].dropna().unique().tolist()

        df_organisme = pd.read_sql(f'SELECT * FROM "{table_organisme}"', engine)
        df_ptech = pd.read_sql(f'SELECT * FROM "{table_ptech}"', engine)
        df_reference = pd.read_sql(f'SELECT * FROM "{table_reference}"', engine)
        df_cassette = pd.read_sql(f'SELECT * FROM "{table_cassette}"', engine)

        # Normalisation des colonnes
        df_ebp.columns = df_ebp.columns.str.lower().str.strip()
        df_organisme.columns = df_organisme.columns.str.lower().str.strip()
        df_ptech.columns = df_ptech.columns.str.lower().str.strip()
        df_reference.columns = df_reference.columns.str.lower().str.strip()
        df_cassette.columns = df_cassette.columns.str.lower().str.strip()

        # Nettoyage des valeurs
        def clean(val):
            return str(val).strip().upper() if pd.notna(val) else val

        for col in df_ebp.columns:
            df_ebp[col] = df_ebp[col].apply(clean)

        for df in [df_organisme, df_ptech, df_reference, df_cassette]:
            for col in df.columns:
                df[col] = df[col].apply(clean)

        # Vérification de bp_codeext
        df_ebp['bp_codeext'] = df_ebp['bp_codeext'].fillna('')
        df_ebp['bp_codeext'] = df_ebp['bp_codeext'].str.strip().str.upper()
        invalid_bp_codeext = df_ebp[~df_ebp['bp_codeext'].isin(['TERRITOIRE', 'HORS TERRITOIRE'])]['bp_codeext'].unique().tolist()

        # Vérification de bp_pt_code
        pt_codes = df_ptech['pt_code'].dropna().unique()
        invalid_bp_pt_code = df_ebp[~df_ebp['bp_pt_code'].isin(pt_codes)]['bp_pt_code'].dropna().unique().tolist()
        bp_pt_code_filled = df_ebp['bp_pt_code'].notna().sum()
        total_rows = len(df_ebp)
        bp_pt_code_fill_rate = round((bp_pt_code_filled / total_rows) * 100, 2) if total_rows else 0

        # Vérification de bp_prop, bp_gest, bp_user
        or_codes = df_organisme['or_code'].dropna().unique()
        invalid_bp_prop = df_ebp[~df_ebp['bp_prop'].isin(or_codes)]['bp_prop'].dropna().unique().tolist()
        invalid_bp_gest = df_ebp[~df_ebp['bp_gest'].isin(or_codes)]['bp_gest'].dropna().unique().tolist()
        invalid_bp_user = df_ebp[~df_ebp['bp_user'].isin(or_codes)]['bp_user'].dropna().unique().tolist()

        # Vérification de bp_rf_code
        rf_codes = df_reference['rf_code'].dropna().unique()
        invalid_bp_rf_code = df_ebp[~df_ebp['bp_rf_code'].isin(rf_codes)]['bp_rf_code'].dropna().unique().tolist()

        # Vérification des BPE sans cassette
        bp_codes = df_ebp['bp_code'].dropna().unique()
        cs_bp_codes = df_cassette['cs_bp_code'].dropna().unique()
        bpe_without_cassette = list(set(bp_codes) - set(cs_bp_codes))
        bpe_without_cassette_count = len(bpe_without_cassette)
        bpe_without_cassette_rate = round((bpe_without_cassette_count / len(bp_codes)) * 100, 2) if bp_codes.size else 0

        # Résultats
        result = {
            "status": "success",
            "export_date": export_date,
            "invalid_bp_codeext": invalid_bp_codeext,
            "invalid_bp_pt_code": invalid_bp_pt_code,
            "bp_pt_code_fill_rate": bp_pt_code_fill_rate,
            "invalid_bp_prop": invalid_bp_prop,
            "invalid_bp_gest": invalid_bp_gest,
            "invalid_bp_user": invalid_bp_user,
            "invalid_bp_rf_code": invalid_bp_rf_code,
            "bpe_without_cassette": bpe_without_cassette,
            "bpe_without_cassette_rate": bpe_without_cassette_rate,
            "duplicated_bp_code": duplicated_bp_code,
            "bp_code_unicity_rate": round((1 - len(duplicated_bp_code) / len(df_ebp['bp_code'].dropna().unique())) * 100, 2) if len(df_ebp['bp_code'].dropna().unique()) else 100

        }
        # Nombre total de BPE (pour le ratio)
        result["total_bp_count"] = len(df_ebp['bp_code'].dropna().unique())


        # Export CSV
        export_dir = os.path.join("static", "exports")
        os.makedirs(export_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_filename = f"Analyse_EBP_{export_date}_{timestamp}.csv"
        csv_path = os.path.join(export_dir, csv_filename)

        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f, delimiter=';')
            writer.writerow(["Analyse de t_ebp", export_date])
            writer.writerow([])
            writer.writerow(["Champ", "Incohérences"])
            writer.writerow(["bp_codeext", ", ".join(invalid_bp_codeext) or "Aucune"])
            writer.writerow(["bp_pt_code", ", ".join(invalid_bp_pt_code) or "Aucune"])
            writer.writerow(["Taux de remplissage bp_pt_code", f"{bp_pt_code_fill_rate}%"])
            writer.writerow(["bp_prop", ", ".join(invalid_bp_prop) or "Aucune"])
            writer.writerow(["bp_gest", ", ".join(invalid_bp_gest) or "Aucune"])
            writer.writerow(["bp_user", ", ".join(invalid_bp_user) or "Aucune"])
            writer.writerow(["bp_rf_code", ", ".join(invalid_bp_rf_code) or "Aucune"])
            writer.writerow(["BPE sans cassette", ", ".join(bpe_without_cassette) or "Aucune"])
            writer.writerow(["Taux de BPE sans cassette", f"{bpe_without_cassette_rate}%"])
            writer.writerow(["bp_code non uniques", ", ".join(duplicated_bp_code) or "Aucune"])
            writer.writerow(["Taux d’unicité de bp_code", f"{result['bp_code_unicity_rate']}%"])


        # Export HTML
        html_filename = f"Analyse_EBP_{export_date}_{timestamp}.html"
        html_path = os.path.join(export_dir, html_filename)

        def html_voir_plus(liste):
            if not liste:
                return "Aucune"
            html = ", ".join(liste[:10])
            if len(liste) > 10:
                html += f"""<span class="voir-plus" onclick="this.nextElementSibling.style.display='inline'; this.style.display='none';">... Voir plus</span>
                <span style="display:none;">, {', '.join(liste[10:])}</span>"""
            return html

        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Analyse t_ebp - {export_date}</title>
    <style>
        body {{ font-family: Arial; margin: 20px; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; }}
        th {{ background-color: #f2f2f2; }}
        .voir-plus {{ color: blue; cursor: pointer; text-decoration: underline; }}
    </style>
</head>
<body>
    <h1>Analyse t_ebp – {export_date}</h1>
    <table>
        <tr><th>Champ</th><th>Incohérences</th></tr>
        <tr><td>bp_code non uniques</td><td>{html_voir_plus(duplicated_bp_code)}</td></tr>
        <tr><td>Taux d’unicité de bp_code</td><td>{result['bp_code_unicity_rate']}%</td></tr>

        <tr><td>bp_codeext</td><td>{html_voir_plus(invalid_bp_codeext)}</td></tr>
        <tr><td>bp_pt_code</td><td>{html_voir_plus(invalid_bp_pt_code)}</td></tr>
        <tr><td>Taux de remplissage bp_pt_code</td><td>{bp_pt_code_fill_rate}%</td></tr>
        <tr><td>bp_prop</td><td>{html_voir_plus(invalid_bp_prop)}</td></tr>
        <tr><td>bp_gest</td><td>{html_voir_plus(invalid_bp_gest)}</td></tr>
        <tr><td>bp_user</td><td>{html_voir_plus(invalid_bp_user)}</td></tr>
        <tr><td>bp_rf_code</td><td>{html_voir_plus(invalid_bp_rf_code)}</td></tr>
        <tr><td>BPE sans cassette</td><td>{html_voir_plus(bpe_without_cassette)}</td></tr>
        <tr><td>Taux de BPE sans cassette</td><td>{bpe_without_cassette_rate}%</td></tr>
    </table>
</body>
</html>""")

        result["csv_path"] = f"/static/exports/{csv_filename}"
        result["html_path"] = f"/static/exports/{html_filename}"

        return jsonify(result)

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }), 500


#cohérence fibre
@app.route('/analyze_fibre_cable', methods=['POST'])
def analyze_fibre_cable():
    try:
        data = request.get_json()
        export_date = data.get('export_date')
        if not export_date:
            return jsonify({"error": "Date d'export non spécifiée"}), 400

        # Tables
        tf = f'{export_date}_t_fibre.csv'
        tc = f'{export_date}_t_cable.csv'

        # Chargement
        df_fibre = pd.read_sql(f'SELECT * FROM "{tf}"', engine)
        df_cable = pd.read_sql(f'SELECT * FROM "{tc}"', engine)

        # Normalisation
        for df in (df_fibre, df_cable):
            df.columns = df.columns.str.lower().str.strip()
        df_fibre['fo_cb_code'] = df_fibre['fo_cb_code'].astype(str).str.strip().str.lower()
        df_cable['cb_code']   = df_cable['cb_code'].astype(str).str.strip().str.lower()
        df_cable['cb_capafo'] = pd.to_numeric(df_cable['cb_capafo'], errors='coerce').fillna(0).astype(int)

        # 1) Total FO_CB_CODE
        total_fo = df_fibre['fo_cb_code'].dropna().shape[0]

        # 2) fo_cb_code sans correspondance
        mask_found = df_fibre['fo_cb_code'].isin(df_cable['cb_code'])
        non_found = df_fibre.loc[~mask_found, 'fo_cb_code'].dropna().unique().tolist()
        count_non_found = len(df_fibre.loc[~mask_found, 'fo_cb_code'])

        # 3) Pour les codes valides : occurrences vs capafo
        df_valid = df_fibre.loc[mask_found, ['fo_cb_code']]
        occ = df_valid['fo_cb_code'].value_counts()  # série code → nombre d’occurrences

        failures = []
        for code, cnt in occ.items():
            capa = int(df_cable.loc[df_cable['cb_code']==code, 'cb_capafo'].iloc[0])
            if cnt != capa:
                failures.append({
                    "code": code,
                    "occurrences": int(cnt),
                    "capafo": capa
                })

        total_tested = occ.shape[0]
        fail_count  = len(failures)
        success_count = total_tested - fail_count
        success_rate  = round(success_count/total_tested*100,2) if total_tested else 0
        failure_rate  = round(fail_count/total_tested*100,2) if total_tested else 0

        # Analyse de l'unicité de fo_code
        df_fibre['fo_code'] = df_fibre['fo_code'].astype(str).str.strip().str.lower()
        total_fibres = df_fibre.shape[0]
        unique_fo_codes = df_fibre['fo_code'].nunique()
        duplicate_fo_codes = df_fibre['fo_code'].duplicated(keep=False)
        fo_code_duplicates = df_fibre.loc[duplicate_fo_codes, 'fo_code'].unique().tolist()


        # Préparer le résultat
        result = {
            "status": "success",
            "export_date": export_date,
            "total_fo": total_fo,
            "non_found_count": count_non_found,
            "non_found_list": non_found,
            "total_tested": total_tested,
            "failures": failures,
            "success_rate": success_rate,
            "failure_rate": failure_rate,
            "total_fibres": total_fibres,
            "unique_fo_codes": unique_fo_codes,
            "fo_code_duplicates": fo_code_duplicates
        }

        # Export CSV
        export_dir = os.path.join("static","exports"); os.makedirs(export_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_fn = f"Analyse_Fibre_Cable_{export_date}_{ts}.csv"
        csv_p  = os.path.join(export_dir, csv_fn)
        with open(csv_p,'w',newline='',encoding='utf-8') as f:
            w = csv.writer(f, delimiter=';')
            w.writerow(["Analyse t_fibre → t_cable", export_date])
            w.writerow([])
            w.writerow(["Total FO_CB_CODE", total_fo])
            w.writerow(["Sans correspondance", count_non_found])
            w.writerow(["Valeurs"])
            w.writerow(non_found[:10] + (["..."] if len(non_found)>10 else []))
            w.writerow([])
            w.writerow(["Total codes testés", total_tested])
            w.writerow(["Succès (%)", f"{success_rate}%"])
            w.writerow(["Échec (%)", f"{failure_rate}%"])
            w.writerow([])
            w.writerow(["Échecs détaillés (code; occurrences; capafo)"])
            for f_ in failures[:10]:
                w.writerow([f_["code"], f_["occurrences"], f_["capafo"]])
            if len(failures)>10:
                w.writerow(["... et", len(failures)-10, "autres"])
            w.writerow([])
            w.writerow(["Analyse unicité fo_code"])
            w.writerow(["Total fibres", total_fibres])
            w.writerow(["fo_code uniques", unique_fo_codes])
            w.writerow(["fo_code en doublon"])
            w.writerow(fo_code_duplicates[:10] + (["..."] if len(fo_code_duplicates) > 10 else []))

        result["csv_path"] = f"/static/exports/{csv_fn}"

        # Export HTML
        html_fn = f"Analyse_Fibre_Cable_{export_date}_{ts}.html"
        html_p  = os.path.join(export_dir, html_fn)
        def render_list(l):
            if not l: return "Aucune"
            vis = l[:10]
            more = l[10:]
            s = ", ".join(map(str,vis))
            if more:
                s += f"<span class='voir-plus' onclick=\"this.nextElementSibling.style.display='inline';this.style.display='none';\">... Voir plus</span>"
                s += f"<span style='display:none'>, {', '.join(map(str,more))}</span>"
            return s

        def render_failures(fl):
            if not fl: return "<tr><td colspan=3>Aucun</td></tr>"
            rows=[]
            for f_ in fl[:10]:
                rows.append(f"<tr><td>{f_['code']}</td><td>{f_['occurrences']}</td><td>{f_['capafo']}</td></tr>")
            if len(fl)>10:
                rows.append(f"<tr><td colspan=3>... {len(fl)-10} autres</td></tr>")
            return "\n".join(rows)

        with open(html_p,'w',encoding='utf-8') as f:
            f.write(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Analyse Fibre-Cable – {export_date}</title>
<style>
body{{font-family:Arial;margin:20px}}table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ddd;padding:8px}}th{{background:#f2f2f2}}
.voir-plus{{color:blue;cursor:pointer;text-decoration:underline}}
</style></head><body>
            <h2>Unicité des fo_code</h2>
        <p>Total fibres : <strong>{total_fibres}</strong>, codes uniques : <strong>{unique_fo_codes}</strong></p>
        <p>{render_list(fo_code_duplicates)}</p>


  <h1>Analyse t_fibre → t_cable – {export_date}</h1>
  <h2>1. FO_CB_CODE</h2>
  <p>Total : <strong>{total_fo}</strong>, sans correspondance : <strong>{count_non_found}</strong></p>
  <p>{render_list(non_found)}</p>
  <h2>2. Occurrences vs cb_capafo</h2>
  <p>Testés : <strong>{total_tested}</strong> &nbsp; Succès : <strong>{success_rate}%</strong> &nbsp; Échec : <strong>{failure_rate}%</strong></p>
  <table><thead><tr><th>Code</th><th>Occurrences</th><th>Capafo</th></tr></thead><tbody>
    {render_failures(failures)}
  </tbody></table>
</body></html>""")
        result["html_path"] = f"/static/exports/{html_fn}"

        return jsonify(result)

    except Exception as e:
        return jsonify({"status":"error","message":str(e),"traceback":traceback.format_exc()}),500


#conhérence table t_position
@app.route('/analyze_position', methods=['POST'])
def analyze_position():
    try:
        data       = request.get_json()
        export_date= data.get('export_date')
        if not export_date:
            return jsonify({"error": "Date d'export non spécifiée"}), 400

        # Noms de tables
        tbl_pos    = f"{export_date}_t_position.csv"
        tbl_fibre  = f"{export_date}_t_fibre.csv"
        tbl_cass   = f"{export_date}_t_cassette.csv"

        # Chargement
        df_pos    = pd.read_sql(f'SELECT * FROM "{tbl_pos}"', engine)

        # Analyse d’unicité pour ps_code
        df_pos['ps_code'] = df_pos['ps_code'].astype(str).str.strip().str.lower()
        total_ps_code = len(df_pos)
        unique_ps_code = df_pos['ps_code'].nunique()
        duplicated_codes = df_pos[df_pos.duplicated('ps_code', keep=False)]['ps_code'].value_counts().reset_index()
        duplicated_codes.columns = ['ps_code', 'count']
        dupli_list = duplicated_codes.to_dict(orient='records')

        df_fibre  = pd.read_sql(f'SELECT * FROM "{tbl_fibre}"', engine)
        df_cass   = pd.read_sql(f'SELECT * FROM "{tbl_cass}"', engine)

        # Normalisation noms colonnes
        for df in (df_pos, df_fibre, df_cass):
            df.columns = df.columns.str.lower().str.strip()

        # Normalisation valeurs (string)
        for col in ['ps_1','ps_2','ps_cs_code']:
            df_pos[col] = df_pos[col].astype(str).str.strip().str.lower()
        df_fibre['fo_code']     = df_fibre['fo_code'].astype(str).str.strip().str.lower()
        df_cass['cs_code']      = df_cass['cs_code'].astype(str).str.strip().str.lower()

        # Totaux et taux de remplissage
        total_rows = len(df_pos)
        filled = lambda col: df_pos[col].replace({'nan':'','none':''}).dropna().map(lambda x: x!='').sum()
        fill_ps1   = filled('ps_1')
        fill_ps2   = filled('ps_2')
        fill_cs    = filled('ps_cs_code')
        pct_ps1    = round(fill_ps1/total_rows*100,2) if total_rows else 0
        pct_ps2    = round(fill_ps2/total_rows*100,2) if total_rows else 0
        pct_cs     = round(fill_cs/total_rows*100,2)  if total_rows else 0

        # Existence de ps_1 et ps_2 dans fo_code
        mask1      = df_pos['ps_1'].isin(df_fibre['fo_code'])
        mask2      = df_pos['ps_2'].isin(df_fibre['fo_code'])
        missing_ps1= df_pos.loc[~mask1,'ps_1'].dropna().unique().tolist()
        missing_ps2= df_pos.loc[~mask2,'ps_2'].dropna().unique().tolist()

        # Existence de ps_cs_code dans cs_code
        mask_cs    = df_pos['ps_cs_code'].isin(df_cass['cs_code'])
        missing_cs = df_pos.loc[~mask_cs,'ps_cs_code'].dropna().unique().tolist()
        missing_cs_count = df_pos.loc[~mask_cs,'ps_cs_code'].dropna().shape[0]
        missing_cs_pct   = round(missing_cs_count / total_rows * 100, 2) if total_rows else 0

        # Résultat JSON
        result = {
            "status": "success",
            "export_date": export_date,
            "total_rows": total_rows,
            "fill_ps1": fill_ps1,
            "pct_ps1": pct_ps1,
            "fill_ps2": fill_ps2,
            "pct_ps2": pct_ps2,
            "fill_cs": fill_cs,
            "pct_cs": pct_cs,
            "missing_ps1": missing_ps1,
            "missing_ps2": missing_ps2,
            "missing_cs": missing_cs,
            "missing_cs_count": int(missing_cs_count),
            "missing_cs_pct": float(missing_cs_pct),
            "total_ps_code": total_ps_code,
            "unique_ps_code": unique_ps_code,
            "duplicated_ps_code": dupli_list

        }

        for key, val in result.items():
            if isinstance(val, (np.integer, )):
                result[key] = int(val)
            elif isinstance(val, (np.floating, )):
                result[key] = float(val)
            elif isinstance(val, np.ndarray):
                result[key] = val.tolist()

        # --- Export CSV ---
        export_dir = os.path.join("static","exports"); os.makedirs(export_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_fn = f"Analyse_Position_{export_date}_{ts}.csv"
        csv_p  = os.path.join(export_dir, csv_fn)
        with open(csv_p,'w',newline='',encoding='utf-8') as f:
            w=csv.writer(f,delimiter=';')
            w.writerow(["📌 Unicité des ps_code"])
            w.writerow(["Total ps_code", total_ps_code])
            w.writerow(["Valeurs uniques", unique_ps_code])
            w.writerow(["ps_code en doublon", "Occurrences"])
            for row in dupli_list[:10]:
                w.writerow([row['ps_code'], row['count']])
            if len(dupli_list) > 10:
                w.writerow(["...", "..."])
            w.writerow([])
            w.writerow([f"Analyse position – {export_date}"])
            w.writerow([])
            w.writerow(["Total de lignes", total_rows])
            w.writerow([])
            w.writerow(["Champ","Remplis","Taux (%)"])
            w.writerow(["ps_1", fill_ps1, f"{pct_ps1}%"])
            w.writerow(["ps_2", fill_ps2, f"{pct_ps2}%"])
            w.writerow(["ps_cs_code", fill_cs,  f"{pct_cs}%"])
            w.writerow([])
            w.writerow(["📌 Valeurs PS non présentes dans t_fibre.fo_code"])
            w.writerow(["ps_1 manquants", ", ".join(missing_ps1[:10]) or "Aucun"])
            w.writerow(["ps_2 manquants", ", ".join(missing_ps2[:10]) or "Aucun"])
            w.writerow([])
            w.writerow(["📌 Valeurs PS_CS_CODE non présentes dans t_cassette.cs_code"])
            w.writerow(["ps_cs_code manquants", ", ".join(missing_cs[:10]) or "Aucun"])
            w.writerow(["Nombre manquants ps_cs_code", missing_cs_count, f"{missing_cs_pct}%"])
        result["csv_path"] = f"/static/exports/{csv_fn}"

        # --- Export HTML ---
        html_fn = f"Analyse_Position_{export_date}_{ts}.html"
        html_p  = os.path.join(export_dir, html_fn)
        def render(l):
            if not l: return "Aucun"
            v = l[:10]; m = l[10:]
            s = ", ".join(v)
            if m:
                s+=f"<span class='voir-plus' onclick=\"this.nextElementSibling.style.display='inline';this.style.display='none';\">... Voir plus</span>"
                s+=f"<span style='display:none'>, {', '.join(m)}</span>"
            return s

        with open(html_p,'w',encoding='utf-8') as f:
            f.write(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Analyse position – {export_date}</title>
<style>
 body{{font-family:Arial;margin:20px}}
 table{{border-collapse:collapse;width:100%}}
 th,td{{border:1px solid #ddd;padding:8px}}
 th{{background:#f2f2f2}}
 .voir-plus{{color:blue;cursor:pointer;text-decoration:underline}}
</style></head><body>
<h2>0. Unicité des ps_code</h2>
<p>Total : <strong>{total_ps_code}</strong> — Uniques : <strong>{unique_ps_code}</strong></p>
<table>
  <thead><tr><th>ps_code</th><th>Occurrences</th></tr></thead>
  <tbody>
    {''.join(f"<tr><td>{row['ps_code']}</td><td>{row['count']}</td></tr>" for row in dupli_list[:10])}
    {'<tr><td colspan=2>... autres</td></tr>' if len(dupli_list)>10 else ''}
  </tbody>
</table>

  <h1>Analyse position – {export_date}</h1>

  <h2>1. Taux de remplissage</h2>
  <table>
    <thead><tr><th>Champ</th><th>Remplis</th><th>Taux (%)</th></tr></thead>
    <tbody>
      <tr><td>ps_1</td><td>{fill_ps1}</td><td>{pct_ps1}%</td></tr>
      <tr><td>ps_2</td><td>{fill_ps2}</td><td>{pct_ps2}%</td></tr>
      <tr><td>ps_cs_code</td><td>{fill_cs}</td><td>{pct_cs}%</td></tr>
    </tbody>
  </table>

  <h2>2. Existence dans t_fibre.fo_code</h2>
  <table>
    <thead><tr><th>Champ</th><th>Valeurs manquantes</th></tr></thead>
    <tbody>
      <tr><td>ps_1</td><td>{render(missing_ps1)}</td></tr>
      <tr><td>ps_2</td><td>{render(missing_ps2)}</td></tr>
    </tbody>
  </table>

  <h2>3. Existence de ps_cs_code dans t_cassette.cs_code</h2>
  <table>
    <thead><tr><th>ps_cs_code manquants</th></tr></thead>
    <tbody>
      <tr><td><p>Total lignes : <strong>{total_rows}</strong> — Manquants : <strong>{missing_cs_count}</strong> (<strong>{missing_cs_pct}%</strong>)</p>
<p>{render(missing_cs)}</p>
</td></tr>
    </tbody>
  </table>
</body></html>""")
        result["html_path"] = f"/static/exports/{html_fn}"

        return jsonify(result)

    except Exception as e:
        return jsonify({"status":"error","message":str(e),"traceback":traceback.format_exc()}),500


#cohérence table t_ltech
@app.route('/analyze_ltech', methods=['POST'])
def analyze_ltech():
    try:
        data = request.get_json()
        export_date = data.get('export_date')
        if not export_date:
            return jsonify({"error": "Date d'export non spécifiée"}), 400

        # noms des tables
        table_ltech    = f'{export_date}_t_ltech.csv'
        table_sitetech = f'{export_date}_t_sitetech.csv'
        table_org      = f'{export_date}_t_organisme.csv'

        # chargement
        df_ltech    = pd.read_sql(f'SELECT * FROM "{table_ltech}"', engine)
        df_sitetech = pd.read_sql(f'SELECT * FROM "{table_sitetech}"', engine)
        df_org      = pd.read_sql(f'SELECT * FROM "{table_org}"', engine)

        # normalisation colonnes
        for df in (df_ltech, df_sitetech, df_org):
            df.columns = df.columns.str.lower().str.strip()

        # normalisation valeurs
        df_ltech['lt_st_code'] = df_ltech['lt_st_code'].astype(str).str.strip().str.lower()
        for c in ['lt_prop','lt_gest','lt_user']:
            df_ltech[c] = df_ltech[c].astype(str).str.strip().str.lower()
        df_sitetech['st_code'] = df_sitetech['st_code'].astype(str).str.strip().str.lower()
        df_org['or_code']      = df_org['or_code'].astype(str).str.strip().str.lower()

        total_rows = len(df_ltech)

        # 1) st_code
        mask_st = df_ltech['lt_st_code'].isin(df_sitetech['st_code'])
        st_missing_list  = df_ltech.loc[~mask_st,'lt_st_code'].dropna().unique().tolist()
        st_missing_count = int(df_ltech.loc[~mask_st,'lt_st_code'].dropna().shape[0])
        st_missing_pct   = round(st_missing_count/total_rows*100, 2) if total_rows else 0

        # 2) prop
        mask_prop = df_ltech['lt_prop'].isin(df_org['or_code'])
        prop_missing_list  = df_ltech.loc[~mask_prop,'lt_prop'].dropna().unique().tolist()
        prop_missing_count = int(df_ltech.loc[~mask_prop,'lt_prop'].dropna().shape[0])
        prop_missing_pct   = round(prop_missing_count/total_rows*100, 2) if total_rows else 0

        # 3) gest
        mask_gest = df_ltech['lt_gest'].isin(df_org['or_code'])
        gest_missing_list  = df_ltech.loc[~mask_gest,'lt_gest'].dropna().unique().tolist()
        gest_missing_count = int(df_ltech.loc[~mask_gest,'lt_gest'].dropna().shape[0])
        gest_missing_pct   = round(gest_missing_count/total_rows*100, 2) if total_rows else 0

        # 4) user
        mask_user = df_ltech['lt_user'].isin(df_org['or_code'])
        user_missing_list  = df_ltech.loc[~mask_user,'lt_user'].dropna().unique().tolist()
        user_missing_count = int(df_ltech.loc[~mask_user,'lt_user'].dropna().shape[0])
        user_missing_pct   = round(user_missing_count/total_rows*100, 2) if total_rows else 0

        # --- Analyse unicité lt_code ---
        df_ltech['lt_code'] = df_ltech['lt_code'].astype(str).str.strip().str.lower()
        total_lt_code = len(df_ltech)
        unique_lt_code = df_ltech['lt_code'].nunique()
        duplicated_lt_codes = df_ltech[df_ltech.duplicated('lt_code', keep=False)]['lt_code'].value_counts().reset_index()
        duplicated_lt_codes.columns = ['lt_code', 'count']
        dupli_lt_list = duplicated_lt_codes.to_dict(orient='records')


        # préparer le résultat
        result = {
            "status": "success",
            "export_date": export_date,
            "total_rows": total_rows,

            "st_missing_count": st_missing_count,
            "st_missing_pct": st_missing_pct,
            "st_missing_list": st_missing_list,

            "prop_missing_count": prop_missing_count,
            "prop_missing_pct": prop_missing_pct,
            "prop_missing_list": prop_missing_list,

            "gest_missing_count": gest_missing_count,
            "gest_missing_pct": gest_missing_pct,
            "gest_missing_list": gest_missing_list,

            "user_missing_count": user_missing_count,
            "user_missing_pct": user_missing_pct,
            "user_missing_list": user_missing_list,

            "total_lt_code": total_lt_code,
            "unique_lt_code": unique_lt_code,
            "duplicated_lt_code": dupli_lt_list

        }

        # convertir numpy types en natifs
        for k,v in result.items():
            if isinstance(v, (np.integer,)):
                result[k] = int(v)
            elif isinstance(v, (np.floating,)):
                result[k] = float(v)
            elif isinstance(v, np.ndarray):
                result[k] = v.tolist()

        # export CSV + HTML
        export_dir = os.path.join('static','exports')
        os.makedirs(export_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        # CSV
        csv_fn = f"Analyse_LTech_{export_date}_{ts}.csv"
        csv_p  = os.path.join(export_dir, csv_fn)
        with open(csv_p, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f, delimiter=';')
            w.writerow([f"Analyse t_ltech", export_date])
            w.writerow([])
            w.writerow(["Total de lignes", total_rows])
            w.writerow([])
            w.writerow(["Champ", "Manquants", "Pourcentage"])
            w.writerow(["lt_st_code", st_missing_count, f"{st_missing_pct}%"])
            w.writerow(["lt_prop",    prop_missing_count, f"{prop_missing_pct}%"])
            w.writerow(["lt_gest",    gest_missing_count, f"{gest_missing_pct}%"])
            w.writerow(["lt_user",    user_missing_count, f"{user_missing_pct}%"])
            w.writerow([])
            w.writerow(["📌 Unicité des lt_code"])
            w.writerow(["Total lt_code", total_lt_code])
            w.writerow(["Valeurs uniques", unique_lt_code])
            w.writerow(["lt_code en doublon", "Occurrences"])
            for row in dupli_lt_list[:10]:
                w.writerow([row['lt_code'], row['count']])
            if len(dupli_lt_list) > 10:
                w.writerow(["...", "..."])

        result["csv_path"] = f"/static/exports/{csv_fn}"

        # HTML
        def render_list(lst):
            if not lst:
                return "Aucun"
            vis = lst[:10]
            more = lst[10:]
            s = ", ".join(vis)
            if more:
                s += (
                  "<span class='voir-plus' onclick="
                  "this.nextElementSibling.style.display='inline';this.style.display='none';"
                  ">... Voir plus</span>"
                  f"<span style='display:none'>, {', '.join(more)}</span>"
                )
            return s

        html_fn = f"Analyse_LTech_{export_date}_{ts}.html"
        html_p  = os.path.join(export_dir, html_fn)
        with open(html_p, 'w', encoding='utf-8') as f:
            f.write(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Analyse t_ltech – {export_date}</title>
<style>
 body {{font-family:Arial;margin:20px}}
 table {{border-collapse:collapse;width:100%}}
 th,td {{border:1px solid #ddd;padding:8px}}
 th {{background:#f2f2f2}}
 .voir-plus {{color:blue;cursor:pointer;text-decoration:underline}}
</style></head><body>
  <h2>Unicité des lt_code</h2>
  <p>Total : <strong>{total_lt_code}</strong> — Uniques : <strong>{unique_lt_code}</strong></p>
  <table>
    <thead><tr><th>lt_code</th><th>Occurrences</th></tr></thead>
    <tbody>
      {''.join(f"<tr><td>{r['lt_code']}</td><td>{r['count']}</td></tr>" for r in dupli_lt_list[:10])}
      {"<tr><td colspan='2'>... autres</td></tr>" if len(dupli_lt_list) > 10 else ''}
    </tbody>
  </table>

  <h1>Analyse t_ltech – {export_date}</h1>
   <table>
    <tr><th>Champ</th><th>Manquants/Total</th><th>Pourcentage</th></tr>
    <tr><td>lt_st_code</td><td>{st_missing_count}/{total_rows}</td><td>{st_missing_pct}%</td></tr>
    <tr><td>lt_prop</td><td>{prop_missing_count}/{total_rows}</td><td>{prop_missing_pct}%</td></tr>
    <tr><td>lt_gest</td><td>{gest_missing_count}/{total_rows}</td><td>{gest_missing_pct}%</td></tr>
    <tr><td>lt_user</td><td>{user_missing_count}/{total_rows}</td><td>{user_missing_pct}%</td></tr>
  </table>


  <h2>Détails des valeurs manquantes</h2>
  <table>
    <tr><th>Champ</th><th>Valeurs</th></tr>
    <tr><td>lt_st_code</td><td>{render_list(st_missing_list)}</td></tr>
    <tr><td>lt_prop</td><td>{render_list(prop_missing_list)}</td></tr>
    <tr><td>lt_gest</td><td>{render_list(gest_missing_list)}</td></tr>
    <tr><td>lt_user</td><td>{render_list(user_missing_list)}</td></tr>
  </table>
</body></html>""")
        result["html_path"] = f"/static/exports/{html_fn}"

        return jsonify(result)

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }), 500

#cohérence table t_ptech

    """
    Charge la table dont le nom est f"{export_date}_{suffix_with_ext}".
    Si cette table n'existe pas, bascule sur l'autre extension (.csv ↔ .dbf).
    """
    table1 = f"{export_date}_{suffix_with_ext}"
    if suffix_with_ext.lower().endswith('.csv'):
        table2 = table1[:-4] + '.dbf'
    else:
        table2 = table1[:-4] + '.csv'

    try:
        return pd.read_sql(f'SELECT * FROM "{table1}"', engine)
    except Exception:
        return pd.read_sql(f'SELECT * FROM "{table2}"', engine)


#cohérence table t_ptech
@app.route('/analyze_ptech', methods=['POST'])
def analyze_ptech():
    try:
        data        = request.get_json()
        export_date = data.get('export_date')
        if not export_date:
            return jsonify({"error": "Date d'export non spécifiée"}), 400

        # Chargement avec fallback .csv/.dbf
        df      = read_table(export_date, 't_ptech.csv')
        df_nd   = read_table(export_date, 't_noeud.csv')
        df_org  = read_table(export_date, 't_organisme.csv')
        df_addr = read_table(export_date, 't_adresse.csv')

        # Normalisation noms de colonnes
        for d in (df, df_nd, df_org, df_addr):
            d.columns = d.columns.str.lower().str.strip()

        # Normalisation des valeurs
        df['pt_codeext'] = df['pt_codeext'].astype(str).str.strip().str.upper()
        for c in ['pt_nd_code','pt_prop','pt_gest','pt_user','pt_nature']:
            df[c] = df[c].astype(str).str.strip().str.lower()

        df_nd['nd_code']   = df_nd['nd_code'].astype(str).str.strip().str.lower()
        df_org['or_code']  = df_org['or_code'].astype(str).str.strip().str.lower()
        df_addr['ad_code'] = df_addr['ad_code'].astype(str).str.strip().str.lower()

        total = len(df)

        unicite = {
            "total": total,
            "remplis": 0,
            "uniques": 0,
            "doublons": [],
        }
        if 'pt_code' in df.columns:
            df['pt_code'] = df['pt_code'].astype(str).str.strip().str.lower()
            unicite["remplis"]  = df['pt_code'].replace({'nan':'','none':''}).map(lambda x: x!='').sum()
            unicite["uniques"]  = df['pt_code'].loc[lambda s: s != ''].nunique()
            counts              = df['pt_code'].value_counts()
            unicite["doublons"] = counts[counts > 1].index[:10].tolist()
        else:
            unicite["erreur"] = "Colonne pt_code absente"

        # 1) PT_CODEEXT
        valid_ext     = {"TERRITOIRE", "HORS TERRITOIRE"}
        bad_ext_mask  = ~df['pt_codeext'].isin(valid_ext)
        bad_ext       = df.loc[bad_ext_mask, 'pt_codeext'].dropna().unique().tolist()
        bad_ext_count = int(bad_ext_mask.sum())
        bad_ext_pct   = round(bad_ext_count / total * 100, 2) if total else 0

        # 2) pt_nd_code ∈ noeud.nd_code
        mask_nd       = df['pt_nd_code'].isin(df_nd['nd_code'])
        nd_bad        = df.loc[~mask_nd, 'pt_nd_code'].dropna().unique().tolist()
        nd_bad_count  = int((~mask_nd).sum())
        nd_bad_pct    = round(nd_bad_count / total * 100, 2) if total else 0

        # 3) pt_prop / pt_gest / pt_user ∈ org.or_code
        def check(col):
            m   = df[col].isin(df_org['or_code'])
            bad = df.loc[~m, col].dropna().unique().tolist()
            cnt = int((~m).sum())
            pct = round(cnt / total * 100, 2) if total else 0
            return bad, cnt, pct

        prop_bad, prop_cnt, prop_pct = check('pt_prop')
        gest_bad, gest_cnt, gest_pct = check('pt_gest')
        user_bad, user_cnt, user_pct = check('pt_user')

        # 4) pt_nature vide ?
        nat_fill   = df['pt_nature'].replace({'nan':'','none':''}).dropna().map(bool).sum()
        nat_empty  = total - nat_fill
        nat_pct    = round(nat_empty / total * 100, 2) if total else 0

        # 5) pt_ad_code ∈ adresse.ad_code
        mask_ad      = df['pt_ad_code'].isin(df_addr['ad_code'])
        ad_bad       = df.loc[~mask_ad, 'pt_ad_code'].dropna().unique().tolist()
        ad_bad_count = int((~mask_ad).sum())
        ad_bad_pct   = round(ad_bad_count / total * 100, 2) if total else 0

        
        # Résultat
        result = {
            "status":       "success",
            "export_date":  export_date,
            "total":        total,

            "bad_ext":        bad_ext,
            "bad_ext_count":  bad_ext_count,
            "bad_ext_pct":    bad_ext_pct,

            "nd_bad":         nd_bad,
            "nd_bad_count":   nd_bad_count,
            "nd_bad_pct":     nd_bad_pct,

            "prop_bad":       prop_bad,
            "prop_cnt":       prop_cnt,
            "prop_pct":       prop_pct,

            "gest_bad":       gest_bad,
            "gest_cnt":       gest_cnt,
            "gest_pct":       gest_pct,

            "user_bad":       user_bad,
            "user_cnt":       user_cnt,
            "user_pct":       user_pct,

            "nat_empty":      nat_empty,
            "nat_pct":        nat_pct,

            "ad_bad":         ad_bad,
            "ad_bad_count":   ad_bad_count,
            "ad_bad_pct":     ad_bad_pct,
            "unicite_pt_code" : unicite

        }

        # Conversion numpy → natifs
        import numpy as np
        for k, v in list(result.items()):
            if isinstance(v, np.integer):    result[k] = int(v)
            elif isinstance(v, np.floating): result[k] = float(v)
            elif isinstance(v, np.ndarray):  result[k] = v.tolist()

        # export CSV
        d = os.path.join('static','exports'); os.makedirs(d,exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fn = f"Analyse_PTech_{export_date}_{ts}.csv"
        p  = os.path.join(d,fn)
        with open(p,'w',newline='',encoding='utf-8') as f:
            w=csv.writer(f,delimiter=';')
            w.writerow([f"Analyse t_ptech",export_date]); w.writerow([])
            w.writerow(["Total lignes", total]); w.writerow([])
            w.writerow(["PT_CODEEXT invalides", bad_ext_count, f"{bad_ext_pct}%"])
            w.writerow(["pt_nd_code invalides", nd_bad_count, f"{nd_bad_pct}%"])
            w.writerow(["pt_prop invalides", prop_cnt, f"{prop_pct}%"])
            w.writerow(["pt_gest invalides", gest_cnt, f"{gest_pct}%"])
            w.writerow(["pt_user invalides", user_cnt, f"{user_pct}%"])
            w.writerow(["pt_nature vides", nat_empty, f"{round(nat_empty/total*100,2)}%"])
            w.writerow(["pt_ad_code invalides", ad_bad_count, f"{ad_bad_pct}%"])
            w.writerow([])
            w.writerow(["Analyse unicité – pt_code"])
            w.writerow(["Total lignes", unicite["total"]])
            w.writerow(["Valeurs remplies", unicite["remplis"]])
            w.writerow(["Valeurs uniques", unicite["uniques"]])
            w.writerow(["Doublons (max 10)", ", ".join(unicite.get("doublons", [])) or "Aucun"])
            w.writerow([])

        result["csv_path"]=f"/static/exports/{fn}"

        # export HTML
        def render(l):
            if not l: return "Aucun"
            v=l[:10]; m=l[10:]; s=", ".join(v)
            if m: s+=f"<span class='voir-plus' onclick=\"this.nextElementSibling.style.display='inline';this.style.display='none';\">... Voir plus</span><span style='display:none'>, {', '.join(m)}</span>"
            return s

        fn2 = f"Analyse_PTech_{export_date}_{ts}.html"
        p2  = os.path.join(d,fn2)
        with open(p2,'w',encoding='utf-8') as f:
            f.write(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Analyse t_ptech – {export_date}</title>
<style>body{{font-family:Arial;margin:20px}}table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ddd;padding:8px}}th{{background:#f2f2f2}}
.voir-plus{{color:blue;cursor:pointer;text-decoration:underline}}
</style></head><body>
<h2>Unicité de pt_code</h2>
<p>
  Total : <strong>{unicite['total']}</strong><br>
  Remplis : <strong>{unicite['remplis']}</strong><br>
  Uniques : <strong>{unicite['uniques']}</strong><br>
  Doublons : {render(unicite.get('doublons', []))}
</p>

<h1>Analyse t_ptech – {export_date}</h1>
<table>
<tr><th>Test</th><th>Bad/Total</th><th>%</th></tr>
<tr><td>PT_CODEEXT</td><td>{bad_ext_count}/{total}</td><td>{bad_ext_pct}%</td></tr>
<tr><td>pt_nd_code</td><td>{nd_bad_count}/{total}</td><td>{nd_bad_pct}%</td></tr>
<tr><td>pt_prop</td><td>{prop_cnt}/{total}</td><td>{prop_pct}%</td></tr>
<tr><td>pt_gest</td><td>{gest_cnt}/{total}</td><td>{gest_pct}%</td></tr>
<tr><td>pt_user</td><td>{user_cnt}/{total}</td><td>{user_pct}%</td></tr>
<tr><td>pt_nature vides</td><td>{nat_empty}/{total}</td><td>{round(nat_empty/total*100,2)}%</td></tr>
<tr><td>pt_ad_code</td><td>{ad_bad_count}/{total}</td><td>{ad_bad_pct}%</td></tr>
</table>
<h2>Détails invalides (max 10)</h2>
<table>
<tr><th>Test</th><th>Valeurs</th></tr>
<tr><td>PT_CODEEXT</td><td>{render(bad_ext)}</td></tr>
<tr><td>pt_nd_code</td><td>{render(nd_bad)}</td></tr>
<tr><td>pt_prop</td><td>{render(prop_bad)}</td></tr>
<tr><td>pt_gest</td><td>{render(gest_bad)}</td></tr>
<tr><td>pt_user</td><td>{render(user_bad)}</td></tr>
<tr><td>pt_ad_code</td><td>{render(ad_bad)}</td></tr>
</table>
</body></html>""")
        result["html_path"]=f"/static/exports/{fn2}"

        for k, v in result.items():
            if isinstance(v, np.integer):
                result[k] = int(v)
            elif isinstance(v, np.floating):
                result[k] = float(v)
            elif isinstance(v, np.ndarray):
                result[k] = v.tolist()
            elif isinstance(v, dict):
                for kk, vv in v.items():
                    if isinstance(vv, np.integer):
                        v[kk] = int(vv)
                    elif isinstance(vv, np.floating):
                        v[kk] = float(vv)
                    elif isinstance(vv, np.ndarray):
                        v[kk] = vv.tolist()

        return jsonify(result)

    except Exception as e:
        return jsonify({"status":"error","message":str(e),"traceback":traceback.format_exc()}),500


#coherence table t_ropt
@app.route('/analyze_ropt', methods=['POST'])
def analyze_ropt():
    try:
        data        = request.get_json()
        export_date = data.get('export_date')
        if not export_date:
            return jsonify({"error": "Date d'export non spécifiée"}), 400

        # Chargement
        df_ropt  = read_table(export_date, 't_ropt.csv')
        df_fibre = read_table(export_date, 't_fibre.csv')

        # Normalisation
        for d in (df_ropt, df_fibre):
            d.columns = d.columns.str.lower().str.strip()
        df_ropt['rt_fo_code']   = df_ropt['rt_fo_code'].astype(str).str.strip().str.lower()
        df_ropt['rt_code']      = df_ropt['rt_code'].astype(str).str.strip().str.lower()
        df_ropt['rt_code_ext']  = df_ropt['rt_code_ext'].astype(str).str.strip().str.lower()
        df_fibre['fo_code']     = df_fibre['fo_code'].astype(str).str.strip().str.lower()

        total = len(df_ropt)

        # Test 1) Unicité de rt_id
        unique_rt_id = df_ropt['rt_id'].astype(str).str.strip().nunique()
        duplicate_count = total - unique_rt_id
        duplicate_pct = round(duplicate_count / total * 100, 2) if total else 0

        # Test 2) rt_fo_code présent dans t_fibre.fo_code
        mask_fo        = df_ropt['rt_fo_code'].isin(df_fibre['fo_code'])
        fo_missing     = df_ropt.loc[~mask_fo, 'rt_fo_code'].dropna().unique().tolist()
        fo_missing_count = (~mask_fo).sum()
        fo_missing_pct   = round(fo_missing_count / total * 100, 2) if total else 0

        # Test 3) Remplissage rt_code_ext
        filled_ext   = df_ropt['rt_code_ext'].replace({'nan':'','none':''}).dropna().map(bool).sum()
        fill_ext_pct = round(filled_ext / total * 100, 2) if total else 0

        # Test 4) Cohérence rt_code → rt_code_ext
        code_ext_ref = {}
        code_ext_conflicts = []
        for _, row in df_ropt[['rt_code', 'rt_code_ext']].dropna().iterrows():
            code = row['rt_code']
            ext  = row['rt_code_ext']
            if code not in code_ext_ref:
                code_ext_ref[code] = ext
            elif code_ext_ref[code] != ext:
                code_ext_conflicts.append(f"{code} → {code_ext_ref[code]} ≠ {ext}")
        conflict_count = len(code_ext_conflicts)
        conflict_pct   = round(conflict_count / total * 100, 2) if total else 0

        # Résultat JSON
        result = {
            "status":            "success",
            "export_date":       export_date,
            "total_rows":        total,

            "unique_rt_id":      unique_rt_id,
            "duplicate_count":   duplicate_count,
            "duplicate_pct":     duplicate_pct,

            "fo_missing":        fo_missing,
            "fo_missing_count":  fo_missing_count,
            "fo_missing_pct":    fo_missing_pct,

            "filled_ext":        filled_ext,
            "fill_ext_pct":      fill_ext_pct,

            "code_conflicts":    code_ext_conflicts,
            "conflict_count":    conflict_count,
            "conflict_pct":      conflict_pct,
        }

        # Conversion JSON safe
        import numpy as np
        for k, v in list(result.items()):
            if isinstance(v, np.integer):    result[k] = int(v)
            elif isinstance(v, np.floating): result[k] = float(v)
            elif isinstance(v, np.ndarray):  result[k] = v.tolist()

        # CSV export
        export_dir = os.path.join('static','exports'); os.makedirs(export_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_fn = f"Analyse_ROpt_{export_date}_{ts}.csv"
        csv_p  = os.path.join(export_dir, csv_fn)
        with open(csv_p, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f, delimiter=';')
            w.writerow([f"Analyse t_ropt", export_date])
            w.writerow([])
            w.writerow(["Total de lignes", total])
            w.writerow([])
            w.writerow(["1) Unicité de rt_id", unique_rt_id, f"{100 - duplicate_pct}%", "Doublons", duplicate_count, f"{duplicate_pct}%"])
            w.writerow([])
            w.writerow(["2) rt_fo_code manquants", fo_missing_count, f"{fo_missing_pct}%"])
            w.writerow(["   Valeurs", ", ".join(fo_missing[:10]) or "Aucun"])
            w.writerow([])
            w.writerow(["3) rt_code_ext rempli", filled_ext, f"{fill_ext_pct}%"])
            w.writerow([])
            w.writerow(["4) Conflits multiples rt_code/rt_code_ext", conflict_count, f"{conflict_pct}%"])
            w.writerow(["   Exemples", ", ".join(code_ext_conflicts[:10]) or "Aucun"])
        result["csv_path"] = f"/static/exports/{csv_fn}"

        # HTML export
        def render_list(lst):
            if not lst: return "Aucun"
            vis = lst[:10]; more = lst[10:]
            s = ", ".join(vis)
            if more:
                s += (
                    "<span class='voir-plus' onclick=\"this.nextElementSibling.style.display='inline';this.style.display='none';\">... Voir plus</span>"
                    f"<span style='display:none'>, {', '.join(more)}</span>"
                )
            return s

        html_fn = f"Analyse_ROpt_{export_date}_{ts}.html"
        html_p  = os.path.join(export_dir, html_fn)
        with open(html_p, 'w', encoding='utf-8') as f:
            f.write(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Analyse t_ropt – {export_date}</title>
<style>
 body{{font-family:Arial;margin:20px}}
 table{{border-collapse:collapse;width:100%}}
 th,td{{border:1px solid #ddd;padding:8px}}
 th{{background:#f2f2f2}}
 .voir-plus{{color:blue;cursor:pointer;text-decoration:underline}}
</style></head><body>
<h1>Analyse t_ropt – {export_date}</h1>

<h2>1) Unicité de rt_id</h2>
<p>Uniques : <strong>{unique_rt_id}/{total}</strong> ({100 - duplicate_pct}%)</p>
<p>Doublons : <strong>{duplicate_count}</strong> ({duplicate_pct}%)</p>

<h2>2) rt_fo_code manquants</h2>
<p>Count: <strong>{fo_missing_count}/{total}</strong> ({fo_missing_pct}%)</p>
<p>{render_list(fo_missing)}</p>

<h2>3) rt_code_ext</h2>
<p>Remplis: <strong>{filled_ext}/{total}</strong> ({fill_ext_pct}%)</p>

<h2>4) Conflits multiples rt_code/rt_code_ext</h2>
<p>Incohérences : <strong>{conflict_count}/{total}</strong> ({conflict_pct}%)</p>
<p>{render_list(code_ext_conflicts)}</p>

</body></html>""")
        result["html_path"] = f"/static/exports/{html_fn}"

        return jsonify(result)

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }), 500


#coherence t_sitetech
@app.route('/analyze_sitetech', methods=['POST'])
def analyze_sitetech():
    try:
        data        = request.get_json()
        export_date = data.get('export_date')
        if not export_date:
            return jsonify({"error": "Date d'export non spécifiée"}), 400

        # chargement avec fallback .csv/.dbf
        df_site = read_table(export_date, 't_sitetech.csv')
        df_nd   = read_table(export_date, 't_noeud.csv')
        df_org  = read_table(export_date, 't_organisme.csv')

        # normalisation noms de colonnes
        for d in (df_site, df_nd, df_org):
            d.columns = d.columns.str.lower().str.strip()

        # normalisation valeurs (strip + lower)
        df_site['st_nd_code'] = df_site['st_nd_code'].astype(str).str.strip().str.lower()
        df_site['st_prop']    = df_site['st_prop'].astype(str).str.strip().str.lower()
        df_site['st_gest']    = df_site['st_gest'].astype(str).str.strip().str.lower()

        df_nd['nd_code']      = df_nd['nd_code'].astype(str).str.strip().str.lower()
        df_org['or_code']     = df_org['or_code'].astype(str).str.strip().str.lower()

        total = len(df_site)

        unique_st_code   = df_site['st_code'].astype(str).str.strip().nunique()
        duplicate_count  = total - unique_st_code
        duplicate_pct    = round(duplicate_count / total * 100, 2) if total else 0
        unique_pct       = round(unique_st_code / total * 100, 2) if total else 0


        # 1) st_nd_code ∈ t_noeud.nd_code
        mask_nd      = df_site['st_nd_code'].isin(df_nd['nd_code'])
        nd_missing   = df_site.loc[~mask_nd, 'st_nd_code'].dropna().unique().tolist()
        nd_miss_cnt  = int((~mask_nd).sum())
        nd_miss_pct  = round(nd_miss_cnt / total * 100, 2) if total else 0

        # 2) st_prop ∈ t_organisme.or_code
        mask_prop    = df_site['st_prop'].isin(df_org['or_code'])
        prop_missing = df_site.loc[~mask_prop, 'st_prop'].dropna().unique().tolist()
        prop_miss_cnt= int((~mask_prop).sum())
        prop_miss_pct= round(prop_miss_cnt / total * 100, 2) if total else 0

        # 3) st_gest ∈ t_organisme.or_code
        mask_gest    = df_site['st_gest'].isin(df_org['or_code'])
        gest_missing = df_site.loc[~mask_gest, 'st_gest'].dropna().unique().tolist()
        gest_miss_cnt= int((~mask_gest).sum())
        gest_miss_pct= round(gest_miss_cnt / total * 100, 2) if total else 0

        # préparer le JSON
        result = {
            "status":           "success",
            "export_date":      export_date,
            "total_rows":       total,

            "nd_missing":       nd_missing,
            "nd_miss_cnt":      nd_miss_cnt,
            "nd_miss_pct":      nd_miss_pct,

            "prop_missing":     prop_missing,
            "prop_miss_cnt":    prop_miss_cnt,
            "prop_miss_pct":    prop_miss_pct,

            "gest_missing":     gest_missing,
            "gest_miss_cnt":    gest_miss_cnt,
            "gest_miss_pct":    gest_miss_pct,

            "unique_st_code":  unique_st_code,
            "duplicate_count": duplicate_count,
            "duplicate_pct":   duplicate_pct,
            "unique_pct":      unique_pct,

        }

        # convertir numpy → natifs
        import numpy as np
        for k, v in list(result.items()):
            if isinstance(v, np.integer):    result[k] = int(v)
            elif isinstance(v, np.floating): result[k] = float(v)
            elif isinstance(v, np.ndarray):  result[k] = v.tolist()

        # export CSV
        export_dir = os.path.join('static','exports'); os.makedirs(export_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_fn = f"Analyse_SiteTech_{export_date}_{ts}.csv"
        csv_p  = os.path.join(export_dir, csv_fn)
        with open(csv_p,'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f, delimiter=';')
            w.writerow([f"Analyse t_sitetech", export_date])
            w.writerow([])
            w.writerow(["Total de lignes", total])
            w.writerow([])
            w.writerow(["Test",               "Manquants",                "%"])
            w.writerow(["st_nd_code",         nd_miss_cnt,                f"{nd_miss_pct}%"])
            w.writerow(["st_prop",            prop_miss_cnt,              f"{prop_miss_pct}%"])
            w.writerow(["st_gest",            gest_miss_cnt,              f"{gest_miss_pct}%"])
            w.writerow([])
            w.writerow(["Détail (max 10)"])
            w.writerow(["st_nd_code",         ", ".join(nd_missing[:10])    or "Aucun"])
            w.writerow(["st_prop",            ", ".join(prop_missing[:10])  or "Aucun"])
            w.writerow(["st_gest",            ", ".join(gest_missing[:10])  or "Aucun"])
            w.writerow([])
            w.writerow(["Analyse d’unicité sur st_code"])
            w.writerow(["Total de lignes", total])
            w.writerow(["Codes uniques", unique_st_code, f"{unique_pct}%"])
            w.writerow(["Doublons", duplicate_count, f"{duplicate_pct}%"])
            w.writerow([])

        result["csv_path"] = f"/static/exports/{csv_fn}"

        # export HTML
        def render_list(lst):
            if not lst:
                return "Aucun"
            v = lst[:10]; m = lst[10:]
            s = ", ".join(v)
            if m:
                s += ("<span class='voir-plus' onclick="
                      "this.nextElementSibling.style.display='inline';this.style.display='none';>"
                      "... Voir plus</span>")
                s += f"<span style='display:none'>, {', '.join(m)}</span>"
            return s

        html_fn = f"Analyse_SiteTech_{export_date}_{ts}.html"
        html_p  = os.path.join(export_dir, html_fn)
        with open(html_p,'w', encoding='utf-8') as f:
            f.write(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Analyse t_sitetech – {export_date}</title>
<style>
 body {{font-family:Arial,margin:20px}}
 table {{border-collapse:collapse;width:100%}}
 th,td {{border:1px solid #ddd;padding:8px}}
 th {{background:#f2f2f2}}
 .voir-plus {{color:blue;cursor:pointer;text-decoration:underline}}
</style></head><body>
  <h1>Analyse t_sitetech – {export_date}</h1>
  <h2>Unicité de st_code</h2>
<table>
  <tr><th>Mesure</th><th>Valeur</th></tr>
  <tr><td>Total de lignes</td><td>{total}</td></tr>
  <tr><td>Codes uniques</td><td>{unique_st_code} ({unique_pct}%)</td></tr>
  <tr><td>Doublons</td><td>{duplicate_count} ({duplicate_pct}%)</td></tr>
</table><br>

  <table>
    <tr><th>Test</th><th>Manquants/Total</th><th>%</th></tr>
    <tr><td>st_nd_code</td>
        <td>{nd_miss_cnt}/{total}</td>
        <td>{nd_miss_pct}%</td></tr>
    <tr><td>st_prop</td>
        <td>{prop_miss_cnt}/{total}</td>
        <td>{prop_miss_pct}%</td></tr>
    <tr><td>st_gest</td>
        <td>{gest_miss_cnt}/{total}</td>
        <td>{gest_miss_pct}%</td></tr>
  </table>
  <h2>Détails des valeurs manquantes</h2>
  <table>
    <tr><th>Champ</th><th>Valeurs</th></tr>
    <tr><td>st_nd_code</td><td>{render_list(nd_missing)}</td></tr>
    <tr><td>st_prop</td><td>{render_list(prop_missing)}</td></tr>
    <tr><td>st_gest</td><td>{render_list(gest_missing)}</td></tr>
  </table>
</body></html>""")
        result["html_path"] = f"/static/exports/{html_fn}"

        return jsonify(result)

    except Exception as e:
        return jsonify({
            "status":    "error",
            "message":   str(e),
            "traceback": traceback.format_exc()
        }), 500


#coherence t_suf
@app.route('/analyze_suf', methods=['POST'])
def analyze_suf():
    try:
        data        = request.get_json()
        export_date = data.get('export_date')
        if not export_date:
            return jsonify({"error": "Date d'export non spécifiée"}), 400

        # chargement via read_table avec extension
        df_suf     = read_table(export_date, 't_suf.csv')
        df_noeud   = read_table(export_date, 't_noeud.dbf')
        df_addr    = read_table(export_date, 't_adresse.csv')
        df_org     = read_table(export_date, 't_organisme.csv')

        # normalisation noms de colonnes
        for d in (df_suf, df_noeud, df_addr, df_org):
            d.columns = d.columns.str.lower().str.strip()

        # normalisation valeurs (strip + lower)
        df_suf['sf_nd_code']  = df_suf['sf_nd_code'].astype(str).str.strip().str.lower()
        df_suf['sf_ad_code']  = df_suf['sf_ad_code'].astype(str).str.strip().str.lower()
        df_suf['sf_oper']     = df_suf['sf_oper'].astype(str).str.strip().str.lower()
        df_suf['sf_prop']     = df_suf['sf_prop'].astype(str).str.strip().str.lower()
        df_suf['sf_code'] = df_suf['sf_code'].astype(str).str.strip().str.lower()


        df_noeud['nd_code']   = df_noeud['nd_code'].astype(str).str.strip().str.lower()
        df_addr['ad_code']    = df_addr['ad_code'].astype(str).str.strip().str.lower()
        df_org['or_code']     = df_org['or_code'].astype(str).str.strip().str.lower()

       

        total = len(df_suf)

        unique_sf_code  = df_suf['sf_code'].nunique()
        duplicate_count = total - unique_sf_code
        duplicate_pct   = round(duplicate_count / total * 100, 2) if total else 0
        unique_pct      = round(unique_sf_code / total * 100, 2) if total else 0


        # 1) sf_nd_code ∈ t_noeud.nd_code
        mask_nd      = df_suf['sf_nd_code'].isin(df_noeud['nd_code'])
        nd_missing   = df_suf.loc[~mask_nd, 'sf_nd_code'].dropna().unique().tolist()
        nd_miss_cnt  = int((~mask_nd).sum())
        nd_miss_pct  = round(nd_miss_cnt / total * 100, 2) if total else 0

        # 2) sf_ad_code ∈ t_adresse.ad_code
        mask_ad      = df_suf['sf_ad_code'].isin(df_addr['ad_code'])
        ad_missing   = df_suf.loc[~mask_ad, 'sf_ad_code'].dropna().unique().tolist()
        ad_miss_cnt  = int((~mask_ad).sum())
        ad_miss_pct  = round(ad_miss_cnt / total * 100, 2) if total else 0

        # 3) sf_oper ∈ t_organisme.or_code
        mask_oper    = df_suf['sf_oper'].isin(df_org['or_code'])
        oper_missing = df_suf.loc[~mask_oper, 'sf_oper'].dropna().unique().tolist()
        oper_miss_cnt= int((~mask_oper).sum())
        oper_miss_pct= round(oper_miss_cnt / total * 100, 2) if total else 0

        # 4) sf_prop ∈ t_organisme.or_code
        mask_prop    = df_suf['sf_prop'].isin(df_org['or_code'])
        prop_missing = df_suf.loc[~mask_prop, 'sf_prop'].dropna().unique().tolist()
        prop_miss_cnt= int((~mask_prop).sum())
        prop_miss_pct= round(prop_miss_cnt / total * 100, 2) if total else 0

        # préparer le JSON
        result = {
            "status":        "success",
            "export_date":   export_date,
            "total_rows":    total,

            "nd_missing":    nd_missing,
            "nd_miss_cnt":   nd_miss_cnt,
            "nd_miss_pct":   nd_miss_pct,

            "ad_missing":    ad_missing,
            "ad_miss_cnt":   ad_miss_cnt,
            "ad_miss_pct":   ad_miss_pct,

            "oper_missing":  oper_missing,
            "oper_miss_cnt": oper_miss_cnt,
            "oper_miss_pct": oper_miss_pct,

            "prop_missing":  prop_missing,
            "prop_miss_cnt": prop_miss_cnt,
            "prop_miss_pct": prop_miss_pct,

            "unique_sf_code":  unique_sf_code,
            "duplicate_count": duplicate_count,
            "duplicate_pct":   duplicate_pct,
            "unique_pct":      unique_pct,

        }

        # convertir numpy → natifs
        import numpy as np
        for k, v in list(result.items()):
            if isinstance(v, np.integer):    result[k] = int(v)
            elif isinstance(v, np.floating): result[k] = float(v)
            elif isinstance(v, np.ndarray):  result[k] = v.tolist()

        # export CSV
        export_dir = os.path.join('static','exports'); os.makedirs(export_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_fn = f"Analyse_Suf_{export_date}_{ts}.csv"
        csv_p  = os.path.join(export_dir, csv_fn)
        with open(csv_p,'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f, delimiter=';')
            w.writerow([f"Analyse t_suf", export_date])
            w.writerow([])
            w.writerow(["Test",        "Manquants/Total",    "%"])
            w.writerow(["sf_nd_code",  f"{nd_miss_cnt}/{total}",  f"{nd_miss_pct}%"])
            w.writerow(["sf_ad_code",  f"{ad_miss_cnt}/{total}",  f"{ad_miss_pct}%"])
            w.writerow(["sf_oper",     f"{oper_miss_cnt}/{total}",f"{oper_miss_pct}%"])
            w.writerow(["sf_prop",     f"{prop_miss_cnt}/{total}",f"{prop_miss_pct}%"])
            w.writerow([])
            w.writerow(["Détail (max 10)"])
            w.writerow(["sf_nd_code",  ", ".join(nd_missing[:10])    or "Aucun"])
            w.writerow(["sf_ad_code",  ", ".join(ad_missing[:10])    or "Aucun"])
            w.writerow(["sf_oper",     ", ".join(oper_missing[:10])  or "Aucun"])
            w.writerow(["sf_prop",     ", ".join(prop_missing[:10])  or "Aucun"])
            w.writerow([])
            w.writerow(["Unicité de sf_code", unique_sf_code, f"{unique_pct}%"])
            w.writerow(["Doublons", duplicate_count, f"{duplicate_pct}%"])

        result["csv_path"] = f"/static/exports/{csv_fn}"

        # export HTML
        def render_list(lst):
            if not lst:
                return "Aucun"
            vis = lst[:10]; more = lst[10:]
            s = ", ".join(vis)
            if more:
                s += (
                  "<span class='voir-plus' onclick="
                  "this.nextElementSibling.style.display='inline';this.style.display='none';>"
                  "... Voir plus</span>"
                )
                s += f"<span style='display:none'>, {', '.join(more)}</span>"
            return s

        html_fn = f"Analyse_Suf_{export_date}_{ts}.html"
        html_p  = os.path.join(export_dir, html_fn)
        with open(html_p,'w', encoding='utf-8') as f:
            f.write(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Analyse t_suf – {export_date}</title>
<style>
 body{{font-family:Arial;margin:20px}}
 table{{border-collapse:collapse;width:100%}}
 th,td{{border:1px solid #ddd;padding:8px}}
 th{{background:#f2f2f2}}
 .voir-plus{{color:blue;cursor:pointer;text-decoration:underline}}
</style></head><body>
  <h1>Analyse t_suf – {export_date}</h1>
  <table>
  <h2>Unicité de sf_code</h2>
<p>Uniques : <strong>{unique_sf_code}/{total}</strong> ({unique_pct}%)</p>
<p>Doublons : <strong>{duplicate_count}</strong> ({duplicate_pct}%)</p>

    <tr><th>Test</th><th>Manquants/Total</th><th>%</th></tr>
    <tr><td>sf_nd_code</td><td>{nd_miss_cnt}/{total}</td><td>{nd_miss_pct}%</td></tr>
    <tr><td>sf_ad_code</td><td>{ad_miss_cnt}/{total}</td><td>{ad_miss_pct}%</td></tr>
    <tr><td>sf_oper</td><td>{oper_miss_cnt}/{total}</td><td>{oper_miss_pct}%</td></tr>
    <tr><td>sf_prop</td><td>{prop_miss_cnt}/{total}</td><td>{prop_miss_pct}%</td></tr>
  </table>
  <h2>Détails des valeurs manquantes</h2>
  <table>
    <tr><th>Champ</th><th>Valeurs</th></tr>
    <tr><td>sf_nd_code</td><td>{render_list(nd_missing)}</td></tr>
    <tr><td>sf_ad_code</td><td>{render_list(ad_missing)}</td></tr>
    <tr><td>sf_oper</td><td>{render_list(oper_missing)}</td></tr>
    <tr><td>sf_prop</td><td>{render_list(prop_missing)}</td></tr>
  </table>
</body></html>""")
        result["html_path"] = f"/static/exports/{html_fn}"

        return jsonify(result)

    except Exception as e:
        return jsonify({
            "status":    "error",
            "message":   str(e),
            "traceback": traceback.format_exc()
        }), 500


#cohérence t_tiroir
@app.route('/analyze_tiroir', methods=['POST'])
def analyze_tiroir():
    try:
        data        = request.get_json()
        export_date = data.get('export_date')
        if not export_date:
            return jsonify({"error": "Date d'export non spécifiée"}), 400

        # Chargement (fallback .csv ↔ .dbf)
        df_tiroir   = read_table(export_date, 't_tiroir.csv')
        df_baie     = read_table(export_date, 't_baie.csv')
        df_ref      = read_table(export_date, 't_reference.csv')
        df_org      = read_table(export_date, 't_organisme.csv')

        # Normalisation noms de colonnes
        for d in (df_tiroir, df_baie, df_ref, df_org):
            d.columns = d.columns.str.lower().str.strip()

        # Normalisation valeurs (strip + lower)
        df_tiroir['ti_ba_code'] = df_tiroir['ti_ba_code'].astype(str).str.strip().str.lower()
        df_tiroir['ti_rf_code'] = df_tiroir['ti_rf_code'].astype(str).str.strip().str.lower()
        df_tiroir['ti_prop']    = df_tiroir['ti_prop'].astype(str).str.strip().str.lower()

        df_baie['ba_code']      = df_baie['ba_code'].astype(str).str.strip().str.lower()
        df_ref['rf_code']       = df_ref['rf_code'].astype(str).str.strip().str.lower()
        df_org['or_code']       = df_org['or_code'].astype(str).str.strip().str.lower()

        total = len(df_tiroir)

        # Analyse unicité de ti_code
        ti_code_unique = df_tiroir['ti_code'].nunique()
        ti_code_dup    = total - ti_code_unique
        ti_code_dup_pct = round(ti_code_dup / total * 100, 2) if total else 0
        ti_code_unique_pct = round(ti_code_unique / total * 100, 2) if total else 0


        # 1) ti_ba_code ∈ t_baie.ba_code
        mask_ba      = df_tiroir['ti_ba_code'].isin(df_baie['ba_code'])
        ba_missing   = df_tiroir.loc[~mask_ba,'ti_ba_code'].dropna().unique().tolist()
        ba_cnt       = int((~mask_ba).sum())
        ba_pct       = round(ba_cnt/total*100,2) if total else 0

        # 2) ti_rf_code ∈ t_reference.rf_code
        mask_rf      = df_tiroir['ti_rf_code'].isin(df_ref['rf_code'])
        rf_missing   = df_tiroir.loc[~mask_rf,'ti_rf_code'].dropna().unique().tolist()
        rf_cnt       = int((~mask_rf).sum())
        rf_pct       = round(rf_cnt/total*100,2) if total else 0

        # 3) ti_prop ∈ t_organisme.or_code
        mask_prop    = df_tiroir['ti_prop'].isin(df_org['or_code'])
        prop_missing = df_tiroir.loc[~mask_prop,'ti_prop'].dropna().unique().tolist()
        prop_cnt     = int((~mask_prop).sum())
        prop_pct     = round(prop_cnt/total*100,2) if total else 0

        # Construire le JSON
        result = {
            "status":        "success",
            "export_date":   export_date,
            "total_rows":    total,

            "ba_missing":    ba_missing,
            "ba_cnt":        ba_cnt,
            "ba_pct":        ba_pct,

            "rf_missing":    rf_missing,
            "rf_cnt":        rf_cnt,
            "rf_pct":        rf_pct,

            "prop_missing":  prop_missing,
            "prop_cnt":      prop_cnt,
            "prop_pct":      prop_pct,

            "ti_code_unique":      ti_code_unique,
            "ti_code_unique_pct":  ti_code_unique_pct,
            "ti_code_dup":         ti_code_dup,
            "ti_code_dup_pct":     ti_code_dup_pct

        }

        # Convert numpy → natifs
        import numpy as np
        for k,v in list(result.items()):
            if isinstance(v, np.integer):    result[k] = int(v)
            elif isinstance(v, np.floating): result[k] = float(v)
            elif isinstance(v, np.ndarray):  result[k] = v.tolist()

        # Export CSV
        export_dir = os.path.join('static','exports'); os.makedirs(export_dir,exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_fn = f"Analyse_Tiroir_{export_date}_{ts}.csv"
        csv_p  = os.path.join(export_dir, csv_fn)
        with open(csv_p,'w',newline='',encoding='utf-8') as f:
            w = csv.writer(f, delimiter=';')
            w.writerow([f"Analyse t_tiroir", export_date])
            w.writerow([])
            w.writerow(["Test",            "Manquants/Total",      "%"])
            w.writerow(["ti_ba_code",      f"{ba_cnt}/{total}",    f"{ba_pct}%"])
            w.writerow(["ti_rf_code",      f"{rf_cnt}/{total}",    f"{rf_pct}%"])
            w.writerow(["ti_prop",         f"{prop_cnt}/{total}",  f"{prop_pct}%"])
            w.writerow([])
            w.writerow(["Détail (max 10)"])
            w.writerow(["ti_ba_code",      ", ".join(ba_missing[:10])    or "Aucun"])
            w.writerow(["ti_rf_code",      ", ".join(rf_missing[:10])    or "Aucun"])
            w.writerow(["ti_prop",         ", ".join(prop_missing[:10])  or "Aucun"])
            w.writerow([])
            w.writerow(["ti_code (unicité)", f"{ti_code_unique}/{total}", f"{ti_code_unique_pct}%"])

        result["csv_path"] = f"/static/exports/{csv_fn}"

        # Export HTML
        def render_list(lst):
            if not lst: return "Aucun"
            vis, more = lst[:10], lst[10:]
            s = ", ".join(vis)
            if more:
                s += (
                  "<span class='voir-plus' onclick=\"this.nextElementSibling.style.display='inline';this.style.display='none';\">"
                  "... Voir plus</span>"
                )
                s += f"<span style='display:none'>, {', '.join(more)}</span>"
            return s

        html_fn = f"Analyse_Tiroir_{export_date}_{ts}.html"
        html_p  = os.path.join(export_dir, html_fn)
        with open(html_p,'w',encoding='utf-8') as f:
            f.write(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Analyse t_tiroir – {export_date}</title>
<style>
 body {{ font-family:Arial;margin:20px }}
 table {{ border-collapse:collapse;width:100% }}
 th,td {{ border:1px solid #ddd;padding:8px }}
 th {{ background:#f2f2f2 }}
 .voir-plus {{ color:blue;cursor:pointer;text-decoration:underline }}
</style></head><body>
  <h1>Analyse t_tiroir – {export_date}</h1>
  <table>
    <tr><th>Test</th><th>Manquants/Total</th><th>%</th></tr>
    <tr><td>ti_ba_code</td><td>{ba_cnt}/{total}</td><td>{ba_pct}%</td></tr>
    <tr><td>ti_rf_code</td><td>{rf_cnt}/{total}</td><td>{rf_pct}%</td></tr>
    <tr><td>ti_prop</td><td>{prop_cnt}/{total}</td><td>{prop_pct}%</td></tr>
  </table>
  <h2>Détails des valeurs manquantes</h2>
  <table>
    <tr><th>Champ</th><th>Valeurs</th></tr>
    <tr><td>ti_ba_code</td><td>{render_list(ba_missing)}</td></tr>
    <tr><td>ti_rf_code</td><td>{render_list(rf_missing)}</td></tr>
    <tr><td>ti_prop</td><td>{render_list(prop_missing)}</td></tr>
  </table>
</body></html>""")
        result["html_path"] = f"/static/exports/{html_fn}"

        return jsonify(result)

    except Exception as e:
        return jsonify({
            "status":    "error",
            "message":   str(e),
            "traceback": traceback.format_exc()
        }), 500


#cohérence t_cableline
@app.route('/analyze_cableline', methods=['POST'])
def analyze_cableline():
    try:
        data        = request.get_json()
        export_date = data.get('export_date')
        if not export_date:
            return jsonify({"error": "Date d'export non spécifiée"}), 400

        # Chargement avec fallback .csv ↔ .dbf
        df_cl    = read_table(export_date, 't_cableline.csv')
        df_cable = read_table(export_date, 't_cable.csv')

        # Normalisation noms de colonnes
        for d in (df_cl, df_cable):
            d.columns = d.columns.str.lower().str.strip()

        # Normalisation des valeurs (strip + lower)
        df_cl   ['cl_cb_code'] = df_cl   ['cl_cb_code'].astype(str).str.strip().str.lower()
        df_cable['cb_code']    = df_cable['cb_code'].astype(str).str.strip().str.lower()

        total = len(df_cl)

        unique_cl_code  = df_cl['cl_code'].nunique()
        duplicate_count = total - unique_cl_code
        duplicate_pct   = round(duplicate_count / total * 100, 2) if total else 0
        unique_pct      = round(unique_cl_code / total * 100, 2) if total else 0


        # Test cl_cb_code ∈ t_cable.cb_code
        mask      = df_cl['cl_cb_code'].isin(df_cable['cb_code'])
        missing   = df_cl.loc[~mask, 'cl_cb_code'].dropna().unique().tolist()
        miss_cnt  = int((~mask).sum())
        miss_pct  = round(miss_cnt / total * 100, 2) if total else 0

        # Construire le JSON
        result = {
            "status":        "success",
            "export_date":   export_date,
            "total_rows":    total,

            "missing":       missing,
            "miss_cnt":      miss_cnt,
            "miss_pct":      miss_pct,

            "unique_cl_code":  unique_cl_code,
            "duplicate_count": duplicate_count,
            "duplicate_pct":   duplicate_pct,
            "unique_pct":      unique_pct,

        }

        # Convert numpy → natifs
        import numpy as np
        for k, v in list(result.items()):
            if isinstance(v, np.integer):    result[k] = int(v)
            elif isinstance(v, np.floating): result[k] = float(v)
            elif isinstance(v, np.ndarray):  result[k] = v.tolist()

        # Export CSV
        export_dir = os.path.join('static','exports'); os.makedirs(export_dir, exist_ok=True)
        ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_fn    = f"Analyse_CableLine_{export_date}_{ts}.csv"
        csv_path  = os.path.join(export_dir, csv_fn)
        with open(csv_path,'w',newline='',encoding='utf-8') as f:
            w = csv.writer(f, delimiter=';')
            w.writerow([f"Analyse t_cableline", export_date])
            w.writerow([])
            w.writerow(["Total de lignes", total])
            w.writerow([])
            w.writerow(["Test",              "Manquants/Total",      "%"])
            w.writerow(["cl_cb_code",        f"{miss_cnt}/{total}",  f"{miss_pct}%"])
            w.writerow([])
            w.writerow(["Détail (max 10)"])
            w.writerow(["cl_cb_code",        ", ".join(missing[:10]) or "Aucun"])
            w.writerow([])
            w.writerow(["Unicité de cl_code", unique_cl_code, f"{unique_pct}%"])
            w.writerow(["Doublons", duplicate_count, f"{duplicate_pct}%"])

        result["csv_path"] = f"/static/exports/{csv_fn}"

        # Export HTML
        def render_list(lst):
            if not lst:
                return "Aucun"
            vis, more = lst[:10], lst[10:]
            s = ", ".join(vis)
            if more:
                s += (
                  "<span class='voir-plus' onclick=\"this.nextElementSibling.style.display='inline';this.style.display='none';\">"
                  "... Voir plus</span>"
                )
                s += f"<span style='display:none'>, {', '.join(more)}</span>"
            return s

        html_fn  = f"Analyse_CableLine_{export_date}_{ts}.html"
        html_path= os.path.join(export_dir, html_fn)
        with open(html_path,'w',encoding='utf-8') as f:
            f.write(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Analyse t_cableline – {export_date}</title>
<style>
 body {{font-family:Arial;margin:20px}}
 table {{border-collapse:collapse;width:100%}}
 th,td {{border:1px solid #ddd;padding:8px}}
 th {{background:#f2f2f2}}
 .voir-plus {{color:blue;cursor:pointer;text-decoration:underline}}
</style></head><body>
  <h1>Analyse t_cableline – {export_date}</h1>
  <h2>Unicité de cl_code</h2>
<p>Uniques : <strong>{unique_cl_code}/{total}</strong> ({unique_pct}%)</p>
<p>Doublons : <strong>{duplicate_count}</strong> ({duplicate_pct}%)</p>

  <table>
    <tr><th>Test</th><th>Manquants/Total</th><th>%</th></tr>
    <tr><td>cl_cb_code</td><td>{miss_cnt}/{total}</td><td>{miss_pct}%</td></tr>
  </table>
  <h2>Détails des valeurs manquantes</h2>
  <table>
    <tr><th>Champ</th><th>Valeurs</th></tr>
    <tr><td>cl_cb_code</td><td>{render_list(missing)}</td></tr>
  </table>
</body></html>""")
        result["html_path"] = f"/static/exports/{html_fn}"

        return jsonify(result)

    except Exception as e:
        return jsonify({
            "status":    "error",
            "message":   str(e),
            "traceback": traceback.format_exc()
        }), 500


#coherence t_noeud
@app.route('/analyze_noeud', methods=['POST'])
def analyze_noeud():
    try:
        data        = request.get_json()
        export_date = data.get('export_date')
        if not export_date:
            return jsonify({"error": "Date d'export non spécifiée"}), 400

        # Chargement avec fallback .csv/.dbf
        df_nd = read_table(export_date, 't_noeud.csv')

        # Normalisation colonnes
        df_nd.columns = df_nd.columns.str.lower().str.strip()

        # Normalisation des valeurs (strip + upper)
        df_nd['nd_codeext'] = df_nd['nd_codeext'].astype(str).str.strip().str.upper()
        
        # Détection automatique d'erreur : nd_codeext identique à nd_code → mauvais mapping
        if df_nd["nd_codeext"].equals(df_nd["nd_code"]):
            raise ValueError(" Problème détecté : 'nd_codeext' contient les mêmes valeurs que 'nd_code'. Vérifie la table source.")
        
        df_nd["nd_code"]    = df_nd["nd_code"].astype(str).str.strip()
        df_nd["nd_codeext"] = df_nd["nd_codeext"].astype(str).str.strip().str.upper()


        total = len(df_nd)

        unique_nd_code  = df_nd['nd_code'].nunique()
        duplicate_count = total - unique_nd_code
        duplicate_pct   = round(duplicate_count / total * 100, 2) if total else 0
        duplicates = (
            df_nd['nd_code']
            .value_counts()
            .loc[lambda x: x > 1]
            .index
            .tolist()
        )

        unique_pct      = round(unique_nd_code / total * 100, 2) if total else 0


        # Test : codeex ∈ {TERRITOIRE, HORS TERRITOIRE}
        valid       = {"TERRITOIRE", "HORS TERRITOIRE"}
        bad_mask    = ~df_nd['nd_codeext'].isin(valid)
        missing     = df_nd.loc[bad_mask, 'nd_codeext'].dropna().unique().tolist()
        miss_count  = int(bad_mask.sum())
        miss_pct    = round(miss_count / total * 100, 2) if total else 0

        # Préparer le JSON
        result = {
            "status":        "success",
            "export_date":   export_date,
            "total_rows":    total,
            "missing":       missing,
            "miss_count":    miss_count,
            "miss_pct":      miss_pct,
            "unique_nd_code":  unique_nd_code,
            "duplicate_count": duplicate_count,
            "duplicate_pct":   duplicate_pct,
            "unique_pct":      unique_pct,
            "duplicates": duplicates,

        }

        # Convert numpy → natifs
        import numpy as np
        for k, v in list(result.items()):
            if isinstance(v, np.integer):    result[k] = int(v)
            elif isinstance(v, np.floating): result[k] = float(v)
            elif isinstance(v, np.ndarray):  result[k] = v.tolist()

        # Export CSV
        export_dir = os.path.join('static','exports'); os.makedirs(export_dir, exist_ok=True)
        ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_fn    = f"Analyse_Noeud_{export_date}_{ts}.csv"
        csv_p     = os.path.join(export_dir, csv_fn)
        with open(csv_p,'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f, delimiter=';')
            w.writerow([f"Analyse t_noeud", export_date])
            w.writerow([])
            w.writerow(["Total de lignes", total])
            w.writerow([])
            w.writerow(["Test",         "Manquants/Total",    "%"])
            w.writerow(["nd_codeext",       f"{miss_count}/{total}", f"{miss_pct}%"])
            w.writerow([])
            w.writerow(["Détail (max 10)"])
            w.writerow(["nd_codeext", ", ".join(missing[:10]) or "Aucun"])
            w.writerow([])
            w.writerow(["Unicité de nd_code", unique_nd_code, f"{unique_pct}%"])
            w.writerow(["Doublons", duplicate_count, f"{duplicate_pct}%"])
            w.writerow(["Doublons", duplicate_count, f"{duplicate_pct}%"])


        result["csv_path"] = f"/static/exports/{csv_fn}"

        # Export HTML
        def render_list(lst):
            if not lst:
                return "Aucun"
            vis, more = lst[:10], lst[10:]
            s = ", ".join(vis)
            if more:
                s += (
                  "<span class='voir-plus' onclick="
                  "this.nextElementSibling.style.display='inline';this.style.display='none';>"
                  "... Voir plus</span>"
                )
                s += f"<span style='display:none'>, {', '.join(more)}</span>"
            return s

        html_fn  = f"Analyse_Noeud_{export_date}_{ts}.html"
        html_p   = os.path.join(export_dir, html_fn)
        with open(html_p,'w', encoding='utf-8') as f:
            f.write(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Analyse t_noeud – {export_date}</title>
<style>
 body {{font-family:Arial;margin:20px}}
 table {{border-collapse:collapse;width:100%}}
 th,td {{border:1px solid #ddd;padding:8px}}
 th {{background:#f2f2f2}}
 .voir-plus {{color:blue;cursor:pointer;text-decoration:underline}}
</style></head><body>
  <h1>Analyse t_noeud – {export_date}</h1>
  <h2>Unicité de nd_code</h2>
<p>Uniques : <strong>{unique_nd_code}/{total}</strong> ({unique_pct}%)</p>
<p>Doublons : <strong>{duplicate_count}</strong> ({duplicate_pct}%)</p>
<h2>Codes nd_code dupliqués (max 10)</h2>
<p>{render_list(duplicates)}</p>

  <table>
    <tr><th>Test</th><th>Manquants/Total</th><th>%</th></tr>
    <tr><td>nd_codeext</td><td>{miss_count}/{total}</td><td>{miss_pct}%</td></tr>
  </table>
  <h2>Détails des valeurs invalides</h2>
  <table>
    <tr><th>Champ</th><th>Valeurs</th></tr>
    <tr><td>nd_codeext</td><td>{render_list(missing)}</td></tr>
  </table>
</body></html>""")
        result["html_path"] = f"/static/exports/{html_fn}"

        return jsonify(result)

    except Exception as e:
        return jsonify({
            "status":    "error",
            "message":   str(e),
            "traceback": traceback.format_exc()
        }), 500


#super boutou
@app.route('/analyze_all', methods=['POST'])
def analyze_all():
    export_date = request.json.get("export_date") if request.is_json else request.form.get("export_date")

    if not export_date:
        return jsonify({"status": "error", "message": "Date manquante"}), 400

    temp_dir = tempfile.mkdtemp()
    result_dir = "static/results"
    os.makedirs(result_dir, exist_ok=True)
    collected_files = []

    # Mapping des routes à appeler
    route_map = {
        "analyze_bpe": "/analyze_bpe",
        "analyze_cable": "/analyze_cable",
        "analyze_chambre": "/analyze_chambre",
        "analyze_fourreaux": "/analyze_fourreaux",
        "analyze_t_baie": "/analyze_t_baie",
        "analyze_t_cab_cond": "/analyze_t_cab_cond",
        "analyze_t_cassette": "/analyze_t_cassette",
        "analyze_cheminement": "/analyze_cheminement",
        "analyze_t_cond_chem": "/analyze_t_cond_chem",
        "analyze_coherence_cable": "/analyze_coherence_cable",
        "analyze_conduite_organisme": "/analyze_conduite_organisme",
        "analyze_ebp": "/analyze_ebp",
        "analyze_fibre_cable": "/analyze_fibre_cable",
        "analyze_position": "/analyze_position",
        "analyze_ltech": "/analyze_ltech",
        "analyze_ptech": "/analyze_ptech",
        "analyze_ropt": "/analyze_ropt",
        "analyze_sitetech": "/analyze_sitetech",
        "analyze_suf": "/analyze_suf",
        "analyze_tiroir": "/analyze_tiroir",
        "analyze_cableline": "/analyze_cableline",
        "analyze_noeud": "/analyze_noeud"
    }

    for name, endpoint in route_map.items():
        try:
            resp = requests.post(f"{APP_BASE_URL}{endpoint}", json={"export_date": export_date})
            if resp.ok:
                data = resp.json()
                for path in [data.get("csv_path"), data.get("html_path")]:
                    if path and os.path.exists(path[1:] if path.startswith("/") else path):
                        abs_path = path[1:] if path.startswith("/") else path
                        collected_files.append(abs_path)
            else:
                print(f"[!] {endpoint} : {resp.status_code} {resp.text}")
        except Exception as e:
            print(f"[Erreur] Appel à {endpoint} échoué → {e}")

    # Création ZIP
    zip_path = os.path.join(result_dir, f"analyse_complete_{export_date.replace('-', '_')}.zip")
    with ZipFile(zip_path, 'w') as zipf:
        for file in collected_files:
            zipf.write(file, arcname=os.path.basename(file))

    return jsonify({
        "status": "ok",
        "zip_path": f"/{zip_path}"
    })


@app.route('/liste_exports', methods=['GET'])
def liste_exports():
    try:
        dates = db.session.query(Export.export_date).distinct().order_by(Export.export_date.desc()).all()
        # Formater les dates sous forme de chaînes "aaaa-mm"
        dates_str = [d[0] for d in dates if d[0]]
        return jsonify({"dates": dates_str})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    try:
        dates = db.session.query(Export.export_date).distinct().order_by(Export.export_date.desc()).all()
        # Formater les dates sous forme de chaînes "aaaa-mm"
        dates_str = [d[0] for d in dates if d[0]]
        return jsonify({"dates": dates_str})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    try:
        dates = db.session.query(Export.export_date).distinct().order_by(Export.export_date.desc()).all()
        # Formater les dates sous forme de chaînes "aaaa-mm"
        dates_str = [d[0] for d in dates if d[0]]
        return jsonify({"dates": dates_str})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


    try:
        dates = db.session.query(Export.export_date).distinct().order_by(Export.export_date.desc()).all()
        # Formater les dates sous forme de chaînes "aaaa-mm"
        dates_str = [d[0] for d in dates if d[0]]
        return jsonify({"dates": dates_str})
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route('/resilience')
def resilience():
    return render_template('resilience.html')


@app.route('/upload_resilience', methods=['POST'])
def upload_resilience():
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

        for ds in datasets:
            name = (names.get(ds["key"]) or names.get(ds["default_name"]) or "")
            if not name and legacy_names:
                name = legacy_names.pop(0)
            name = (name or "").strip()
            if not name:
                return jsonify({'status': 'error', 'message': f'Nom manquant pour {ds["key"]}'})
            try:
                try:
                    gdf = _read_geofile(ds["path"])
                except Exception as read_err:
                    return jsonify({'status': 'error', 'message': f'Erreur lecture {os.path.basename(ds["path"])} : {str(read_err)}'})
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
                    return jsonify({'status': 'error', 'message': f'Géométrie introuvable pour {ds["key"]}'} )

                # Coercion + réparation des géométries
                geom_series = gpd.GeoSeries(gdf['geometry'].apply(_coerce_geometry_value), crs=gdf.crs)
                try:
                    geom_series = geom_series.make_valid()
                except Exception:
                    # fallback buffer(0)
                    geom_series = geom_series.buffer(0)

                geom_series = geom_series[geom_series.notnull() & ~geom_series.is_empty]
                if geom_series.empty:
                    return jsonify({'status': 'error', 'message': f'Géométries invalides pour {ds["key"]}'} )

                gdf = gdf.loc[geom_series.index].reset_index(drop=True)
                gdf = gdf.set_geometry(geom_series.reset_index(drop=True))

                if gdf.empty:
                    return jsonify({'status': 'error', 'message': f'Géométries invalides pour {ds["key"]}'} )

                if gdf.crs is None:
                    gdf = gdf.set_crs(epsg=4326)
                if gdf.crs.to_epsg() != 2154:
                    gdf = gdf.to_crs(epsg=2154)
                with engine.begin() as conn:
                    gdf.to_postgis(name, conn, schema="resilience", if_exists="replace", index=False)
            except Exception as e:
                return jsonify({'status': 'error', 'message': f'Erreur traitement {os.path.basename(ds["path"])} : {str(e)}'})

    return jsonify({"status": "ok"})


# Route pour lister les couches dans le schéma resilience
@app.route('/resilience_layers')
def get_resilience_layers():
    with engine.connect() as conn:
        # Tables et vues (hors préfixe alea)
        result1 = conn.execute(text("""
            SELECT table_name 
            FROM information_schema.tables
            WHERE table_schema = 'resilience'
              AND table_type IN ('BASE TABLE', 'VIEW')
              AND table_name NOT LIKE 'alea%';
        """))
        tables = [row[0] for row in result1]

        # Vues matérialisées (on prend tout)
        result2 = conn.execute(text("""
            SELECT matviewname 
            FROM pg_matviews
            WHERE schemaname = 'resilience';
        """))
        matviews = [row[0] for row in result2]

    all_layers = sorted(set(tables + matviews))
    return jsonify(all_layers)


#route création de la view
@app.route('/create_resilience_view', methods=['POST'])
def create_resilience_view():
    data = request.json
    main_table = data.get('main_table')
    alea_tables = data.get('alea_tables', [])
    view_name = data.get('view_name', 'vue_resilience')
    preview_only = data.get('preview_only', False)

    if not main_table or not alea_tables or not isinstance(alea_tables, list):
        return jsonify({'status': 'error', 'message': 'Table principale ou couches alea manquantes.'})

    # Récupère la liste des colonnes de la table principale
    with engine.begin() as conn:
        result = conn.execute(text(f'''
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'resilience' AND table_name = :main_table
        '''), {'main_table': main_table})
        main_columns = set([row[0] for row in result])

    select_fields = ['row_number() OVER () AS id_unique', 'p.*']
    join_clauses = []
    for i, alea_table in enumerate(alea_tables):
        alias = f'a{i+1}'
        target_col = alea_table  # nom qu'on veut donner à la colonne résultante
        # Ne rajoute l'alias QUE SI pas déjà dans la table principale
        if target_col not in main_columns:
            select_fields.append(f'{alias}.alea AS {target_col}')
        join_clauses.append(f'LEFT JOIN "{alea_table}" {alias} ON ST_Intersects({alias}.geometry, p.geometry)')

    sql = f'''
        DROP MATERIALIZED VIEW IF EXISTS resilience."{view_name}";
        CREATE MATERIALIZED VIEW resilience."{view_name}" AS
        SELECT {', '.join(select_fields)}
        FROM resilience."{main_table}" p
        {' '.join(join_clauses)};
    '''


    if preview_only:
        aleas_desc = ', '.join([f'la couche de support "{a}" (valeur de l’aléa)' for a in alea_tables])
        description = (
            f'La vue matérialisée "{view_name}" croisera la couche principale "{main_table}" '
            f'(toutes ses colonnes) avec {aleas_desc}.<br>'
            "Pour chaque entité de la table principale, la vue ajoutera une colonne pour chaque aléa sélectionné, "
            "indiquant la valeur d’aléa si elle croise spatialement cette entité (ou NULL sinon).<br>"
            "Chaque ligne de la vue représente une entité de la couche principale enrichie de ses risques."
        )
        return jsonify({
            'status': 'preview',
            'sql': sql,
            'dependencies': [main_table] + alea_tables,
            'description': description,
        })



    try:
        with engine.begin() as conn:
            conn.execute(text(sql))
            return jsonify({
            'status': 'ok',
            'view': view_name,
            'dependencies': [main_table] + alea_tables,
            'sql': sql,
            'description': f'Vue matérialisée créée à partir de {main_table} et des couches alea {alea_tables}.'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e), 'sql': sql})


# Route pour charger une couche spécifique renvoie seulement les couches principales (sans préfixe alea)
@app.route('/resilience_layer_data/<layer_name>')
def get_resilience_layer_data(layer_name):
    try:
        with engine.begin() as conn:

            gdf = gpd.read_postgis(f'SELECT * FROM "{layer_name}"', con=conn, geom_col='geometry')
            gdf = gdf.to_crs(epsg=4326)
        
        # 🔧 Nettoyer les NaN
        gdf_clean = gdf.copy()
        gdf_clean = gdf_clean.replace({pd.NA: None})
        gdf_clean = gdf_clean.fillna('')  
        geojson = gdf_clean.__geo_interface__
        table_data = gdf_clean.drop(columns='geometry').to_dict(orient='records')

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
        result = conn.execute(text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'resilience'
              AND table_type IN ('BASE TABLE', 'VIEW')
              AND table_name LIKE 'alea%';
        """))
        alea_tables = [row[0] for row in result]
    return jsonify(sorted(alea_tables))


#dependance    
@app.route('/resilience_dependencies/<layer>')
def resilience_dependencies(layer):
    with engine.begin() as conn:
        result = conn.execute(text(f"""
            SELECT matviewname FROM pg_matviews
            WHERE schemaname = 'resilience'
              AND definition ILIKE '%{layer}%';
        """))
        deps = [row[0] for row in result]
    return jsonify({"dependencies": deps})


# route de suppression d'une couche
@app.route('/delete_resilience_layer', methods=['POST'])
def delete_resilience_layer():
    data = request.json
    layer = data.get('layer')

    try:
        with engine.begin() as conn:
            conn.execute(text(f'''
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT FROM pg_matviews 
                        WHERE matviewname = '{layer}' AND schemaname = 'resilience'
                    ) THEN
                        EXECUTE 'DROP MATERIALIZED VIEW resilience."{layer}" CASCADE';
                    ELSE
                        EXECUTE 'DROP TABLE IF EXISTS resilience."{layer}" CASCADE';
                    END IF;
                END;
                $$;
            '''))
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


# route de téléchargement d'une couche
@app.route('/download_resilience_layer/<layer>')
def download_resilience_layer(layer):
    format = request.args.get('format', 'csv')
    try:
        gdf = gpd.read_postgis(f'SELECT * FROM resilience."{layer}"', con=engine, geom_col='geometry')
        gdf = gdf.to_crs(epsg=4326)
        df = gdf.drop(columns='geometry')

        tmp = tempfile.TemporaryDirectory()

        if format == 'csv':
            path = os.path.join(tmp.name, f"{layer}.csv")
            df.to_csv(path, index=False, sep=';', encoding='utf-8')
            return send_file(path, as_attachment=True, download_name=f"{layer}.csv")

        elif format == 'html':
            path = os.path.join(tmp.name, f"{layer}.html")
            df.to_html(path, index=False)
            return send_file(path, as_attachment=True, download_name=f"{layer}.html")

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


@app.route('/alea_batch_run', methods=['POST'])
def alea_batch_run():
    data = request.get_json(force=True)
    main = (data or {}).get('main_layer')
    if not main:
        return jsonify({'status': 'error', 'message': 'Couche principale manquante'}), 400

    alea_tables = _list_alea_tables()
    if not alea_tables:
        return jsonify({'status': 'error', 'message': 'Aucune couche aléa trouvée.'}), 400

    result_table = f"{main}_alea_result"

    logs = []
    try:
        with engine.begin() as conn:
            # vérif existence de la couche principale
            exists = conn.execute(text("""
                SELECT 1 FROM information_schema.tables
                WHERE table_schema='resilience' AND table_name=:t
            """), {"t": main}).first()
            if not exists:
                return jsonify({'status': 'error', 'message': f'Couche principale {main} introuvable.'}), 400

            result_table = f"{main}_alea_result"
            conn.execute(text(f'DROP TABLE IF EXISTS "resilience"."{result_table}" CASCADE'))
            conn.execute(text(f'''
                CREATE TABLE "resilience"."{result_table}" AS
                SELECT *, row_number() OVER () AS __rowid
                FROM "resilience"."{main}"
            '''))
            conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{result_table}_geom_idx" ON "resilience"."{result_table}" USING GIST(geometry)'))
            conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{result_table}__rowid_idx" ON "resilience"."{result_table}" (__rowid)'))

            for idx, alea in enumerate(alea_tables, 1):
                start = time.time()
                col_name = f'alea-{alea}'
                conn.execute(text(f'ALTER TABLE "resilience"."{result_table}" ADD COLUMN "{col_name}" text'))
                conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{alea}_geom_idx" ON "resilience"."{alea}" USING GIST(geometry)'))

                value_col = 'alea' if _has_column(conn, 'resilience', alea, 'alea') else None
                if not value_col:
                    alt = conn.execute(text("""
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema='resilience' AND table_name=:t AND column_name <> 'geometry'
                        ORDER BY ordinal_position LIMIT 1
                    """), {"t": alea}).scalar()
                    value_col = alt or 'id'

                conn.execute(text(f'''
                    WITH agg AS (
                        SELECT r.__rowid,
                               string_agg(DISTINCT a."{value_col}"::text, ',') AS val
                        FROM "resilience"."{result_table}" r
                        JOIN "resilience"."{alea}" a
                          ON ST_Intersects(r.geometry, a.geometry)
                        GROUP BY r.__rowid
                    )
                    UPDATE "resilience"."{result_table}" r
                    SET "{col_name}" = agg.val
                    FROM agg
                    WHERE r.__rowid = agg.__rowid;
                '''))

                elapsed = round(time.time() - start, 2)
                logs.append({'layer': alea, 'seconds': elapsed, 'step': idx, 'total': len(alea_tables)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

    return jsonify({
        'status': 'ok',
        'result_table': result_table,
        'logs': logs,
        'download_csv': f'/download_alea_result/{result_table}'
    })


# --- Version streaming pour afficher la progression en temps réel (SSE) ---
from flask import stream_with_context
import json
import uuid

@app.route('/alea_batch_stream')
def alea_batch_stream():
    main = request.args.get('main_layer')
    if not main:
        return jsonify({'status': 'error', 'message': 'Couche principale manquante'}), 400

    alea_tables = _list_alea_tables()
    if not alea_tables:
        return jsonify({'status': 'error', 'message': 'Aucune couche aléa trouvée.'}), 400

    run_id = str(uuid.uuid4())
    result_table = f"{main}_alea_result"

    def gen():
        try:
            with engine.begin() as conn:
                exists = conn.execute(text("""
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema='resilience' AND table_name=:t
                """), {"t": main}).first()
                if not exists:
                    yield f"data: {json.dumps({'status':'error','message':f'Couche {main} introuvable'})}\n\n"
                    return

                conn.execute(text(f'DROP TABLE IF EXISTS "resilience"."{result_table}" CASCADE'))
                conn.execute(text(f'''
                    CREATE TABLE "resilience"."{result_table}" AS
                    SELECT *, row_number() OVER () AS __rowid
                    FROM "resilience"."{main}"
                '''))
                conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{result_table}_geom_idx" ON "resilience"."{result_table}" USING GIST(geometry)'))
                conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{result_table}__rowid_idx" ON "resilience"."{result_table}" (__rowid)'))

                for idx, alea in enumerate(alea_tables, 1):
                    start = time.time()
                    col_name = f'alea-{alea}'
                    conn.execute(text(f'ALTER TABLE "resilience"."{result_table}" ADD COLUMN "{col_name}" text'))
                    conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{alea}_geom_idx" ON "resilience"."{alea}" USING GIST(geometry)'))

                    value_col = 'alea' if _has_column(conn, 'resilience', alea, 'alea') else None
                    if not value_col:
                        alt = conn.execute(text("""
                            SELECT column_name FROM information_schema.columns
                            WHERE table_schema='resilience' AND table_name=:t AND column_name <> 'geometry'
                            ORDER BY ordinal_position LIMIT 1
                        """), {"t": alea}).scalar()
                        value_col = alt or 'id'

                    conn.execute(text(f'''
                        WITH agg AS (
                            SELECT r.__rowid,
                                   string_agg(DISTINCT a."{value_col}"::text, ',') AS val
                            FROM "resilience"."{result_table}" r
                            JOIN "resilience"."{alea}" a
                              ON ST_Intersects(r.geometry, a.geometry)
                            GROUP BY r.__rowid
                        )
                        UPDATE "resilience"."{result_table}" r
                        SET "{col_name}" = agg.val
                        FROM agg
                        WHERE r.__rowid = agg.__rowid;
                    '''))

                    elapsed = round(time.time() - start, 2)
                    payload = {
                        'status': 'progress',
                        'layer': alea,
                        'seconds': elapsed,
                        'step': idx,
                        'total': len(alea_tables)
                    }
                    yield f"data: {json.dumps(payload)}\n\n"

                conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{result_table}_geom_idx2" ON "resilience"."{result_table}" USING GIST(geometry)'))

            # fin
            yield f"data: {json.dumps({'status':'done','result_table':result_table,'download_csv':f'/download_alea_result/{result_table}'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'status':'error','message':str(e)})}\n\n"

    return Response(stream_with_context(gen()), mimetype='text/event-stream')


@app.route('/download_alea_result/<table>')
def download_alea_result(table):
    if not re.match(r'^[A-Za-z0-9_.-]+$', table or ''):
        return jsonify({'status': 'error', 'message': 'Nom de table invalide'}), 400
    sql = text(f'SELECT * FROM "resilience"."{table}"')
    df = pd.read_sql(sql, engine)
    # Nettoyage : on enlève la géométrie et l'id technique
    for col in ['geometry', '__rowid']:
        if col in df.columns:
            df = df.drop(columns=[col])
    csv_data = df.to_csv(index=False, sep=';', encoding='utf-8-sig')
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={table}.csv"})

