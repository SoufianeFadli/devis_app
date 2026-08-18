from __future__ import annotations

import unittest
from pathlib import Path

from app.services.engine import (
    build_poutrelles_ml_by_type,
    compute_devis,
    group_identical_articles,
    sort_articles_for_display,
)
from app.services.parser_progiciel import parse_progiciel_csv
from app.services.hourdis_corrections import (
    apply_hourdis_overrides,
    build_hourdis_overrides,
)


BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLE_CSV = BASE_DIR / "data" / "s sol type 1.CSV"


class CsvProcessingTests(unittest.TestCase):
    def test_parse_real_progiciel_csv(self) -> None:
        parsed = parse_progiciel_csv(SAMPLE_CSV)

        self.assertEqual(len(parsed["poutrelles"]), 4)
        self.assertEqual(len(parsed["hourdis"]), 4)
        self.assertAlmostEqual(parsed["surface_ct"], 94.22)
        self.assertAlmostEqual(parsed["surface_ts"], 110.16)

    def test_two_csv_are_consolidated_in_one_devis(self) -> None:
        poutrelles = []
        hourdis = []
        surface_ct = 0.0
        surface_ts = 0.0

        for _ in range(2):
            parsed = parse_progiciel_csv(SAMPLE_CSV)
            poutrelles.extend(parsed["poutrelles"])
            hourdis.extend(parsed["hourdis"])
            surface_ct += parsed["surface_ct"]
            surface_ts += parsed["surface_ts"]

        result_before_grouping = compute_devis(
            poutrelles=poutrelles,
            hourdis=hourdis,
            surface_ct=surface_ct,
            surface_ts=surface_ts,
            remise_poutrelle=30,
            remise_hourdis=25,
            prix_ct=3,
            prix_treillis=160,
            mode_transport="depart",
            transport_mode="auto",
            distance_km=0,
            transport_poutrelle_manuel=0,
            transport_hourdis_manuel=0,
        )

        poutrelles, hourdis = group_identical_articles(poutrelles, hourdis)

        result = compute_devis(
            poutrelles=poutrelles,
            hourdis=hourdis,
            surface_ct=surface_ct,
            surface_ts=surface_ts,
            remise_poutrelle=30,
            remise_hourdis=25,
            prix_ct=3,
            prix_treillis=160,
            mode_transport="depart",
            transport_mode="auto",
            distance_km=0,
            transport_poutrelle_manuel=0,
            transport_hourdis_manuel=0,
        )

        self.assertEqual(len(poutrelles), 4)
        self.assertEqual(len(hourdis), 3)
        self.assertEqual(
            next(item for item in hourdis if item["type"] == "H16")["nombre"],
            940,
        )
        self.assertAlmostEqual(surface_ct, 188.44)
        self.assertAlmostEqual(surface_ts, 220.32)
        self.assertEqual(result["total_ht"], 20295.27)
        self.assertEqual(result["total_ttc"], 24354.32)
        self.assertEqual(result["total_ht"], result_before_grouping["total_ht"])
        self.assertEqual(result["total_ttc"], result_before_grouping["total_ttc"])

    def test_poutrelles_with_different_dimensions_stay_separate(self) -> None:
        poutrelles = [
            {"type": "135", "longueur": 5.6, "etrier": 10, "nombre": 2},
            {"type": "135", "longueur": 5.6, "etrier": 10, "nombre": 3},
            {"type": "135", "longueur": 4.8, "etrier": 10, "nombre": 4},
            {"type": "135", "longueur": 5.6, "etrier": 8, "nombre": 5},
        ]

        grouped_poutrelles, _ = group_identical_articles(poutrelles, [])

        self.assertEqual(len(grouped_poutrelles), 3)
        self.assertEqual(grouped_poutrelles[0]["nombre"], 5)

    def test_articles_are_sorted_for_display_without_changing_totals(self) -> None:
        parsed = parse_progiciel_csv(SAMPLE_CSV)
        grouped_poutrelles, grouped_hourdis = group_identical_articles(
            parsed["poutrelles"], parsed["hourdis"]
        )

        before_sort = compute_devis(
            grouped_poutrelles,
            grouped_hourdis,
            parsed["surface_ct"],
            parsed["surface_ts"],
            30,
            25,
            3,
            160,
            "depart",
            "auto",
            0,
            0,
            0,
        )
        sorted_poutrelles, sorted_hourdis = sort_articles_for_display(
            grouped_poutrelles, grouped_hourdis
        )
        after_sort = compute_devis(
            sorted_poutrelles,
            sorted_hourdis,
            parsed["surface_ct"],
            parsed["surface_ts"],
            30,
            25,
            3,
            160,
            "depart",
            "auto",
            0,
            0,
            0,
        )

        self.assertEqual(
            [item["longueur"] for item in sorted_poutrelles],
            [5.6, 4.7, 4.05, 3.8],
        )
        self.assertEqual(
            [item["type"] for item in sorted_hourdis],
            ["H12", "H16", "H20"],
        )
        self.assertEqual(before_sort["total_ht"], after_sort["total_ht"])
        self.assertEqual(before_sort["total_ttc"], after_sort["total_ttc"])

    def test_hourdis_can_be_corrected_before_grouping_and_calculation(self) -> None:
        source_rows = [
            {"type": "H30", "nombre": 10},
            {"type": "H30", "nombre": 5},
            {"type": "H16", "nombre": 4},
        ]
        overrides = build_hourdis_overrides(
            ["0:0", "0:1", "0:2"], ["H8", "H12", "H16"]
        )

        corrected, changes = apply_hourdis_overrides(
            source_rows, 0, overrides, "RDC.csv"
        )
        _, grouped = group_identical_articles([], corrected)
        result = compute_devis(
            [], grouped, 0, 0, 0, 0, 0, 0, "depart", "auto", 0, 0, 0
        )

        self.assertEqual([row["type"] for row in corrected], ["H8", "H12", "H16"])
        self.assertEqual([row["type"] for row in source_rows], ["H30", "H30", "H16"])
        self.assertEqual(len(changes), 2)
        self.assertEqual(changes[0]["detected_type"], "H30")
        self.assertEqual(changes[0]["corrected_type"], "H8")
        self.assertEqual(result["total_ht"], 82.43)

    def test_hourdis_correction_is_scoped_by_file_and_rejects_unknown_type(self) -> None:
        overrides = build_hourdis_overrides(
            ["0:0", "1:0", "bad-key"], ["H8", "H99", "H12"]
        )
        file_zero, _ = apply_hourdis_overrides(
            [{"type": "H30", "nombre": 2}], 0, overrides, "RDC.csv"
        )
        file_one, _ = apply_hourdis_overrides(
            [{"type": "H30", "nombre": 2}], 1, overrides, "ETAGE.csv"
        )

        self.assertEqual(file_zero[0]["type"], "H8")
        self.assertEqual(file_one[0]["type"], "H30")

    def test_poutrelles_ml_by_type_include_their_own_etriers(self) -> None:
        poutrelles = [
            {"type": "113", "longueur": 5, "etrier": 10, "nombre": 2},
            {"type": "113", "longueur": 4, "etrier": 8, "nombre": 3},
            {"type": "135", "longueur": 6, "etrier": 5, "nombre": 1},
        ]
        remise = 20
        transport_ml = 1.5

        grouped = build_poutrelles_ml_by_type(
            poutrelles, remise, transport_ml
        )
        regular = compute_devis(
            poutrelles,
            [],
            0,
            0,
            remise,
            0,
            0,
            0,
            "rendu",
            "manuel",
            1,
            transport_ml,
            0,
        )
        regular_poutrelles_total = round(
            sum(
                row["total"]
                for row in regular["lignes"]
                if row["type"] in {"113", "135", "ETRIERS"}
            ),
            2,
        )

        self.assertEqual([row["type"] for row in grouped], ["113", "135"])
        self.assertEqual(grouped[0]["total_ml"], 22.0)
        self.assertEqual(grouped[0]["total_etriers"], 88)
        self.assertEqual(grouped[0]["prix_ml_complet"], 27.46)
        self.assertEqual(grouped[1]["total_ml"], 6.0)
        self.assertEqual(grouped[1]["total_etriers"], 10)
        self.assertEqual(
            round(sum(row["total"] for row in grouped), 2),
            regular_poutrelles_total,
        )


if __name__ == "__main__":
    unittest.main()
