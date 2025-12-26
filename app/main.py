from __future__ import annotations
from pathlib import Path
import sqlite3 
from datetime import date
from io import BytesIO
import shutil
import tempfile
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


def get_next_ref_devis() -> str:
    """
    Génère une référence de devis auto-incrémentée.
    Exemple : D00001, D00002, ...
    """
    global REF_COUNTER
    ref = f"D{REF_COUNTER:05d}"
    REF_COUNTER += 1
    return ref
def init_db() -> None:
    """Crée la table devis si elle n'existe pas."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS devis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_devis TEXT,
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
    conn.commit()
    conn.close()




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


@app.get("/")
def read_root():
    # redirige vers le formulaire
    return RedirectResponse(url="/devis/form")

@app.get("/api/status")
def api_status():
    return {"status": "OK - Application Devis SBBM"}

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
            "next_ref_devis": next_ref,  # envoyé au template
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