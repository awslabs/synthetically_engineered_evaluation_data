"""Custom graph nodes and edge condition functions."""
from strands.multiagent.base import MultiAgentBase, NodeResult, Status, MultiAgentResult
from strands.agent.agent_result import AgentResult
from strands.types.content import ContentBlock, Message


class FunctionNode(MultiAgentBase):
    """Execute a Python function as a graph node."""

    def __init__(self, func, name: str):
        super().__init__()
        self.func = func
        self.name = name

    async def invoke_async(self, task, invocation_state=None, **kwargs):
        result_text = self.func(task if isinstance(task, str) else str(task))
        agent_result = AgentResult(
            stop_reason="end_turn",
            message=Message(role="assistant", content=[ContentBlock(text=str(result_text))]),
            metrics=None,
            state=None,
        )
        return MultiAgentResult(
            status=Status.COMPLETED,
            results={self.name: NodeResult(result=agent_result, status=Status.COMPLETED)},
        )


# ---------------------------------------------------------------------------
# Edge condition helpers
# ---------------------------------------------------------------------------
def _check_verdict(state, node_name: str, expected: str) -> bool:
    node_result = state.results.get(node_name)
    if not node_result:
        return False
    text = str(node_result.result).lower().replace("*", "").replace("_", "")
    return f"verdict:{expected}" in text.replace(" ", "") or f'"verdict": "{expected}"' in text


def was_rejected_visual(state):
    return _check_verdict(state, "doc_critic", "rejected")

def was_rejected_data(state):
    return _check_verdict(state, "data_critic", "rejected")

def data_accepted(state):
    return _check_verdict(state, "data_critic", "accepted")

def doc_accepted(state):
    return _check_verdict(state, "doc_critic", "accepted")

def aug_rejected(state):
    return _check_verdict(state, "aug_critic", "rejected")
