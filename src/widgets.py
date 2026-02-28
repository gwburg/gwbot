import models
from textual import events
from textual.binding import Binding
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widgets import Header, OptionList, Static, TextArea
from textual.widgets.option_list import Option
from memory.background import spawn_note_background
from rich.text import Text


class StatusBar(Static):
    """Displays model info, token count, cost, and context usage."""

    model_name: reactive[str] = reactive("")
    total_tokens: reactive[int] = reactive(0)
    cost_usd: reactive[float] = reactive(0.0)
    context_pct: reactive[float | None] = reactive(None)

    def render(self) -> Text:
        parts = [f"Model: {self.model_name}"]
        parts.append(f"Tokens: {self.total_tokens:,}")
        parts.append(f"Cost: ${self.cost_usd:.4f}")
        if self.context_pct is not None:
            pct = self.context_pct * 100
            bar_width = 20
            filled = int(pct / 100 * bar_width)
            if pct >= 80:
                color = "#f38ba8"
            elif pct >= 50:
                color = "#f9e2af"
            else:
                color = "#a6e3a1"
            bar = f"[{color}]{'█' * filled}{'░' * (bar_width - filled)}[/{color}] {pct:.0f}%"
            parts.append(f"Context: {bar}")
        return Text.from_markup(" | ".join(parts))


class ModelSelector(ModalScreen[str | None]):
    """Modal screen for selecting a model."""

    BINDINGS = [("escape", "dismiss_modal", "Cancel")]

    def compose(self):
        model_map = {k: v for k, v in vars(models).items() if not k.startswith("_")}
        options = [Option(f"{alias}  ({model_id})", id=alias) for alias, model_id in model_map.items()]
        yield OptionList(*options, id="model-list")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        self.dismiss(event.option.id)

    def action_dismiss_modal(self):
        self.dismiss(None)


class NoteInput(TextArea):
    """TextArea that submits on Enter instead of inserting a newline."""

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            text = self.text.strip()
            if text:
                event.prevent_default()
                self.post_message(self.Submitted(text))
                self.load_text("")


class NoteScreen(Screen):
    """Full-screen note editor for quickly saving memories."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def compose(self):
        yield Header()
        yield Static("[bold] New Note [/bold]", id="note-header")
        yield NoteInput(id="note-input", language=None, soft_wrap=True, show_line_numbers=False)
        yield Static("Enter: Save  |  Escape: Close", id="note-footer")

    def on_mount(self):
        self.query_one("#note-input").focus()

    def on_note_input_submitted(self, event: NoteInput.Submitted) -> None:
        spawn_note_background(event.text)
        self.notify("Note saved", timeout=2)

    def action_cancel(self):
        self.dismiss(None)
