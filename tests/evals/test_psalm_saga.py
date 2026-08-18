from importlib import import_module

import pytest

from deepeval import assert_test
from deepeval.dataset import EvaluationDataset
from deepeval.simulator import ConversationSimulator

from metrics import MULTI_TURN_METRICS

# Round 2 (24-golden run) showed 10 turns is too tight for denser premises
# (comparing two concepts, critiquing an existing draft): the agent asked
# good structured questions but never reached a consolidated spec + sign-off
# before the simulated conversation ended, dragging SpecFirstAdherence/
# RoleAdherence down for reasons unrelated to actual behavior quality.
MAX_TURNS = 18
ai_app = import_module("ai_app")

simulator = ConversationSimulator(model_callback=ai_app.chatbot_callback)
dataset = EvaluationDataset()
dataset.add_goldens_from_json_file(file_path="tests/evals/.dataset.json")

simulated_test_cases = simulator.simulate(
    conversational_goldens=dataset.goldens,
    max_user_simulations=MAX_TURNS,
)
for _test_case in simulated_test_cases:
    _test_case.chatbot_role = ai_app.CHATBOT_ROLE


@pytest.mark.parametrize("test_case", simulated_test_cases)
def test_conversation(test_case):
    assert_test(test_case=test_case, metrics=MULTI_TURN_METRICS)
