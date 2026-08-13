"""
Tests for archive_ha_data.py — durable accumulation of HA exports.

The archive is the only copy of history that survives Home Assistant's own
purging, so the properties that matter are: merging never loses rows, repeated
runs never duplicate them, and a failed write never truncates what was there.
"""

import csv
from pathlib import Path

import pytest

import archive_ha_data as aha


def write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=aha.FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return path


def row(entity="sensor.a", state="1.0", time="2026-07-01T00:00:00+00:00"):
    return {"entity_id": entity, "state": state, "last_changed": time}


def read_rows(path: Path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# read_csv
# ---------------------------------------------------------------------------

def test_read_csv_missing_file_is_empty(tmp_path):
    """A first run has no archive yet — that is not an error."""
    assert aha.read_csv(tmp_path / "nope.csv") == {}


def test_read_csv_keys_on_entity_and_time(tmp_path):
    path = write_csv(tmp_path / "a.csv", [
        row("sensor.a", "1.0", "2026-07-01T00:00:00+00:00"),
        row("sensor.b", "2.0", "2026-07-01T00:00:00+00:00"),
    ])

    assert set(aha.read_csv(path)) == {
        ("sensor.a", "2026-07-01T00:00:00+00:00"),
        ("sensor.b", "2026-07-01T00:00:00+00:00"),
    }


def test_read_csv_rejects_wrong_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("entity_id,value\nsensor.a,1.0\n")

    with pytest.raises(ValueError, match="missing column"):
        aha.read_csv(path)


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------

def test_merge_adds_new_rows():
    archive = {("sensor.a", "t1"): row(time="t1")}
    incoming = {("sensor.a", "t2"): row(time="t2")}

    merged, added, updated = aha.merge(archive, incoming)
    assert (added, updated) == (1, 0)
    assert len(merged) == 2


def test_merge_is_idempotent():
    """Re-running over the same export must not duplicate or churn."""
    archive = {("sensor.a", "t1"): row(time="t1")}

    merged, added, updated = aha.merge(archive, dict(archive))
    assert (added, updated) == (0, 0)
    assert merged == archive


def test_merge_prefers_incoming_value():
    """A later fetch of the same hour is based on more complete data."""
    archive = {("sensor.a", "t1"): row(state="1.0", time="t1")}
    incoming = {("sensor.a", "t1"): row(state="2.0", time="t1")}

    merged, added, updated = aha.merge(archive, incoming)
    assert (added, updated) == (0, 1)
    assert merged[("sensor.a", "t1")]["state"] == "2.0"


def test_merge_does_not_mutate_archive():
    archive = {("sensor.a", "t1"): row(time="t1")}
    aha.merge(archive, {("sensor.a", "t2"): row(time="t2")})
    assert len(archive) == 1


def test_merge_never_drops_existing_rows():
    """Rows absent from the new export stay in the archive — HA may have purged them."""
    archive = {("sensor.a", f"t{i}"): row(time=f"t{i}") for i in range(5)}

    merged, _, _ = aha.merge(archive, {("sensor.a", "t9"): row(time="t9")})
    assert set(archive).issubset(merged)


# ---------------------------------------------------------------------------
# write_csv
# ---------------------------------------------------------------------------

def test_write_csv_sorts_by_time_then_entity(tmp_path):
    rows = {
        ("sensor.b", "2026-07-01T00:00:00+00:00"): row("sensor.b", "2", "2026-07-01T00:00:00+00:00"),
        ("sensor.a", "2026-07-01T01:00:00+00:00"): row("sensor.a", "3", "2026-07-01T01:00:00+00:00"),
        ("sensor.a", "2026-07-01T00:00:00+00:00"): row("sensor.a", "1", "2026-07-01T00:00:00+00:00"),
    }
    out = tmp_path / "arch.csv"
    aha.write_csv(out, rows)

    assert [(r["entity_id"], r["state"]) for r in read_rows(out)] == [
        ("sensor.a", "1"), ("sensor.b", "2"), ("sensor.a", "3")
    ]


def test_write_csv_creates_parent_directory(tmp_path):
    out = tmp_path / "deep" / "nested" / "arch.csv"
    aha.write_csv(out, {("sensor.a", "t1"): row(time="t1")})
    assert out.exists()


def test_write_csv_leaves_no_temp_file(tmp_path):
    """The write is atomic via a temp file that must be renamed away."""
    out = tmp_path / "arch.csv"
    aha.write_csv(out, {("sensor.a", "t1"): row(time="t1")})
    assert list(tmp_path.iterdir()) == [out]


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------

def test_repeated_merges_converge(tmp_path):
    """Two overlapping exports merge to the union, and re-running changes nothing."""
    first = write_csv(tmp_path / "a.csv", [
        row("sensor.a", "1.0", "2026-07-01T00:00:00+00:00"),
        row("sensor.a", "2.0", "2026-07-01T01:00:00+00:00"),
    ])
    second = write_csv(tmp_path / "b.csv", [
        row("sensor.a", "2.0", "2026-07-01T01:00:00+00:00"),
        row("sensor.a", "3.0", "2026-07-01T02:00:00+00:00"),
    ])
    archive = tmp_path / "arch.csv"

    state = {}
    for src in (first, second, first, second):
        state, _, _ = aha.merge(state, aha.read_csv(src))
    aha.write_csv(archive, state)

    rows = read_rows(archive)
    assert len(rows) == 3
    assert [r["state"] for r in rows] == ["1.0", "2.0", "3.0"]


def test_archive_is_loadable_by_rainlib(tmp_path):
    """The archive feeds the analysis directly, so load_ha_csv must read it."""
    import rainlib as rl

    src = write_csv(tmp_path / "a.csv", [
        row("sensor.datchik_klimata_temperatura", "20.5", "2026-07-01T00:00:00+00:00"),
        row("sensor.datchik_klimata_temperatura", "21.0", "2026-07-01T01:00:00+00:00"),
    ])
    archive = tmp_path / "arch.csv"
    aha.write_csv(archive, aha.read_csv(src))

    loaded = rl.load_ha_csv(str(archive))
    assert len(loaded) == 2
    assert loaded["value"].tolist() == [20.5, 21.0]
