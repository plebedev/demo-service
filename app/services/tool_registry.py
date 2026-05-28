"""Shared decorator-based registry for backend agent tools."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import asyncio
import inspect
import json
from typing import Any, Callable, TypeVar

from pydantic import BaseModel
from pydantic_ai import Tool


class ToolCategory(StrEnum):
    """Supported classes of backend tools."""

    READ_ONLY = "read_only"
    MUTATIVE = "mutative"


@dataclass(frozen=True)
class ToolRegistryEntry:
    """Metadata for a tool exposed to one or more backend experiences."""

    name: str
    description: str
    prompt_instructions: str
    implementation: Callable[..., Any]
    category: ToolCategory
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    provider_override: str | None = None
    model_override: str | None = None
    implemented: bool = True
    is_terminal: bool = False

    def to_pydantic_tool(self) -> Tool[Any]:
        """Convert registry metadata into a PydanticAI tool wrapper."""
        return Tool(
            self.implementation,
            name=self.name,
            description=self.description,
        )

    def to_tool_definition(self) -> dict[str, Any]:
        """Generate an OpenAI-compatible function tool definition."""
        schema = self.input_model.model_json_schema()
        schema.pop("title", None)
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": schema,
        }

    def execute(self, payload: BaseModel) -> BaseModel:
        """Execute a deterministic registry tool with typed input/output."""
        result = self.implementation(payload)
        if isinstance(result, self.output_model):
            return result
        return self.output_model.model_validate(result)

    def execute_json(self, args: dict[str, Any], tool_config: dict[str, Any]) -> str:
        """Validate dict args, execute a voice-style tool, and return JSON."""
        validated = self.input_model.model_validate(args)
        result = self.implementation(validated, tool_config)
        if isinstance(result, BaseModel):
            return result.model_dump_json()
        return json.dumps(result)

    async def execute_json_async(
        self, args: dict[str, Any], tool_config: dict[str, Any]
    ) -> str:
        """Validate dict args, execute a voice-style tool off the event loop."""
        validated = self.input_model.model_validate(args)
        if inspect.iscoroutinefunction(self.implementation):
            result = await self.implementation(validated, tool_config)
        else:
            result = await asyncio.to_thread(
                self.implementation, validated, tool_config
            )
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, BaseModel):
            return result.model_dump_json()
        return json.dumps(result)


ToolCallableT = TypeVar("ToolCallableT", bound=Callable[..., Any])


def tool_decorator(
    category: ToolCategory,
    *,
    description: str,
    prompt_instructions: str,
    input_model: type[BaseModel],
    output_model: type[BaseModel],
    provider_override: str | None = None,
    model_override: str | None = None,
    implemented: bool = True,
    is_terminal: bool = False,
) -> Callable[[ToolCallableT], ToolCallableT]:
    """Attach registry metadata to a backend tool function."""

    def decorator(fn: ToolCallableT) -> ToolCallableT:
        fn._tool_meta = ToolRegistryEntry(  # type: ignore[attr-defined]
            name=fn.__name__,
            description=description,
            prompt_instructions=prompt_instructions,
            implementation=fn,
            category=category,
            input_model=input_model,
            output_model=output_model,
            provider_override=provider_override,
            model_override=model_override,
            implemented=implemented,
            is_terminal=is_terminal,
        )
        return fn

    return decorator


class ToolRegistry:
    """In-memory registry for discovered backend tools."""

    def __init__(self, entries: list[ToolRegistryEntry]) -> None:
        self._entries: dict[str, ToolRegistryEntry] = {}
        for entry in entries:
            if entry.name in self._entries:
                raise ValueError(f"Duplicate tool registry entry '{entry.name}'.")
            self._entries[entry.name] = entry

    def get(self, name: str) -> ToolRegistryEntry:
        """Return one registry entry or raise a clear lookup error."""
        try:
            return self._entries[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool '{name}'.") from exc

    def resolve(self, names: list[str] | None = None) -> list[ToolRegistryEntry]:
        """Resolve a configured tool list into concrete registry entries."""
        if names is None:
            return list(self._entries.values())
        return [self.get(name) for name in names]

    def scoped(self, names: list[str]) -> "ToolRegistry":
        """Build a registry containing only the selected tool names."""
        return ToolRegistry(self.resolve(names))

    def validate_tool_names(self, workflow_key: str, tool_names: list[str]) -> None:
        """Fail fast when configuration references unknown tool names."""
        for tool_name in tool_names:
            try:
                self.get(tool_name)
            except KeyError as exc:
                raise KeyError(
                    f"Workflow '{workflow_key}' references unknown tool '{tool_name}'."
                ) from exc

    def prompt_block(self, tool_names: list[str] | None = None) -> str | None:
        """Build a tool-instruction prompt block."""
        tools = self.resolve(tool_names)
        if not tools:
            return None
        lines = ["Tool instructions:"]
        for tool in tools:
            lines.append(f"- {tool.name}: {tool.prompt_instructions}")
        return "\n".join(lines)

    def tool_definitions(
        self, tool_names: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Return OpenAI-compatible function definitions for selected tools."""
        return [entry.to_tool_definition() for entry in self.resolve(tool_names)]

    def execute(self, name: str, payload: BaseModel) -> BaseModel:
        """Execute one registered deterministic tool."""
        return self.get(name).execute(payload)

    def execute_json(
        self, name: str, args: dict[str, Any], tool_config: dict[str, Any]
    ) -> str:
        """Execute one registered JSON/function-call style tool."""
        return self.get(name).execute_json(args, tool_config)

    async def execute_json_async(
        self, name: str, args: dict[str, Any], tool_config: dict[str, Any]
    ) -> str:
        """Execute one registered JSON/function-call style tool asynchronously."""
        return await self.get(name).execute_json_async(args, tool_config)


WorkflowToolRegistry = ToolRegistry


def build_tool_registry() -> ToolRegistry:
    """Build the backend tool registry by scanning decorated tool exports."""
    from app.services import tools as tools_module

    entries: list[ToolRegistryEntry] = []
    for name in tools_module.__all__:
        obj = getattr(tools_module, name, None)
        if obj is None or not callable(obj) or isinstance(obj, type):
            continue
        meta: ToolRegistryEntry | None = getattr(obj, "_tool_meta", None)
        if meta is None:
            raise ValueError(f"Tool '{name}' is exported but missing @tool_decorator")
        entries.append(meta)
    return ToolRegistry(entries)
