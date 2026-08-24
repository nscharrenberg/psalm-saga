from deepeval.metrics import (
    ConversationalGEval,
    RoleAdherenceMetric,
    TurnRelevancyMetric,
)
from deepeval.test_case import MultiTurnParams

# Keep metrics in one module so eval files stay focused on app execution.
# Reuse existing project metrics and thresholds before adding new ones.

# Custom criterion for psalm-saga's core behavioral contract (the
# `using-psalm-saga` bootstrap): elicit every PSALM dimension explicitly and
# get sign-off on the written spec before any chapter prose gets drafted.
SPEC_FIRST_ADHERENCE = ConversationalGEval(
    name="SpecFirstAdherence",
    evaluation_params=[MultiTurnParams.CONTENT],
    criteria=(
        "Determine whether the assistant follows psalm-saga's spec-first "
        "workflow. It should elicit the user's explicit choices for all six "
        "PSALM dimensions (writing style, narrative voice, character, plot "
        "structure, scene sequence, world-building) one at a time, backed "
        "by concrete questions rather than one open-ended 'tell me about "
        "your story' prompt. It must not produce chapter prose before the "
        "user has explicitly signed off on the written spec, and it must "
        "not silently skip a dimension."
    ),
)

# `GoalAccuracyMetric` rewarded delivering concrete content and penalized
# clarifying questions -- exactly the friction `SpecFirstAdherence` and
# `RoleAdherenceMetric` require during elicitation, so it fought the product's
# own design (round 1: it got worse as spec-first adherence improved).
# `ElicitationProgress` rewards forward motion through the dimensions instead
# of rewarding delivered content, so it doesn't fight the other metrics.
#
# `ConversationCompletenessMetric` and a GEval using EXPECTED_OUTCOME both
# need `expected_outcome`, which `deepeval generate --method scratch
# --variation multi-turn` leaves null on every golden in this deepeval
# release regardless of `--include-expected` -- avoid that field until a
# generation path actually populates it.
ELICITATION_PROGRESS = ConversationalGEval(
    name="ElicitationProgress",
    evaluation_params=[MultiTurnParams.CONTENT],
    criteria=(
        "Determine whether the conversation makes real forward progress "
        "through psalm-saga's dimension elicitation. Each assistant turn "
        "should either ask a question that resolves a new dimension or "
        "sub-dimension, explicitly record/confirm a choice the user just "
        "gave, or ask a clarifying question genuinely needed to move that "
        "dimension forward. Penalize the assistant for stalling: re-asking "
        "an already-answered question, looping without acknowledging a "
        "choice the user already made, or leaving a stated choice "
        "unconfirmed. Do NOT penalize the assistant for withholding "
        "concrete story content, recommendations, or prose -- that "
        "restraint is the intended behavior, not a stall."
    ),
)

# Added after a real session (see docs/psalm-saga, "the-kindness-of-hands")
# shipped a spec where Character changed a giant to a wild elephant but
# World-Building's material detail still said "preserve the coat, button,
# cuff" -- nothing checked the two against each other. This metric catches
# the same failure mode in either direction: a from-scratch session where
# later dimensions clash with earlier ones, or a source-derived session
# where an open dimension's answer breaks a locked one.
CROSS_DIMENSION_CONSISTENCY = ConversationalGEval(
    name="CrossDimensionConsistency",
    evaluation_params=[MultiTurnParams.CONTENT],
    criteria=(
        "Determine whether the assistant keeps dimension choices consistent "
        "with each other across the conversation. When a choice recorded "
        "for one PSALM dimension (writing style, narrative voice, character, "
        "plot structure, scene sequence, world-building) would contradict or "
        "make physically/logically impossible a choice already recorded for "
        "another dimension -- including a dimension the user asked to keep "
        "unchanged from a supplied source text -- the assistant should name "
        "the contradiction explicitly and ask the user which side to revise, "
        "rather than silently carrying both contradictory choices forward "
        "into the spec or silently resolving the conflict itself. Penalize "
        "the assistant for producing or finalizing a spec containing an "
        "unresolved contradiction between dimensions."
    ),
)

MULTI_TURN_METRICS = [
    SPEC_FIRST_ADHERENCE,
    ELICITATION_PROGRESS,
    CROSS_DIMENSION_CONSISTENCY,
    RoleAdherenceMetric(),
    TurnRelevancyMetric(),
]
