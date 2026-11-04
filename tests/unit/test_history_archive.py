from __future__ import annotations

from pathlib import Path

from workers.app.utils.history_archive import STAT_SPECS


def test_stat_specs_raw_ozon_funnel_import() -> None:
    spec = STAT_SPECS["raw_ozon_funnel_import"]
    assert spec.marketplace == "ozon"
    assert spec.key == ("day", "sku", "scheme")
    assert spec.time_column == "day"
    assert spec.observed_column == "imported_at"
    assert spec.volatile == ("imported_at",)
    assert spec.true_instants is True


def test_raw_ozon_funnel_import_matches_migration_ddl() -> None:
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "warehouse"
        / "migrations"
        / "0050_ozon_funnel_import.sql"
    )
    assert migration_path.exists()
    content = migration_path.read_text(encoding="utf-8")
    assert "imported_at DateTime64" in content
    assert "ingested_at" not in content
    spec = STAT_SPECS["raw_ozon_funnel_import"]
    assert spec.observed_column == "imported_at"
    assert "imported_at" in spec.volatile


def test_stat_specs_observed_column_consistency() -> None:
    for table_name, spec in STAT_SPECS.items():
        assert table_name.startswith("raw_")
        if spec.observed_column is not None:
            assert spec.observed_column in spec.volatile
