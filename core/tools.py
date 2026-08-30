"""Tool registry, JSON-schema generation, and the approval policy layer.

Ground rule #4 of the hackathon requires consequential actions to be gated
behind human approval. That gate lives here rather than inside each tool, so
the policy is auditable in one place and provable in the trajectory log.
"""
from __future__ import annotations

import fnmatch
import inspect
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean",
               list: "array", dict: "object"}


class Decision(Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass
class Policy:
    pattern: str
    decision: Decision


def allow(p: str) -> Policy: return Policy(p, Decision.ALLOW)
def deny(p: str) -> Policy: return Policy(p, Decision.DENY)
def ask_user(p: str) -> Policy: return Policy(p, Decision.ASK)


def resolve(policies: list[Policy], tool: str) -> Decision:
    """Last matching rule wins, so `[deny("*"), allow("read_file")]` reads
    top-to-bottom like a firewall."""
    decision = Decision.ALLOW
    for p in policies:
        if fnmatch.fnmatch(tool, p.pattern):
            decision = p.decision
    return decision


@dataclass
class Tool:
    fn: Callable
    name: str
    description: str
    schema: dict

    def declaration(self) -> dict:
        return {"type": "function", "name": self.name,
                "description": self.description, "parameters": self.schema}


def build_tool(fn: Callable) -> Tool:
    """Derive the declaration from the signature and docstring. One source of
    truth means the schema cannot drift from the implementation."""
    sig = inspect.signature(fn)
    props, required = {}, []
    doc = inspect.getdoc(fn) or ""
    summary = doc.split("\n\n")[0].strip()

    for pname, param in sig.parameters.items():
        ann = param.annotation
        props[pname] = {"type": _JSON_TYPES.get(ann, "string")}
        if param.default is inspect.Parameter.empty:
            required.append(pname)

    return Tool(fn=fn, name=fn.__name__, description=summary,
                schema={"type": "object", "properties": props, "required": required})


class Registry:
    def __init__(self, tools: list[Callable], policies: list[Policy] | None = None):
        self.tools = {t.name: t for t in (build_tool(f) for f in tools)}
        self.policies = policies or []

    def declarations(self) -> list[dict]:
        return [t.declaration() for t in self.tools.values()]

    def decide(self, name: str) -> Decision:
        return resolve(self.policies, name)

    def invoke(self, name: str, args: dict[str, Any]) -> str:
        tool = self.tools.get(name)
        if tool is None:
            return f"ERROR: no such tool '{name}'"
        try:
            return str(tool.fn(**args))
        except Exception as e:
            # Errors go back to the model as text. An agent that can read its
            # own failure recovers; one that gets an exception just dies.
            return f"ERROR: {type(e).__name__}: {e}"


# --------------------------------------------------------------------------- #
# Default filesystem toolset. Every path is confined to a workspace root.

_BLOCKED = ("rm ", "del ", "format", "mkfs", "shutdown", "reboot", ":(){",
            "sudo", "chmod 777", "curl ", "wget ", "pip install", "git push")


def make_fs_tools(workspace: Path, cmd_timeout: int = 60) -> list[Callable]:
    root = workspace.resolve()

    def _safe(p: str) -> Path:
        # is_relative_to compares path components. A string prefix check would
        # let a sibling directory through: "/repo-secret".startswith("/repo").
        target = (root / p).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"path escapes workspace: {p}")
        return target

    def read_file(path: str) -> str:
        """Read a UTF-8 text file relative to the workspace root."""
        text = _safe(path).read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        if len(lines) > 400:
            return "\n".join(lines[:400]) + f"\n... [{len(lines)-400} more lines]"
        return text

    def list_dir(path: str = ".") -> str:
        """List files and directories at a path relative to the workspace root."""
        target = _safe(path)
        entries = sorted(
            f"{e.name}/" if e.is_dir() else f"{e.name} ({e.stat().st_size}b)"
            for e in target.iterdir()
            if not e.name.startswith(".")
        )
        return "\n".join(entries) or "(empty)"

    def run_command(command: str) -> str:
        """Run a shell command inside the workspace. Consequential — gated."""
        low = command.lower()
        if any(b in low for b in _BLOCKED):
            return f"ERROR: command blocked by safety policy: {command}"
        r = subprocess.run(command, shell=True, cwd=root, capture_output=True,
                           text=True, timeout=cmd_timeout)
        out = (r.stdout or "") + (("\nSTDERR:\n" + r.stderr) if r.stderr else "")
        return f"exit={r.returncode}\n{out[:8000]}"

    return [read_file, list_dir, run_command]
