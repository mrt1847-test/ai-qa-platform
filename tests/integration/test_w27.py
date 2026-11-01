"""Synthetic metadata scale and scenario ownership."""

from __future__ import annotations

from pathlib import Path

from tools.validation.benchmark_metadata import (
    MetadataWorkload,
    benchmark_metadata,
    render_metadata_load,
)


def test_w27_04(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    report = benchmark_metadata(
        MetadataWorkload(
            database_path=tmp_path / "metadata.sqlite",
            coverage_path=root / "docs" / "execution" / "COVERAGE.md",
            index_path=root / "docs" / "execution" / "TASK_INDEX.json",
        )
    )
    (root / "docs" / "validation" / "metadata-load.md").write_text(
        render_metadata_load(report),
        encoding="utf-8",
    )
    observed = {
        "items": report.items,
        "actions": report.actions,
        "trend_target_ms": report.trend_target_ms,
        "event_page_target_ms": report.event_page_target_ms,
        "untracked_scenarios": report.untracked_scenarios,
    }
    assert report.trend_p95_ms <= report.trend_target_ms
    assert report.event_page_p95_ms <= report.event_page_target_ms
    assert len(report.scenarios) == 32
    assert observed == {
        "items": 10000,
        "actions": 100000,
        "trend_target_ms": 1000,
        "event_page_target_ms": 500,
        "untracked_scenarios": 0,
    }
