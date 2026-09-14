"""Review exports must declare UTF-8 for spreadsheet auto-detection."""

import codecs
import csv
import io
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "relative",
    [
        "datasets/evals/job-search-v1/label-review.csv",
        "docs/experiments/phase1-case-review.csv",
    ],
)
def test_review_csv_declares_utf8_and_keeps_readable_chinese(relative):
    data = (ROOT / relative).read_bytes()
    assert data.startswith(codecs.BOM_UTF8), "Excel auto-detection needs a UTF-8 signature"
    text = data.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert "case_id" in rows[0]  # No BOM leaking into the first column name.
    assert "岗位职责匹配：" in text
    assert "\ufffd" not in text
