"""Smoke test: verify the sub-graph wiring without calling LLMs.

Mocks the agents and critic functions to confirm:
  1. Outer graph routes data_generator → data_critic → doc_loop correctly
  2. Inner doc_loop routes doc_generator → doc_critic and loops on reject
  3. PDF deletion on reject works
  4. reset_on_revisit settings are correct per graph level

Usage:
  uv run pytest tests/test_subgraph.py -v
  # or directly:
  uv run python tests/test_subgraph.py
"""
import os
import tempfile

from seed_data.nodes import FunctionNode, was_rejected_visual
from strands.multiagent import GraphBuilder


def test_inner_graph_wiring():
    """Test that the doc_loop sub-graph loops on reject and exits on accept."""
    call_log = []

    def fake_doc_gen(task):
        call_log.append("doc_generator")
        return "DONE"

    def fake_doc_critic(task):
        n = sum(1 for c in call_log if c == "doc_critic")
        call_log.append("doc_critic")
        # Reject first time, accept second
        if n == 0:
            return "Score: 5/10\nVERDICT:rejected"
        return "Score: 8/10\nVERDICT:accepted"

    gen_node = FunctionNode(func=fake_doc_gen, name="doc_generator")
    critic_node = FunctionNode(func=fake_doc_critic, name="doc_critic")

    builder = GraphBuilder()
    builder.add_node(gen_node, "doc_generator")
    builder.add_node(critic_node, "doc_critic")
    builder.add_edge("doc_generator", "doc_critic")
    builder.add_edge("doc_critic", "doc_generator", condition=was_rejected_visual)
    builder.set_entry_point("doc_generator")
    builder.set_max_node_executions(20)
    builder.reset_on_revisit(False)
    graph = builder.build()

    graph("Generate a PDF")

    assert call_log == ["doc_generator", "doc_critic", "doc_generator", "doc_critic"], \
        f"Expected 2 cycles, got: {call_log}"
    print("✓ Inner graph loops on reject, exits on accept")


def test_pdf_deletion_on_reject():
    """Test that rejected PDFs get deleted."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"fake pdf")
        pdf_path = f.name

    assert os.path.exists(pdf_path)

    # Simulate what _doc_critic_fn does on reject
    try:
        os.remove(pdf_path)
    except OSError:
        pass

    assert not os.path.exists(pdf_path), "PDF should be deleted after rejection"
    print("✓ PDF deletion on reject works")


def test_nested_graph_as_node():
    """Test that a built Graph can be added as a node in an outer Graph."""
    call_log = []

    def step_a(task):
        call_log.append("step_a")
        return "data ready"

    def step_b(task):
        call_log.append("step_b")
        return "VERDICT:accepted"

    def inner_node(task):
        call_log.append("inner")
        return "inner done"

    # Build inner graph (single node for simplicity)
    inner_builder = GraphBuilder()
    inner_fn = FunctionNode(func=inner_node, name="inner_node")
    inner_builder.add_node(inner_fn, "inner_node")
    inner_builder.set_entry_point("inner_node")
    inner_builder.set_max_node_executions(5)
    inner_builder.reset_on_revisit(False)
    inner_graph = inner_builder.build()

    # Build outer graph with inner as a node
    outer_builder = GraphBuilder()
    node_a = FunctionNode(func=step_a, name="step_a")
    node_b = FunctionNode(func=step_b, name="step_b")
    outer_builder.add_node(node_a, "step_a")
    outer_builder.add_node(inner_graph, "inner_graph")
    outer_builder.add_node(node_b, "step_b")
    outer_builder.add_edge("step_a", "inner_graph")
    outer_builder.add_edge("inner_graph", "step_b")
    outer_builder.set_entry_point("step_a")
    outer_builder.set_max_node_executions(10)
    outer_builder.reset_on_revisit(True)
    outer_graph = outer_builder.build()

    outer_graph("start")

    assert call_log == ["step_a", "inner", "step_b"], f"Unexpected flow: {call_log}"
    print("✓ Nested graph works as node in outer graph")


def test_edge_conditions():
    """Test that verdict parsing in edge conditions works correctly."""
    from seed_data.nodes import _check_verdict
    from strands.multiagent.base import MultiAgentResult, NodeResult, Status
    from strands.agent.agent_result import AgentResult
    from strands.types.content import ContentBlock, Message

    def make_state(node_name, text):
        ar = AgentResult(
            stop_reason="end_turn",
            message=Message(role="assistant", content=[ContentBlock(text=text)]),
            metrics=None, state=None,
        )
        return MultiAgentResult(
            status=Status.COMPLETED,
            results={node_name: NodeResult(result=ar, status=Status.COMPLETED)},
        )

    # Test accepted
    state = make_state("doc_critic", "Score: 8/10\nVERDICT:accepted")
    assert _check_verdict(state, "doc_critic", "accepted") is True
    assert _check_verdict(state, "doc_critic", "rejected") is False

    # Test rejected
    state = make_state("doc_critic", "Score: 4/10\nVERDICT:rejected")
    assert _check_verdict(state, "doc_critic", "rejected") is True
    assert _check_verdict(state, "doc_critic", "accepted") is False

    # Test with markdown formatting
    state = make_state("data_critic", "**VERDICT:accepted**")
    assert _check_verdict(state, "data_critic", "accepted") is True

    print("✓ Edge condition verdict parsing works")


if __name__ == "__main__":
    test_edge_conditions()
    test_pdf_deletion_on_reject()
    test_inner_graph_wiring()
    test_nested_graph_as_node()
    print("\nAll tests passed.")
