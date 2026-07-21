import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "c1c_claims_appreciation.py"


def test_discord_bot_disables_default_help_command():
    tree = ast.parse(ENTRYPOINT.read_text(encoding="utf-8"))
    bot_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Bot"
    ]

    assert len(bot_calls) == 1
    help_keyword = next(
        (keyword for keyword in bot_calls[0].keywords if keyword.arg == "help_command"),
        None,
    )
    assert help_keyword is not None
    assert isinstance(help_keyword.value, ast.Constant)
    assert help_keyword.value.value is None


def test_help_is_not_registered_by_local_command_decorators():
    registrations = []
    for source_path in ROOT.rglob("*.py"):
        if "tests" in source_path.parts:
            continue
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                command_name = next(
                    (
                        keyword.value.value
                        for keyword in decorator.keywords
                        if keyword.arg == "name"
                        and isinstance(keyword.value, ast.Constant)
                    ),
                    None,
                )
                if command_name == "help":
                    registrations.append((source_path.relative_to(ROOT), node.name))

    assert registrations == []
