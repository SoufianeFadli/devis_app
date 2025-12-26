# app/services/parser_progiciel.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
from typing import Any


def _to_float(x: Any) -> float:
    """Convertit une chaîne (avec virgule possible) en float, sinon 0.0."""
    if x is None:
        return 0.0
    s = str(x).strip()
    if not s:
        return 0.0
    # nettoyer espaces & nbsp et gérer la virgule française
    s = s.replace("\u00a0", " ").replace(" ", "")
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _to_str(x: Any) -> str:
    return str(x).strip() if x is not None else ""


@dataclass
class LigneDevis:
    type: str
    longueur: float | None
    etrier: float | None
    nombre: float
    prix_ml: float
    prix: float
    total: float


def parse_progiciel_csv(file_path: str | Path) -> dict:
    """
    Parse le CSV brut du progiciel (structure réelle comme dans ton exemple).

    On extrait :
      - poutrelles : depuis le tableau REPERE;SOUS TYPE;LONGUEUR/PAS ETRIERS;...;NOMBRE;LONGUEUR;...
      - hourdis   : depuis le tableau FAMILLE;DESIGNATION;...;NOMBRE;...
      - surface_ct  : valeur après 'SURFACE'
      - surface_ts  : valeur après 'SURFACE TS'
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"Fichier introuvable: {p}")

    with p.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.reader(f, delimiter=";")
        rows = list(reader)

    poutrelles: list[dict[str, Any]] = []
    hourdis: list[dict[str, Any]] = []
    surface_ct: float = 0.0
    surface_ts: float = 0.0

    in_poutrelles = False
    in_hourdis = False

    for raw in rows:
        # on nettoie les cellules
        row = [_to_str(c) for c in raw]
        if not any(row):
            # ligne complètement vide : on sort des tableaux
            in_poutrelles = False
            in_hourdis = False
            continue

        joined_upper = ";".join(row).upper()

        # === SURFACE (CT) ===
        if "SURFACE TS" in joined_upper:
            # SURFACE TS
            try:
                idx = next(
                    i for i, c in enumerate(row) if "SURFACE TS" in c.upper()
                )
                # chercher la première cellule non vide après
                for j in range(idx + 1, len(row)):
                    if row[j]:
                        surface_ts = _to_float(row[j])
                        break
            except StopIteration:
                pass

        elif "SURFACE" in joined_upper and "SURFACE TS" not in joined_upper:
            # SURFACE (CT)
            try:
                idx = next(i for i, c in enumerate(row) if c.upper() == "SURFACE")
                for j in range(idx + 1, len(row)):
                    if row[j]:
                        surface_ct = _to_float(row[j])
                        break
            except StopIteration:
                pass

        # === Début tableau POUTRELLES ===
        if (
            len(row) >= 6
            and row[0].upper() == "REPERE"
            and row[1].upper().startswith("SOUS")
            and row[4].upper() == "NOMBRE"
        ):
            in_poutrelles = True
            in_hourdis = False
            continue

        # === Lignes de POUTRELLES ===
        if in_poutrelles:
            # ex: D;157;12;0;9;6,9;...
            repere = row[0]
            t = row[1]
            if not t:
                continue
            if t.isdigit():  # 113 / 114 / 115 / 135 / 157
                type_p = t
                etrier = _to_float(row[2])   # LONGUEUR/PAS ETRIERS
                nb = _to_float(row[4])       # NOMBRE
                longueur = _to_float(row[5]) # LONGUEUR
                if longueur > 0 and nb > 0:
                    poutrelles.append(
                        {
                            "type": type_p,
                            "longueur": longueur,
                            "etrier": etrier,
                            "nombre": nb,
                        }
                    )
            continue

        # === Début tableau HOURDIS ===
        if (
            len(row) >= 7
            and row[0].upper() == "FAMILLE"
            and row[1].upper() == "DESIGNATION"
            and row[6].upper() == "NOMBRE"
        ):
            in_hourdis = True
            in_poutrelles = False
            continue

        # === Lignes de HOURDIS ===
        if in_hourdis:
            # ex: BETON;H16;...;NOMBRE=113;...
            if not row[0]:
                continue
            type_h = row[1].upper()
            qte = _to_float(row[6])  # NOMBRE
            if type_h.startswith("H") and qte > 0:
                hourdis.append(
                    {
                        "type": type_h,
                        "nombre": qte,
                    }
                )
            continue

    print(
        f"DEBUG parse_progiciel_csv: trouvé {len(poutrelles)} poutrelles "
        f"et {len(hourdis)} lignes hourdis, SURFACE CT={surface_ct}, SURFACE TS={surface_ts}"
    )

    return {
        "poutrelles": poutrelles,
        "hourdis": hourdis,
        "surface_ct": surface_ct,
        "surface_ts": surface_ts,
    }
