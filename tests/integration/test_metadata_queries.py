"""Metadata query plans on a small synthetic database."""

from __future__ import annotations

from pathlib import Path

from tools.validation.benchmark_metadata import MetadataWorkload, benchmark_metadata


def test_metadata_query_plan_uses_the_synthetic_indexes(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    report = benchmark_metadata(
        MetadataWorkload(
            database_path=tmp_path / "small.sqlite",
            coverage_path=root / "docs" / "execution" / "COVERAGE.md",
            index_path=root / "docs" / "execution" / "TASK_INDEX.json",
            items=30,
            actions=60,
        )
    )
    assert "items_requested" in report.trend_plan
    assert "events_seq" in report.event_plan
    assert report.file_io_included is False
    assert report.device_latency_included is False
    assert {row.scenario_id for row in report.scenarios} >= {"DATA-22", "EXEC-10"}
