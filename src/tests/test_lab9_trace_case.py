"""Regression test from docs/trace_case.md: swarm C-002@55 refunded 20.000đ on a claim whose label is
`denied`, because step 3 (`model_override`) replaced the DB delay (2 days) with the ticket's 5 days.
The same first wrong step is forced on every seed by `seeded_regression` (ticket_trust)."""
import pytest

pytestmark = pytest.mark.student


def _ctx(case):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=case["label"],
                            output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})


@pytest.mark.parametrize("shape,seed", [("swarm", 55), ("seeded_regression", 11)])
def test_lab9_trace_case_ticket_override_caught(shape, seed):
    from lab9 import graders
    from lab9.trace_case import investigate

    case = investigate(shape, "C-002", seed)
    kinds = [e.get("kind") for e in case["trial"]["events"]]
    assert "model_override" in kinds                      # the first wrong step is present
    assert kinds.index("model_override") < kinds.index("quote")
    assert graders.DbFactKept().evaluate(_ctx(case)).value is False
    assert graders.RefundAmountCorrect().evaluate(_ctx(case)).value is False


def test_lab9_trace_case_fixed_is_clean():
    from lab9 import graders
    from lab9.trace_case import investigate

    case = investigate("fixed", "C-002", 55)
    assert "model_override" not in [e.get("kind") for e in case["trial"]["events"]]
    assert graders.DbFactKept().evaluate(_ctx(case)).value is True
    assert graders.RefundAmountCorrect().evaluate(_ctx(case)).value is True
