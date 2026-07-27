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
    "/",
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
    "/static/",
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


def _is_allowed_resilience_only_path(path: str) -> bool:
    exact_paths = set(app.config.get("RESILIENCE_ONLY_EXACT_PATHS", ()))
    prefix_paths = tuple(app.config.get("RESILIENCE_ONLY_PREFIX_PATHS", ()))
    if path in exact_paths:
        return True
    return any(path.startswith(prefix) for prefix in prefix_paths)


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
    if app.config.get("RESILIENCE_ONLY") and not _is_allowed_resilience_only_path(request.path):
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

