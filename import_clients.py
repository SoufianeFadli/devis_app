from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

# Dossiers / chemins
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "devis.db"
CSV_PATH = BASE_DIR / "data" / "liste_client_sbbm.csv"


def ensure_table_clients(conn: sqlite3.Connection) -> None:
    """Crée la table clients si elle n'existe pas."""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code_client TEXT UNIQUE,
            nom_client  TEXT
        )
        """
    )
    conn.commit()


def import_clients() -> None:
    print(f"Base SQLite : {DB_PATH}")
    print(f"Fichier CSV : {CSV_PATH}")

    if not CSV_PATH.exists():
        print("❌ CSV introuvable, vérifie le chemin.")
        return

    conn = sqlite3.connect(DB_PATH)
    ensure_table_clients(conn)
    cur = conn.cursor()

    # très important : utf-8-sig pour supprimer le BOM (\ufeff)
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        headers = reader.fieldnames or []
        print("En-têtes détectées :", headers)

        total_lues = 0
        inserees = 0
        ignorees = 0

        for row in reader:
            # Récupérer proprement les colonnes
            code = (row.get("CODE_CLIENT") or "").strip()
            nom = (row.get("NOM_CLIENT") or "").strip()

            if not code or not nom:
                ignorees += 1
                continue

            total_lues += 1
            try:
                cur.execute(
                    """
                    INSERT OR IGNORE INTO clients (code_client, nom_client)
                    VALUES (?, ?)
                    """,
                    (code, nom),
                )
                # si la ligne a vraiment été insérée (et pas ignorée pour doublon)
                if cur.rowcount:
                    inserees += 1
                else:
                    ignorees += 1
            except Exception as e:
                print("⚠️ Ligne ignorée pour erreur :", e, "→", row)
                ignorees += 1

    conn.commit()
    conn.close()

    print(
        f"Import terminé. {total_lues} lignes lues, {inserees} insérées, "
        f"{ignorees} ignorées (doublons ou invalides)."
    )


if __name__ == "__main__":
    import_clients()