import queue

from cics.dispatcher import InputEvent
from cics.screen.driver import (
    Abended,
    AwaitingInput,
    Ended,
    PseudoConversationalDriver,
    Returned,
)
from cics.screen.payload import SendTextPayload
from cics.types import DispatchKind, DispatchResult
from tests.covers import NotLanguageFeature, covers


class _Region:
    """Fakes just enough of CicsRegion for PseudoConversationalDriver. Each
    result names its kind, the screen it sends, and whether the region is done
    after it: a RETURN that adopted a started task leaves the region not done."""

    def __init__(self, channel, results):
        self.channel, self.results, self.calls = channel, list(results), []
        self.done = False

    def _next(self, call):
        self.calls.append(call)
        kind, text, *done = self.results.pop(0)
        self.channel.put({"type": "text", "text": text})
        self.done = (
            done[0] if done else kind in (DispatchKind.RETURN, DispatchKind.ABEND)
        )
        return DispatchResult(
            kind=kind, abcode="ASRA" if kind is DispatchKind.ABEND else None
        )

    def start(self, transid):
        return self._next(("start", transid))

    def step(self, input_event=None):
        return self._next(("step", input_event))


def _driver(*results):
    channel: queue.Queue = queue.Queue()
    region = _Region(channel, results)
    return PseudoConversationalDriver(region, channel, frozenset({"CC00"})), region


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_xctl_continues_without_input_and_collects_every_screen():
    driver, region = _driver(
        (DispatchKind.XCTL, "a"), (DispatchKind.RETURN_TRANSID, "b")
    )
    assert driver.start("CC00") == AwaitingInput(
        (SendTextPayload("a"), SendTextPayload("b"))
    )
    assert region.calls == [("start", "CC00"), ("step", None)]


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_respond_passes_the_event_and_reports_endings():
    driver, region = _driver((DispatchKind.RETURN, "x"), (DispatchKind.ABEND, "y"))
    event = InputEvent(eibaid="\xf3")
    assert driver.respond(event) == Ended((SendTextPayload("x"),), Returned())
    assert driver.respond(event) == Ended((SendTextPayload("y"),), Abended("ASRA"))
    assert region.calls[0] == ("step", event)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_knows_configured_transids():
    driver, _ = _driver()
    assert (driver.knows("CC00"), driver.knows("ZZZZ")) == (True, False)


@covers(NotLanguageFeature.INFRASTRUCTURE)
def test_a_return_that_adopted_a_started_task_runs_it_before_the_terminal():
    """A task's own START for this terminal, then RETURN: the region adopts the
    started transaction and is not done, so the driver runs it with no terminal
    input, as it would after an XCTL, instead of reporting the task ended."""
    driver, region = _driver(
        (DispatchKind.RETURN, "a", False), (DispatchKind.RETURN_TRANSID, "b")
    )
    assert driver.start("CC00") == AwaitingInput(
        (SendTextPayload("a"), SendTextPayload("b"))
    )
    assert region.calls == [("start", "CC00"), ("step", None)]
