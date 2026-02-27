import argparse

import models
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
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Footer, Header, Input, RichLog, Static
from tools import tools

from widgets import ModelSelector, StatusBar

MODEL_MAP = {k: v for k, v in vars(models).items() if not k.startswith("_")}


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
        self.messages: list[dict] = [{"role": "system", "content": system_prompt}]
        self._streaming_parts: list[str] = []
        self._is_running = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield RichLog(id="chat-log", wrap=True, highlight=True, markup=True)
        yield Static(id="streaming-text")
        yield StatusBar(id="status-bar")
        yield Input(placeholder="Type a message...", id="user-input")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = self.model_id
        status = self.query_one(StatusBar)
        status.model_name = self.model_id
        self._stream_timer = self.set_interval(0.05, self._flush_stream, pause=True)
        if self.initial_task:
            self._submit_message(self.initial_task)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.clear()
        self._submit_message(text)

    def _submit_message(self, text: str) -> None:
        if self._is_running:
            return

        chat_log = self.query_one("#chat-log", RichLog)
        chat_log.write(f"[bold cyan]\\[user][/] {text}")

        self.messages.append({"role": "user", "content": text})
        self._is_running = True
        self.query_one("#user-input", Input).disabled = True
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
            chat_log = self.query_one("#chat-log", RichLog)
            chat_log.write(f"[bold red]\\[error][/] {e}")
        finally:
            self._is_running = False
            input_widget = self.query_one("#user-input", Input)
            input_widget.disabled = False
            input_widget.focus()

    def on_agent_message(self, message: AgentMessage) -> None:
        event = message.event
        chat_log = self.query_one("#chat-log", RichLog)
        streaming = self.query_one("#streaming-text", Static)

        match event:
            case StreamStart():
                self._streaming_parts = []
                streaming.update("[bold green]\\[assistant][/] ")
                streaming.display = True
                self._stream_timer.resume()

            case StreamChunk(text=text):
                self._streaming_parts.append(text)

            case StreamEnd(content=content):
                self._stream_timer.pause()
                streaming.display = False
                streaming.update("")
                if content:
                    from rich.markdown import Markdown
                    chat_log.write(Markdown(content))
                    chat_log.scroll_end(animate=False)

            case ToolCallEvent(name=name, args=args):
                chat_log.write(f"[dim yellow]  \\[tool] {name}({_fmt_args(args)})[/]")
                chat_log.scroll_end(animate=False)

            case ToolResultEvent():
                pass

            case UsageEvent() as e:
                status = self.query_one(StatusBar)
                status.total_tokens = e.total_prompt_tokens + e.total_completion_tokens
                status.cost_usd = e.cost_usd
                status.context_pct = e.context_pct

            case WarningEvent(message=msg):
                chat_log.write(f"[bold red]  \\[warning] {msg}[/]")
                chat_log.scroll_end(animate=False)

            case RunEndEvent():
                pass

    def _flush_stream(self) -> None:
        if self._streaming_parts:
            streaming = self.query_one("#streaming-text", Static)
            full_text = "".join(self._streaming_parts)
            streaming.update(f"[bold green]\\[assistant][/] {full_text}")

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
    parser.add_argument("--system-prompt", default="You are a helpful, personal assistant, who can do a variety of general purpose tasks based on the tools provided to you")
    parser.add_argument("--max-iterations", type=int, default=50)
    parser.add_argument("--log", metavar="PATH", help="Write a JSONL log to this file")
    args = parser.parse_args()

    app = AgentApp(
        model=args.model,
        system_prompt=args.system_prompt,
        max_iterations=args.max_iterations,
        log_path=args.log,
        initial_task=args.task,
    )
    app.run()
