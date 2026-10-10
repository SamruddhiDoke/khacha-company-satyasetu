from app.pipeline.verdicts import EvidenceInput as E
from app.pipeline.verdicts import decide_claim, decide_overall, overall_strength


def test_not_checkable():
    assert decide_claim(False, [E("supports", True, "official", "a.gov.in")]).verdict == "not_checkable"


def test_no_evidence_is_insufficient_not_false():
    d = decide_claim(True, [])
    assert d.verdict == "insufficient_evidence" and d.strength == "none"


def test_invalid_quotes_are_not_counted():
    d = decide_claim(True, [E("refutes", False, "official", "a.gov.in"), E("refutes", False, "news", "b.com")])
    assert d.verdict == "insufficient_evidence"


def test_not_relevant_is_not_counted():
    d = decide_claim(True, [E("not_relevant", True, "official", "a.gov.in")])
    assert d.verdict == "insufficient_evidence"


def test_single_official_refutation_is_false():
    d = decide_claim(True, [E("refutes", True, "official", "rbi.org.in")])
    assert d.verdict == "false" and d.strength == "moderate"


def test_single_weak_source_is_insufficient():
    d = decide_claim(True, [E("supports", True, "other", "someblog.com")])
    assert d.verdict == "insufficient_evidence" and d.strength == "weak"


def test_two_independent_weak_sources_verify():
    d = decide_claim(True, [E("supports", True, "other", "a.com"), E("supports", True, "other", "b.com")])
    assert d.verdict == "verified"


def test_same_domain_counts_once():
    d = decide_claim(True, [E("supports", True, "other", "a.com"), E("supports", True, "other", "a.com")])
    assert d.verdict == "insufficient_evidence"


def test_strong_requires_two_domains():
    d = decide_claim(True, [E("supports", True, "official", "a.gov.in"), E("supports", True, "news", "thehindu.com")])
    assert d.verdict == "verified" and d.strength == "strong"


def test_conflicting_when_both_sides_credible():
    d = decide_claim(True, [E("supports", True, "news", "x.com"), E("refutes", True, "fact_check", "boomlive.in")])
    assert d.verdict == "conflicting"


def test_weak_support_outweighed_by_credible_refutation():
    d = decide_claim(True, [E("supports", True, "other", "blog.com"), E("refutes", True, "fact_check", "altnews.in")])
    assert d.verdict == "false"


def test_outdated():
    d = decide_claim(True, [E("supports", True, "official", "a.gov.in", temporal_issue=True)])
    assert d.verdict == "outdated"


def test_misleading_missing_context():
    d = decide_claim(True, [E("supports", True, "news", "thehindu.com", missing_context="applies only to Kerala")])
    assert d.verdict == "misleading"


def test_partly_true():
    d = decide_claim(True, [E("partially_supports", True, "official", "a.gov.in")])
    assert d.verdict == "partly_true"


def test_overall():
    assert decide_overall([]) == "not_checkable"
    assert decide_overall(["not_checkable"]) == "not_checkable"
    assert decide_overall(["false", "not_checkable"]) == "false"
    assert decide_overall(["verified", "verified"]) == "verified"
    assert decide_overall(["verified", "false"]) == "mixed"
    assert decide_overall(["insufficient_evidence", "verified"]) == "mixed"


def test_overall_strength_is_weakest_link():
    assert overall_strength(["strong", "weak"]) == "weak"
    assert overall_strength([]) == "none"
