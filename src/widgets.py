from models import MODEL_MAP
from textual import events
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.css.query import NoMatches
from textual.widgets import OptionList, Static, TextArea
from textual.widgets.option_list import Option
from memory import list_conversations
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
        options = [Option(f"{alias}  ({model_id})", id=alias) for alias, model_id in MODEL_MAP.items()]
        yield OptionList(*options, id="model-list")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        self.dismiss(event.option.id)

    def action_dismiss_modal(self):
        self.dismiss(None)


class ConversationSelector(ModalScreen[str | None]):
    """Modal screen for selecting a conversation to resume."""

    BINDINGS = [("escape", "dismiss_modal", "Cancel")]
    PAGE_SIZE = 10

    def __init__(self, context_length: int | None = None):
        super().__init__()
        self.context_length = context_length
        self._offset = 0

    def _make_option(self, conv: dict) -> Option:
        date_str = conv["date"].strftime("%b %-d %-I:%M%p").lower()
        preview = conv["preview"] or "(no user messages)"
        tokens = conv["estimated_tokens"]
        label = f"{date_str}  {preview}"

        if self.context_length and tokens > self.context_length:
            label += f"  [#6c7086](exceeds context window)[/#6c7086]"
            return Option(label, id=conv["id"], disabled=True)
        elif self.context_length and tokens > 0.75 * self.context_length:
            pct = int(tokens / self.context_length * 100)
            label += f"  [#f9e2af](~{pct}% of context)[/#f9e2af]"
        return Option(label, id=conv["id"])

    def compose(self):
        conversations = list_conversations(limit=self.PAGE_SIZE)
        self._offset = len(conversations)
        if not conversations:
            yield Static("No saved conversations.", id="conv-empty")
            return
        options = [self._make_option(c) for c in conversations]
        # Check if there are more conversations to load
        if len(conversations) == self.PAGE_SIZE:
            options.append(Option("[#6c7086]Load more...[/#6c7086]", id="__load_more__"))
        yield OptionList(*options, id="conv-list")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        if event.option.id == "__load_more__":
            self._load_more()
        else:
            self.dismiss(event.option.id)

    def _load_more(self) -> None:
        option_list = self.query_one("#conv-list", OptionList)
        # Remove the "Load more" option
        option_list.remove_option("__load_more__")
        # Fetch next page
        conversations = list_conversations(limit=self.PAGE_SIZE, offset=self._offset)
        self._offset += len(conversations)
        for conv in conversations:
            option_list.add_option(self._make_option(conv))
        # Add "Load more" again if we got a full page
        if len(conversations) == self.PAGE_SIZE:
            option_list.add_option(Option("[#6c7086]Load more...[/#6c7086]", id="__load_more__"))

    def action_dismiss_modal(self):
        self.dismiss(None)


class SubmittableTextArea(TextArea):
    """TextArea that submits on Enter and wraps long lines."""

    class Submitted(Message):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def on_key(self, event: events.Key) -> None:
        if event.key == "shift+enter":
            event.prevent_default()
            self.insert("\n")
        elif event.key == "enter":
            event.prevent_default()
            text = self.text.strip()
            if text:
                self.post_message(self.Submitted(text))
                self.load_text("")


class NoteInput(SubmittableTextArea):
    """SubmittableTextArea used in the notes pane."""


class NotesPane(Vertical):
    """Side panel note editor — shown/hidden on alt+n / Escape."""

    BINDINGS = [Binding("escape", "close_notes", "Close", show=False)]

    def compose(self):
        yield Static("[ notes ]", id="notes-header")
        yield NoteInput(id="notes-input", language=None, soft_wrap=True, show_line_numbers=False)
        yield Static("Enter: Save  |  Shift+Enter: Newline  |  Escape: Close", id="notes-footer")

    def on_submittable_text_area_submitted(self, event: SubmittableTextArea.Submitted) -> None:
        spawn_note_background(event.value)
        self.app.notify("Note saved", timeout=2)
        event.stop()

    def action_close_notes(self) -> None:
        self.display = False
        self.app.refresh_bindings()
        try:
            self.app.query_one("#user-input").focus()
        except NoMatches:
            pass
