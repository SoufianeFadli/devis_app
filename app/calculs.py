# app/calculator.py

from typing import List, Dict


class ParametresDevis:
    def __init__(
        self,
        remise_poutrelle: float,
        remise_hourdis: float,
        transport_ml_poutrelle: float,
        transport_hourdis: float,
        prix_treillis: float,
        prix_controle_technique: float,
        tva: float = 0.20,
    ):
        self.remise_poutrelle = remise_poutrelle
        self.remise_hourdis = remise_hourdis
        self.transport_ml_poutrelle = transport_ml_poutrelle
        self.transport_hourdis = transport_hourdis
        self.prix_treillis = prix_treillis
        self.prix_controle_technique = prix_controle_technique
        self.tva = tva
PRIX_POUTRELLES_ML = {
    113: 28.89,
    114: 33.33,
    115: 38.89,
    135: 51.11,
    157: 64.44,
}

PRIX_HOURDIS = {
    "H8": 4.00,
    "H12": 4.11,
    "H16": 5.47,
    "H20": 6.40,
    "H25": 7.73,
    "H30": 9.07,
}
def prix_ml_poutrelle(type_poutrelle: int, params: ParametresDevis) -> float:
    base = PRIX_POUTRELLES_ML.get(type_poutrelle, 0)
    return base * (1 - params.remise_poutrelle) + params.transport_ml_poutrelle


def prix_hourdis(code: str, params: ParametresDevis) -> float:
    base = PRIX_HOURDIS.get(code.upper(), 0)
    return base * (1 - params.remise_hourdis) + params.transport_hourdis
def calcul_ligne(
    designation: str,
    longueur: float,
    quantite: float,
    params: ParametresDevis,
) -> Dict:

    prix_ml = 0
    prix_unitaire = 0

    # POUTRELLES
    if designation.isdigit():
        type_p = int(designation)
        prix_ml = prix_ml_poutrelle(type_p, params)
        prix_unitaire = longueur * prix_ml

    # HOURDIS
    elif designation.upper().startswith("H"):
        prix_unitaire = prix_hourdis(designation, params)

    # ETRIER
    elif designation.lower() == "etrier":
        prix_unitaire = 0.89 * (1 - params.remise_poutrelle)

    # CONTROLE TECHNIQUE
    elif designation.upper() == "CONTROLE TECHNIQUE":
        prix_unitaire = params.prix_controle_technique

    # TREILLIS
    elif designation.upper() == "TREILLES SOUDEES":
        prix_unitaire = params.prix_treillis

    total = round(prix_unitaire * quantite, 2)

    return {
        "designation": designation,
        "longueur": longueur,
        "quantite": quantite,
        "prix_ml": round(prix_ml, 4),
        "prix_unitaire": round(prix_unitaire, 4),
        "total": total,
    }
def calcul_devis(lignes: List[Dict], params: ParametresDevis) -> Dict:
    lignes_calculees = []
    total_ht = 0

    for l in lignes:
        ligne = calcul_ligne(
            designation=l["designation"],
            longueur=l.get("longueur", 0),
            quantite=l["quantite"],
            params=params,
        )
        lignes_calculees.append(ligne)
        total_ht += ligne["total"]

    tva = round(total_ht * params.tva, 2)
    total_ttc = round(total_ht + tva, 2)

    return {
        "lignes": lignes_calculees,
        "total_ht": round(total_ht, 2),
        "tva": tva,
        "total_ttc": total_ttc,
    }
