from __future__ import annotations

import pytest

from nakama_kun.tools.interfaces import BaseTool, ToolResult
from nakama_kun.tools.registry import ToolRegistry
from nakama_kun.tools.router import ToolRouter, is_mutating_command


class _MockTool(BaseTool):
    def __init__(self, name: str, parameters: dict | None = None) -> None:
        self.name = name
        self.description = f"Mock tool {name}"
        self.parameters = parameters or {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: object) -> ToolResult:
        return ToolResult(success=True, output="success")


@pytest.mark.parametrize(
    "cmd,expected_violation",
    [
        # Package installation
        ("pip install pytest", "installing packages"),
        ("pip3 install -r requirements.txt", "installing packages"),
        ("pipenv install black", "installing packages"),
        ("poetry add fastapi", "installing packages"),
        ("npm install --save lodash", "installing packages"),
        ("yarn add react", "installing packages"),
        ("pnpm install", "installing packages"),
        ("apt install curl", "installing packages"),
        ("apt-get install -y git", "installing packages"),
        # Git operations (mutating)
        ("git add src/main.py", "git operations"),
        ("git commit -m 'feat: auth'", "git operations"),
        ("git push origin main", "git operations"),
        ("git pull origin dev", "git operations"),
        ("git clone https://github.com/user/repo", "git operations"),
        ("git checkout -b feature", "git operations"),
        ("git reset --hard HEAD", "git operations"),
        ("git revert HEAD", "git operations"),
        ("git merge master", "git operations"),
        ("git rebase master", "git operations"),
        ("git init", "git operations"),
        ("git rm file.py", "git operations"),
        ("git mv file.py src/", "git operations"),
        # mkdir
        ("mkdir -p src/utils", "mkdir"),
        # Source modifications
        ("touch test.txt", "source modifications (touch)"),
        ("rm -rf node_modules", "source modifications (rm)"),
        ("mv old.py new.py", "source modifications (mv)"),
        ("cp a.py b.py", "source modifications (cp)"),
        ("ln -s a b", "source modifications (ln)"),
        ("chmod +x run.sh", "source modifications (chmod)"),
        ("chown root:root file", "source modifications (chown)"),
        ("echo 'text' | tee file.txt", "source modifications (tee)"),
        ("sed -i 's/foo/bar/g' file.py", "source modifications (sed)"),
        # Redirections
        ("echo 'hello' > test.py", "source modifications (redirection)"),
        ("cat info.json >> database.json", "source modifications (redirection)"),
        ("node build.js &> /dev/null", "source modifications (redirection)"),
    ],
)
def test_is_mutating_command_blocked(cmd: str, expected_violation: str) -> None:
    assert is_mutating_command(cmd) == expected_violation


@pytest.mark.parametrize(
    "cmd",
    [
        "echo hello",
        "cat src/main.py",
        "ls -la",
        "git status",
        "git diff",
        "git log -n 5",
        "git show HEAD",
        "git config --get user.name",
        "pytest tests/",
        "python -c 'import sys; print(sys.version)'",
        "command 2> /dev/null",
        "command 2>&1",
        "command >&2",
    ],
)
def test_is_mutating_command_allowed(cmd: str) -> None:
    assert is_mutating_command(cmd) is None


@pytest.mark.anyio
async def test_retrieval_safety_blocks_mutating_tool_names() -> None:
    registry = ToolRegistry()
    write_tool = _MockTool("write_file")
    create_tool = _MockTool("create_file")
    delete_tool = _MockTool("delete_file")
    mkdir_tool = _MockTool("mkdir")
    replace_tool = _MockTool("replace_file_content")
    multi_replace_tool = _MockTool("multi_replace_file_content")
    read_tool = _MockTool("read_file")

    registry.register(write_tool)
    registry.register(create_tool)
    registry.register(delete_tool)
    registry.register(mkdir_tool)
    registry.register(replace_tool)
    registry.register(multi_replace_tool)
    registry.register(read_tool)

    router = ToolRouter(registry)

    # Under "RETRIEVAL", mutating tools are blocked
    for name in ["write_file", "create_file", "delete_file", "mkdir", "replace_file_content", "multi_replace_file_content"]:
        res = await router.dispatch(name, {}, task_type="RETRIEVAL")
        assert not res.success
        assert "prohibited" in res.error

    # Under "RETRIEVAL", non-mutating tool like read_file is allowed
    res_read = await router.dispatch("read_file", {}, task_type="RETRIEVAL")
    assert res_read.success
    assert res_read.output == "success"

    # Under "MODIFICATION", mutating tools are allowed
    res_write_mod = await router.dispatch("write_file", {}, task_type="MODIFICATION")
    assert res_write_mod.success

    # Violations should be recorded for the 6 blocked attempts
    assert len(router.violations) == 6
    assert router.violations[0]["tool"] == "write_file"
    assert "prohibited" in router.violations[0]["reason"]


@pytest.mark.anyio
async def test_retrieval_safety_blocks_mutating_commands() -> None:
    registry = ToolRegistry()
    cmd_tool = _MockTool("run_command", parameters={
        "type": "object",
        "properties": {
            "cmd": {"type": "string"}
        },
        "required": ["cmd"]
    })
    registry.register(cmd_tool)

    router = ToolRouter(registry)

    # Mutating command blocked
    res_blocked = await router.dispatch("run_command", {"cmd": "pip install requests"}, task_type="RETRIEVAL")
    assert not res_blocked.success
    assert "Blocked: installing packages" in res_blocked.error
    assert len(router.violations) == 1
    assert router.violations[0]["arguments"]["cmd"] == "pip install requests"

    # Non-mutating command allowed
    res_allowed = await router.dispatch("run_command", {"cmd": "echo 'ok'"}, task_type="RETRIEVAL")
    assert res_allowed.success
    assert res_allowed.output == "success"
    # Violations count remains 1
    assert len(router.violations) == 1
