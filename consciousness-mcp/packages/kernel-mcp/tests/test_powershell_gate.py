"""The Windows shell has to reach the same gate as the POSIX one.

Antigravity CLI exposes PowerShell as a tool of its own on Windows, where it is the
primary shell. `is_external_tool` named Bash and not PowerShell, so a command the
Bash branch refuses was allowed verbatim through the PowerShell one -- the two
shells disagreed about the same effect.
"""

from __future__ import annotations

from kernel_mcp.agency import is_external_tool


class TestPowerShellReachesTheGate:
    def test_a_recursive_delete_is_outward(self) -> None:
        assert is_external_tool(
            "PowerShell", {"command": "Remove-Item -Recurse -Force ./tmp"}
        )

    def test_the_two_shells_agree_about_the_same_effect(self) -> None:
        delete = {
            "Bash": "rm -rf ./tmp",
            "PowerShell": "Remove-Item -Recurse -Force ./tmp",
        }
        assert {tool: is_external_tool(tool, {"command": cmd}) for tool, cmd in delete.items()} == {
            "Bash": True,
            "PowerShell": True,
        }

    def test_a_missing_command_is_still_outward(self) -> None:
        # The Bash branch reads the command to classify it; this one does not, so
        # an absent or malformed input cannot soften the verdict.
        assert is_external_tool("PowerShell", {})

    def test_an_inspection_command_is_outward_too(self) -> None:
        # Deliberate. There is no _powershell_is_read_only() counterpart, and a
        # wrong read-only verdict would reopen the bypass, so reads cost an
        # intention on Windows. Remove this test when that counterpart lands.
        assert is_external_tool("PowerShell", {"command": "Get-ChildItem"})


class TestBashClassificationIsUnchanged:
    def test_read_only_bash_is_still_internal(self) -> None:
        assert not is_external_tool("Bash", {"command": "ls -la"})

    def test_writing_bash_is_still_outward(self) -> None:
        assert is_external_tool("Bash", {"command": "echo hi > out.txt"})
