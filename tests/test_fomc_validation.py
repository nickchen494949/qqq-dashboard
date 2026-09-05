from pathlib import Path
import csv
import json

import pytest

from tools.fomc_validation import (
    enumerate_sep_sources,
    match_member,
    Member,
    parse_key_text,
    parse_projection_text,
    partition_for,
    person_slug,
    extract_artifact_text,
    parse_fred_xml,
    months_before,
    text_terms,
    build_vocabulary,
    ridge_predict,
    direction_label,
    balanced_accuracy,
    passage_for_review,
)

import numpy as np


def test_parse_early_key_with_affiliations_and_titles():
    text = """
    Participant Participant Participant
    Number Name Affiliation
    1 Eric Rosengren Boston FRB
    4 Chairman Bernanke Board of Governors
    9 Janet Yellen Board of Governors
    10 Narayana Kocherlakota Minneapolis FRB
    11 James Bullard St. Louis FRB
    12 William Dudley New York FRB
    13 Charles L Evans Chicago FRB
    14 Richard Fisher Dallas FRB
    15 Esther George Kansas City FRB
    16 Daniel Tarullo Board of Governors
    """
    parsed = parse_key_text(text)
    assert parsed[1] == "Eric Rosengren"
    assert parsed[4] == "Bernanke"
    assert parsed[15] == "Esther George"


def test_parse_projection_rows_and_normalize_eighth_points():
    text = """
    Table 2: January Economic Projections
    Projection Year Change GDP Unemployment PCE Core Federal Funds Rate
    1 2012 2.4 8.5 1.5 1.5 0.13
    2 2012 2.5 8.2 1.5 1.5 0.38
    1 2013 3.0 8.1 1.4 1.4 0.63
    1 LR 2.5 5.2 2.0 4.00
    """
    rows = parse_projection_text(text)
    assert len(rows) == 3
    assert rows[0]["federal_funds_rate_bp"] == 12.5
    assert rows[1]["federal_funds_rate_bp"] == 62.5
    assert rows[2]["federal_funds_rate_bp"] == 37.5


def test_projection_parser_excludes_appendix_and_repairs_spaced_decimals():
    text = """Table 2: Individual Projections
1 2019 2. 6 3. 7 1. 8 1. 9 2. 38
\fTable 2. Appendix
1 2019 9.0 9.0 9.0 9.0 9.0
"""
    rows = parse_projection_text(text)
    assert len(rows) == 1
    assert rows[0]["gdp"] == 2.6
    assert rows[0]["federal_funds_rate_bp"] == 237.5


def test_projection_parser_accepts_2020_heading():
    rows = parse_projection_text("Individual Projections Table\n3 2021 4.0 5.0 1.8 1.7 0.13")
    assert rows[0]["participant_number"] == 3
    assert rows[0]["federal_funds_rate_bp"] == 12.5


def test_member_matching_is_explicit_and_unique():
    members = [
        Member("ben-s-bernanke", "Ben S. Bernanke", ("ben", "s", "bernanke")),
        Member("janet-l-yellen", "Janet L. Yellen", ("janet", "l", "yellen")),
    ]
    assert match_member("Chairman Bernanke", members)[0].member_id == "ben-s-bernanke"
    assert match_member("Janet Yellen", members)[0].member_id == "janet-l-yellen"
    with pytest.raises(ValueError):
        match_member("Unknown Person", members)
    assert person_slug("Blake Prichard") == "blake-prichard"


def test_partitions_are_chronological():
    assert partition_for("2016-12-14") == "DEVELOPMENT"
    assert partition_for("2017-03-15") == "VALIDATION"
    assert partition_for("2019-03-20") == "FINAL_HOLDOUT"


def test_official_index_enumeration_finds_frozen_36_pairs():
    tracker = Path("data/fomc_tracker")
    rows = enumerate_sep_sources(tracker)
    assert len(rows) == 36
    assert rows[0]["sep_date"] == "2012-01-25"
    assert rows[-1]["sep_date"] == "2020-12-16"
    assert rows[-1]["analytical_cutoff_date"] == "2020-12-05"


def test_html_text_extraction_rejects_metadata_only_and_uses_article(tmp_path):
    metadata = tmp_path / "metadata.raw"
    metadata.write_text("<html><main><p>short catalog record only</p></main></html>")
    text, method = extract_artifact_text(metadata)
    assert text == "short catalog record only"
    assert method == "HTML_METADATA_ONLY"

    article = tmp_path / "article.raw"
    body = " ".join(["policy inflation employment rates"] * 60)
    article.write_text(f"<html><nav>noise</nav><div class='dal-main-content'><p>{body}</p></div></html>")
    text, method = extract_artifact_text(article)
    assert "noise" not in text
    assert len(text.split()) == 240
    assert method == "HTML_MAIN"


def test_html_fallback_starts_after_last_title(tmp_path):
    path = tmp_path / "fallback.raw"
    navigation = " ".join(["navigation"] * 550)
    body = " ".join(["inflation employment policy rates"] * 60)
    title = "Economic Outlook"
    path.write_text(f"<html><body>{title} {navigation} {title} {body}</body></html>")
    text, method = extract_artifact_text(path, title)
    assert text.startswith("inflation employment")
    assert "navigation" not in text
    assert method == "HTML_ALL_TITLE_TRIMMED"


def test_parse_fred_vintage_xml_and_month_math(tmp_path):
    path = tmp_path / "series.xml"
    path.write_text(
        '<observations realtime_start="2019-03-08" realtime_end="2019-03-08">'
        '<observation realtime_start="2019-03-08" realtime_end="2019-03-08" date="2019-01-01" value="100.5"/>'
        '<observation realtime_start="2019-03-08" realtime_end="2019-03-08" date="2019-02-01" value="."/>'
        '</observations>'
    )
    rows = parse_fred_xml(path)
    assert rows == [{
        "observation_date": "2019-01-01",
        "value": 100.5,
        "realtime_start": "2019-03-08",
        "realtime_end": "2019-03-08",
    }]
    assert months_before(__import__("datetime").date(2019, 2, 1), 12) == (2018, 2)


def test_text_vocabulary_uses_document_frequency_and_removes_names():
    removed = {"jerome", "powell"}
    documents = [
        text_terms("Jerome Powell inflation policy inflation", removed),
        text_terms("inflation policy employment", removed),
        text_terms("inflation policy growth", removed),
    ]
    vocabulary = build_vocabulary(documents, minimum_df=3, maximum=10)
    assert "jerome" not in vocabulary and "powell" not in vocabulary
    assert "inflation" in vocabulary and "inflation_policy" in vocabulary


def test_ridge_and_direction_scoring_are_deterministic():
    train_x = np.array([[0.0], [1.0], [2.0]])
    train_y = np.array([0.0, 10.0, 20.0])
    first = ridge_predict(train_x, train_y, np.array([[1.5]]), alpha=10.0)
    second = ridge_predict(train_x, train_y, np.array([[1.5]]), alpha=10.0)
    assert first.tolist() == second.tolist()
    assert direction_label(106.3, 100.0) == "HIGHER"
    assert direction_label(105.0, 100.0) == "UNCHANGED"
    assert balanced_accuracy(["A", "A", "B"], ["A", "B", "B"]) == 0.75


def test_human_review_passage_redacts_identity_and_bank():
    text = "Jerome Powell at the Federal Reserve Bank of New York said inflation policy " + "support growth " * 300
    passage = passage_for_review(text, {"jerome", "powell"})
    assert "Jerome" not in passage and "Powell" not in passage
    assert "Federal Reserve Bank of New York" not in passage
    assert "[REDACTED]" in passage


def test_frozen_outputs_have_no_lookahead_and_expected_verdict():
    with open("data/fomc_validation/features/sep_validation_examples.csv") as handle:
        examples = list(csv.DictReader(handle))
    assert len(examples) == 1875
    assert all(row["previous_sep_date"] < row["analytical_cutoff_date"] < row["target_sep_date"] for row in examples)
    with open("data/fomc_validation/features/macro_features.csv") as handle:
        macro = list(csv.DictReader(handle))
    assert len(macro) == 35
    assert all(
        row[field] <= row["alfred_vintage_date"]
        for row in macro
        for field in (
            "unemployment_observation_date", "cpi_observation_date", "core_pce_observation_date",
            "payroll_observation_date", "real_gdp_observation_date",
        )
    )
    result = json.loads(Path("data/fomc_validation/results/sep_validation_results.json").read_text())
    assert result["verdict"] == "SEP_VALUE_FAIL"
    assert result["partition_integrity"]["strict_untouched_claim_allowed"] is False


def test_human_review_packet_is_blank_unique_and_complete():
    with open("data/fomc_validation/human_review/reviewer_1.csv") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 120
    assert len({row["sample_id"] for row in rows}) == 120
    assert all(not row["label"] and not row["confidence_1_to_5"] for row in rows)
