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


def group_identical_articles(
    poutrelles: List[Dict[str, Any]],
    hourdis: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Regroupe les articles identiques sans modifier les listes reçues.

    Deux poutrelles sont identiques si leur type, leur longueur et leur nombre
    d'étriers sont identiques. Les hourdis sont regroupés par type. L'ordre de
    la première apparition de chaque article est conservé.
    """
    poutrelles_groupees: Dict[Tuple[str, float, float], Dict[str, Any]] = {}
    for poutrelle in poutrelles:
        type_p = str(poutrelle.get("type", "")).strip().upper()
        longueur = _flt(poutrelle.get("longueur"))
        etrier = _flt(poutrelle.get("etrier"))
        nombre = _flt(poutrelle.get("nombre"))

        if not type_p or longueur <= 0 or nombre <= 0:
            continue

        # Le CSV utilise des valeurs décimales courtes. L'arrondi évite qu'une
        # différence binaire invisible empêche le regroupement de deux articles.
        key = (type_p, round(longueur, 4), round(etrier, 4))
        if key not in poutrelles_groupees:
            poutrelles_groupees[key] = {
                "type": type_p,
                "longueur": longueur,
                "etrier": etrier,
                "nombre": 0.0,
            }
        poutrelles_groupees[key]["nombre"] += nombre

    hourdis_groupes: Dict[str, Dict[str, Any]] = {}
    for ligne_hourdis in hourdis:
        type_h = str(ligne_hourdis.get("type", "")).strip().upper()
        nombre = _flt(ligne_hourdis.get("nombre"))

        if not type_h or nombre <= 0:
            continue

        if type_h not in hourdis_groupes:
            hourdis_groupes[type_h] = {"type": type_h, "nombre": 0.0}
        hourdis_groupes[type_h]["nombre"] += nombre

    return list(poutrelles_groupees.values()), list(hourdis_groupes.values())


def sort_articles_for_display(
    poutrelles: List[Dict[str, Any]],
    hourdis: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Retourne les articles dans l'ordre souhaité sur le devis.

    Les poutrelles sont classées de la plus longue à la plus courte. Les
    hourdis sont classés selon la valeur numérique de leur désignation : H8,
    H12, H16, H20, H25, H30. Les articles inconnus sont placés à la fin.
    """

    def poutrelle_key(article: Dict[str, Any]) -> Tuple[float, str, float]:
        return (
            -_flt(article.get("longueur")),
            str(article.get("type", "")).strip().upper(),
            _flt(article.get("etrier")),
        )

    def hourdis_key(article: Dict[str, Any]) -> Tuple[float, str]:
        type_h = str(article.get("type", "")).strip().upper()
        try:
            hauteur = float(type_h[1:]) if type_h.startswith("H") else float("inf")
        except ValueError:
            hauteur = float("inf")
        return hauteur, type_h

    return sorted(poutrelles, key=poutrelle_key), sorted(hourdis, key=hourdis_key)


def build_poutrelles_ml_by_type(
    poutrelles: List[Dict[str, Any]],
    remise_poutrelle: float,
    transport_par_ml: float = 0.0,
) -> List[Dict[str, Any]]:
    """Regroupe les poutrelles par type avec un prix ML incluant les étriers.

    Cette présentation reprend exactement les règles de ``compute_devis`` :
    prix de la poutrelle remisé, transport au ML et étriers remisés. Elle ne
    modifie pas le calcul général du devis et sert uniquement à sa présentation.
    """
    grouped: Dict[str, Dict[str, float]] = {}
    discount_factor = 1.0 - _flt(remise_poutrelle) / 100.0
    transport_ml = max(0.0, _flt(transport_par_ml))

    for poutrelle in poutrelles:
        type_p = str(poutrelle.get("type", "")).strip().upper()
        longueur = _flt(poutrelle.get("longueur"))
        nombre = _flt(poutrelle.get("nombre"))
        etriers_par_cote = _flt(poutrelle.get("etrier"))
        if type_p not in PRICE_STD_POUTRELLE_ML or longueur <= 0 or nombre <= 0:
            continue

        item = grouped.setdefault(
            type_p,
            {"total_ml": 0.0, "total_etriers": 0.0, "total_ht": 0.0},
        )
        total_ml = longueur * nombre
        total_etriers = nombre * etriers_par_cote * 2.0
        prix_poutrelle_ml = (
            PRICE_STD_POUTRELLE_ML[type_p] * discount_factor + transport_ml
        )
        prix_etrier = ETRIER_STD_PRICE * discount_factor

        item["total_ml"] += total_ml
        item["total_etriers"] += total_etriers
        item["total_ht"] += total_ml * prix_poutrelle_ml + total_etriers * prix_etrier

    order = {type_p: index for index, type_p in enumerate(PRICE_STD_POUTRELLE_ML)}
    result: List[Dict[str, Any]] = []
    for type_p, item in sorted(grouped.items(), key=lambda entry: order[entry[0]]):
        total_ml = item["total_ml"]
        total_ht = item["total_ht"]
        result.append(
            {
                "type": type_p,
                "total_ml": round(total_ml, 2),
                "total_etriers": int(round(item["total_etriers"])),
                "prix_ml_complet": round(total_ht / total_ml, 4),
                "total": round(total_ht, 2),
            }
        )
    return result


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
                "prix_ml": round(prix_ml, 2),
                "prix": round(prix, 2),
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
                "longueur": "",
                "etrier": "",
                "nombre": int(qte_e),
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
                "longueur": "",  
                "etrier": "",
                "nombre": int(qte),
                "prix_ml": round(prix_u, 2),
                "prix": round(prix_u, 2),
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
                "longueur": "",
                "etrier": "",
                "nombre": round(surface_ct, 2),
                "prix_ml": round(prix_ct, 2),
                "prix": round(prix_ct, 2),
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
                "longueur": "",
                "etrier": "",
                "nombre": int(nb_ts),
                "prix_ml": round(prix_treillis, 2),
                "prix": round(prix_treillis, 2),
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
        # Valeurs non arrondies réutilisées pour ventiler exactement le même
        # transport dans la présentation détaillée par niveau.
        "transport_par_ml_brut": info_tr["transport_par_ml_effectif"],
        "transport_par_hourdis_brut": info_tr["transport_par_hourdis_effectif"],
        "nb_camions": info_tr["nb_camions"],
        "poids_total": round(info_tr["poids_total"], 2),
        "poids_poutrelles": round(info_tr["poids_poutrelles"], 2),
        "poids_hourdis": round(info_tr["poids_hourdis"], 2),
    }
