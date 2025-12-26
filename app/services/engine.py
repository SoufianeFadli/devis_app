# app/services/engine.py
from __future__ import annotations

from math import ceil
from typing import Any, Dict, List, Tuple

# ================== PRIX STANDARDS =====================================

PRICE_STD_POUTRELLE_ML: Dict[str, float] = {
    "113": 28.89,
    "114": 33.33,
    "115": 38.89,
    "135": 51.11,
    "157": 64.44,
}

PRICE_STD_HOURDIS_U: Dict[str, float] = {
    "H8": 4.00,
    "H12": 4.11,
    "H16": 5.47,
    "H20": 6.40,
    "H25": 7.73,
    "H30": 9.07,
}

ETRIER_STD_PRICE = 0.89  # DH / étrier (avant remise)

# ================== POIDS POUR TRANSPORT ===============================

WEIGHT_POUTRELLE_ML_KG: Dict[str, float] = {
    "113": 18.0,
    "114": 18.0,
    "115": 19.0,
    "135": 22.0,
    "157": 32.0,
}

WEIGHT_HOURDIS_U_KG: Dict[str, float] = {
    "H8": 10.0,
    "H12": 12.0,
    "H16": 14.0,
    "H20": 15.0,
    "H25": 20.0,
    "H30": 25.0,
}


def _flt(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _compute_poids(
    poutrelles: List[Dict[str, Any]], hourdis: List[Dict[str, Any]]
) -> Tuple[float, float, float, float, float]:
    """
    Retourne :
      total_ml_poutrelles, poids_poutrelles, total_u_hourdis, poids_hourdis, poids_total
    """
    total_ml_p = 0.0
    poids_p = 0.0

    for p in poutrelles:
        t = str(p.get("type", "")).strip()
        longueur = _flt(p.get("longueur"))
        nb = _flt(p.get("nombre"))
        if not t or longueur <= 0 or nb <= 0:
            continue
        ml = longueur * nb
        total_ml_p += ml
        poids_ml = WEIGHT_POUTRELLE_ML_KG.get(t, 0.0)
        poids_p += ml * poids_ml

    total_u_h = 0.0
    poids_h = 0.0
    for h in hourdis:
        t = str(h.get("type", "")).upper()
        qte = _flt(h.get("nombre"))
        if not t or qte <= 0:
            continue
        total_u_h += qte
        poids_u = WEIGHT_HOURDIS_U_KG.get(t, 0.0)
        poids_h += qte * poids_u

    poids_total = poids_p + poids_h
    return total_ml_p, poids_p, total_u_h, poids_h, poids_total


def simulate_transport(
    poutrelles: List[Dict[str, Any]],
    hourdis: List[Dict[str, Any]],
    distance_km: float,
    mode_transport: str,
    transport_mode: str,
    transport_poutrelle_manuel: float = 0.0,
    transport_hourdis_manuel: float = 0.0,
) -> Dict[str, float]:
    """
    Calcule le coût de transport :
     - transport_par_ml_auto / transport_par_hourdis_auto
     - transport_par_ml_effectif / transport_par_hourdis_effectif (auto ou manuel)
     - total transport, nb camions, poids, etc.
    """
    distance_km = _flt(distance_km)

    total_ml_p, poids_p, total_u_h, poids_h, poids_total = _compute_poids(
        poutrelles, hourdis
    )

    result = {
        "poids_total": poids_total,
        "poids_poutrelles": poids_p,
        "poids_hourdis": poids_h,
        "total_ml_poutrelles": total_ml_p,
        "total_u_hourdis": total_u_h,
        "nb_camions": 0.0,
        "prix_camion_auto": 0.0,
        "transport_total_auto": 0.0,
        "transport_par_ml_auto": 0.0,
        "transport_par_hourdis_auto": 0.0,
        "transport_par_ml_effectif": 0.0,
        "transport_par_hourdis_effectif": 0.0,
        "transport_total_effectif": 0.0,
    }

    # Mode départ → pas de transport
    if mode_transport != "rendu":
        return result

    # Pas de marchandises ou distance nulle
    if poids_total <= 0 or distance_km <= 0:
        return result

    # Nombre de camions
    nb_camions = ceil(poids_total / 17000.0)
    result["nb_camions"] = nb_camions

    # Prix d'un seul camion (dernière formule que tu as donnée)
    prix_camion = ((distance_km * 2.0 * 0.4 * 11.0)+200) * 1.05
    result["prix_camion_auto"] = prix_camion

    transport_total_auto = nb_camions * prix_camion
    result["transport_total_auto"] = transport_total_auto

    # Clé de répartition (que tu as validée)
    transport_par_ml_auto = 0.0
    if total_ml_p > 0 and poids_p > 0:
        transport_par_ml_auto = (
            poids_p * transport_total_auto / (poids_total * total_ml_p)
        )

    transport_par_hourdis_auto = 0.0
    if total_u_h > 0 and poids_h > 0:
        transport_par_hourdis_auto = (
            poids_h * transport_total_auto / (poids_total * total_u_h)
        )

    result["transport_par_ml_auto"] = transport_par_ml_auto
    result["transport_par_hourdis_auto"] = transport_par_hourdis_auto

    # Valeurs effectives (celles qu'on applique dans le devis)
    if transport_mode == "auto":
        tr_ml = transport_par_ml_auto
        tr_h = transport_par_hourdis_auto
    else:  # manuel avec 2 champs séparés
        tr_ml = max(0.0, _flt(transport_poutrelle_manuel))
        tr_h = max(0.0, _flt(transport_hourdis_manuel))

    result["transport_par_ml_effectif"] = tr_ml
    result["transport_par_hourdis_effectif"] = tr_h

    transport_total_effectif = tr_ml * total_ml_p + tr_h * total_u_h
    result["transport_total_effectif"] = transport_total_effectif

    return result


def compute_devis(
    poutrelles: List[Dict[str, Any]],
    hourdis: List[Dict[str, Any]],
    surface_ct: float,
    surface_ts: float,
    remise_poutrelle: float,
    remise_hourdis: float,
    prix_ct: float,
    prix_treillis: float,
    mode_transport: str,
    transport_mode: str,
    distance_km: float,
    transport_poutrelle_manuel: float,
    transport_hourdis_manuel: float,
) -> Dict[str, Any]:
    """
    Calcule les lignes du devis + TOTAL HT / TVA / TTC
    avec :
      - prix standards + remises
      - transport intégré au prix unitaire poutrelles & hourdis
      - contrôle technique (surface_ct) et treillis soudés (surface_ts)
    """
    lignes: List[Dict[str, Any]] = []
    total_ht = 0.0

    # ================== TRANSPORT =======================================
    info_tr = simulate_transport(
        poutrelles,
        hourdis,
        distance_km,
        mode_transport,
        transport_mode,
        transport_poutrelle_manuel,
        transport_hourdis_manuel,
    )

    tr_ml = info_tr["transport_par_ml_effectif"]
    tr_h = info_tr["transport_par_hourdis_effectif"]

    # ================== POUTRELLES ======================================
    total_etriers_global = 0.0

    for p in poutrelles:
        t = str(p.get("type", "")).strip()
        longueur = _flt(p.get("longueur"))
        nb = _flt(p.get("nombre"))
        etrier = _flt(p.get("etrier"))

        if not t or longueur <= 0 or nb <= 0:
            continue

        # Prix standard + remise
        base_ml = PRICE_STD_POUTRELLE_ML.get(t, 0.0)
        base_ml_remise = base_ml * (1.0 - remise_poutrelle / 100.0)

        # Transport intégré
        prix_ml = base_ml_remise + tr_ml
        prix = prix_ml * longueur
        total = prix * nb

        lignes.append(
            {
                "type": t,
                "longueur": round(longueur, 2),
                "etrier": int(etrier) if etrier else "",
                "nombre": int(nb),
                "prix_ml": round(prix_ml, 4),
                "prix": round(prix, 4),
                "total": round(total, 2),
            }
        )

        total_ht += total
        # nb poutrelles * (nb après F) * 2 = nb étriers
        total_etriers_global += nb * etrier * 2.0

    # ================== ETRIERS =========================================
    if total_etriers_global > 0:
        qte_e = total_etriers_global
        prix_etrier = ETRIER_STD_PRICE * (1.0 - remise_poutrelle / 100.0)
        total_e = qte_e * prix_etrier

        lignes.append(
            {
                "type": "ETRIERS",
                "longueur": int(qte_e),
                "etrier": 0,
                "nombre": 0,
                "prix_ml": round(prix_etrier, 4),
                "prix": round(prix_etrier, 4),
                "total": round(total_e, 2),
            }
        )
        total_ht += total_e

    # ================== HOURDIS =========================================
    for h in hourdis:
        t = str(h.get("type", "")).upper()
        qte = _flt(h.get("nombre"))

        if not t or qte <= 0:
            continue

        base_u = PRICE_STD_HOURDIS_U.get(t, 0.0)
        base_u_remise = base_u * (1.0 - remise_hourdis / 100.0)

        prix_u = base_u_remise + tr_h
        total = prix_u * qte

        lignes.append(
            {
                "type": t,
                "longueur": int(qte),  # On affiche la qté dans la colonne "Longueur"
                "etrier": "",
                "nombre": 0,
                "prix_ml": round(prix_u, 4),
                "prix": round(prix_u, 4),
                "total": round(total, 2),
            }
        )
        total_ht += total

    # ================== CONTROLE TECHNIQUE ==============================
    surface_ct = _flt(surface_ct)
    if surface_ct > 0 and prix_ct > 0:
        total_ct = surface_ct * prix_ct
        lignes.append(
            {
                "type": "CONTROLE TECHNIQUE",
                "longueur": round(surface_ct, 2),
                "etrier": 0,
                "nombre": 0,
                "prix_ml": round(prix_ct, 4),
                "prix": round(prix_ct, 4),
                "total": round(total_ct, 2),
            }
        )
        total_ht += total_ct

    # ================== TREILLES SOUDEES ================================
    surface_ts = _flt(surface_ts)
    if surface_ts > 0 and prix_treillis > 0:
        nb_ts = ceil(surface_ts / 10.0)
        total_tr = nb_ts * prix_treillis
        lignes.append(
            {
                "type": "TREILLES SOUDEES",
                "longueur": int(nb_ts),
                "etrier": 0,
                "nombre": 0,
                "prix_ml": round(prix_treillis, 4),
                "prix": round(prix_treillis, 4),
                "total": round(total_tr, 2),
            }
        )
        total_ht += total_tr

    # ================== TOTAUX ==========================================
    tva = round(total_ht * 0.20, 2)
    total_ttc = round(total_ht + tva, 2)

    return {
        "lignes": lignes,
        "total_ht": round(total_ht, 2),
        "tva": tva,
        "total_ttc": total_ttc,
        # Infos transport pour affichage / debug
        "transport_total_auto": round(info_tr["transport_total_auto"], 2),
        "transport_total_choisi": round(info_tr["transport_total_effectif"], 2),
        "transport_par_ml": round(info_tr["transport_par_ml_effectif"], 4),
        "transport_par_hourdis": round(info_tr["transport_par_hourdis_effectif"], 4),
        "nb_camions": info_tr["nb_camions"],
        "poids_total": round(info_tr["poids_total"], 2),
        "poids_poutrelles": round(info_tr["poids_poutrelles"], 2),
        "poids_hourdis": round(info_tr["poids_hourdis"], 2),
    }
