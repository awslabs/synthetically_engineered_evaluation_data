"""A scripted Strands model, for tests that must run the real Agent machinery.

Stubbing ``Agent`` out skips exactly what a structured-output change can break:
Strands validates the model's tool input against ``structured_output_model`` and,
on a validation error, sends the error back for another (paid) turn. A
``ScriptedModel`` answers every turn by calling one tool with a fixed input, so a
test can see how many turns that took and what the agent sent back. Bedrock is
never contacted.
"""
import json

from strands.models import Model


class ScriptedModel(Model):
    def __init__(self, tool_name, tool_input, *, usage=None, max_turns=3):
        self.tool_name = tool_name
        self.tool_input = tool_input
        self.usage = usage or {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120}
        self.max_turns = max_turns
        self.turns = 0
        self.tool_feedback: list[tuple[str, str]] = []   # (status, text) sent back to the model

    def update_config(self, **model_config):
        pass

    def get_config(self):
        return {}

    async def structured_output(self, *args, **kwargs):  # pragma: no cover - unused
        raise NotImplementedError

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.turns += 1
        for block in messages[-1]["content"]:
            if "toolResult" in block:
                result = block["toolResult"]
                self.tool_feedback.append((result["status"], result["content"][0]["text"]))
        offered = [spec["name"] for spec in tool_specs or []]
        if self.tool_name not in offered:
            raise AssertionError(f"tool {self.tool_name!r} not offered; got {offered}")
        if self.turns > self.max_turns:
            raise RuntimeError(f"ScriptedModel: more than {self.max_turns} turns")

        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"start": {"toolUse": {
            "toolUseId": f"tool-{self.turns}", "name": self.tool_name}}}}
        yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(self.tool_input)}}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "tool_use"}}
        yield {"metadata": {"usage": self.usage, "metrics": {"latencyMs": 1}}}
