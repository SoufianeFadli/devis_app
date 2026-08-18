from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Tuple

from app.services.engine import PRICE_STD_HOURDIS_U


HOURDIS_TYPES: Tuple[str, ...] = tuple(PRICE_STD_HOURDIS_U.keys())


def normalize_hourdis_type(value: Any) -> str:
    """Normalise et valide un type d'hourdis connu par le moteur de prix."""
    normalized = str(value or "").strip().upper()
    return normalized if normalized in HOURDIS_TYPES else ""


def build_hourdis_overrides(
    keys: Iterable[str], values: Iterable[str]
) -> Dict[Tuple[int, int], str]:
    """Construit la table des corrections reçues depuis le formulaire.

    Une clé est au format ``index_fichier:index_ligne``. Les clés malformées et
    les types sans prix connu sont ignorés afin de ne jamais produire une ligne
    de devis à prix nul à cause d'une valeur envoyée manuellement.
    """
    overrides: Dict[Tuple[int, int], str] = {}
    for raw_key, raw_value in zip(keys, values):
        try:
            file_index_text, row_index_text = str(raw_key).split(":", 1)
            key = (int(file_index_text), int(row_index_text))
        except (TypeError, ValueError):
            continue

        corrected_type = normalize_hourdis_type(raw_value)
        if key[0] < 0 or key[1] < 0 or not corrected_type:
            continue
        overrides[key] = corrected_type
    return overrides


def apply_hourdis_overrides(
    hourdis: List[Dict[str, Any]],
    file_index: int,
    overrides: Mapping[Tuple[int, int], str],
    filename: str = "",
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Applique les corrections sans modifier les données issues du parseur."""
    corrected_rows: List[Dict[str, Any]] = []
    changes: List[Dict[str, Any]] = []

    for row_index, source_row in enumerate(hourdis):
        row = dict(source_row)
        detected_type = str(row.get("type", "")).strip().upper()
        corrected_type = overrides.get((file_index, row_index), detected_type)
        corrected_type = normalize_hourdis_type(corrected_type) or detected_type
        row["type"] = corrected_type
        corrected_rows.append(row)

        if corrected_type != detected_type:
            changes.append(
                {
                    "filename": filename,
                    "row_index": row_index,
                    "detected_type": detected_type,
                    "corrected_type": corrected_type,
                    "nombre": float(row.get("nombre", 0.0) or 0.0),
                }
            )

    return corrected_rows, changes
