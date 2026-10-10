"""Explicit, testable verdict rules.

The language model never decides a verdict. It labels individual passages
(supports / refutes / partially supports / not relevant) and must quote the
passage verbatim. Only assessments whose quote was found in the retrieved
source text are counted. These rules then turn counted evidence into a verdict.

Self-contradictory sources: if one domain has counted quotes that both support
and refute the claim, only its majority side is kept; on a tie the domain is
dropped from both sides (a page that says "1934" in one sentence and "1935" in
another cannot vouch for either). Partial support is unaffected.

Weighting: each *domain* contributes at most once per stance, with the weight
of its tier (official 3, fact_check 3, news 2, reference 2, other 1). A side
is "credible" when its weight reaches CREDIBLE (2) - i.e. one official,
fact-check, news or reference source, or two independent other sources.

Claim verdicts
  not_checkable          claim is opinion / prediction / question / not objectively checkable
  insufficient_evidence  no counted evidence, or no side reaches CREDIBLE
  conflicting            both supporting and refuting sides reach CREDIBLE
  outdated               counted evidence flagged as describing a past state reaches CREDIBLE
  false                  refuting side reaches CREDIBLE, supporting side does not
  misleading             supported (or partly supported) but credible evidence flags missing context
  partly_true            partial support reaches CREDIBLE and neither full side does
  verified               supporting side reaches CREDIBLE, refuting side does not

Evidence strength (no percentages - categorical only)
  none      nothing counted
  weak      winning side below CREDIBLE
  moderate  winning side CREDIBLE from one domain, or weight 2-3
  strong    winning side weight >= 4 from >= 2 independent domains
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.pipeline.sources import TIER_WEIGHT

CREDIBLE = 2

CLAIM_VERDICTS = (
    "verified", "false", "partly_true", "misleading", "outdated", "conflicting", "insufficient_evidence",
    "not_checkable",
)
OVERALL_VERDICTS = CLAIM_VERDICTS + ("mixed",)


@dataclass
class EvidenceInput:
    stance: str  # supports | refutes | partially_supports | not_relevant
    quote_valid: bool
    tier: str
    domain: str
    temporal_issue: bool = False
    missing_context: str | None = None


@dataclass
class ClaimDecision:
    verdict: str
    strength: str
    reason: str
    weights: dict = field(default_factory=dict)


def _side_weight(items: list[EvidenceInput]) -> tuple[int, int]:
    by_domain: dict[str, int] = {}
    for e in items:
        by_domain[e.domain] = max(by_domain.get(e.domain, 0), TIER_WEIGHT.get(e.tier, 1))
    return sum(by_domain.values()), len(by_domain)


def _strength(weight: int, domains: int) -> str:
    if weight == 0:
        return "none"
    if weight < CREDIBLE:
        return "weak"
    if weight >= 4 and domains >= 2:
        return "strong"
    return "moderate"


def _resolve_self_contradictions(items: list[EvidenceInput]) -> tuple[list[EvidenceInput], list[str]]:
    sup: dict[str, int] = {}
    ref: dict[str, int] = {}
    for e in items:
        if e.stance == "supports":
            sup[e.domain] = sup.get(e.domain, 0) + 1
        elif e.stance == "refutes":
            ref[e.domain] = ref.get(e.domain, 0) + 1
    drop: dict[str, set[str]] = {}
    tied: list[str] = []
    for d in sup.keys() & ref.keys():
        if sup[d] > ref[d]:
            drop[d] = {"refutes"}
        elif ref[d] > sup[d]:
            drop[d] = {"supports"}
        else:
            drop[d] = {"supports", "refutes"}
            tied.append(d)
    kept = [e for e in items if e.stance not in drop.get(e.domain, ())]
    return kept, sorted(tied)


def counted_mask(evidence: list[EvidenceInput]) -> list[tuple[bool, str | None]]:
    """Per item: (counted by the rules?, reason if a valid quote was excluded). Mirrors decide_claim."""
    eligible = [e for e in evidence if e.quote_valid and e.stance in ("supports", "refutes", "partially_supports")]
    kept, tied = _resolve_self_contradictions(eligible)
    kept_ids = {id(e) for e in kept}
    eligible_ids = {id(e) for e in eligible}
    out = []
    for e in evidence:
        if id(e) in kept_ids:
            out.append((True, None))
        elif id(e) in eligible_ids:
            out.append((False, "Excluded: this source contradicts itself on this claim" if e.domain in tied
                        else "Excluded: minority stance within the same source"))
        else:
            out.append((False, None))
    return out


def decide_claim(checkable: bool, evidence: list[EvidenceInput]) -> ClaimDecision:
    if not checkable:
        return ClaimDecision("not_checkable", "none", "The statement is not an objectively checkable factual claim.")

    counted = [e for e in evidence if e.quote_valid and e.stance in ("supports", "refutes", "partially_supports")]
    counted, contradictory = _resolve_self_contradictions(counted)
    sup = [e for e in counted if e.stance == "supports"]
    ref = [e for e in counted if e.stance == "refutes"]
    par = [e for e in counted if e.stance == "partially_supports"]
    tmp = [e for e in counted if e.temporal_issue]
    ctx = [e for e in counted if e.missing_context and e.stance in ("supports", "partially_supports")]
    S, s_dom = _side_weight(sup)
    R, r_dom = _side_weight(ref)
    P, p_dom = _side_weight(par)
    T, t_dom = _side_weight(tmp)
    C, _ = _side_weight(ctx)
    weights = {"supports": S, "refutes": R, "partial": P, "temporal": T, "missing_context": C,
               "counted": len(counted), "considered": len(evidence),
               "self_contradictory_domains": contradictory}

    if not counted:
        return ClaimDecision("insufficient_evidence", "none",
                             "No retrieved source contained a passage that addresses this claim.", weights)
    if S >= CREDIBLE and R >= CREDIBLE:
        return ClaimDecision("conflicting", _strength(max(S, R), max(s_dom, r_dom)),
                             "Credible sources both support and contradict this claim.", weights)
    if T >= CREDIBLE:
        return ClaimDecision("outdated", _strength(T, t_dom),
                             "Credible sources indicate the claim describes a situation that has since changed.", weights)
    if R >= CREDIBLE:
        return ClaimDecision("false", _strength(R, r_dom), "Credible sources contradict this claim.", weights)
    if S >= CREDIBLE or P >= CREDIBLE:
        if C >= CREDIBLE:
            return ClaimDecision("misleading", _strength(max(S, P), max(s_dom, p_dom)),
                                 "Sources support parts of the claim but it omits context that changes its meaning.",
                                 weights)
        if S >= CREDIBLE:
            return ClaimDecision("verified", _strength(S, s_dom), "Credible sources support this claim.", weights)
        return ClaimDecision("partly_true", _strength(P, p_dom),
                             "Credible sources support only part of this claim.", weights)
    return ClaimDecision("insufficient_evidence", "weak",
                         "Some relevant material was found, but not enough credible evidence to reach a conclusion.",
                         weights)


def decide_overall(claim_verdicts: list[str]) -> str:
    checkable = [v for v in claim_verdicts if v != "not_checkable"]
    if not claim_verdicts or not checkable:
        return "not_checkable"
    distinct = set(checkable)
    if len(distinct) == 1:
        return checkable[0]
    return "mixed"


def overall_strength(strengths: list[str]) -> str:
    order = ["none", "weak", "moderate", "strong"]
    relevant = [s for s in strengths if s in order]
    if not relevant:
        return "none"
    return order[min(order.index(s) for s in relevant)]
