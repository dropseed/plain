"""Internal subsystem powering the ``plain postgres sync`` / ``converge`` /
``schema`` commands.

This is not a public import API. End users drive convergence through those CLI
commands, not by importing from here, and it is intentionally absent from the
top-level ``plain.postgres`` surface. The names re-exported below exist for the
rest of ``plain.postgres`` (the CLI) to use; the drift types, ``DriftKind``,
the ``Correction`` classes, and the ``Status`` records are convergence-internal and
live in the ``.analysis`` / ``.corrections`` / ``.planning`` submodules.
"""

from .analysis import (
    ModelAnalysis,
    ReadOnlyConnectionError,
    analyze_model,
)
from .planning import (
    ConvergencePlan,
    ConvergenceResult,
    CorrectionResult,
    PlanItem,
    can_auto_correct,
    execute_plan,
    plan_convergence,
    plan_model_convergence,
)

__all__ = [
    "ConvergencePlan",
    "ConvergenceResult",
    "CorrectionResult",
    "ModelAnalysis",
    "PlanItem",
    "ReadOnlyConnectionError",
    "analyze_model",
    "can_auto_correct",
    "execute_plan",
    "plan_convergence",
    "plan_model_convergence",
]
