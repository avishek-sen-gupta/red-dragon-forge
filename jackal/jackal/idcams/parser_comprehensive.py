"""Entry point for the comprehensive IDCAMS ("AMS") grammar.

Distinct from jackal.idcams.parser.parse_idcams -- that module parses the
older, minimal IDCAMS grammar (jackal/jackal/idcams/grammar.lark) and is
untouched by this work. This module parses the new, comprehensive grammar
at jackal/jackal/idcams/grammar/ams.lark, built up incrementally across
Tasks 2-11 of the IDCAMS comprehensive-grammar plan.

Return type note for future tasks: `AmsCommand` (the full union across all
14 IDCAMS commands) is not defined until Task 11. Until then, parse_ams
returns `tuple[object, ...]` -- in practice a tuple of whichever typed
dataclasses the grammar built so far (today: DefineCluster, DefineAlternateIndex).
Task 11 should tighten this to `tuple[AmsCommand, ...]` once the union
exists, and extend `_Build` with each new command's rule callbacks along
the way -- this module is meant to be extended in place, not recreated.
"""

from __future__ import annotations

from importlib.resources import files

from lark import Lark, Token, Transformer
from lark.exceptions import VisitError

from jackal.idcams.ast_define_alternateindex import (
    AixDataComponent,
    AixIndexComponent,
    DefineAlternateIndex,
)
from jackal.idcams.ast_define_cluster import (
    DatabaseSpec,
    DataComponent,
    DefineCluster,
    IndexComponent,
)
from jackal.idcams.ast_define_gdg import DefineGenerationDataGroup
from jackal.idcams.ast_define_nonvsam import DefineNonvsam
from jackal.idcams.ast_define_path import DefinePath
from jackal.idcams.ast_values import Name, Retention, SpaceAllocation
from jackal.idcams.preprocess import join_plus_continuations

_GRAMMAR_PATH = str(files("jackal.idcams") / "grammar" / "ams.lark")


def _int(tok: Token) -> int:
    return int(tok)


def _name(tok: Token) -> Name:
    return Name.parse(str(tok))


def _dequote(tok: Token) -> str:
    """Strip surrounding quotes and de-escape '' -> ' from a QUOTED_STRING token."""
    return str(tok)[1:-1].replace("''", "'")


class _Build(Transformer):
    # -- shared value alternation (Task 1 placeholder rule, still used
    # standalone by lexical tests) -----------------------------------
    def value(self, c: list) -> object:
        return c[0]

    # -- space allocation (mutually exclusive CYLINDERS|KILOBYTES|... ) -
    def _space(self, unit: str, c: list) -> SpaceAllocation:
        primary = _int(c[0])
        secondary = _int(c[1]) if len(c) > 1 else None
        return SpaceAllocation(unit=unit, primary=primary, secondary=secondary)

    def cylinders_alloc(self, c: list) -> SpaceAllocation:
        return self._space("CYLINDERS", c)

    def kilobytes_alloc(self, c: list) -> SpaceAllocation:
        return self._space("KILOBYTES", c)

    def megabytes_alloc(self, c: list) -> SpaceAllocation:
        return self._space("MEGABYTES", c)

    def records_alloc(self, c: list) -> SpaceAllocation:
        return self._space("RECORDS", c)

    def tracks_alloc(self, c: list) -> SpaceAllocation:
        return self._space("TRACKS", c)

    def space_choice(self, c: list) -> tuple:
        return ("space", c[0])

    # -- simple keyword(value) params, one (key, value) tuple each -----
    def name_param(self, c: list) -> tuple:
        return ("name", _name(c[0]))

    def volumes_param(self, c: list) -> tuple:
        return ("volumes", tuple(str(t) for t in c))

    def account_param(self, c: list) -> tuple:
        return ("account", str(c[0]))

    def bufferspace_param(self, c: list) -> tuple:
        return ("buffer_space", _int(c[0]))

    def bwo_param(self, c: list) -> tuple:
        return ("bwo", str(c[0]))

    def catalog_param(self, c: list) -> tuple:
        return ("catalog", str(c[0]))

    def cisz_param(self, c: list) -> tuple:
        return ("control_interval_size", _int(c[0]))

    def database_format_param(self, c: list) -> tuple:
        return ("database_format", str(c[0]))

    def keyname_param(self, c: list) -> tuple:
        return ("database_key_name", (str(c[0]), False))

    def keynameu_param(self, c: list) -> tuple:
        return ("database_key_name", (str(c[0]), True))

    def dataclass_param(self, c: list) -> tuple:
        return ("data_class", str(c[0]))

    def eattr_param(self, c: list) -> tuple:
        return ("eattr", str(c[0]))

    def erase_flag(self, c: list) -> tuple:
        return ("erase", True)

    def noerase_flag(self, c: list) -> tuple:
        return ("erase", False)

    def exceptionexit_param(self, c: list) -> tuple:
        return ("exception_exit", str(c[0]))

    def file_param(self, c: list) -> tuple:
        return ("file", str(c[0]))

    def freespace_param(self, c: list) -> tuple:
        return ("freespace", (_int(c[0]), _int(c[1])))

    def frlog_param(self, c: list) -> tuple:
        return ("frlog", str(c[0]))

    def organization_param(self, c: list) -> tuple:
        return ("organization", str(c[0]))

    def keylabel_param(self, c: list) -> tuple:
        return ("key_label", str(c[0]))

    def keys_param(self, c: list) -> tuple:
        return ("keys", (_int(c[0]), _int(c[1])))

    def log_param(self, c: list) -> tuple:
        return ("log", str(c[0]))

    def logreplicate_flag(self, c: list) -> tuple:
        return ("log_replicate", True)

    def nologreplicate_flag(self, c: list) -> tuple:
        return ("log_replicate", False)

    def logstreamid_param(self, c: list) -> tuple:
        return ("log_stream_id", str(c[0]))

    def managementclass_param(self, c: list) -> tuple:
        return ("management_class", str(c[0]))

    def model_param(self, c: list) -> tuple:
        entry = _name(c[0])
        catalog = _name(c[1]) if len(c) > 1 else None
        return ("model", (entry, catalog))

    def owner_param(self, c: list) -> tuple:
        return ("owner", str(c[0]))

    def recatalog_flag(self, c: list) -> tuple:
        return ("recatalog", True)

    def norecatalog_flag(self, c: list) -> tuple:
        return ("recatalog", False)

    def recordsize_param(self, c: list) -> tuple:
        return ("record_size", (_int(c[0]), _int(c[1])))

    def reuse_flag(self, c: list) -> tuple:
        return ("reuse", True)

    def noreuse_flag(self, c: list) -> tuple:
        return ("reuse", False)

    def rlsquiesce_flag(self, c: list) -> tuple:
        return ("rls_mode", "QUIESCE")

    def rlsenable_flag(self, c: list) -> tuple:
        return ("rls_mode", "ENABLE")

    def shareoptions_param(self, c: list) -> tuple:
        first = _int(c[0])
        second = _int(c[1]) if len(c) > 1 else None
        return ("share_options", (first, second))

    def spanned_flag(self, c: list) -> tuple:
        return ("spanned", True)

    def nonspanned_flag(self, c: list) -> tuple:
        return ("spanned", False)

    def speed_flag(self, c: list) -> tuple:
        return ("speed", True)

    def recovery_flag(self, c: list) -> tuple:
        return ("speed", False)

    def storageclass_param(self, c: list) -> tuple:
        return ("storage_class", str(c[0]))

    def to_retention(self, c: list) -> tuple:
        return ("retention", Retention(to_date=str(c[0])))

    def for_retention(self, c: list) -> tuple:
        return ("retention", Retention(for_days=_int(c[0])))

    def writecheck_flag(self, c: list) -> tuple:
        return ("write_check", True)

    def nowritecheck_flag(self, c: list) -> tuple:
        return ("write_check", False)

    def obsolete_ignored(self, c: list) -> None:
        return None

    # -- DEFINE ALTERNATEINDEX-specific params --------------------------
    def relate_param(self, c: list) -> tuple:
        return ("relate", _name(c[0]))

    def altkey_entry(self, c: list) -> tuple:
        return (str(c[0]), str(c[1]))

    def altkeys_param(self, c: list) -> tuple:
        return ("alt_keys", tuple(c))

    def altkeysu_param(self, c: list) -> tuple:
        return ("alt_keys_utf8", tuple(c))

    def altkey_choice(self, c: list) -> tuple:
        return c[0]

    def attempts_param(self, c: list) -> tuple:
        return ("attempts", _int(c[0]))

    def authorization_param(self, c: list) -> tuple:
        module = str(c[0])
        parm = _dequote(c[1]) if len(c) > 1 else None
        return ("authorization", (module, parm))

    def code_param(self, c: list) -> tuple:
        return ("code", str(c[0]))

    def imbed_flag(self, c: list) -> tuple:
        return ("imbed", True)

    def noimbed_flag(self, c: list) -> tuple:
        return ("imbed", False)

    def keyranges_ignored(self, c: list) -> tuple:
        return ("key_ranges_ignored", True)

    def order_ignored_flag(self, c: list) -> tuple:
        return ("order_ignored", True)

    def replicate_ignored_flag(self, c: list) -> tuple:
        return ("replicate_ignored", True)

    def uniquekey_flag(self, c: list) -> tuple:
        return ("unique_key", True)

    def nonuniquekey_flag(self, c: list) -> tuple:
        return ("unique_key", False)

    def upgrade_flag(self, c: list) -> tuple:
        return ("upgrade", True)

    def noupgrade_flag(self, c: list) -> tuple:
        return ("upgrade", False)

    # -- DEFINE GENERATIONDATAGROUP-specific params ---------------------
    def limit_param(self, c: list) -> tuple:
        return ("limit", _int(c[0]))

    def empty_flag(self, c: list) -> tuple:
        return ("empty", True)

    def noempty_flag(self, c: list) -> tuple:
        return ("empty", False)

    def extended_flag(self, c: list) -> tuple:
        return ("extended", True)

    def noextended_flag(self, c: list) -> tuple:
        return ("extended", False)

    def gdgorder_param(self, c: list) -> tuple:
        return ("order", str(c[0]))

    def purge_flag(self, c: list) -> tuple:
        return ("purge", True)

    def nopurge_flag(self, c: list) -> tuple:
        return ("purge", False)

    def scratch_flag(self, c: list) -> tuple:
        return ("scratch", True)

    def noscratch_flag(self, c: list) -> tuple:
        return ("scratch", False)

    # -- DEFINE NONVSAM-specific params ----------------------------------
    def devicetypes_param(self, c: list) -> tuple:
        return ("device_types", tuple(str(t) for t in c))

    def nonvsam_volume_item(self, c: list) -> object:
        return c[0]

    def nonvsam_volumes_param(self, c: list) -> tuple:
        return ("volumes", tuple(str(t) for t in c))

    def collection_flag(self, c: list) -> tuple:
        return ("collection", True)

    def filesequencenumbers_param(self, c: list) -> tuple:
        return ("file_sequence_numbers", tuple(_int(t) for t in c))

    # -- DEFINE PATH-specific params --------------------------------------
    def pathentry_param(self, c: list) -> tuple:
        return ("path_entry", _name(c[0]))

    def update_flag(self, c: list) -> tuple:
        return ("update", True)

    def noupdate_flag(self, c: list) -> tuple:
        return ("update", False)

    # -- param dispatch (single-alternative pass-through wrappers) -----
    def cluster_param(self, c: list) -> tuple | None:
        return c[0]

    def data_param(self, c: list) -> tuple | None:
        return c[0]

    def index_param(self, c: list) -> tuple | None:
        return c[0]

    def aix_param(self, c: list) -> tuple | None:
        return c[0]

    def aixdata_param(self, c: list) -> tuple | None:
        return c[0]

    def aixindex_param(self, c: list) -> tuple | None:
        return c[0]

    def gdg_param(self, c: list) -> tuple | None:
        return c[0]

    def nonvsam_param(self, c: list) -> tuple | None:
        return c[0]

    def path_param(self, c: list) -> tuple | None:
        return c[0]

    # -- mutually-exclusive-choice state machines (see ams.lark's
    # cluster_seq_*/data_seq_*/index_seq_* comment): each of these
    # right-recursive rules has either 0 children (the empty/base-case
    # alternative) or exactly 2 (the consumed item, then the tail of the
    # sequence) -- flatten them back into the same flat list shape that
    # cluster_param*/data_param*/index_param* used to produce directly.
    @staticmethod
    def _flatten_seq(c: list) -> list:
        if not c:
            return []
        head, tail = c
        return [head, *tail]

    def cluster_seq_00(self, c: list) -> list:
        return self._flatten_seq(c)

    def cluster_seq_10(self, c: list) -> list:
        return self._flatten_seq(c)

    def cluster_seq_01(self, c: list) -> list:
        return self._flatten_seq(c)

    def cluster_seq_11(self, c: list) -> list:
        return self._flatten_seq(c)

    def data_seq_0(self, c: list) -> list:
        return self._flatten_seq(c)

    def data_seq_1(self, c: list) -> list:
        return self._flatten_seq(c)

    def index_seq_0(self, c: list) -> list:
        return self._flatten_seq(c)

    def index_seq_1(self, c: list) -> list:
        return self._flatten_seq(c)

    def aix_seq_00(self, c: list) -> list:
        return self._flatten_seq(c)

    def aix_seq_10(self, c: list) -> list:
        return self._flatten_seq(c)

    def aix_seq_01(self, c: list) -> list:
        return self._flatten_seq(c)

    def aix_seq_11(self, c: list) -> list:
        return self._flatten_seq(c)

    def aixdata_seq_0(self, c: list) -> list:
        return self._flatten_seq(c)

    def aixdata_seq_1(self, c: list) -> list:
        return self._flatten_seq(c)

    def aixindex_seq_0(self, c: list) -> list:
        return self._flatten_seq(c)

    def aixindex_seq_1(self, c: list) -> list:
        return self._flatten_seq(c)

    # -- DATA(...) / INDEX(...) trailers --------------------------------
    def data_clause(self, c: list) -> DataComponent:
        fields: dict[str, object] = {}
        for item in c[0]:
            if item is None:
                continue
            key, value = item
            fields[key] = value
        return DataComponent(**fields)

    def index_clause(self, c: list) -> IndexComponent:
        fields: dict[str, object] = {}
        for item in c[0]:
            if item is None:
                continue
            key, value = item
            fields[key] = value
        return IndexComponent(**fields)

    def component_clause(self, c: list) -> object:
        return c[0]

    # -- DEFINE ALTERNATEINDEX DATA(...) / INDEX(...) trailers ----------
    def aixdata_clause(self, c: list) -> AixDataComponent:
        fields: dict[str, object] = {}
        for item in c[0]:
            if item is None:
                continue
            key, value = item
            fields[key] = value
        return AixDataComponent(**fields)

    def aixindex_clause(self, c: list) -> AixIndexComponent:
        fields: dict[str, object] = {}
        for item in c[0]:
            if item is None:
                continue
            key, value = item
            fields[key] = value
        return AixIndexComponent(**fields)

    def aix_component_clause(self, c: list) -> object:
        return c[0]

    # -- DEFINE ALTERNATEINDEX assembly -----------------------------------
    def define_alternateindex(self, c: list) -> DefineAlternateIndex:
        param_list, *components = c
        fields: dict[str, object] = {}
        for item in param_list:
            if item is None:
                continue
            key, value = item
            fields[key] = value
        for component in components:
            if isinstance(component, AixDataComponent):
                fields["data"] = component
            elif isinstance(component, AixIndexComponent):
                fields["index"] = component
        return DefineAlternateIndex(**fields)

    # -- DEFINE CLUSTER assembly -----------------------------------------
    def define_cluster(self, c: list) -> DefineCluster:
        param_list, *components = c
        fields: dict[str, object] = {}
        database_format: str | None = None
        database_key: tuple[str, bool] | None = None
        for item in param_list:
            if item is None:
                continue
            key, value = item
            if key == "database_format":
                database_format = value
                continue
            if key == "database_key_name":
                database_key = value
                continue
            fields[key] = value
        for component in components:
            if isinstance(component, DataComponent):
                fields["data"] = component
            elif isinstance(component, IndexComponent):
                fields["index"] = component
        if database_format is not None or database_key is not None:
            if database_format is None or database_key is None:
                # DATABASE(...) and its KEYNAME/KEYNAMEU are a single unit
                # per the IDCAMS manual -- fabricating a fake key_name=""
                # or a guessed format="JSON" when only one half is present
                # would silently hide a malformed control statement.
                raise ValueError(
                    "DEFINE CLUSTER: DATABASE(...) requires KEYNAME(...) or "
                    "KEYNAMEU(...) (and vice versa) -- they must both be "
                    "specified together"
                )
            key_name, is_utf8 = database_key
            fields["database"] = DatabaseSpec(
                format=database_format,
                key_name=key_name,
                key_name_is_utf8=is_utf8,
            )
        return DefineCluster(**fields)

    # -- DEFINE GENERATIONDATAGROUP / NONVSAM / PATH assembly -------------
    @staticmethod
    def _fields_dict(param_list: list) -> dict[str, object]:
        fields: dict[str, object] = {}
        for item in param_list:
            if item is None:
                continue
            key, value = item
            fields[key] = value
        return fields

    def define_gdg(self, c: list) -> DefineGenerationDataGroup:
        return DefineGenerationDataGroup(**self._fields_dict(c))

    def define_nonvsam(self, c: list) -> DefineNonvsam:
        return DefineNonvsam(**self._fields_dict(c))

    def define_path(self, c: list) -> DefinePath:
        return DefinePath(**self._fields_dict(c))

    def command(self, c: list) -> object:
        return c[0]


_PARSER = Lark.open(_GRAMMAR_PATH, start="start", parser="earley")


def parse_ams(text: str) -> tuple[object, ...]:
    """Parse comprehensive-grammar IDCAMS control statements.

    Applies the "+" mid-token continuation preprocessing pass first (the
    grammar itself only understands "-" continuation, via %ignore), then
    parses with the shared ams.lark grammar and reduces the tree with a
    Transformer producing typed dataclasses (today: DefineCluster only --
    see the module docstring for the plan across Tasks 3-11).
    """
    src = join_plus_continuations(text)
    if not src.endswith("\n"):
        src += "\n"
    tree = _PARSER.parse(src)
    try:
        result = _Build().transform(tree)
    except VisitError as exc:
        # Lark wraps any exception raised inside a Transformer callback
        # (e.g. the ValueError DatabaseSpec construction raises when
        # DATABASE(...) and KEYNAME/KEYNAMEU don't co-occur) in its own
        # VisitError. Re-raise the original so callers see the real
        # exception type instead of a Lark-internal wrapper.
        raise exc.orig_exc from exc
    return tuple(result.children)
