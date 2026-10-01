"""ADR-028 task 13: held-out constant gate uses Student-t bounds by degrees of freedom."""

import math

import pytest

from app.modules.autonomy.qualification import (
    constant_advantage_established,
    paired_student_t_lower,
    student_t_quantile,
)


@pytest.mark.parametrize(
    "df,expected",
    [(1, 12.706204736), (3, 3.182446305), (11, 2.200985160), (30, 2.042272456), (1000, 1.962339081)],
)
def test_student_t_quantile_reference_values(df, expected):
    assert student_t_quantile(0.975, df) == pytest.approx(expected, abs=2e-6)


@pytest.mark.parametrize("probability,df", [(0.5, 3), (1.0, 3), (0.975, 0), (0.975, 2.5)])
def test_invalid_quantile_requests_are_refused(probability, df):
    with pytest.raises(ValueError):
        student_t_quantile(probability, df)


def test_lower_bound_uses_df_and_is_undefined_below_two_pairs():
    assert paired_student_t_lower([1.0, 2.0, 3.0]) == pytest.approx(2 - 4.302652730 / math.sqrt(3), abs=1e-6)
    assert paired_student_t_lower([0.4]) is None and paired_student_t_lower([]) is None


def test_small_samples_no_longer_pass_on_a_normal_approximation():
    differences = [0.05, 0.06]
    mean = sum(differences) / 2
    normal_lower = mean - 1.96 * math.sqrt(sum((d - mean) ** 2 for d in differences) / 1 / 2)
    assert normal_lower > 0  # the retired normal approximation would have passed this gate
    assert not constant_advantage_established(differences, 0.02, 0.0)
    assert paired_student_t_lower(differences) < 0
    assert constant_advantage_established([0.05, 0.06, 0.055, 0.052] * 3, 0.02, 0.0)


@pytest.mark.parametrize(
    "differences",
    [[], [0.5], [0.01] * 12, [0.3, -0.25] * 6],
)
def test_gate_fails_closed_on_undefined_small_or_uncertain_advantage(differences):
    assert not constant_advantage_established(differences, 0.02, 0.0)
