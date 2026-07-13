"""Compatibility facade for FastAPI chat access to the packaged harness."""

from app.harness.runtime import MyClaudeRuntime, my_claude_runtime


MyClaudeRuntimeService = MyClaudeRuntime
my_claude_runtime_service = my_claude_runtime
