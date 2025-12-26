from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

TVA_RATE = 0.20

# Prix standards AVANT remise (comme Excel)
POUTRELLE_PRIX_ML = {
    113: 28.89,
    114: 33.33,
    115: 38.89,
    135: 51.11,
    157: 64.44,
}

HOURDIS_PRIX_U = {
    "H8": 4.00,
    "H12": 4.11,
    "H16": 5.47,
    "H20": 6.40,
    "H25": 7.73,
    "H30": 9.07,
}

ETRIER_PRIX_U = 0.89  # HT / unité AVANT remise poutrelles


@dataclass
class Params:
    remise_poutrelle: float  # ex 0.10
    remise_hourdis: float    # ex 0.05
    transport_hourdis_u: float  # F6
    transport_poutrelle_ml: float  # F7
    prix_treillis_u: float  # F8 (HT / unité)
    prix_controle_m2: float # F9 (HT / m²)

def price_poutrelle_ml(type_p: int, params: Params) -> float:
    base = POUTRELLE_PRIX_ML.get(type_p, 0.0)
    if base <= 0:
        return 0.0
    return base * (1 - params.remise_poutrelle) + params.transport_poutrelle_ml

def price_hourdis_u(code: str, params: Params) -> float:
    base = HOURDIS_PRIX_U.get(code.upper(), 0.0)
    if base <= 0:
        return 0.0
    return base * (1 - params.remise_hourdis) + params.transport_hourdis_u

def price_etrier_u(params: Params) -> float:
    return ETRIER_PRIX_U * (1 - params.remise_poutrelle)
