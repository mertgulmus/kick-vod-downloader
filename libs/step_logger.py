from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional, Dict

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text


@dataclass
class Step:
    title: str
    status: str = "pending"  # pending | running | done | error | skipped
    detail: Optional[str] = None


class StepLogger:
    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()
        self.steps: Dict[int, Step] = {}
        self._next_id: int = 1
        self._live: Optional[Live] = None

    def _render(self):
        table = Table.grid(padding=(0, 1))
        table.expand = True
        for idx in sorted(self.steps.keys()):
            step = self.steps[idx]
            if step.status == "running":
                prefix = Spinner("dots", text="")
                title = Text(step.title, style="bold cyan")
            elif step.status == "done":
                prefix = Text("✔", style="bold green")
                title = Text(step.title, style="green")
            elif step.status == "error":
                prefix = Text("✖", style="bold red")
                title = Text(step.title, style="red")
            elif step.status == "skipped":
                prefix = Text("↷", style="yellow")
                title = Text(step.title, style="yellow")
            else:
                prefix = Text("•", style="dim")
                title = Text(step.title, style="dim")

            row = Table.grid()
            row.add_column(width=2)
            row.add_column(ratio=1)
            row.add_row(prefix, title)
            if step.detail:
                detail_text = Text(step.detail, style="dim")
                row.add_row(Text(""), detail_text)
            table.add_row(row)
        return Panel(table, title="Progress", border_style="cyan")

    def _ensure_live(self):
        if self._live is None:
            self._live = Live(self._render(), console=self.console, refresh_per_second=10)
            self._live.start()
        else:
            self._live.update(self._render())

    def start_step(self, title: str, detail: Optional[str] = None) -> int:
        step_id = self._next_id
        self._next_id += 1
        self.steps[step_id] = Step(title=title, status="running", detail=detail)
        self._ensure_live()
        self._live.update(self._render())
        return step_id

    def set_detail(self, step_id: int, detail: Optional[str]):
        step = self.steps.get(step_id)
        if step:
            step.detail = detail
            if self._live:
                self._live.update(self._render())

    def complete_step(self, step_id: int, detail: Optional[str] = None):
        step = self.steps.get(step_id)
        if step:
            step.status = "done"
            if detail is not None:
                step.detail = detail
            if self._live:
                self._live.update(self._render())

    def error_step(self, step_id: int, detail: Optional[str] = None):
        step = self.steps.get(step_id)
        if step:
            step.status = "error"
            if detail is not None:
                step.detail = detail
            if self._live:
                self._live.update(self._render())

    def skip_step(self, step_id: int, detail: Optional[str] = None):
        step = self.steps.get(step_id)
        if step:
            step.status = "skipped"
            if detail is not None:
                step.detail = detail
            if self._live:
                self._live.update(self._render())

    def stop(self):
        if self._live:
            self._live.stop()
            self._live = None

    @contextmanager
    def step(self, title: str, detail: Optional[str] = None):
        sid = self.start_step(title, detail)
        try:
            yield lambda d=None: self.set_detail(sid, d)
            self.complete_step(sid)
        except Exception as e:
            self.error_step(sid, detail=str(e))
            raise
