"""Tests for seed_data.tools.calculator — the AST-allowlisted arithmetic tool that
replaces the deprecated strands_tools.calculator."""
import pytest

from seed_data.tools import calculator, evaluate_arithmetic


@pytest.mark.parametrize("expr,expected", [
    ("12.5 * 3 + 7.25", 44.75),
    ("round(1 / 3, 4)", 0.3333),
    ("2 ^ 10", 1024),
    ("sum(1, 2, 3) - max(1, 5) + min(4, 2)", 3),
    ("abs(-7) % 4", 3),
    ("floor(2.7) + ceil(2.1) + sqrt(16)", 9.0),
    ("-(3 - 5) * +2", 4),
    ("1199.99 * 0.0825", pytest.approx(98.999175)),
])
def test_evaluates_arithmetic(expr, expected):
    assert evaluate_arithmetic(expr) == expected


@pytest.mark.parametrize("expr", [
    '__import__("os").system("id")',
    "open('/etc/passwd')",
    "(1).real",
    "x + 1",
    "[1, 2]",
    "lambda: 1",
    "9 ** 9 ** 9",            # exponent bomb
    "10 ** 30",               # result out of range
    "'a' * 3",
    "round(1, ndigits=2)",    # keywords not allowed
    "1" * 3000,               # too long
])
def test_rejects_anything_but_arithmetic(expr):
    with pytest.raises((ValueError, SyntaxError)):
        evaluate_arithmetic(expr)


def test_tool_reports_errors_instead_of_raising():
    out = calculator._tool_func(expression="1 / 0")
    assert out["status"] == "error" and "1 / 0" in out["content"][0]["text"]
    deep = "(" * 5000 + "1" + ")" * 5000
    assert calculator._tool_func(expression=deep)["status"] == "error"


def test_tool_success_format_and_integral_floats():
    out = calculator._tool_func(expression="2.5 * 4")
    assert out == {"status": "success", "content": [{"text": "2.5 * 4 = 10"}]}


def test_tool_name_matches_what_the_prompts_ask_for():
    # prompts/data_generator.j2 and the data critic instruct "use the calculator tool"
    assert calculator.tool_name == "calculator"
