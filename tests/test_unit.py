"""Unit tests for doc-gen-agent core modules.

No LLM calls — tests utilities, schema loading, critique models,
tool wrappers, and node logic.

Usage:
  uv run pytest tests/test_unit.py -v
  # or directly:
  uv run python tests/test_unit.py
"""
import json
import os
import tempfile


# ---------------------------------------------------------------------------
# utils.py
# ---------------------------------------------------------------------------

def test_sha256_file():
    from doc_gen_agent.utils import sha256_file
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        f.write(b"hello world")
        path = f.name
    try:
        h = sha256_file(path)
        assert len(h) == 64
        assert h == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    finally:
        os.unlink(path)
    print("✓ sha256_file")


def test_load_schema_dir():
    from doc_gen_agent.utils import load_schema_dir
    schema_dir = os.path.join("src", "doc_gen_agent", "schemas", "cable-bill")
    if not os.path.isdir(schema_dir):
        print("⊘ load_schema_dir (cable-bill schema not found, skipping)")
        return
    schema, steering, samples = load_schema_dir(schema_dir)
    assert isinstance(schema, dict)
    assert "title" in schema
    assert isinstance(steering, str)
    assert len(steering) > 0
    assert isinstance(samples, list)
    print("✓ load_schema_dir")


def test_load_schema_dir_missing():
    from doc_gen_agent.utils import load_schema_dir
    try:
        load_schema_dir("/nonexistent/path")
        assert False, "Should have raised"
    except FileNotFoundError:
        pass
    print("✓ load_schema_dir raises on missing dir")


# ---------------------------------------------------------------------------
# critique.py — Pydantic models
# ---------------------------------------------------------------------------

def test_critique_result_model():
    from doc_gen_agent.critique import CritiqueResult, CritiqueIssue
    result = CritiqueResult(
        score=7,
        issues=[CritiqueIssue(
            category="layout", severity="minor",
            description="Too much whitespace", fix_hint="Reduce margins",
        )],
        summary="Decent document",
    )
    assert result.score == 7
    assert len(result.issues) == 1
    assert result.issues[0].category == "layout"
    d = result.model_dump()
    assert d["score"] == 7
    assert d["issues"][0]["fix_hint"] == "Reduce margins"
    print("✓ CritiqueResult pydantic model")


def test_critique_result_validation():
    from doc_gen_agent.critique import CritiqueResult
    from pydantic import ValidationError
    try:
        CritiqueResult(score=0, issues=[], summary="bad")
        assert False, "score=0 should fail (ge=1)"
    except ValidationError:
        pass
    try:
        CritiqueResult(score=11, issues=[], summary="bad")
        assert False, "score=11 should fail (le=10)"
    except ValidationError:
        pass
    print("✓ CritiqueResult validation bounds")


# ---------------------------------------------------------------------------
# nodes.py
# ---------------------------------------------------------------------------

def test_check_verdict():
    from doc_gen_agent.nodes import _check_verdict
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

    # Plain verdict
    s = make_state("doc_critic", "Score: 8/10\nVERDICT:accepted")
    assert _check_verdict(s, "doc_critic", "accepted") is True
    assert _check_verdict(s, "doc_critic", "rejected") is False

    # Markdown bold
    s = make_state("data_critic", "**VERDICT:rejected**")
    assert _check_verdict(s, "data_critic", "rejected") is True

    # JSON-style
    s = make_state("aug_critic", '{"verdict": "accepted"}')
    assert _check_verdict(s, "aug_critic", "accepted") is True

    # Missing node
    assert _check_verdict(s, "nonexistent", "accepted") is False

    print("✓ _check_verdict edge conditions")


# ---------------------------------------------------------------------------
# tools.py — save_json_file, read_json_file
# ---------------------------------------------------------------------------

def test_save_and_read_json():
    from doc_gen_agent.tools import save_json_file, read_json_file
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.json")
        data = {"name": "test", "value": 42}

        result = save_json_file(file_path=path, json_content=json.dumps(data))
        assert result["status"] == "success"
        assert os.path.exists(path)

        result = read_json_file(file_path=path)
        assert result["status"] == "success"
        loaded = json.loads(result["content"][0]["text"])
        assert loaded["name"] == "test"
        assert loaded["value"] == 42
    print("✓ save_json_file + read_json_file round-trip")


def test_read_json_missing():
    from doc_gen_agent.tools import read_json_file
    result = read_json_file(file_path="/nonexistent/file.json")
    assert result["status"] == "error"
    print("✓ read_json_file handles missing file")


def test_save_json_invalid():
    from doc_gen_agent.tools import save_json_file
    result = save_json_file(file_path=os.path.join(tempfile.gettempdir(), "test.json"), json_content="not valid json{{{")
    assert result["status"] == "error"
    print("✓ save_json_file handles invalid JSON")


# ---------------------------------------------------------------------------
# prompts
# ---------------------------------------------------------------------------

def test_prompt_render():
    from doc_gen_agent import prompts
    # All templates should render without error
    templates = [
        ("data_generator", {"schema_json": "{}", "steering": "", "extra": "", "data_json_path": os.path.join(tempfile.gettempdir(), "x.json")}),
        ("data_critic", {"schema_json": "{}", "steering": "", "data_json": "{}"}),
        ("critic_vision", {"threshold": 7, "steering": "", "has_samples": False, "data_json": ""}),
    ]
    for name, kwargs in templates:
        text = prompts.render(name, **kwargs)
        assert len(text) > 50, f"Template {name} rendered too short"
    print("✓ prompt templates render")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_sha256_file()
    test_load_schema_dir()
    test_load_schema_dir_missing()
    test_critique_result_model()
    test_critique_result_validation()
    test_check_verdict()
    test_save_and_read_json()
    test_read_json_missing()
    test_save_json_invalid()
    test_prompt_render()
    print("\nAll unit tests passed.")
