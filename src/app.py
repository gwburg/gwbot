import argparse
import logging
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

from rich.markdown import Markdown
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import Footer, Header, Static
from tools import categories as tool_categories, tools

from models import MODEL_MAP
from memory import load_conversation, new_conversation_id
from memory.background import process_note, spawn_background
from prompts import SYSTEM_PROMPTS, build_system_prompt
from widgets import ConversationSelector, ModelSelector, NotesPane, StatusBar, SubmittableTextArea
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
    fetch_credits,
    fetch_model_info,
)


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
        Binding("ctrl+c", "ctrl_c", "Quit", show=False, priority=True),
        Binding("alt+m", "switch_model", "Switch Model"),
        Binding("alt+n", "open_note", "Note"),
        Binding("alt+h", "focus_chat", "Chat", priority=True),
        Binding("alt+l", "focus_notes", "Notes", priority=True),
    ]

    def __init__(self, model: str, system_prompt: str, max_iterations: int = 50, initial_note: bool = False, initial_resume: bool = False):
        super().__init__()
        self.model_alias = model
        self.model_id = MODEL_MAP[model]
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.initial_note = initial_note
        self.initial_resume = initial_resume

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
        self._user_sent_message = False  # whether the user has typed a message
        self._ctrl_c_pressed = False  # tracks double ctrl+c for quit
        self._is_exiting = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-split"):
            yield VerticalScroll(id="chat-scroll")
            yield NotesPane(id="notes-pane")
        yield StatusBar(id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = self.model_id
        status = self.query_one(StatusBar)
        status.model_name = self.model_id
        self._stream_timer = self.set_interval(0.05, self._flush_stream, pause=True)
        self._spinner_timer = self.set_interval(0.08, self._tick_spinner, pause=True)
        self._note_spinner_frame = 0
        self._note_spinner_timer = self.set_interval(0.08, self._tick_note_spinner, pause=True)
        self._note_queue: list[str] = []
        self._note_processing = False

        # Fire-and-forget: run scheduler to catch overdue jobs
        self._spawn_scheduler()
        self.run_worker(self._fetch_credits(), exclusive=False, group="credits")

        if self.initial_resume:
            self.run_worker(self._show_resume_selector(), exclusive=True)
        elif self.initial_note:
            self.action_open_note()
        else:
            self._mount_input()

    async def _show_resume_selector(self) -> None:
        """Fetch model info and show the conversation selector."""
        import asyncio
        model_info = await asyncio.to_thread(fetch_model_info, self.model_id)
        context_length = model_info.get("context_length")

        def on_resume(conversation_id: str | None) -> None:
            if conversation_id:
                self._resume_conversation(conversation_id)
            else:
                self._mount_input()

        self.push_screen(ConversationSelector(context_length), callback=on_resume)

    def _resume_conversation(self, conversation_id: str) -> None:
        """Load a previous conversation and render a recap in the chat."""
        try:
            prior_messages = load_conversation(conversation_id)
        except FileNotFoundError:
            self._append_widget(f"[{C_WARN}]\\[error][/] Conversation not found")
            self._mount_input()
            return

        self.conversation_id = conversation_id
        self._user_sent_message = True

        # Inject prior messages after the system prompt
        self.messages.extend(prior_messages)

        # Render a visual recap
        self._append_widget(
            f"[{C_DIM}]── Resumed conversation {conversation_id} ({len(prior_messages)} messages) ──[/]",
            classes="message",
        )
        for msg in prior_messages:
            role = msg.get("role")
            content = msg.get("content")
            if role == "user" and content:
                self._append_widget(f"[{C_USER}]\\[user][/] {content}", classes="message user-msg")
            elif role == "assistant" and content:
                self._append_widget(f"[{C_AGENT}]\\[agent][/]", classes="agent-label")
                self._append_widget(Markdown(content), classes="message agent-content")

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

    def _tick_note_spinner(self) -> None:
        """Advance the notes footer spinner by one frame."""
        self._note_spinner_frame = (self._note_spinner_frame + 1) % len(SPINNER)
        self._set_notes_footer(f"{SPINNER[self._note_spinner_frame]} Committing to memory…")

    def _set_notes_footer(self, text: str) -> None:
        try:
            footer = self.query_one("#notes-footer", Static)
            footer.update(f"[{C_DIM}]{text}[/]")
        except NoMatches:
            pass

    def on_notes_pane_note_submitted(self, event: NotesPane.NoteSubmitted) -> None:
        self._note_queue.append(event.text)
        if not self._note_processing:
            self._note_processing = True
            self._note_spinner_frame = 0
            self._note_spinner_timer.resume()
            self.run_worker(self._drain_note_queue(), exclusive=False)

    async def _drain_note_queue(self) -> None:
        errors = 0
        while self._note_queue:
            text = self._note_queue.pop(0)
            try:
                await process_note(self.client, text)
            except Exception:
                errors += 1
        self._note_processing = False
        self._note_spinner_timer.pause()
        self._set_notes_footer("✗ Failed to save note" if errors else "✓ Note remembered")
        self.set_timer(2.5, lambda: self._set_notes_footer(NotesPane.FOOTER_DEFAULT))

    def _mount_input(self) -> None:
        """Mount a new inline [user] prompt with Input inside the chat scroll."""
        scroll = self.query_one("#chat-scroll", VerticalScroll)
        row = Horizontal(id="input-row")
        label = Static(f"[{C_USER}]\\[user][/] ", id="input-label")
        inp = SubmittableTextArea("", id="user-input", language=None, soft_wrap=True, show_line_numbers=False)
        scroll.mount(row)
        row.mount(label)
        row.mount(inp)
        row.scroll_visible(animate=False)
        inp.focus()

    def on_submittable_text_area_submitted(self, event: SubmittableTextArea.Submitted) -> None:
        text = event.value
        if not text:
            return
        row = self.query_one("#input-row", Horizontal)
        row.remove()
        self._submit_message(text)

    async def _fetch_credits(self) -> None:
        import asyncio
        credits = await asyncio.to_thread(fetch_credits)
        if credits is not None:
            self.query_one(StatusBar).credits_remaining = credits

    def _spawn_scheduler(self) -> None:
        """Spawn the scheduler as a detached subprocess to catch overdue jobs."""
        import subprocess as _sp
        try:
            _sp.Popen(
                [sys.executable, "-m", "scheduler"],
                cwd=os.path.join(os.path.dirname(__file__)),
                start_new_session=True,
                stdin=_sp.DEVNULL,
                stdout=_sp.DEVNULL,
                stderr=_sp.DEVNULL,
            )
        except Exception:
            logging.getLogger(__name__).debug("scheduler spawn failed", exc_info=True)

    def _submit_message(self, text: str) -> None:
        if self._is_running:
            return

        self._user_sent_message = True
        self._append_widget(f"[{C_USER}]\\[user][/] {text}", classes="message user-msg")

        ts = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        self.messages.append({"role": "user", "content": f"{ts} {text}"})
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
                on_event=lambda e: self.post_message(AgentMessage(e)),
            )
        except Exception as e:
            self._hide_spinner()
            self._append_widget(f"[{C_WARN}]\\[error][/] {e}")
        finally:
            self._is_running = False
            if not self._is_exiting:
                self._mount_input()

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
                self.run_worker(self._fetch_credits(), exclusive=False, group="credits")

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

    async def action_quit(self) -> None:
        """Spawn background memory process, then quit immediately."""
        self._is_exiting = True
        if self._user_sent_message:
            try:
                spawn_background(self.conversation_id, self.messages)
            except Exception:
                pass  # Memory is best-effort — never block exit
        self.exit()

    def action_ctrl_c(self) -> None:
        """Quit on double ctrl+c; warn on first press."""
        if self._ctrl_c_pressed:
            self.run_worker(self.action_quit())
        else:
            self._ctrl_c_pressed = True
            self.notify("Press ctrl+c again to quit", timeout=2)
            self.set_timer(2, self._reset_ctrl_c)

    def _reset_ctrl_c(self) -> None:
        self._ctrl_c_pressed = False

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        if action in ("focus_chat", "focus_notes"):
            try:
                return self.query_one("#notes-pane", NotesPane).display
            except NoMatches:
                return None
        return True

    def action_open_note(self) -> None:
        pane = self.query_one("#notes-pane", NotesPane)
        if pane.display:
            pane.action_close_notes()
        else:
            pane.display = True
            self.refresh_bindings()
            pane.query_one("#notes-input").focus()

    def action_focus_chat(self) -> None:
        try:
            self.query_one("#user-input").focus()
        except NoMatches:
            pass

    def action_focus_notes(self) -> None:
        pane = self.query_one("#notes-pane", NotesPane)
        if pane.display:
            pane.query_one("#notes-input").focus()

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


def main():
    parser = argparse.ArgumentParser(description="Run the agent TUI")
    parser.add_argument("--model", default="SONNET", choices=MODEL_MAP, metavar="MODEL", help=f"Model alias. Choices: {', '.join(MODEL_MAP)}")
    parser.add_argument("--persona", default="minimal", choices=SYSTEM_PROMPTS, help=f"System prompt persona. Choices: {', '.join(SYSTEM_PROMPTS)}")
    parser.add_argument("--max-iterations", type=int, default=50)
    parser.add_argument("--note", action="store_true", help="Open note editor on startup")
    parser.add_argument("--resume", action="store_true", help="Resume a previous conversation")
    parser.add_argument("--init", action="store_true", help="Run interactive setup wizard")
    args = parser.parse_args()

    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")

    if args.init or not os.path.exists(env_path) or not os.environ.get("OPENROUTER_API_KEY"):
        from init import run_init
        run_init()
        load_dotenv(override=True)

    system_prompt = build_system_prompt(args.persona, tool_categories)

    app = AgentApp(
        model=args.model,
        system_prompt=system_prompt,
        max_iterations=args.max_iterations,
        initial_note=args.note,
        initial_resume=args.resume,
    )
    app.run()


if __name__ == "__main__":
    main()
