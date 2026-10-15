"""Driving a CICS region headlessly: one small facade (``CicsSession``) that
owns the queues/holders cicada's dispatcher needs, plus two turn-stepping
helpers.  Agnostic to any one program -- the main program and every LINK
target are compiled through the same session so they share one VsamEngine
and one program_cache, exactly as a real CICS region would.
"""
from __future__ import annotations

import queue
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from cics.coprocessor import build_cics_spec
from cics.runtime import install_cics_runtime
from cics.dispatcher import CicsRegion, InputEvent
from cics.interval import StartQueue
from interpreter.cobol.field_position import FieldPosition
from interpreter.cobol.layout_data import field_positions
from interpreter.run import main_declarations

from .compile import compile_link_targets, compile_main_program, make_parser
from .vsam import VsamFixture


@dataclass
class Turn:
    """One CICS turn's result: the DispatchResult plus every screen the
    program SEND MAPped during it (drained from the screen queue)."""

    result: Any
    screens: list[dict]

    def screen(self, map_name: str) -> dict | None:
        """Last SEND MAP matching ``map_name`` this turn, or None."""
        matches = [s for s in self.screens if s.get("map") == map_name]
        return matches[-1] if matches else None

    def field(self, map_name: str, field_name: str, default: str = "") -> str:
        s = self.screen(map_name)
        return (s or {}).get("fields", {}).get(field_name, default)


@dataclass
class CicsSession:
    """Owns one CICS region's compile-time and run-time state: the parser,
    the VSAM fixture, the program_cache, and (once ``region()`` is called)
    the CicsRegion itself.

    Typical use::

        session = CicsSession(copybook_dirs, vsam_dir="/tmp/foo-vsam")
        session.vsam.register("USRSEC", record_length=80, key_offset=0, key_length=8)
        session.compile_main(source_bytes, "COSGN00C")
        session.compile_link_targets(["COMEN01C"], stub_dir=stubs_dir)
        session.region({"CC00": "COSGN00C"})
        turn = session.start_turn("CC00", commarea=..., eibaid=ENTER, fields={...})
    """

    copybook_dirs: Sequence[Path]
    vsam_dir: Path
    tolerant: bool = True
    parser: Any = None

    vsam: VsamFixture = field(init=False)
    program_cache: dict = field(init=False, default_factory=dict)
    transid_to_program: dict[str, str] = field(init=False, default_factory=dict)
    """Shared, mutable cell: ``region()`` ``.update()``s this in place rather
    than replacing it, because the ``EXEC CICS START`` builtin inside every
    already-compiled program captured a REFERENCE to this exact dict object
    when the CICS runtime was installed."""
    screen_q: "queue.Queue" = field(init=False)
    input_q: "queue.Queue" = field(init=False)
    context_holder: list = field(init=False)
    result_holder: list = field(init=False)
    start_queue: Any = field(init=False)
    spec: Any = field(init=False)
    main_name: str | None = field(init=False, default=None)
    _region: CicsRegion | None = field(init=False, default=None)
    last_vm: Any = field(init=False, default=None)
    """The final VMState from the most recent start_turn/step_turn call --
    None until the first turn runs."""

    def __post_init__(self) -> None:
        if self.parser is None:
            self.parser = make_parser(self.copybook_dirs)
        self.vsam = VsamFixture.create(Path(self.vsam_dir))
        self.screen_q = queue.Queue()
        self.input_q = queue.Queue()
        self.context_holder = [None]
        self.result_holder = [None]
        self.start_queue = StartQueue()
        install_cics_runtime(
            self.context_holder,
            start_queue=self.start_queue,
            result_holder=self.result_holder,
            program_cache=self.program_cache,
            vsam_engine=self.vsam.engine,
            screen_queue=self.screen_q,
            input_queue=self.input_q,
            transid_to_program=self.transid_to_program,
        )
        self.spec = build_cics_spec()

    # ---- compile-time ----------------------------------------------------

    def compile_main(self, source: bytes, name: str) -> Any:
        """Compile the program under test. Returns its LinkedProgram."""
        linked = compile_main_program(self.parser, self.spec, self.program_cache, source, name, tolerant=self.tolerant)
        self.main_name = name
        return linked

    def compile_link_targets(self, names: Sequence[str], *, stub_dir: Path | None = None) -> None:
        compile_link_targets(self.parser, self.spec, self.program_cache, names, stub_dir=stub_dir, tolerant=self.tolerant)

    @property
    def positions(self) -> Mapping[str, FieldPosition]:
        """The main program's field-name -> FieldPosition table, needed by
        ``commarea.build_commarea``."""
        if self.main_name is None:
            raise RuntimeError("compile_main() hasn't been called yet")
        return field_positions(main_declarations(self.program_cache[self.main_name]))

    def build_record(self, copy_member: str, record_name: str, overrides: dict[str, str], expected_length: int | None = None) -> bytes:
        """See ``vsam.build_record`` -- re-exposed here so callers that
        already have a ``CicsSession`` don't need a second import."""
        from .vsam import build_record

        return build_record(self.parser, self.copybook_dirs, copy_member, record_name, overrides, expected_length)

    # ---- run-time ----------------------------------------------------------

    def region(self, transid_to_program: dict[str, str], *, max_steps: int = 2_000_000, min_commarea_len: int = 0) -> CicsRegion:
        """Build (or rebuild, for a fresh task) the CicsRegion. Must be
        called again before ``start_turn`` for each independent test case
        that needs a clean task/transaction state -- CicsRegion itself is
        NOT safely reusable across unrelated START calls.

        Updates ``self.transid_to_program`` IN PLACE (never replaces it --
        see its field docstring) so every already-compiled program's own
        ``EXEC CICS START`` validation sees these entries too."""
        self.transid_to_program.update(transid_to_program)
        self._region = CicsRegion(
            self.program_cache,
            self.transid_to_program,
            self.screen_q,
            self.input_q,
            context_holder=self.context_holder,
            result_holder=self.result_holder,
            start_queue=self.start_queue,
            max_steps=max_steps,
            min_commarea_len=min_commarea_len,
        )
        return self._region

    @contextmanager
    def _capturing_vm(self) -> "Iterator[None]":
        """Monkeypatch ``cics.dispatcher.run_cics`` for the duration of one
        turn to additionally stash the final VMState into ``self.last_vm``.
        """
        import cics.dispatcher as _disp
        from cics.types import DispatchKind, DispatchResult
        from cics.vm_init import make_cics_initial_vm, make_entry_point
        from interpreter.run import run_linked

        original = _disp.run_cics
        session = self

        def _wrapped(program, context, screen_queue, input_queue, *, context_holder, result_holder, max_steps=50_000):
            _disp.hold(context_holder, context)
            _disp.hold(result_holder, None)
            vm = run_linked(
                program,
                make_entry_point(program),
                max_steps=max_steps,
                initial_vm=make_cics_initial_vm(context, context.commarea),
            )
            session.last_vm = vm
            return _disp.held_or(result_holder, DispatchResult(kind=DispatchKind.RETURN))

        _disp.run_cics = _wrapped
        try:
            yield
        finally:
            _disp.run_cics = original

    def _drain_screens(self) -> list[dict]:
        out = []
        while True:
            try:
                out.append(self.screen_q.get_nowait())
            except queue.Empty:
                break
        return out

    def start_turn(self, transid: str, *, commarea: bytes, eibaid: str, fields: dict[str, str]) -> Turn:
        """Begin a fresh task (EIBCALEN = len(commarea), so a non-empty
        commarea takes a program's ``IF EIBCALEN > 0`` continuation branch
        immediately).

        Updates ``self.last_vm`` -- read program fields afterward with
        ``state.read_vm_field(session.last_vm, "SOME-FIELD")``."""
        if self._region is None:
            raise RuntimeError("call region(...) before start_turn")
        with self._capturing_vm():
            result = self._region.start(transid, commarea=commarea, input_event=InputEvent(eibaid=eibaid, fields=fields))
        return Turn(result=result, screens=self._drain_screens())

    def step_turn(self, *, eibaid: str | None = None, fields: dict[str, str] | None = None) -> Turn:
        """Continue the current pseudo-conversational task with the next
        terminal input (or no input, for an XCTL'd-in redisplay turn).
        Updates ``self.last_vm``."""
        if self._region is None:
            raise RuntimeError("call region(...) before step_turn")
        kwargs = {}
        if eibaid is not None or fields is not None:
            kwargs["input_event"] = InputEvent(eibaid=eibaid or "", fields=fields or {})
        with self._capturing_vm():
            result = self._region.step(**kwargs)
        return Turn(result=result, screens=self._drain_screens())
