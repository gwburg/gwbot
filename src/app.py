import argparse

from rich.markdown import Markdown
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.message import Message
from textual.widgets import Footer, Header, Input, Static
from tools import categories as tool_categories, tools

import models
from memory import new_conversation_id
from memory.background import process_conversation
from prompts import SYSTEM_PROMPTS, build_system_prompt
from widgets import ModelSelector, StatusBar
from agent import (
    AgentEvent,
    RunEndEvent,
    StreamChunk,
    StreamEnd,
    StreamStart,
    ToolCallEvent,
    ToolResultEvent,
    UsageEvent,
    WarningEvent,
    _fmt_args,
    agent_loop,
    create_client,
)


MODEL_MAP = {k: v for k, v in vars(models).items() if not k.startswith("_")}

# Catppuccin Mocha palette — modern, easy on the eyes
C_USER = "#89b4fa"
C_AGENT = "#a6e3a1"
C_TOOL = "#f9e2af"
C_WARN = "#f38ba8"
C_DIM = "#6c7086"

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class AgentMessage(Message):
    """Wraps an AgentEvent for Textual's message system."""

    def __init__(self, event: AgentEvent):
        super().__init__()
        self.event = event


class AgentApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "Agent"

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+n", "switch_model", "Switch Model"),
    ]

    def __init__(self, model: str, system_prompt: str, max_iterations: int = 50, log_path: str | None = None, initial_task: str | None = None):
        super().__init__()
        self.model_alias = model
        self.model_id = MODEL_MAP[model]
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.log_path = log_path
        self.initial_task = initial_task

        self.client = create_client()
        self.conversation_id = new_conversation_id()
        self.messages: list[dict] = [{"role": "system", "content": system_prompt}]
        self._streaming_parts: list[str] = []
        self._streaming_widget: Static | None = None
        self._is_running = False
        self._msg_counter = 0
        self._spinner_widget: Static | None = None
        self._spinner_frame = 0
        self._tool_widgets: list[tuple[Static, str, dict]] = []  # (widget, name, args)
        self._has_agent_label = False  # whether [agent] label has been mounted this turn

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(id="chat-scroll")
        yield StatusBar(id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = self.model_id
        status = self.query_one(StatusBar)
        status.model_name = self.model_id
        self._stream_timer = self.set_interval(0.05, self._flush_stream, pause=True)
        self._spinner_timer = self.set_interval(0.08, self._tick_spinner, pause=True)
        if self.initial_task:
            self._submit_message(self.initial_task)
        else:
            self._mount_input()

    def _next_msg_id(self) -> str:
        self._msg_counter += 1
        return f"msg-{self._msg_counter}"

    def _append_widget(self, content, classes: str = "message") -> Static:
        """Mount a new Static widget into the chat scroll area."""
        scroll = self.query_one("#chat-scroll", VerticalScroll)
        widget = Static(content, id=self._next_msg_id(), classes=classes)
        scroll.mount(widget)
        widget.scroll_visible(animate=False)
        return widget

    def _show_spinner(self) -> None:
        """Mount and start the spinner animation."""
        if self._spinner_widget:
            return
        self._spinner_frame = 0
        self._spinner_widget = self._append_widget(
            f"[{C_DIM}]{SPINNER[0]}[/]", classes="message spinner"
        )
        self._spinner_timer.resume()

    def _hide_spinner(self) -> None:
        """Remove the spinner widget and stop the timer."""
        self._spinner_timer.pause()
        if self._spinner_widget:
            self._spinner_widget.remove()
            self._spinner_widget = None

    def _tick_spinner(self) -> None:
        """Advance the spinner animation by one frame."""
        if self._spinner_widget:
            self._spinner_frame = (self._spinner_frame + 1) % len(SPINNER)
            self._spinner_widget.update(f"[{C_DIM}]{SPINNER[self._spinner_frame]}[/]")

    def _mount_input(self) -> None:
        """Mount a new inline [user] prompt with Input inside the chat scroll."""
        scroll = self.query_one("#chat-scroll", VerticalScroll)
        row = Horizontal(id="input-row")
        label = Static(f"[{C_USER}]\\[user][/] ", id="input-label")
        inp = Input(id="user-input")
        scroll.mount(row)
        row.mount(label)
        row.mount(inp)
        row.scroll_visible(animate=False)
        inp.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        row = self.query_one("#input-row", Horizontal)
        row.remove()
        self._submit_message(text)

    def _submit_message(self, text: str) -> None:
        if self._is_running:
            return

        self._append_widget(f"[{C_USER}]\\[user][/] {text}", classes="message user-msg")

        self.messages.append({"role": "user", "content": text})
        self._is_running = True
        self._show_spinner()
        self.run_worker(self._run_agent(), exclusive=True)

    async def _run_agent(self) -> None:
        try:
            await agent_loop(
                self.client,
                self.model_id,
                self.messages,
                tools,
                max_iterations=self.max_iterations,
                log_path=self.log_path,
                on_event=lambda e: self.post_message(AgentMessage(e)),
            )
        except Exception as e:
            self._hide_spinner()
            self._append_widget(f"[{C_WARN}]\\[error][/] {e}")
        finally:
            self._is_running = False
            self._mount_input()
            self.run_worker(self._save_memory(), exclusive=False)

    async def _save_memory(self) -> None:
        """Save conversation log and run background summarization (best-effort)."""
        try:
            result = await process_conversation(self.client, self.conversation_id, self.messages)
            if result:
                action = result.get("action", "saved")
                self.notify(f"Memory {action}", timeout=3)
        except Exception:
            pass  # Memory is best-effort — never disrupt the chat

    def _render_tool(self, connector: str, name: str, args: dict) -> str:
        return f"[{C_DIM}]{connector}[/] [{C_TOOL}]\\[tool][/] [{C_DIM}]{name}({_fmt_args(args)})[/]"

    def _close_tool_group(self) -> None:
        """Swap the last tool call's connector from ├─ to └─."""
        if not self._tool_widgets:
            return
        widget, name, args = self._tool_widgets[-1]
        widget.update(self._render_tool("└─", name, args))
        self._tool_widgets = []

    def on_agent_message(self, message: AgentMessage) -> None:
        event = message.event

        match event:
            case StreamStart():
                self._hide_spinner()
                self._close_tool_group()
                # Mount [agent] label if not already shown this turn
                if not self._has_agent_label:
                    self._append_widget(f"[{C_AGENT}]\\[agent][/]", classes="agent-label")
                self._has_agent_label = True
                # Mount the content widget for streaming
                self._streaming_parts = []
                self._streaming_widget = self._append_widget("", classes="message agent-content")
                self._stream_timer.resume()

            case StreamChunk(text=text):
                self._streaming_parts.append(text)

            case StreamEnd(content=content):
                self._stream_timer.pause()
                if self._streaming_widget:
                    if content:
                        self._streaming_widget.update(Markdown(content))
                        self._streaming_widget.scroll_visible(animate=False)
                    else:
                        self._streaming_widget.remove()
                self._streaming_widget = None
                self._streaming_parts = []
                self._has_agent_label = False
                self._show_spinner()

            case ToolCallEvent(name=name, args=args):
                self._hide_spinner()
                # Mount [agent] label if tools arrive without a preceding stream
                if not self._has_agent_label:
                    self._append_widget(f"[{C_AGENT}]\\[agent][/]", classes="agent-label")
                    self._has_agent_label = True
                widget = self._append_widget(
                    self._render_tool("├─", name, args), classes="message tool-group"
                )
                self._tool_widgets.append((widget, name, args))
                self._show_spinner()

            case ToolResultEvent():
                pass

            case UsageEvent() as e:
                status = self.query_one(StatusBar)
                status.total_tokens = e.total_prompt_tokens + e.total_completion_tokens
                status.cost_usd = e.cost_usd
                status.context_pct = e.context_pct

            case WarningEvent(message=msg):
                self._append_widget(f"[{C_WARN}]\\[warning][/] {msg}")

            case RunEndEvent():
                self._hide_spinner()
                self._close_tool_group()
                self._has_agent_label = False

    def _flush_stream(self) -> None:
        """Periodically update the streaming widget with accumulated text."""
        if self._streaming_parts and self._streaming_widget:
            full_text = "".join(self._streaming_parts)
            self._streaming_widget.update(Markdown(full_text))
            self._streaming_widget.scroll_visible(animate=False)

    def action_switch_model(self) -> None:
        if self._is_running:
            return

        def on_dismiss(alias: str | None) -> None:
            if alias:
                self.model_alias = alias
                self.model_id = MODEL_MAP[alias]
                self.sub_title = self.model_id
                status = self.query_one(StatusBar)
                status.model_name = self.model_id

        self.push_screen(ModelSelector(), callback=on_dismiss)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the agent TUI")
    parser.add_argument("task", nargs="?", default=None, help="Initial task to send")
    parser.add_argument("--model", default="MINIMAX", choices=MODEL_MAP, metavar="MODEL", help=f"Model alias. Choices: {', '.join(MODEL_MAP)}")
    parser.add_argument("--system-prompt", default=None, help="Override system prompt text directly")
    parser.add_argument("--persona", default="default", choices=SYSTEM_PROMPTS, help=f"System prompt persona. Choices: {', '.join(SYSTEM_PROMPTS)}")
    parser.add_argument("--max-iterations", type=int, default=50)
    parser.add_argument("--log", metavar="PATH", help="Write a JSONL log to this file")
    args = parser.parse_args()

    system_prompt = args.system_prompt or build_system_prompt(args.persona, tool_categories)

    app = AgentApp(
        model=args.model,
        system_prompt=system_prompt,
        max_iterations=args.max_iterations,
        log_path=args.log,
        initial_task=args.task,
    )
    app.run()
