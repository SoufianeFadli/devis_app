from __future__ import annotations
from pathlib import Path
import hashlib
import os
import sqlite3 
from datetime import date
from io import BytesIO
import shutil
import tempfile
import base64 
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, Request, UploadFile, File, Form, HTTPException,Query, status
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app.services.parser_progiciel import parse_progiciel_csv
from app.services.engine import (
    PRICE_STD_POUTRELLE_ML,
    build_poutrelles_ml_by_type,
    compute_devis,
    group_identical_articles,
    simulate_transport,
    sort_articles_for_display,
)
from app.services.hourdis_corrections import (
    HOURDIS_TYPES,
    apply_hourdis_overrides,
    build_hourdis_overrides,
)
from pydantic import BaseModel
from jinja2 import Environment, FileSystemLoader, select_autoescape
from import_clients import import_clients

BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", str(BASE_DIR))).resolve()
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = STORAGE_DIR / "devis.db"
UPLOAD_DIR = STORAGE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
PDF_DIR = STORAGE_DIR / "generated_pdfs"
PDF_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
templates = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"])
)
SECRET_KEY = os.getenv("SECRET_KEY", "local-development-secret")

# --- Initialisation base SQLite (table users) ---

def init_db_users():
    """Crée la table users si elle n'existe pas et insère les commerciaux de base."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Création de la table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            code_commercial TEXT NOT NULL,
            nom TEXT NOT NULL
        )
        """
    )

    # Données de base (commerciaux)
    seed_users = [
        ("ga",              "1234",     "GA",  "Commercial GA"),
        ("FIKRI HAMMADI",   "SBBM FH",  "FH",  "Commercial FH"),
        ("ELOMARI AHMED",   "SBBM EA",  "EA",  "Commercial EA"),
        ("CHARROUK ABDELKARIM", "SBBM CH", "CH", "Commercial CH"),
        ("BOUALI",          "SBBM BA",  "BA",  "Commercial BA"),
        ("DGA",             "SBBM DGA", "DGA", "Commercial DGA"),
    ]

    # INSERT OR IGNORE → ne double pas les lignes si elles existent
    cur.executemany(
        """
        INSERT OR IGNORE INTO users (username, password_hash, code_commercial, nom)
        VALUES (?, ?, ?, ?)
        """,
        seed_users,
    )

    conn.commit()
    conn.close()


# Appel au démarrage du module (local + Render)
init_db_users()

def hash_password(pwd: str) -> str:
    """Retourne le hash SHA256 d'un mot de passe en texte clair."""
    return hashlib.sha256(pwd.encode("utf-8")).hexdigest()


def authenticate_user(username: str, password: str):
    """Vérifie username / password, retourne le row user ou None."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    if row["password_hash"] != hash_password(password):
        return None

    return row


def get_current_user(request: Request):
    """Récupère l'utilisateur courant à partir du cookie session_username."""
    username = request.cookies.get("session_username")
    if not username:
        return None

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT id, username, code_commercial, nom FROM users WHERE username = ?",
        (username,),
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "id": row["id"],
        "username": row["username"],
        "code_commercial": row["code_commercial"],
        "nom": row["nom"],
    }


# --- Initialisation table clients + import CSV si nécessaire ---
def ensure_clients_imported():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        # 1) vérifier si la table existe
        cur.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='clients'
        """)
        has_table = cur.fetchone() is not None

        if not has_table:
            # si la table n'existe pas du tout, on lance l'import
            conn.close()
            print("Table clients absente → import CSV...")
            import_clients(DB_PATH)
            return

        # 2) si la table existe, vérifier si elle est vide
        cur.execute("SELECT COUNT(*) FROM clients")
        (nb,) = cur.fetchone()
        conn.close()

        if nb == 0:
            print("Table clients vide → import CSV...")
            import_clients(DB_PATH)
        else:
            print(f"Table clients déjà peuplée ({nb} lignes), pas d'import.")
    except Exception as e:
        print("⚠️ Erreur ensure_clients_imported:", e)


# Appel au démarrage du module
ensure_clients_imported()

# === Base SQLite clients ======================================================
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


class ClientCreate(BaseModel):
    code_client: str
    nom_client: str



# === Logo en base64 pour HTML & PDF ==========================================
STATIC_DIR = BASE_DIR / "static"
LOGO_DATA_URI = ""

try:
    logo_path = STATIC_DIR / "logo_sbbm.jpg"
    with open(logo_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
        LOGO_DATA_URI = f"data:image/jpeg;base64,{encoded}"
    print("Logo SBBM chargé en base64 pour PDF.")
except Exception as e:
    print("⚠️ Impossible de charger le logo SBBM :", e)
          
# === WeasyPrint optionnel =====================================================
try:
    from weasyprint import HTML, CSS  # type: ignore

    WEASYPRINT_OK = True
    print("WeasyPrint détecté : génération PDF activée.")
except Exception as e:  # ImportError + libs natives manquantes
    HTML = None  # type: ignore
    CSS = None   # type: ignore
    WEASYPRINT_OK = False
    print("⚠️ WeasyPrint indisponible, PDF désactivé :", e)

def get_pdf_path(ref_devis: str) -> Path:
    """Construit le chemin du fichier PDF pour un ref_devis donné."""
    safe_ref = "".join(c for c in ref_devis if c.isalnum() or c in "-_")
    if not safe_ref:
        safe_ref = "NOREF"
    return PDF_DIR / f"Devis_SBBM_{safe_ref}.pdf"
    

# === Compteur simple pour les références de devis ============================
REF_COUNTER = 1  # redémarre à 1 à chaque lancement du serveur

# === SQLite : création table devis si nécessaire ==============================
def init_db():
    """Crée les tables nécessaires et importe les clients depuis le CSV si besoin."""
    # 1) Création des tables
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Table devis (adapte les colonnes si tu as déjà une définition différente)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS devis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_devis TEXT UNIQUE NOT NULL,
            date_devis TEXT,
            client TEXT,
            chantier TEXT,
            code_client TEXT,
            code_commercial TEXT,
            nom_commercial TEXT,
            total_ht REAL,
            total_ttc REAL,
            mode_saisie TEXT,
            mode_transport TEXT,
            transport_mode TEXT
        )
        """
    )

    # Table clients
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code_client TEXT UNIQUE NOT NULL,
            nom_client TEXT NOT NULL
        )
        """
    )

    conn.commit()

    # 2) Import CSV si la table clients est vide
    try:
        cur.execute("SELECT COUNT(*) FROM clients")
        nb = cur.fetchone()[0]
    except Exception as e:
        print("⚠️ Erreur lecture nombre de clients :", e)
        nb = 0

    if nb == 0 and CLIENTS_CSV.exists():
        print(f"Import clients depuis : {CLIENTS_CSV}")
        try:
            rows_to_insert = []
            with CLIENTS_CSV.open("r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f, delimiter=";")
                for row in reader:
                    code = (row.get("CODE_CLIENT") or "").strip()
                    nom = (row.get("NOM_CLIENT") or "").strip()
                    if not code or not nom:
                        continue
                    rows_to_insert.append((code, nom))

            with conn:
                conn.executemany(
                    "INSERT OR IGNORE INTO clients (code_client, nom_client) VALUES (?, ?)",
                    rows_to_insert,
                )

            print(
                f"Import terminé. {len(rows_to_insert)} lignes insérées (INSERT OR IGNORE)."
            )
        except Exception as e:
            print("⚠️ Erreur import clients CSV :", e)
    else:
        print(f"Table clients déjà remplie ({nb} lignes). Pas d'import CSV.")

    conn.close()

init_db()

def get_next_ref_devis() -> str:
    """
    Retourne la prochaine référence de devis au format D00001, D00002, ...
    en se basant sur la dernière ligne de la table devis.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT ref_devis FROM devis ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()

    if not row or not row[0]:
        return "D00001"

    last = row[0]
    # On suppose un format Dxxxxx
    try:
        num = int(last[1:])
    except ValueError:
        return "D00001"

    return f"D{num + 1:05d}"


def insert_devis_row(
    ref_devis: str,
    date_devis: str,
    client: str,
    chantier: str,
    code_client: str,
    code_commercial: str,
    nom_commercial: str,
    total_ht: float,
    total_ttc: float,
    saisie_mode: str,
    mode_transport: str,
    transport_mode: str,
) -> None:
    """Insère (ou remplace) un enregistrement dans la table devis."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR REPLACE INTO devis (
            ref_devis, date_devis, client, chantier, code_client,
            code_commercial, nom_commercial,
            total_ht, total_ttc,
            mode_saisie, mode_transport, transport_mode
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ref_devis,
            date_devis,
            client,
            chantier,
            code_client,
            code_commercial,
            nom_commercial,
            float(total_ht or 0.0),
            float(total_ttc or 0.0),
            saisie_mode,
            mode_transport,
            transport_mode,
        ),
    )
    conn.commit()
    conn.close()


def fetch_devis_list(limit: int = 200) -> List[Dict[str, Any]]:
    """Retourne les derniers devis pour l'historique."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            id,
            ref_devis,
            date_devis,
            client,
            chantier,
            total_ht,
            total_ttc,
            code_commercial,
            nom_commercial
        FROM devis
        ORDER BY date_devis DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows





# === WeasyPrint optionnel =====================================================
try:
    from weasyprint import HTML  # type: ignore

    WEASYPRINT_OK = True
    print("WeasyPrint détecté : génération PDF activée.")
except Exception as e:  # ImportError + libs natives manquantes
    HTML = None  # type: ignore
    WEASYPRINT_OK = False
    print("⚠️ WeasyPrint indisponible, PDF désactivé :", e)



# === FastAPI / Templates / Static ============================================
app = FastAPI()

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": "",
        },
    )

# Traitement login (POST)
@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    """
    Authentification SIMPLE :
    - on compare username ET password_hash exactement comme en base.
    """

    username_input = (username or "").strip()
    password_input = (password or "").strip()

    # Petit log dans le terminal pour debug
    print("Tentative login →", repr(username_input), repr(password_input))

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 🔹 Requête ultra simple : username + password_hash
    cur.execute(
        """
        SELECT id, username, password_hash, code_commercial, nom
        FROM users
        WHERE username = ? AND password_hash = ?
        """,
        (username_input, password_input),
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        print("⚠️ Login échoué")
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Identifiant ou mot de passe incorrect.",
            },
            status_code=401,
        )

    print("✅ Login OK pour", row["username"], "code_commercial:", row["code_commercial"])

    # 🔹 Redirection vers le formulaire AVEC cookies
    resp = RedirectResponse(url="/devis/form", status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie("user_code_commercial", row["code_commercial"], httponly=True)
    resp.set_cookie("user_nom", row["nom"], httponly=False)
    resp.set_cookie("user_username", row["username"], httponly=False)
    return resp


@app.get("/logout")
def logout():
    """Déconnexion : on supprime les cookies et on renvoie vers /login."""
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie("user_id")
    resp.delete_cookie("user_username")
    resp.delete_cookie("user_code_commercial")
    resp.delete_cookie("user_nom")
    return resp

@app.post("/clients/new")
async def create_client(
    code_client: str = Form(...),
    nom_client: str = Form(...),
):
    """
    Ajoute un nouveau client dans la table 'clients'.
    """
    code_client = code_client.strip()
    nom_client = nom_client.strip()

    if not code_client or not nom_client:
        raise HTTPException(status_code=400, detail="Code et nom obligatoires")

    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        # on garde le code_client unique
        cur.execute(
            """
            INSERT OR IGNORE INTO clients (code_client, nom_client)
            VALUES (?, ?)
            """,
            (code_client, nom_client),
        )
        conn.commit()
    finally:
        conn.close()

    # Réponse simple pour le JS
    return JSONResponse(
        {
            "status": "ok",
            "code_client": code_client,
            "nom_client": nom_client,
        }
    )
# === Données commerciales =====================================================

COMMERCIAUX: Dict[str, str] = {
    "FH": "FIKRI HAMADI",
    "AE": "ELOMARI AHMED",
    "CH": "CHARROUK ABDELKARIM",
    "BA": "BOUALI ABDERAZAK",
    "GA": "GÉNÉRAL",
}

# Pour l'endpoint AJAX de simulation de transport
LAST_POUTRELLES: List[dict] = []
LAST_HOURDIS: List[dict] = []
LAST_SURFACE_CT: float = 0.0
LAST_SURFACE_TS: float = 0.0


# === ROUTES ===================================================================


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    # connecté → on envoie vers le formulaire
    return RedirectResponse(url="/devis/form", status_code=303)


@app.get("/health")
def health_check():
    """Contrôle de santé utilisé par Render pendant les déploiements."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("SELECT 1")
        conn.close()
    except sqlite3.Error as e:
        raise HTTPException(status_code=503, detail="Base SQLite indisponible") from e
    return {"status": "ok"}

@app.get("/devis/form", response_class=HTMLResponse)
def devis_form(request: Request):
    """Affiche le formulaire de saisie."""

    today_str = date.today().strftime("%d/%m/%Y")

    try:
        next_ref = get_next_ref_devis()
    except Exception as e:
        print("⚠️ Erreur get_next_ref_devis:", e)
        next_ref = ""

    # 🔹 Infos de l’utilisateur connecté (cookies mis au login)
    user_code_commercial = request.cookies.get("user_code_commercial", "")
    user_nom = request.cookies.get("user_nom", "")
    user_username = request.cookies.get("user_username", "")

    return templates.TemplateResponse(
        "devis_form.html",
        {
            "request": request,
            "today": today_str,
            "liste_commerciaux": COMMERCIAUX,
            "next_ref_devis": next_ref,
            "user_code_commercial": user_code_commercial,
            "user_nom": user_nom,
            "user_username": user_username,
        },
    )


@app.post("/api/csv/hourdis-preview")
async def preview_csv_hourdis(
    fichiers: Optional[List[UploadFile]] = File(None),
):
    """Analyse les CSV sélectionnés pour permettre la correction des hourdis."""
    preview_files: List[Dict[str, Any]] = []

    for file_index, fichier in enumerate(
        f for f in (fichiers or []) if f.filename
    ):
        tmp_path: Optional[Path] = None
        filename = Path(fichier.filename or "fichier.csv").name
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
                shutil.copyfileobj(fichier.file, tmp)
                tmp_path = Path(tmp.name)

            parsed = parse_progiciel_csv(tmp_path)
            rows = [
                {
                    "key": f"{file_index}:{row_index}",
                    "row_index": row_index,
                    "detected_type": str(row.get("type", "")).strip().upper(),
                    "nombre": float(row.get("nombre", 0.0) or 0.0),
                }
                for row_index, row in enumerate(parsed.get("hourdis", []))
            ]
            preview_files.append(
                {
                    "file_index": file_index,
                    "filename": filename,
                    "level_name": Path(filename).stem.strip().upper() or "NIVEAU",
                    "rows": rows,
                }
            )
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Impossible de lire le fichier CSV '{filename}': {e}",
            ) from e
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
            await fichier.close()

    return JSONResponse(
        {"files": preview_files, "allowed_types": list(HOURDIS_TYPES)}
    )


@app.post("/generate")
async def generate_devis(
    request: Request,
    code_client: str = Form(""),
    client: str = Form(...),
    chantier: str = Form(...),
    niveau: str = Form(""),
    affaire: str = Form(""),
    date_devis: str = Form(""),
    ref_devis: str = Form(""),
    mode_livraison: str = Form("SOLO"),
    distance_km: float = Form(0.0),
    validite: str = Form("30 jours"),
    # Données commerciales
    code_commercial: str = Form("GA"),
    remise_poutrelle: float = Form(0.0),
    remise_hourdis: float = Form(0.0),
    prix_ct: float = Form(3.0),
    prix_treillis: float = Form(160.0),
    # Transport
    mode_transport: str = Form("depart"),
    transport_mode: str = Form("auto"),
    transport_prix_poutrelle_manuel: float = Form(0.0),
    transport_prix_hourdis_manuel: float = Form(0.0),
    # Choix de saisie : "progiciel" ou "manuel"
    saisie_mode: str = Form("progiciel"),
    # Présentation : devis consolidé ou sections séparées par fichier/niveau
    presentation_mode: str = Form("regroupe"),
    # Saisie manuelle – listes dynamiques
    manual_pout_type: Optional[List[str]] = Form(None),
    manual_pout_longueur: Optional[List[float]] = Form(None),
    manual_pout_etrier: Optional[List[float]] = Form(None),
    manual_pout_nombre: Optional[List[float]] = Form(None),
    manual_hourdis_type: Optional[List[str]] = Form(None),
    manual_hourdis_nombre: Optional[List[float]] = Form(None),
    hourdis_override_key: Optional[List[str]] = Form(None),
    hourdis_override_type: Optional[List[str]] = Form(None),
    surface_ct_manual: float = Form(0.0),
    nb_treillis_manual: float = Form(0.0),
    # Un ou plusieurs fichiers progiciel
    fichier_progiciel: Optional[List[UploadFile]] = File(None),
):
    """
    Récupère le formulaire + (optionnellement) le CSV progiciel ou la saisie manuelle,
    calcule le devis puis renvoie l’HTML (et génère le PDF sur disque si WeasyPrint OK).
    """
    global LAST_POUTRELLES, LAST_HOURDIS, LAST_SURFACE_CT, LAST_SURFACE_TS

    # 🟢 Infos utilisateur depuis les cookies (mis au login)
    user_code_commercial = request.cookies.get("user_code_commercial", "")
    user_nom = request.cookies.get("user_nom", "")
    user_username = request.cookies.get("user_username", "")

    # Si un code commercial est dans le cookie, on force cette valeur
    if user_code_commercial:
        code_commercial = user_code_commercial

    poutrelles: List[dict] = []
    hourdis: List[dict] = []
    surface_ct: float = 0.0
    surface_ts: float = 0.0
    source_filenames: List[str] = []
    niveaux_sources: List[Dict[str, Any]] = []
    hourdis_corrections: List[Dict[str, Any]] = []

    # Normaliser les listes manuelles pour éviter None
    manual_pout_type = manual_pout_type or []
    manual_pout_longueur = manual_pout_longueur or []
    manual_pout_etrier = manual_pout_etrier or []
    manual_pout_nombre = manual_pout_nombre or []
    manual_hourdis_type = manual_hourdis_type or []
    manual_hourdis_nombre = manual_hourdis_nombre or []
    hourdis_overrides = build_hourdis_overrides(
        hourdis_override_key or [], hourdis_override_type or []
    )

    # Si la réf devis est vide (ou non envoyée), on génère automatiquement
    if not ref_devis or not ref_devis.strip():
        ref_devis = get_next_ref_devis()

    # === 1) MODE PROGICIEL ====================================================
    if saisie_mode == "progiciel":
        fichiers = [f for f in (fichier_progiciel or []) if f.filename]
        if fichiers:
            for file_index, fichier in enumerate(fichiers):
                tmp_path: Optional[Path] = None
                filename = Path(fichier.filename or "fichier.csv").name
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
                        shutil.copyfileobj(fichier.file, tmp)
                        tmp_path = Path(tmp.name)

                    parsed = parse_progiciel_csv(tmp_path)
                    fichier_poutrelles = parsed.get("poutrelles", [])
                    fichier_hourdis = parsed.get("hourdis", [])
                    fichier_hourdis, fichier_corrections = apply_hourdis_overrides(
                        fichier_hourdis,
                        file_index,
                        hourdis_overrides,
                        filename,
                    )
                    hourdis_corrections.extend(fichier_corrections)
                    fichier_surface_ct = float(parsed.get("surface_ct", 0.0) or 0.0)
                    fichier_surface_ts = float(parsed.get("surface_ts", 0.0) or 0.0)

                    niveau_poutrelles, niveau_hourdis = group_identical_articles(
                        fichier_poutrelles, fichier_hourdis
                    )
                    niveau_poutrelles, niveau_hourdis = sort_articles_for_display(
                        niveau_poutrelles, niveau_hourdis
                    )
                    niveaux_sources.append(
                        {
                            "nom": Path(filename).stem.strip().upper() or "NIVEAU",
                            "filename": filename,
                            "poutrelles": niveau_poutrelles,
                            "hourdis": niveau_hourdis,
                            "surface_ct": fichier_surface_ct,
                            "surface_ts": fichier_surface_ts,
                        }
                    )

                    # Un seul devis consolidé : les lignes sont concaténées et
                    # les surfaces de tous les fichiers sont additionnées.
                    poutrelles.extend(fichier_poutrelles)
                    hourdis.extend(fichier_hourdis)
                    surface_ct += fichier_surface_ct
                    surface_ts += fichier_surface_ts
                    source_filenames.append(filename)

                    print(
                        f"DEBUG CSV {filename}: {len(fichier_poutrelles)} poutrelles, "
                        f"{len(fichier_hourdis)} hourdis, "
                        f"SURFACE CT={fichier_surface_ct}, SURFACE TS={fichier_surface_ts}"
                    )
                except Exception as e:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Impossible de lire le fichier CSV '{filename}': {e}",
                    ) from e
                finally:
                    if tmp_path is not None:
                        try:
                            tmp_path.unlink(missing_ok=True)
                        except Exception:
                            pass
                    await fichier.close()

            nb_poutrelles_avant = len(poutrelles)
            nb_hourdis_avant = len(hourdis)
            poutrelles, hourdis = group_identical_articles(poutrelles, hourdis)

            LAST_POUTRELLES = poutrelles
            LAST_HOURDIS = hourdis
            LAST_SURFACE_CT = surface_ct
            LAST_SURFACE_TS = surface_ts

            print(
                f"DEBUG consolidation {len(source_filenames)} CSV: "
                f"poutrelles {nb_poutrelles_avant} -> {len(poutrelles)}, "
                f"hourdis {nb_hourdis_avant} -> {len(hourdis)}, "
                f"SURFACE CT={surface_ct}, SURFACE TS={surface_ts}"
            )
        else:
            LAST_POUTRELLES = []
            LAST_HOURDIS = []
            LAST_SURFACE_CT = 0.0
            LAST_SURFACE_TS = 0.0
            print("DEBUG generate_devis: mode progiciel mais aucun fichier fourni.")

    # === 2) MODE MANUEL =======================================================
    else:
        # Poutrelles manuelles
        for t, L, e, n in zip(
            manual_pout_type, manual_pout_longueur, manual_pout_etrier, manual_pout_nombre
        ):
            t_str = (t or "").strip()
            if not t_str:
                continue
            try:
                L_val = float(L)
                e_val = float(e)
                n_val = float(n)
            except (TypeError, ValueError):
                continue
            if L_val <= 0 or n_val <= 0:
                continue
            poutrelles.append(
                {
                    "type": t_str,
                    "longueur": L_val,
                    "etrier": e_val,
                    "nombre": n_val,
                }
            )

        # Hourdis manuels
        for t, q in zip(manual_hourdis_type, manual_hourdis_nombre):
            t_str = (t or "").strip()
            if not t_str:
                continue
            try:
                q_val = float(q)
            except (TypeError, ValueError):
                continue
            if q_val <= 0:
                continue
            hourdis.append({"type": t_str, "nombre": q_val})

        surface_ct = float(surface_ct_manual or 0.0)
        # On reconstruit surface_ts à partir du nombre de treillis saisi
        surface_ts = float(nb_treillis_manual or 0.0) * 10.0

        niveau_poutrelles, niveau_hourdis = sort_articles_for_display(
            poutrelles, hourdis
        )

        niveaux_sources.append(
            {
                "nom": (niveau or "SAISIE MANUELLE").strip().upper(),
                "filename": "",
                "poutrelles": niveau_poutrelles,
                "hourdis": niveau_hourdis,
                "surface_ct": surface_ct,
                "surface_ts": surface_ts,
            }
        )

        print(
            f"DEBUG saisie manuelle: {len(poutrelles)} poutrelles, "
            f"{len(hourdis)} hourdis, SURFACE CT={surface_ct}, SURFACE TS={surface_ts}"
        )

        LAST_POUTRELLES = poutrelles
        LAST_HOURDIS = hourdis
        LAST_SURFACE_CT = surface_ct
        LAST_SURFACE_TS = surface_ts

    # === 3) TRI VISUEL ET CALCUL DU DEVIS ====================================
    poutrelles, hourdis = sort_articles_for_display(poutrelles, hourdis)

    data_calc = compute_devis(
        poutrelles,
        hourdis,
        surface_ct,
        surface_ts,
        remise_poutrelle,
        remise_hourdis,
        prix_ct,
        prix_treillis,
        mode_transport,
        transport_mode,
        distance_km,
        transport_prix_poutrelle_manuel,
        transport_prix_hourdis_manuel,
    )

    # === 4) PRÉSENTATION DÉTAILLÉE PAR NIVEAU ================================
    if presentation_mode not in {"regroupe", "par_niveau", "ml_par_type"}:
        presentation_mode = "regroupe"

    niveaux_calc: List[Dict[str, Any]] = []
    lignes_globales: List[Dict[str, Any]] = []
    lignes_poutrelles_ml: List[Dict[str, Any]] = []
    lignes_autres_ml: List[Dict[str, Any]] = []

    if presentation_mode == "par_niveau" and niveaux_sources:
        tr_ml_global = float(data_calc.get("transport_par_ml_brut", 0.0) or 0.0)
        tr_hourdis_global = float(
            data_calc.get("transport_par_hourdis_brut", 0.0) or 0.0
        )

        for source in niveaux_sources:
            niveau_calc = compute_devis(
                source["poutrelles"],
                source["hourdis"],
                source["surface_ct"],
                0.0,  # le treillis est arrondi et facturé une seule fois globalement
                remise_poutrelle,
                remise_hourdis,
                prix_ct,
                prix_treillis,
                mode_transport,
                "manuel" if mode_transport == "rendu" else transport_mode,
                distance_km,
                tr_ml_global,
                tr_hourdis_global,
            )
            niveaux_calc.append(
                {
                    **source,
                    "lignes": niveau_calc["lignes"],
                    "subtotal_ht": niveau_calc["total_ht"],
                }
            )

        lignes_globales = [
            ligne
            for ligne in data_calc.get("lignes", [])
            if ligne.get("type") == "TREILLES SOUDEES"
        ]

        # Répartit l'éventuel centime d'arrondi sur le dernier sous-total afin
        # que la somme affichée des niveaux reste égale au total général.
        total_global_lines = round(
            sum(float(ligne.get("total", 0.0) or 0.0) for ligne in lignes_globales),
            2,
        )
        total_niveaux_cible = round(data_calc["total_ht"] - total_global_lines, 2)
        total_niveaux_affiche = round(
            sum(float(item["subtotal_ht"]) for item in niveaux_calc), 2
        )
        ecart_arrondi = round(total_niveaux_cible - total_niveaux_affiche, 2)
        if niveaux_calc and ecart_arrondi:
            niveaux_calc[-1]["subtotal_ht"] = round(
                float(niveaux_calc[-1]["subtotal_ht"]) + ecart_arrondi, 2
            )

    if presentation_mode == "ml_par_type":
        lignes_poutrelles_ml = build_poutrelles_ml_by_type(
            poutrelles,
            remise_poutrelle,
            float(data_calc.get("transport_par_ml_brut", 0.0) or 0.0),
        )
        lignes_autres_ml = [
            ligne
            for ligne in data_calc.get("lignes", [])
            if ligne.get("type") not in PRICE_STD_POUTRELLE_ML
            and ligne.get("type") != "ETRIERS"
        ]

        # Affecte les éventuels centimes d'arrondi à la dernière famille pour
        # que la somme des lignes présentées reste exactement égale au total HT.
        cible_poutrelles = round(
            float(data_calc.get("total_ht", 0.0))
            - sum(float(ligne.get("total", 0.0)) for ligne in lignes_autres_ml),
            2,
        )
        total_poutrelles_affiche = round(
            sum(float(ligne["total"]) for ligne in lignes_poutrelles_ml), 2
        )
        ecart_ml = round(cible_poutrelles - total_poutrelles_affiche, 2)
        if lignes_poutrelles_ml and ecart_ml:
            derniere_ligne = lignes_poutrelles_ml[-1]
            derniere_ligne["total"] = round(
                float(derniere_ligne["total"]) + ecart_ml, 2
            )
            derniere_ligne["prix_ml_complet"] = round(
                float(derniere_ligne["total"])
                / float(derniere_ligne["total_ml"]),
                4,
            )

    print(
        "DEBUG main.generate_devis -> "
        f"poutrelles={len(poutrelles)}, hourdis={len(hourdis)}, "
        f"SURFACE CT={surface_ct}, SURFACE TS={surface_ts}, "
        f"transport_total_choisi={data_calc.get('transport_total_choisi')}"
    )

    # === 5) SAUVEGARDE EN BASE SQLITE ========================================
    date_devis_finale = date_devis or date.today().strftime("%d/%m/%Y")
    code_commercial_up = (code_commercial or "GA").upper()
    nom_commercial = user_nom or COMMERCIAUX.get(code_commercial_up, "")

    try:
        insert_devis_row(
            ref_devis=ref_devis,
            date_devis=date_devis_finale,
            client=client,
            chantier=chantier,
            code_client=code_client,
            code_commercial=code_commercial_up,
            nom_commercial=nom_commercial,
            total_ht=data_calc.get("total_ht", 0.0),
            total_ttc=data_calc.get("total_ttc", 0.0),
            saisie_mode=saisie_mode,
            mode_transport=mode_transport,
            transport_mode=transport_mode,
        )
    except Exception as e:
        print("⚠️ Erreur insert_devis_row:", e)

    # === 6) CONTEXTE TEMPLATE ================================================
    context: Dict[str, Any] = {
        "request": request,
        "code_client": code_client,
        "client": client,
        "chantier": chantier,
        "niveau": niveau,
        "affaire": affaire,
        "ref_devis": ref_devis,
        "date_devis": date_devis_finale,
        "mode_livraison": mode_livraison,
        "distance_km": distance_km,
        "validite": validite,
        "code_commercial": code_commercial_up,
        "nom_commercial": nom_commercial,
        # Infos user (pour bandeau, etc.)
        "user_code_commercial": user_code_commercial,
        "user_nom": user_nom,
        "user_username": user_username,
        "mode_transport": mode_transport,
        "transport_mode": transport_mode,
        "transport_prix_poutrelle_manuel": transport_prix_poutrelle_manuel,
        "transport_prix_hourdis_manuel": transport_prix_hourdis_manuel,
        "remise_poutrelle": remise_poutrelle,
        "remise_hourdis": remise_hourdis,
        "prix_ct": prix_ct,
        "prix_treillis": prix_treillis,
        "saisie_mode": saisie_mode,
        "presentation_mode": presentation_mode,
        "niveaux_calc": niveaux_calc,
        "lignes_globales": lignes_globales,
        "lignes_poutrelles_ml": lignes_poutrelles_ml,
        "lignes_autres_ml": lignes_autres_ml,
        "source_filenames": source_filenames,
        "nombre_fichiers": len(source_filenames),
        "hourdis_corrections": hourdis_corrections,
        "surface_ct": surface_ct,
        "surface_ts": surface_ts,
        "logo_data_uri": LOGO_DATA_URI,
        "pdf_available": WEASYPRINT_OK and HTML is not None,
        **data_calc,
    }

    # === 7) Rendu HTML + génération PDF éventuelle ===========================
    template = templates.get_template("devis.html")
    html = template.render(context)

    if WEASYPRINT_OK and HTML is not None:
        try:
            stylesheets = []
            if CSS is not None:
                stylesheets = [CSS(str(BASE_DIR / "static" / "style.css"))]

            pdf_bytes = HTML(
                string=html,
                base_url=str(BASE_DIR),
            ).write_pdf(stylesheets=stylesheets)

            pdf_path = get_pdf_path(ref_devis)
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)

            print(f"PDF sauvegardé : {pdf_path}")
        except Exception as e:
            print("⚠️ Erreur génération PDF :", e)

    return HTMLResponse(content=html)
    
@app.get("/pdf/{ref_devis}")
def export_pdf(ref_devis: str):
    """Retourne le PDF correspondant à la réf devis."""
    pdf_path = get_pdf_path(ref_devis)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF introuvable, regénérez le devis.")

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=pdf_path.name,
    )   


@app.post("/simulate-transport")
async def simulate_transport_endpoint(
    distance_km: float = Body(...),
    mode_transport: str = Body("depart"),
    transport_mode: str = Body("auto"),
    transport_prix_poutrelle_manuel: float = Body(0.0),
    transport_prix_hourdis_manuel: float = Body(0.0),
):
    """
    Endpoint AJAX pour calculer en direct le coût de transport
    à partir du dernier CSV ou de la dernière saisie manuelle.
    """
    global LAST_POUTRELLES, LAST_HOURDIS

    info = simulate_transport(
        LAST_POUTRELLES,
        LAST_HOURDIS,
        distance_km,
        mode_transport,
        transport_mode,
        transport_prix_poutrelle_manuel,
        transport_prix_hourdis_manuel,
    )
    return JSONResponse(info)

@app.get("/devis/historique", response_class=HTMLResponse)
def devis_historique(request: Request):
    """Affiche la liste des devis enregistrés en base."""
    devis_list = fetch_devis_list(limit=200)
    return templates.TemplateResponse(
        "devis_historique.html",
        {
            "request": request,
            "devis_list": devis_list,
        },
    )
@app.get("/api/clients")
def api_search_clients(q: str = Query("", min_length=0, description="Code ou nom client")):
    """
    Recherche de clients pour l'auto-complétion.
    - q : texte saisi (code ou nom)
    Retourne une liste de dicts : {code_client, nom_client}
    """
    term = (q or "").strip()
    results = []

    # Si rien saisi, on peut soit renvoyer vide, soit quelques clients au hasard
    if not term:
        return JSONResponse(results)

    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        # Recherche sur code_client OU nom_client (insensible à la casse)
        cur.execute(
            """
            SELECT code_client, nom_client
            FROM clients
            WHERE code_client LIKE ? OR nom_client LIKE ?
            ORDER BY nom_client
            LIMIT 20
            """,
            (f"%{term}%", f"%{term}%"),
        )
        rows = cur.fetchall()
        conn.close()

        for code_client, nom_client in rows:
            results.append(
                {
                    "code_client": code_client.strip() if code_client else "",
                    "nom_client": nom_client.strip() if nom_client else "",
                }
            )
    except Exception as e:
        print("⚠️ Erreur api_search_clients:", e)

    return JSONResponse(results)
@app.post("/api/clients")
async def api_create_client(payload: dict = Body(...)):
    """
    Création rapide d'un client depuis le formulaire (+ Nouveau client).
    - Si le code_client n'existe pas encore => insertion.
    - Si le code_client existe déjà      => on retourne l'existant (status = "exists").
    """
    code = (payload.get("code_client") or "").strip()
    nom = (payload.get("nom_client") or "").strip()

    if not code or not nom:
        return JSONResponse(
            {"detail": "Code client et nom client sont obligatoires."},
            status_code=400,
        )

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO clients (code_client, nom_client) VALUES (?, ?)",
                (code, nom),
            )
        client_id = cur.lastrowid
        status = "created"
    except sqlite3.IntegrityError:
        # Le code client existe déjà, on récupère la ligne
        cur = conn.execute(
            "SELECT id, code_client, nom_client FROM clients WHERE code_client = ?",
            (code,),
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            return JSONResponse(
                {"detail": "Erreur interne lors de la récupération du client."},
                status_code=500,
            )
        client_id = row["id"]
        code = row["code_client"]
        nom = row["nom_client"]
        status = "exists"
    finally:
        conn.close()

    return {
        "status": status,          # "created" ou "exists"
        "id": client_id,
        "code_client": code,
        "nom_client": nom,
    }
