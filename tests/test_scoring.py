"""Unit tests for score.py — individual dimension scorers and weighted calculation."""

import pytest

from harness.heuristic_scorer import (
    _coverage_ratio,
    _disallowed_hits,
    _full_text,
    score,
    score_completeness,
    score_correctness,
    score_hallucination_risk,
    score_reviewer_usefulness,
)
from tests.factories import make_gold_annotation as make_gold
from tests.factories import make_model_output as make_output
from tests.factories import make_test_case

# ---------------------------------------------------------------------------
# _full_text
# ---------------------------------------------------------------------------


class TestFullText:
    def test_includes_title_and_steps(self):
        tc = make_test_case(title="login succeeds", steps=["click submit"])
        output = make_output(test_cases=[tc])
        text = _full_text(output)
        assert "login succeeds" in text
        assert "click submit" in text

    def test_includes_assumptions_and_notes(self):
        output = make_output(assumptions=["no rate limit"], notes="coverage gap")
        text = _full_text(output)
        assert "no rate limit" in text
        assert "coverage gap" in text

    def test_lowercased(self):
        tc = make_test_case(title="Login SUCCEEDS")
        output = make_output(test_cases=[tc])
        assert "login succeeds" in _full_text(output)


# ---------------------------------------------------------------------------
# Coverage ratio
# ---------------------------------------------------------------------------


class TestCoverageRatio:
    def test_full_coverage(self):
        output = make_output(
            test_cases=[
                make_test_case(
                    title="redirected to dashboard after login",
                    preconditions=["user account exists"],
                )
            ]
        )
        gold = make_gold(coverage_points=["redirected to dashboard", "user account exists"])
        assert _coverage_ratio(output, gold) == 1.0

    def test_partial_coverage(self):
        output = make_output(
            test_cases=[make_test_case(title="redirected to dashboard")]
        )
        gold = make_gold(coverage_points=["redirected to dashboard", "session token created"])
        ratio = _coverage_ratio(output, gold)
        assert ratio == 0.5

    def test_zero_coverage(self):
        output = make_output(test_cases=[make_test_case(title="unrelated test")])
        gold = make_gold(coverage_points=["session token", "admin panel"])
        assert _coverage_ratio(output, gold) == 0.0

    def test_variant_counts_for_its_specific_point(self):
        # "authenticated successfully" not directly matched, but its bound variant is present.
        # "session token" not matched and has no variants → stays uncovered.
        output = make_output(test_cases=[make_test_case(title="user is logged in successfully")])
        gold = make_gold(
            coverage_points=["authenticated successfully", "session token"],
            variants={"authenticated successfully": ["logged in"]},
        )
        ratio = _coverage_ratio(output, gold)
        # "authenticated successfully" credited via variant; "session token" not matched → 0.5
        assert ratio == pytest.approx(0.5)

    def test_variant_does_not_credit_wrong_point(self):
        # Variant is bound to point A; if point A is already matched, point B should not be credited.
        output = make_output(test_cases=[make_test_case(title="authenticated successfully logged in")])
        gold = make_gold(
            coverage_points=["authenticated successfully", "session token"],
            variants={"authenticated successfully": ["logged in"]},
        )
        ratio = _coverage_ratio(output, gold)
        # "authenticated successfully" matched by primary; "session token" unmatched → 0.5
        assert ratio == pytest.approx(0.5)

    def test_empty_coverage_points_returns_one(self):
        output = make_output()
        gold = make_gold(coverage_points=[])
        assert _coverage_ratio(output, gold) == 1.0

    def test_keyword_match_does_not_false_positive_on_substring(self):
        # "log" must not match inside "login" or "dialogue" — word-boundary matching required.
        output = make_output(test_cases=[make_test_case(title="login and dialogue with admin")])
        gold = make_gold(coverage_points=["log"])
        assert _coverage_ratio(output, gold) == 0.0

    def test_keyword_match_does_not_false_positive_on_prefix(self):
        # "session" must not match inside "sessions" or "sessionless".
        output = make_output(test_cases=[make_test_case(title="sessions are sessionless")])
        gold = make_gold(coverage_points=["session"])
        assert _coverage_ratio(output, gold) == 0.0


# ---------------------------------------------------------------------------
# Disallowed hits
# ---------------------------------------------------------------------------


class TestDisallowedHits:
    def test_detects_disallowed_phrase_in_assumptions(self):
        output = make_output(assumptions=["password stored in plain text"])
        gold = make_gold(disallowed=["password stored in plain text"])
        assert _disallowed_hits(output, gold) == ["password stored in plain text"]

    def test_no_hits_when_clean(self):
        output = make_output()
        gold = make_gold(disallowed=["auto-approve all logins"])
        assert _disallowed_hits(output, gold) == []

    def test_partial_word_match_required(self):
        # "plain" alone shouldn't match "password stored in plain text"
        output = make_output(assumptions=["plain"])
        gold = make_gold(disallowed=["password stored in plain text"])
        assert _disallowed_hits(output, gold) == []

    def test_negation_does_not_trigger_disallowed_hit(self):
        # Model correctly describes the absence of a disallowed behavior using all
        # the same words in a negated sentence. Must NOT produce a false positive.
        tc = make_test_case(
            title="Account is not permanently locked after failed login",
            steps=[
                "Enter wrong password",
                "Verify account is not locked permanently after first failure",
            ],
            expected_result="Account is not locked after first failure",
        )
        output = make_output(test_cases=[tc])
        gold = make_gold(disallowed=["account locked permanently after first failure"])
        # Exact phrase "account locked permanently after first failure" does not
        # appear literally — it is always preceded by "not" in the model output.
        assert _disallowed_hits(output, gold) == []

    def test_disallowed_phrase_detected_when_literal(self):
        # Sanity-check: if the phrase appears verbatim (not negated), it IS flagged.
        output = make_output(
            assumptions=["account locked permanently after first failure"]
        )
        gold = make_gold(disallowed=["account locked permanently after first failure"])
        assert _disallowed_hits(output, gold) == ["account locked permanently after first failure"]


# ---------------------------------------------------------------------------
# score_completeness
# ---------------------------------------------------------------------------


class TestScoreCompleteness:
    def test_high_coverage(self):
        assert score_completeness(0.75) == 2.0
        assert score_completeness(1.0) == 2.0

    def test_medium_coverage(self):
        assert score_completeness(0.5) == 1.0
        assert score_completeness(0.74) == 1.0

    def test_low_coverage(self):
        assert score_completeness(0.0) == 0.0
        assert score_completeness(0.49) == 0.0


# ---------------------------------------------------------------------------
# score_correctness
# ---------------------------------------------------------------------------


class TestScoreCorrectness:
    def test_two_tc_no_hits(self):
        output = make_output(test_cases=[make_test_case(), make_test_case(title="Failure case")])
        assert score_correctness(output, []) == 2.0

    def test_single_tc_penalty(self):
        # 1 test case → -0.5 penalty → 1.5
        output = make_output(test_cases=[make_test_case()])
        assert score_correctness(output, []) == 1.5

    def test_penalty_for_disallowed_hit(self):
        # 2 TCs, 1 hit → 2.0 - 1.0 = 1.0
        output = make_output(test_cases=[make_test_case(), make_test_case(title="Negative")])
        assert score_correctness(output, ["bad assumption"]) == 1.0

    def test_two_hits_zeroes_out(self):
        output = make_output(test_cases=[make_test_case(), make_test_case(title="Negative")])
        assert score_correctness(output, ["bad", "worse"]) == 0.0

    def test_penalty_capped_at_two(self):
        # Three hits should not go below 0
        output = make_output(test_cases=[make_test_case(), make_test_case(title="Negative")])
        result = score_correctness(output, ["a", "b", "c"])
        assert result == 0.0

    def test_correctness_independent_of_coverage_ratio(self):
        # Score depends on output content and hits, NOT on coverage ratio
        output_a = make_output(test_cases=[make_test_case(), make_test_case(title="Negative")])
        output_b = make_output(test_cases=[make_test_case(), make_test_case(title="Negative")])
        # Both should score the same regardless of what coverage ratio would be
        assert score_correctness(output_a, []) == score_correctness(output_b, [])


# ---------------------------------------------------------------------------
# score_hallucination_risk
# ---------------------------------------------------------------------------


class TestScoreHallucinationRisk:
    def test_no_hits_clean_output(self):
        output = make_output(assumptions=[])
        assert score_hallucination_risk(output, []) == 2.0

    def test_one_hit(self):
        output = make_output(assumptions=[])
        assert score_hallucination_risk(output, ["one bad thing"]) == 1.0

    def test_two_hits(self):
        output = make_output(assumptions=[])
        assert score_hallucination_risk(output, ["bad", "worse"]) == 0.0

    def test_large_assumptions_list_penalized(self):
        output = make_output(assumptions=["a", "b", "c", "d"])
        assert score_hallucination_risk(output, []) == 1.0

    def test_three_assumptions_still_clean(self):
        output = make_output(assumptions=["a", "b", "c"])
        assert score_hallucination_risk(output, []) == 2.0


# ---------------------------------------------------------------------------
# score_reviewer_usefulness
# ---------------------------------------------------------------------------


class TestScoreReviewerUsefulness:
    def test_all_signals_present(self):
        tcs = [
            make_test_case(
                steps=["step1", "step2", "step3"],
                preconditions=["state A"],
                tc_type="positive",
            ),
            make_test_case(
                steps=["step1", "step2", "step3"],
                preconditions=["state B"],
                tc_type="negative",
            ),
        ]
        output = make_output(test_cases=tcs)
        assert score_reviewer_usefulness(output) == 2.0

    def test_missing_preconditions(self):
        tcs = [
            make_test_case(title="Login succeeds", steps=["s1", "s2", "s3"], preconditions=[]),
            make_test_case(title="Login fails", steps=["s1", "s2", "s3"], preconditions=[], tc_type="negative"),
        ]
        output = make_output(test_cases=tcs)
        # Has: avg_steps>=3 ✓, all expected_results ✓, types>=2 ✓, preconditions ✗ → 3 signals → 2
        assert score_reviewer_usefulness(output) == 2.0

    def test_single_short_test_case(self):
        tc = make_test_case(steps=["one step"], preconditions=[], expected_result="")
        output = make_output(test_cases=[tc])
        # avg_steps=1 ✗, expected_result empty ✗, preconditions ✗, 1 type ✗ → 0 signals
        assert score_reviewer_usefulness(output) == 0.0


# ---------------------------------------------------------------------------
# score() integration
# ---------------------------------------------------------------------------


class TestScore:
    def test_pass_decision(self):
        tcs = [
            make_test_case(
                title="user is redirected to dashboard on login",
                steps=["open page", "enter credentials", "submit form"],
                preconditions=["user account exists"],
                tc_type="positive",
            ),
            make_test_case(
                title="session token is created",
                steps=["login", "inspect storage", "verify token"],
                preconditions=["account active"],
                tc_type="positive",
            ),
        ]
        output = make_output(test_cases=tcs)
        gold = make_gold(
            coverage_points=["redirected to dashboard", "user account exists", "session token"],
        )
        result = score(output, gold)
        assert result.decision == "pass"
        assert result.weighted_score >= 1.6

    def test_fail_decision_low_coverage(self):
        output = make_output(test_cases=[make_test_case(title="unrelated")])
        gold = make_gold(coverage_points=["session token", "admin role", "audit log", "redirect"])
        result = score(output, gold)
        assert result.decision == "fail"

    def test_disallowed_hit_lowers_score(self):
        tcs = [
            make_test_case(
                title="redirected to dashboard",
                steps=["open", "submit", "verify"],
                preconditions=["user exists"],
                tc_type="positive",
            )
        ]
        output = make_output(
            test_cases=tcs,
            assumptions=["auto-approve all logins"],
        )
        gold = make_gold(
            coverage_points=["redirected to dashboard"],
            disallowed=["auto-approve all logins"],
        )
        result_with_hit = score(output, gold)
        output_clean = make_output(test_cases=tcs, assumptions=[])
        result_clean = score(output_clean, gold)
        assert result_with_hit.weighted_score < result_clean.weighted_score

    def test_result_contains_requirement_id(self):
        output = make_output(requirement_id="REQ-007")
        gold = make_gold(requirement_id="REQ-007")
        result = score(output, gold)
        assert result.requirement_id == "REQ-007"
