from anthropic import Anthropic
from anthropic.types import Message
import json
from types import SimpleNamespace

# class Claude:
#     def __init__(self, model: str):
#         self.client = Anthropic(api_key="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",base_url="https://openrouter.ai/api/v1/chat/completions")
#         self.model = model

#     def add_user_message(self, messages: list, message):
#         user_message = {
#             "role": "user",
#             "content": message.content
#             if isinstance(message, Message)
#             else message,
#         }
#         messages.append(user_message)

#     def add_assistant_message(self, messages: list, message):
#         assistant_message = {
#             "role": "assistant",
#             "content": message.content
#             if isinstance(message, Message)
#             else message,
#         }
#         messages.append(assistant_message)

#     def text_from_message(self, message: Message):
#         return "\n".join(
#             [block.text for block in message.content if block.type == "text"]
#         )

#     def chat(
#         self,
#         messages,
#         system=None,
#         temperature=1.0,
#         stop_sequences=[],
#         tools=None,
#         thinking=False,
#         thinking_budget=1024,
#     ) -> Message:
#         params = {
#             "model": self.model,
#             "max_tokens": 8000,
#             "messages": messages,
#             "temperature": temperature,
#             "stop_sequences": stop_sequences,
#         }

#         if thinking:
#             params["thinking"] = {
#                 "type": "enabled",
#                 "budget_tokens": thinking_budget,
#             }

#         if tools:
#             params["tools"] = tools

#         if system:
#             params["system"] = system

#         message = self.client.messages.create(**params)
#         return message


import json
from types import SimpleNamespace
from typing import Any, Optional

from openai import OpenAI
import os
from dotenv import load_dotenv
load_dotenv()

class Claude:
    def __init__(self, model: str):
        self.client = OpenAI(
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("BASE_URL"),
        )
        self.model = model

    def _stringify_content(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, (dict, list)):
            return json.dumps(content, ensure_ascii=False)
        return str(content)

    def _content_from_input(self, message: Any) -> Any:
        return getattr(message, "content", message)

    def _is_tool_result_block(self, item: Any) -> bool:
        if isinstance(item, dict):
            return item.get("type") == "tool_result"
        return getattr(item, "type", None) == "tool_result"

    def _tool_result_block_to_openai_message(self, item: Any) -> dict:
        if isinstance(item, dict):
            tool_call_id = item["tool_use_id"]
            content = item.get("content", "")
        else:
            tool_call_id = getattr(item, "tool_use_id")
            content = getattr(item, "content", "")

        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": self._stringify_content(content),
        }

    def _assistant_to_openai_message(self, message: Any) -> dict:
        # already a valid OpenAI-format assistant message
        if (
            isinstance(message, dict)
            and message.get("role") == "assistant"
            and isinstance(message.get("content"), (str, type(None)))
        ):
            return message

        content = getattr(message, "content", None)
        if isinstance(message, dict):
            content = message.get("content", content)

        # plain assistant text
        if isinstance(content, str):
            return {"role": "assistant", "content": content}

        text_parts = []
        tool_calls = []

        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get("type")
                    if block_type == "text":
                        text_parts.append(block.get("text", ""))
                    elif block_type == "tool_use":
                        tool_calls.append(
                            {
                                "id": block["id"],
                                "type": "function",
                                "function": {
                                    "name": block["name"],
                                    "arguments": json.dumps(
                                        block.get("input", {}), ensure_ascii=False
                                    ),
                                },
                            }
                        )
                else:
                    block_type = getattr(block, "type", None)
                    if block_type == "text":
                        text_parts.append(getattr(block, "text", ""))
                    elif block_type == "tool_use":
                        tool_calls.append(
                            {
                                "id": getattr(block, "id"),
                                "type": "function",
                                "function": {
                                    "name": getattr(block, "name"),
                                    "arguments": json.dumps(
                                        getattr(block, "input", {}),
                                        ensure_ascii=False,
                                    ),
                                },
                            }
                        )

        assistant_message = {
            "role": "assistant",
            "content": "\n".join(p for p in text_parts if p) or None,
        }

        if tool_calls:
            assistant_message["tool_calls"] = tool_calls

        return assistant_message

    def _to_openai_messages(self, messages: list[Any]) -> list[dict]:
        converted = []

        for message in messages:
            # already a proper wire-format message
            if isinstance(message, dict) and message.get("role") in {
                "system",
                "user",
                "assistant",
                "tool",
            }:
                if message["role"] == "assistant":
                    converted.append(self._assistant_to_openai_message(message))
                elif message["role"] == "tool":
                    converted.append(
                        {
                            "role": "tool",
                            "tool_call_id": message["tool_call_id"],
                            "content": self._stringify_content(
                                message.get("content", "")
                            ),
                        }
                    )
                else:
                    converted.append(
                        {
                            "role": message["role"],
                            "content": self._stringify_content(
                                message.get("content", "")
                            ),
                        }
                    )
                continue

            # anthropic-style tool_result block accidentally stored directly
            if self._is_tool_result_block(message):
                converted.append(self._tool_result_block_to_openai_message(message))
                continue

            # internal adapted assistant object
            if getattr(message, "role", None) == "assistant":
                converted.append(self._assistant_to_openai_message(message))
                continue

            # generic user/system object
            role = getattr(message, "role", None)
            if role in {"user", "system"}:
                converted.append(
                    {
                        "role": role,
                        "content": self._stringify_content(
                            getattr(message, "content", "")
                        ),
                    }
                )
                continue

            raise TypeError(
                f"Unsupported message type in history: {type(message).__name__}"
            )

        return converted

    def add_user_message(self, messages: list, message: Any) -> None:
        # Anthropic-style tool results are sent back as role="tool" messages in OpenAI
        if (
            isinstance(message, list)
            and message
            and all(self._is_tool_result_block(item) for item in message)
        ):
            for item in message:
                messages.append(self._tool_result_block_to_openai_message(item))
            return

        messages.append(
            {
                "role": "user",
                "content": self._stringify_content(self._content_from_input(message)),
            }
        )

    def add_assistant_message(self, messages: list, message: Any) -> None:
        messages.append(self._assistant_to_openai_message(message))

    def text_from_message(self, message: Any) -> str:
        content = getattr(message, "content", "")

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif getattr(block, "type", None) == "text":
                    parts.append(getattr(block, "text", ""))
            return "\n".join(p for p in parts if p)

        return str(content or "")

    def _parse_tool_args(self, raw_args: Any) -> dict:
        if raw_args is None:
            return {}
        if isinstance(raw_args, dict):
            return raw_args
        if isinstance(raw_args, str):
            try:
                parsed = json.loads(raw_args)
                return parsed if isinstance(parsed, dict) else {"_raw_arguments": raw_args}
            except json.JSONDecodeError:
                return {"_raw_arguments": raw_args}
        return {}

    def _adapt_openai_message(self, completion: Any):
        choice = completion.choices[0]
        message = choice.message

        finish_reason = choice.finish_reason
        stop_reason = "tool_use" if finish_reason == "tool_calls" else finish_reason

        content_blocks = []

        if message.content:
            content_blocks.append(SimpleNamespace(type="text", text=message.content))

        if getattr(message, "tool_calls", None):
            for tc in message.tool_calls:
                content_blocks.append(
                    SimpleNamespace(
                        type="tool_use",
                        id=tc.id,
                        name=tc.function.name,
                        input=self._parse_tool_args(tc.function.arguments),
                    )
                )

        return SimpleNamespace(
            role="assistant",
            content=content_blocks,
            stop_reason=stop_reason,
            raw_message=message,
            raw_completion=completion,
        )

    def convert_anthropic_tools_to_openai(self, tools: list[dict]) -> list[dict]:
        converted = []

        for tool in tools:
            converted.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get(
                            "input_schema",
                            {
                                "type": "object",
                                "properties": {},
                            },
                        ),
                    },
                }
            )

        return converted

    def chat(
        self,
        messages,
        system: Optional[str] = None,
        temperature: float = 1.0,
        stop_sequences: Optional[list[str]] = None,
        tools: Optional[list] = None,
        thinking: bool = False,
        thinking_budget: int = 1024,
    ):
        chat_messages = self._to_openai_messages(messages)

        if system:
            chat_messages.insert(0, {"role": "system", "content": system})

        params = {
            "model": self.model,
            "messages": chat_messages,
            "temperature": temperature,
            "max_tokens": 8000,
        }

        if stop_sequences:
            params["stop"] = stop_sequences

        if tools:
            params["tools"] = self.convert_anthropic_tools_to_openai(tools)

        if thinking:
            params["extra_body"] = {
                "reasoning": {"max_tokens": thinking_budget}
            }

        completion = self.client.chat.completions.create(**params)
        return self._adapt_openai_message(completion)