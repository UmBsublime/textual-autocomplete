from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Iterable, Callable

from rich.console import Console, ConsoleOptions, RenderableType
from rich.measure import Measurement
from rich.text import Text
from textual import events
from textual.css.styles import RenderStyles
from textual.reactive import watch
from textual.widget import Widget
from textual.widgets import Input


class AutoCompleteError(Exception):
    pass


class DropdownRender:
    def __init__(
        self,
        filter: str,
        matches: Iterable[Candidate],
        highlight_index: int,
        component_styles: dict[str, RenderStyles],
    ) -> None:
        self.filter = filter
        self.matches = matches
        self.highlight_index = highlight_index

    def __rich_console__(self, console: Console, options: ConsoleOptions):
        matches = []
        for match in self.matches:
            candidate_text = Text(match.main)
            candidate_text.highlight_words([self.filter], style="on yellow")
            matches.append(candidate_text)
        return Text("\n").join(matches).append("\n")

    def __rich_measure__(self, console: "Console", options: "ConsoleOptions") -> Measurement:
        get = partial(Measurement.get, console, options)
        maximum = 0
        for match in self.matches:
            maximum = max(get(match.left_meta)[1] + get(match.main)[1] + get(match.right_meta)[1], maximum)
        return Measurement(10, maximum)


@dataclass
class Candidate:
    """A single option appearing in the autocompletion dropdown. Each option has up to 3 columns.
    Note that this is not a widget, it's simply a data structure for describing dropdown items.

    Args:
        left: The left column will often contain an icon/symbol, the main (middle)
            column contains the text that represents this option.
        main: The main text representing this option - this will be highlighted by default.
            In an IDE, the `main` (middle) column might contain the name of a function or method.
        right: The text appearing in the right column of the dropdown.
            The right column often contains some metadata relating to this option.
        highlight_ranges: Custom ranges to highlight. By default, textual-autocomplete highlights
            substrings: if the thing you've typed into the Input is a substring of the candidates
            `main` attribute, then that substring will be highlighted. If you supply your own
            implementation of get_results which uses a more complex process to decide what to
            display in the dropdown, then you can customise the highlighting of the returned
            candidates by supplying index ranges to highlight.

    """
    main: str = ""
    left_meta: str = ""
    right_meta: str = ""
    highlight_ranges: Iterable[tuple[int, int]] = ()


class AutoComplete(Widget):
    """An autocompletion dropdown widget. This widget gets linked to an Input widget, and is automatically
    updated based on the state of that Input."""

    DEFAULT_CSS = """\
AutoComplete {
    layer: textual-autocomplete;
    display: none;
    margin-top: 3;
    background: $panel;
    width: auto;
    height: auto;
}
    """

    def __init__(
        self,
        linked_input: Input | str,
        get_results: Callable[[str, int], list[Candidate]],
        id: str | None = None,
        classes: str | None = None,
    ):
        """Construct an Autocomplete. Autocomplete only works if your Screen has a dedicated layer
        called `textual-autocomplete`.

        Args:
            linked_input: A reference to the Input Widget to add autocomplete to, or a selector/query string
                identifying the Input Widget that should power this autocomplete.
            get_results: Function to call to retrieve the list of completion results for the current input value.
                Function takes the current input value and cursor position as arguments, and returns a list of
                `AutoCompleteOption` which will be displayed as a dropdown list.
            id: The ID of the widget, allowing you to directly refer to it using CSS and queries.
            classes: The classes of this widget, a space separated string.
        """

        super().__init__(
            id=id,
            classes=classes,
        )
        self._get_results = get_results
        self._linked_input = linked_input
        self._matches: list[Candidate] = []
        self._input_widget: Input | None = None

    def on_mount(self, event: events.Mount) -> None:
        # Ensure we have a reference to the Input widget we're subscribing to
        if isinstance(self._linked_input, str):
            self._input_widget = self.app.query_one(self._linked_input, Input)
        else:
            self._input_widget = self._linked_input

        # A quick sanity check - make sure we have the appropriate layer available
        # TODO - think about whether it makes sense to enforce this.
        if "textual-autocomplete" not in self.screen.layers:
            raise AutoCompleteError(
                "Screen must have a layer called `textual-autocomplete`."
            )

        # Configure the watch methods - we want to subscribe to a couple of the reactives inside the Input
        # so that we can react accordingly.
        # TODO: Error cases - Handle case where reference to input widget no longer exists for example
        watch(self._input_widget, attribute_name="cursor_position", callback=self._input_cursor_position_changed)
        watch(self._input_widget, attribute_name="value", callback=self._input_value_changed)

        self._sync_state(self._input_widget.value, self._input_widget.cursor_position)

    def render(self) -> RenderableType:
        assert self._input_widget is not None, "input_widget set in on_mount"
        return DropdownRender(
            filter=self._input_widget.value,
            matches=self._matches,
            highlight_index=0,
            component_styles={},
        )

    def _input_cursor_position_changed(self, cursor_position: int) -> None:
        assert self._input_widget is not None, "input_widget set in on_mount"
        self._sync_state(self._input_widget.value, cursor_position)

    def _input_value_changed(self, value: str) -> None:
        assert self._input_widget is not None, "input_widget set in on_mount"
        self._sync_state(value, self._input_widget.cursor_position)

    def _sync_state(self, value: str, cursor_position: int) -> None:
        self._matches = self._get_results(value, cursor_position)
        self.display = len(self._matches) > 0 and value != ""
        self.refresh()
