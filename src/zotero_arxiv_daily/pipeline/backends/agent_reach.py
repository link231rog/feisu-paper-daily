"""Agent-Reach CLI adapter.

Communicates with external 'agent-reach' CLI (https://github.com/Panniantong/Agent-Reach)
via JSON stdin/stdout pipes, providing zero-install external capability assembly for:
1. Universal URL reading with anti-scraping bypass.
2. Video & presentation searches (Bilibili, YouTube) and transcripts.
3. Community discussions & repository insights (Reddit, GitHub, X).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any, Optional

from loguru import logger


class AgentReachCLI:
    """External CLI wrapper for agent-reach."""

    @classmethod
    def is_installed(cls) -> bool:
        """Checks if agent-reach binary is available on PATH."""
        return shutil.which("agent-reach") is not None

    @classmethod
    def run_raw(cls, args: list[str], timeout: float = 20.0) -> Optional[dict[str, Any]]:
        """Invokes agent-reach CLI command and returns parsed JSON output."""
        if not cls.is_installed():
            return None

        cmd = ["agent-reach"] + args
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            stdout = proc.stdout.strip()
            if not stdout:
                if proc.stderr:
                    logger.debug(f"agent-reach stderr: {proc.stderr[:200]}")
                return None

            # Try parsing complete output as JSON
            try:
                data = json.loads(stdout)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                # Scan lines for JSON block if CLI emitted informational banners
                for line in stdout.splitlines():
                    line = line.strip()
                    if line.startswith("{") and line.endswith("}"):
                        try:
                            data = json.loads(line)
                            if isinstance(data, dict):
                                return data
                        except Exception:
                            continue

            return {"ok": proc.returncode == 0, "result": stdout}
        except subprocess.TimeoutExpired:
            logger.debug(f"agent-reach command timed out after {timeout}s: {' '.join(cmd)}")
            return None
        except Exception as exc:
            logger.debug(f"agent-reach command failed: {exc}")
            return None

    @classmethod
    def read_url(cls, url: str, timeout: float = 25.0) -> Optional[str]:
        """Reads a webpage using agent-reach's automated fallback reader."""
        if not url:
            return None
        resp = cls.run_raw(["read", url], timeout=timeout)
        if not resp:
            return None

        # Agent-Reach format: {"ok": true, "result": {"content": "..."} or "markdown"}
        if resp.get("ok"):
            res = resp.get("result")
            if isinstance(res, str):
                return res.strip()
            if isinstance(res, dict):
                return (res.get("content") or res.get("text") or res.get("markdown") or "").strip() or None
        return None

    @classmethod
    def search_bilibili(cls, query: str, limit: int = 3, timeout: float = 15.0) -> list[dict[str, Any]]:
        """Searches Bilibili for paper breakdown videos and tech talks."""
        if not query:
            return []
        resp = cls.run_raw(["bilibili", "search", query, "--limit", str(limit)], timeout=timeout)
        if not resp or not resp.get("ok"):
            return []

        res = resp.get("result")
        if isinstance(res, list):
            return res[:limit]
        if isinstance(res, dict) and isinstance(res.get("items"), list):
            return res["items"][:limit]
        return []

    @classmethod
    def search_youtube(cls, query: str, limit: int = 3, timeout: float = 15.0) -> list[dict[str, Any]]:
        """Searches YouTube for paper author presentations and discussions."""
        if not query:
            return []
        resp = cls.run_raw(["youtube", "search", query, "--limit", str(limit)], timeout=timeout)
        if not resp or not resp.get("ok"):
            return []

        res = resp.get("result")
        if isinstance(res, list):
            return res[:limit]
        if isinstance(res, dict) and isinstance(res.get("items"), list):
            return res["items"][:limit]
        return []

    @classmethod
    def search_reddit(cls, query: str, limit: int = 3, timeout: float = 15.0) -> list[dict[str, Any]]:
        """Searches Reddit (e.g. r/MachineLearning, r/LocalLLaMA) for community pulse."""
        if not query:
            return []
        resp = cls.run_raw(["reddit", "search", query, "--limit", str(limit)], timeout=timeout)
        if not resp or not resp.get("ok"):
            return []

        res = resp.get("result")
        if isinstance(res, list):
            return res[:limit]
        if isinstance(res, dict) and isinstance(res.get("items"), list):
            return res["items"][:limit]
        return []

    @classmethod
    def inspect_github_repo(cls, repo_or_url: str, timeout: float = 15.0) -> Optional[dict[str, Any]]:
        """Fetches repository insights and issue discussions via agent-reach."""
        if not repo_or_url:
            return None
        resp = cls.run_raw(["github", "repo", repo_or_url], timeout=timeout)
        if not resp or not resp.get("ok"):
            return None

        res = resp.get("result")
        return res if isinstance(res, dict) else None
