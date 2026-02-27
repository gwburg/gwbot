import models
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option
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
