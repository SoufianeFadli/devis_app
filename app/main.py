from __future__ import annotations
from pathlib import Path
import sqlite3 
from datetime import date
from io import BytesIO
import shutil
import tempfile
import base64 
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app.services.parser_progiciel import parse_progiciel_csv
from app.services.engine import compute_devis, simulate_transport

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "devis.db"
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
PDF_DIR = BASE_DIR / "generated_pdfs"
PDF_DIR.mkdir(exist_ok=True)
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
def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS devis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_devis TEXT UNIQUE NOT NULL,
            date_devis TEXT NOT NULL,
            client TEXT,
            chantier TEXT,
            code_client TEXT,
            code_commercial TEXT,
            nom_commercial TEXT,
            total_ht REAL,
            total_ttc REAL,
            saisie_mode TEXT,
            mode_transport TEXT,
            transport_mode TEXT
        )
        """
    )
    conn.commit()
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
            saisie_mode, mode_transport, transport_mode
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
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

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
    return templates.TemplateResponse(
        "home.html",
        {"request": request},
    )

@app.get("/devis/form", response_class=HTMLResponse)
def devis_form(request: Request):
    """Affiche le formulaire de saisie."""
    today_str = date.today().strftime("%d/%m/%Y")
    try:
        next_ref = get_next_ref_devis()
    except Exception as e:
        print("⚠️ Erreur get_next_ref_devis:", e)
        next_ref = ""

    return templates.TemplateResponse(
        "devis_form.html",
        {
            "request": request,
            "today": today_str,
            "liste_commerciaux": COMMERCIAUX,
            "next_ref_devis": next_ref,
            "logo_data_uri": LOGO_DATA_URI,
        },
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
    # Saisie manuelle – listes dynamiques
    manual_pout_type: Optional[List[str]] = Form(None),
    manual_pout_longueur: Optional[List[float]] = Form(None),
    manual_pout_etrier: Optional[List[float]] = Form(None),
    manual_pout_nombre: Optional[List[float]] = Form(None),
    manual_hourdis_type: Optional[List[str]] = Form(None),
    manual_hourdis_nombre: Optional[List[float]] = Form(None),
    surface_ct_manual: float = Form(0.0),
    nb_treillis_manual: float = Form(0.0),
    # Fichier progiciel
    fichier_progiciel: UploadFile | None = File(None),
):
    """
    Récupère le formulaire + (optionnellement) le CSV progiciel ou la saisie manuelle,
    calcule le devis puis renvoie un PDF (si WeasyPrint OK) ou l’HTML sinon.
    """
    global LAST_POUTRELLES, LAST_HOURDIS, LAST_SURFACE_CT, LAST_SURFACE_TS

    poutrelles: List[dict] = []
    hourdis: List[dict] = []
    surface_ct: float = 0.0
    surface_ts: float = 0.0

    # Normaliser les listes manuelles pour éviter None
    manual_pout_type = manual_pout_type or []
    manual_pout_longueur = manual_pout_longueur or []
    manual_pout_etrier = manual_pout_etrier or []
    manual_pout_nombre = manual_pout_nombre or []
    manual_hourdis_type = manual_hourdis_type or []
    manual_hourdis_nombre = manual_hourdis_nombre or []
        # Si la réf devis est vide (ou non envoyée), on génère automatiquement
    if not ref_devis or not ref_devis.strip():
        ref_devis = get_next_ref_devis()
    # === 1) MODE PROGICIEL ====================================================
    if saisie_mode == "progiciel":
        if fichier_progiciel and fichier_progiciel.filename:
            suffix = ".csv"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                shutil.copyfileobj(fichier_progiciel.file, tmp)
                tmp_path = Path(tmp.name)

            parsed = parse_progiciel_csv(tmp_path)
            poutrelles = parsed.get("poutrelles", [])
            hourdis = parsed.get("hourdis", [])
            surface_ct = float(parsed.get("surface_ct", 0.0) or 0.0)
            surface_ts = float(parsed.get("surface_ts", 0.0) or 0.0)

            print(
                f"DEBUG parse_progiciel_csv: {len(poutrelles)} poutrelles, "
                f"{len(hourdis)} hourdis, SURFACE CT={surface_ct}, SURFACE TS={surface_ts}"
            )

            LAST_POUTRELLES = poutrelles
            LAST_HOURDIS = hourdis
            LAST_SURFACE_CT = surface_ct
            LAST_SURFACE_TS = surface_ts

            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
        else:
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

        print(
            f"DEBUG saisie manuelle: {len(poutrelles)} poutrelles, "
            f"{len(hourdis)} hourdis, SURFACE CT={surface_ct}, SURFACE TS={surface_ts}"
        )

        LAST_POUTRELLES = poutrelles
        LAST_HOURDIS = hourdis
        LAST_SURFACE_CT = surface_ct
        LAST_SURFACE_TS = surface_ts

    # === 3) CALCUL DU DEVIS ===================================================
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

    print(
        "DEBUG main.generate_devis -> "
        f"poutrelles={len(poutrelles)}, hourdis={len(hourdis)}, "
        f"SURFACE CT={surface_ct}, SURFACE TS={surface_ts}, "
        f"transport_total_choisi={data_calc.get('transport_total_choisi')}"
    )

    nom_commercial = COMMERCIAUX.get(code_commercial.upper(), "")

        # === 4) SAUVEGARDE EN BASE SQLITE ========================================
    date_devis_finale = date_devis or date.today().strftime("%d/%m/%Y")
    code_commercial_up = (code_commercial or "GA").upper()
    nom_commercial = COMMERCIAUX.get(code_commercial_up, "")

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

    # === 4) CONTEXTE TEMPLATE =================================================
    context: Dict[str, Any] = {
        "request": request,
        "code_client": code_client,
        "client": client,
        "chantier": chantier,
        "niveau": niveau,
        "affaire": affaire,
        "ref_devis": ref_devis,
        "date_devis": date_devis or date.today().strftime("%d/%m/%Y"),
        "mode_livraison": mode_livraison,
        "distance_km": distance_km,
        "validite": validite,
        "code_commercial": code_commercial.upper(),
        "nom_commercial": nom_commercial,
        "mode_transport": mode_transport,
        "transport_mode": transport_mode,
        "transport_prix_poutrelle_manuel": transport_prix_poutrelle_manuel,
        "transport_prix_hourdis_manuel": transport_prix_hourdis_manuel,
        "remise_poutrelle": remise_poutrelle,
        "remise_hourdis": remise_hourdis,
        "prix_ct": prix_ct,
        "prix_treillis": prix_treillis,
        "saisie_mode": saisie_mode,
        "saisie_mode": saisie_mode,
        "logo_data_uri": LOGO_DATA_URI,
        "pdf_available": WEASYPRINT_OK and HTML is not None,
        **data_calc,
    }

        # 4) Rendu HTML du devis
    template = templates.get_template("devis.html")
    html = template.render(context)

    # 5) Si WeasyPrint est dispo, on génère et SAUVEGARDE le PDF sur disque
    if WEASYPRINT_OK and HTML is not None:
        try:
            stylesheets = []
            # On force l'utilisation de ton CSS local pour le PDF
            if CSS is not None:
                stylesheets = [
                    CSS(str(BASE_DIR / "static" / "style.css"))
                ]

            pdf_bytes = HTML(
                string=html,
                base_url=str(BASE_DIR),  # base fichier
            ).write_pdf(stylesheets=stylesheets)

            pdf_path = get_pdf_path(ref_devis)
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)

            print(f"PDF sauvegardé : {pdf_path}")
        except Exception as e:
            print("⚠️ Erreur génération PDF :", e)

    # 6) On renvoie TOUJOURS l’HTML de la page devis (le PDF est récupéré via /pdf/{ref})
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