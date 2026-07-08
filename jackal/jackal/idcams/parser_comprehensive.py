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

from jackal.idcams.ast_alter import Alter, NullifySpec
from jackal.idcams.ast_bldindex import Bldindex
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
from jackal.idcams.ast_delete import Delete
from jackal.idcams.ast_define_gdg import DefineGenerationDataGroup
from jackal.idcams.ast_define_nonvsam import DefineNonvsam
from jackal.idcams.ast_define_path import DefinePath
from jackal.idcams.ast_export import Export
from jackal.idcams.ast_import import Import, ImportObject
from jackal.idcams.ast_listcat import Listcat
from jackal.idcams.ast_modal import AmsCommand, CancelCommand, IfCommand, SetCommand
from jackal.idcams.ast_print import Print
from jackal.idcams.ast_repro import (
    CipherSpec,
    DecipherSpec,
    RangeEnd,
    RangeStart,
    Repro,
)
from jackal.idcams.ast_values import (
    BinLiteral,
    HexLiteral,
    Name,
    QuotedString,
    Retention,
    SpaceAllocation,
)
from jackal.idcams.ast_verify import Verify
from jackal.idcams.preprocess import join_plus_continuations

_GRAMMAR_PATH = str(files("jackal.idcams") / "grammar" / "ams.lark")


def _int(tok: Token) -> int:
    return int(tok)


def _name(tok: Token) -> Name:
    return Name.parse(str(tok))


def _entry_name(tok: Token) -> Name:
    """Convert a DELETE_ENTRY token to a Name, tolerating real MASK filter-key
    patterns ("**", "%") that Name.parse's stricter shared regex rejects --
    see the DELETE_ENTRY terminal's comment in ams.lark for why this can't
    just reuse Name.parse() unconditionally."""
    text = str(tok)
    try:
        return Name.parse(text)
    except ValueError:
        return Name(text=text, generic=True)


def _dequote(tok: Token) -> str:
    """Strip surrounding quotes and de-escape '' -> ' from a QUOTED_STRING token."""
    return str(tok)[1:-1].replace("''", "'")


class _Build(Transformer):
    # -- shared value alternation (Task 1 placeholder rule, still used
    # standalone by lexical tests) -----------------------------------
    def value(self, c: list) -> object:
        """Convert the shared value alternation (Task 1 lexical rule) into
        its typed Value variant. First real consumer: REPRO's RangeStart/
        RangeEnd (Task 7) -- no prior command used `value` for anything but
        standalone lexical tests (which parse without a Transformer, so are
        unaffected by this)."""
        tok = c[0]
        if isinstance(tok, Token):
            if tok.type in ("NAME", "GENERIC_NAME"):
                return _name(tok)
            if tok.type == "QUOTED_STRING":
                return QuotedString(text=_dequote(tok))
            if tok.type == "HEX_LITERAL":
                return HexLiteral(raw=str(tok))
            if tok.type == "BIN_LITERAL":
                return BinLiteral(raw=str(tok))
            if tok.type == "INT":
                return _int(tok)
        return tok

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

    # -- ALTER-specific params ---------------------------------------------
    def newname_param(self, c: list) -> tuple:
        return ("new_name", _name(c[0]))

    def addvolumes_param(self, c: list) -> tuple:
        return ("add_volumes", tuple(str(t) for t in c))

    def removevolumes_param(self, c: list) -> tuple:
        return ("remove_volumes", tuple(str(t) for t in c))

    def bufnd_param(self, c: list) -> tuple:
        return ("bufnd", _int(c[0]))

    def bufni_param(self, c: list) -> tuple:
        return ("bufni", _int(c[0]))

    def ccsid_param(self, c: list) -> tuple:
        return ("ccsid", _int(c[0]))

    def ecsharing_flag(self, c: list) -> tuple:
        return ("ec_sharing", True)

    def noecsharing_flag(self, c: list) -> tuple:
        return ("ec_sharing", False)

    def extendedaddressable_flag(self, c: list) -> tuple:
        return ("extended_addressable", True)

    def filedata_param(self, c: list) -> tuple:
        return ("file_data", str(c[0]))

    def alter_frlog_param(self, c: list) -> tuple:
        return ("frlog", str(c[0]))

    def inhibit_flag(self, c: list) -> tuple:
        return ("inhibit", True)

    def uninhibit_flag(self, c: list) -> tuple:
        return ("inhibit", False)

    def alter_log_param(self, c: list) -> tuple:
        return ("log", str(c[0]))

    def reclaimca_flag(self, c: list) -> tuple:
        return ("reclaim_ca", True)

    def noreclaimca_flag(self, c: list) -> tuple:
        return ("reclaim_ca", False)

    def rollin_flag(self, c: list) -> tuple:
        return ("roll_in", True)

    def strno_param(self, c: list) -> tuple:
        return ("strno", _int(c[0]))

    def typelinear_flag(self, c: list) -> tuple:
        return ("to_linear", True)

    def lock_flag(self, c: list) -> tuple:
        return ("lock", True)

    def unlock_flag(self, c: list) -> tuple:
        return ("lock", False)

    def suspend_flag(self, c: list) -> tuple:
        return ("suspend", True)

    def resume_flag(self, c: list) -> tuple:
        return ("suspend", False)

    def catalog_state_choice(self, c: list) -> tuple:
        return c[0]

    # -- NULLIFY(...) sub-block -------------------------------------------
    def nullify_authorization_param(self, c: list) -> tuple:
        return ("authorization", str(c[0]))

    def nullify_bwo_param(self, c: list) -> tuple:
        return ("bwo", True)

    def nullify_code_param(self, c: list) -> tuple:
        return ("code", True)

    def nullify_exceptionexit_param(self, c: list) -> tuple:
        return ("exception_exit", True)

    def nullify_log_param(self, c: list) -> tuple:
        return ("log", True)

    def nullify_logstreamid_param(self, c: list) -> tuple:
        return ("log_stream_id", True)

    def nullify_managementclass_param(self, c: list) -> tuple:
        return ("management_class", True)

    def nullify_owner_param(self, c: list) -> tuple:
        return ("owner", True)

    def nullify_retention_param(self, c: list) -> tuple:
        return ("retention", True)

    def nullify_param(self, c: list) -> tuple:
        return c[0]

    def nullify_clause(self, c: list) -> tuple:
        return ("nullify", NullifySpec(**self._fields_dict(c)))

    # -- DELETE-specific params -------------------------------------------
    def delete_entries(self, c: list) -> tuple:
        return tuple(_entry_name(tok) for tok in c)

    def entry_type_param(self, c: list) -> tuple:
        return ("entry_type", str(c[0]))

    def force_flag(self, c: list) -> tuple:
        return ("force", True)

    def noforce_flag(self, c: list) -> tuple:
        return ("force", False)

    def mask_flag(self, c: list) -> tuple:
        return ("mask", True)

    def nomask_flag(self, c: list) -> tuple:
        return ("mask", False)

    def nodisconnect_flag(self, c: list) -> tuple:
        return ("no_disconnect", True)

    def delete_recovery_flag(self, c: list) -> tuple:
        return ("recovery", True)

    def delete_norecovery_flag(self, c: list) -> tuple:
        return ("recovery", False)

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

    def delete_param(self, c: list) -> tuple | None:
        return c[0]

    def alter_param(self, c: list) -> tuple | None:
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

    def delete_seq_0(self, c: list) -> list:
        return self._flatten_seq(c)

    def delete_seq_1(self, c: list) -> list:
        return self._flatten_seq(c)

    def alter_seq_0(self, c: list) -> list:
        return self._flatten_seq(c)

    def alter_seq_1(self, c: list) -> list:
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

    # -- DELETE assembly ---------------------------------------------------
    def delete(self, c: list) -> Delete:
        entries, param_list = c
        if len(entries) > 100:
            raise ValueError(f"DELETE: at most 100 entries allowed, got {len(entries)}")
        fields = self._fields_dict(param_list)
        fields["entries"] = entries
        return Delete(**fields)

    # -- ALTER assembly -----------------------------------------------------
    def alter(self, c: list) -> Alter:
        entry_tok, param_list = c
        fields = self._fields_dict(param_list)
        fields["entry"] = _name(entry_tok)
        return Alter(**fields)

    # -- REPRO-specific params ----------------------------------------------
    def infile_param(self, c: list) -> tuple:
        return ("infile", str(c[0]))

    def indataset_param(self, c: list) -> tuple:
        return ("indataset", _name(c[0]))

    def outfile_param(self, c: list) -> tuple:
        return ("outfile", str(c[0]))

    def outdataset_param(self, c: list) -> tuple:
        return ("outdataset", _name(c[0]))

    def entries_param(self, c: list) -> tuple:
        return ("entries", tuple(_name(tok) for tok in c))

    def level_param(self, c: list) -> tuple:
        return ("level", str(c[0]))

    def fromkey_param(self, c: list) -> tuple:
        return ("range_start", RangeStart(kind="FROMKEY", value=c[0]))

    def fromaddress_param(self, c: list) -> tuple:
        return ("range_start", RangeStart(kind="FROMADDRESS", value=c[0]))

    def fromnumber_param(self, c: list) -> tuple:
        return ("range_start", RangeStart(kind="FROMNUMBER", value=c[0]))

    def skip_param(self, c: list) -> tuple:
        return ("range_start", RangeStart(kind="SKIP", value=c[0]))

    def tokey_param(self, c: list) -> tuple:
        return ("range_end", RangeEnd(kind="TOKEY", value=c[0]))

    def toaddress_param(self, c: list) -> tuple:
        return ("range_end", RangeEnd(kind="TOADDRESS", value=c[0]))

    def tonumber_param(self, c: list) -> tuple:
        return ("range_end", RangeEnd(kind="TONUMBER", value=c[0]))

    def count_param(self, c: list) -> tuple:
        return ("range_end", RangeEnd(kind="COUNT", value=c[0]))

    def int_pair(self, c: list) -> tuple:
        return (_int(c[0]), _int(c[1]))

    def insertshift_param(self, c: list) -> tuple:
        return ("insert_shift", tuple(c))

    def insertall_flag(self, c: list) -> tuple:
        return ("insert_all", True)

    def skipdbcscheck_param(self, c: list) -> tuple:
        return ("skip_dbcs_check", tuple(c))

    def nodbcscheck_flag(self, c: list) -> tuple:
        return ("no_dbcs_check", True)

    def repro_param(self, c: list) -> tuple:
        return c[0]

    def repro_cimode_flag(self, c: list) -> tuple:
        return ("cimode", True)

    def repro_nocimode_flag(self, c: list) -> tuple:
        return ("cimode", False)

    def repro_dbcs_flag(self, c: list) -> tuple:
        return ("dbcs", True)

    def errorlimit_param(self, c: list) -> tuple:
        return ("error_limit", _int(c[0]))

    def mergecat_flag(self, c: list) -> tuple:
        return ("merge_cat", True)

    def nomergecat_flag(self, c: list) -> tuple:
        return ("merge_cat", False)

    def messagelevel_param(self, c: list) -> tuple:
        return ("message_level", str(c[0]))

    def replace_flag(self, c: list) -> tuple:
        return ("replace", True)

    def noreplace_flag(self, c: list) -> tuple:
        return ("replace", False)

    def volumeentries_param(self, c: list) -> tuple:
        return ("volume_entries", str(c[0]))

    def rlssource_param(self, c: list) -> tuple:
        return ("rls_source", str(c[0]))

    def rlstarget_param(self, c: list) -> tuple:
        return ("rls_target", str(c[0]))

    # -- ENCIPHER(...) / DECIPHER(...) sub-blocks ----------------------------
    def cipher_param(self, c: list) -> tuple:
        return c[0]

    def externalkeyname_choice(self, c: list) -> tuple:
        return ("key_source", ("EXTERNALKEYNAME", str(c[0])))

    def internalkeyname_choice(self, c: list) -> tuple:
        return ("key_source", ("INTERNALKEYNAME", str(c[0])))

    def privatekey_choice(self, c: list) -> tuple:
        return ("key_source", ("PRIVATEKEY", None))

    def cipherunit_param(self, c: list) -> tuple:
        return ("cipher_unit", _int(c[0]))

    def cipher_datakeyfile(self, c: list) -> tuple:
        return ("data_key_file", str(c[0]))

    def cipher_datakeyvalue(self, c: list) -> tuple:
        tok = c[0]
        return (
            "data_key_value",
            _dequote(tok) if tok.type == "QUOTED_STRING" else str(tok),
        )

    def shipkeynames_param(self, c: list) -> tuple:
        return ("ship_key_names", tuple(str(tok) for tok in c))

    def storedatakey_flag(self, c: list) -> tuple:
        return ("store_data_key", True)

    def nostoredatakey_flag(self, c: list) -> tuple:
        return ("store_data_key", False)

    def storekeyname_param(self, c: list) -> tuple:
        return ("store_key_name", str(c[0]))

    def userdata_param(self, c: list) -> tuple:
        tok = c[0]
        return ("user_data", _dequote(tok) if tok.type == "QUOTED_STRING" else str(tok))

    def encipher_clause(self, c: list) -> tuple:
        items = [item for item in c if item is not None]
        key_sources = [value for key, value in items if key == "key_source"]
        if not key_sources:
            raise ValueError(
                "REPRO ENCIPHER: exactly one of EXTERNALKEYNAME, "
                "INTERNALKEYNAME, or PRIVATEKEY is required"
            )
        if len(key_sources) > 1:
            kind_a, kind_b = key_sources[0][0], key_sources[1][0]
            raise ValueError(
                f"REPRO ENCIPHER: {kind_a} and {kind_b} are mutually "
                "exclusive, both were specified"
            )
        fields: dict[str, object] = {}
        for key, value in items:
            if key == "key_source":
                kind, name = value
                fields["key_source"] = kind
                if name is not None:
                    fields["key_name"] = name
            else:
                fields[key] = value
        return ("encipher", CipherSpec(**fields))

    def decipher_param(self, c: list) -> tuple:
        return c[0]

    def dk_datakeyfile_choice(self, c: list) -> tuple:
        return ("key_source", ("DATAKEYFILE", str(c[0])))

    def dk_datakeyvalue_choice(self, c: list) -> tuple:
        tok = c[0]
        value = _dequote(tok) if tok.type == "QUOTED_STRING" else str(tok)
        return ("key_source", ("DATAKEYVALUE", value))

    def dk_systemkey_choice(self, c: list) -> tuple:
        return ("key_source", ("SYSTEMKEY", None))

    def systemdatakey_param(self, c: list) -> tuple:
        tok = c[0]
        return (
            "system_data_key",
            _dequote(tok) if tok.type == "QUOTED_STRING" else str(tok),
        )

    def systemkeyname_param(self, c: list) -> tuple:
        return ("system_key_name", str(c[0]))

    def decipher_clause(self, c: list) -> tuple:
        items = [item for item in c if item is not None]
        key_sources = [value for key, value in items if key == "key_source"]
        if not key_sources:
            raise ValueError(
                "REPRO DECIPHER: exactly one of DATAKEYFILE, DATAKEYVALUE, "
                "or SYSTEMKEY is required"
            )
        if len(key_sources) > 1:
            kind_a, kind_b = key_sources[0][0], key_sources[1][0]
            raise ValueError(
                f"REPRO DECIPHER: {kind_a} and {kind_b} are mutually "
                "exclusive, both were specified"
            )
        fields: dict[str, object] = {}
        for key, value in items:
            if key == "key_source":
                kind, name = value
                fields["key_source"] = kind
                if kind == "DATAKEYFILE":
                    fields["data_key_file"] = name
                elif kind == "DATAKEYVALUE":
                    fields["data_key_value"] = name
            else:
                fields[key] = value
        return ("decipher", DecipherSpec(**fields))

    # -- REPRO group-exclusivity validation ----------------------------------
    # REPRO's eight top-level "pick one" groups (plus the two nested cipher
    # ones handled above in encipher_clause/decipher_clause) are no longer
    # enforced by the grammar -- ams.lark's repro_param list is flat and
    # freely-repeatable, so any relative order parses structurally. This
    # mirrors DEFINE CLUSTER's DATABASE(...)/KEYNAME(...) pattern
    # (see define_cluster above): the grammar accepts broadly, the
    # transformer raises ValueError on an invalid combination.
    @staticmethod
    def _check_repro_pair_group(
        fields: dict[str, object],
        key_a: str,
        label_a: str,
        key_b: str,
        label_b: str,
        *,
        required: bool,
    ) -> None:
        has_a = key_a in fields
        has_b = key_b in fields
        if has_a and has_b:
            raise ValueError(
                f"REPRO: {label_a} and {label_b} are mutually exclusive, "
                "both were specified"
            )
        if required and not has_a and not has_b:
            raise ValueError(
                f"REPRO: exactly one of {label_a} or {label_b} is required"
            )

    # -- REPRO assembly -------------------------------------------------------
    def repro(self, c: list) -> Repro:
        items = [item for item in c if item is not None]

        # RangeStart's 4-way FROMKEY/FROMADDRESS/FROMNUMBER/SKIP and
        # RangeEnd's 4-way TOKEY/TOADDRESS/TONUMBER/COUNT all funnel into
        # the same "range_start"/"range_end" dict key (see
        # fromkey_param/.../count_param above) -- a duplicate key here means
        # two members of the same 4-way group were both specified.
        range_start_kinds = [value.kind for key, value in items if key == "range_start"]
        if len(range_start_kinds) > 1:
            raise ValueError(
                f"REPRO: {range_start_kinds[0]} and {range_start_kinds[1]} "
                "are mutually exclusive, both were specified"
            )
        range_end_kinds = [value.kind for key, value in items if key == "range_end"]
        if len(range_end_kinds) > 1:
            raise ValueError(
                f"REPRO: {range_end_kinds[0]} and {range_end_kinds[1]} "
                "are mutually exclusive, both were specified"
            )

        fields = self._fields_dict(items)

        self._check_repro_pair_group(
            fields, "infile", "INFILE", "indataset", "INDATASET", required=True
        )
        self._check_repro_pair_group(
            fields, "outfile", "OUTFILE", "outdataset", "OUTDATASET", required=True
        )
        self._check_repro_pair_group(
            fields, "entries", "ENTRIES", "level", "LEVEL", required=False
        )
        self._check_repro_pair_group(
            fields, "encipher", "ENCIPHER", "decipher", "DECIPHER", required=False
        )
        self._check_repro_pair_group(
            fields,
            "insert_shift",
            "INSERTSHIFT",
            "insert_all",
            "INSERTALL",
            required=False,
        )
        self._check_repro_pair_group(
            fields,
            "skip_dbcs_check",
            "SKIPDBCSCHECK",
            "no_dbcs_check",
            "NODBCSCHECK",
            required=False,
        )

        return Repro(**fields)

    # -- generic "at most one (and optionally required) of a pair" helper
    # for PRINT/LISTCAT -- REPRO's own _check_repro_pair_group is left
    # untouched (its error messages hardcode "REPRO:"); this is the same
    # pattern parameterized with a command label for reuse by later
    # commands.
    @staticmethod
    def _check_pair_group(
        fields: dict[str, object],
        command_name: str,
        key_a: str,
        label_a: str,
        key_b: str,
        label_b: str,
        *,
        required: bool,
    ) -> None:
        has_a = key_a in fields
        has_b = key_b in fields
        if has_a and has_b:
            raise ValueError(
                f"{command_name}: {label_a} and {label_b} are mutually "
                "exclusive, both were specified"
            )
        if required and not has_a and not has_b:
            raise ValueError(
                f"{command_name}: exactly one of {label_a} or {label_b} is required"
            )

    # -- PRINT-specific params -----------------------------------------------
    def print_param(self, c: list) -> tuple | None:
        return c[0]

    def print_character_flag(self, c: list) -> tuple:
        return ("format", "CHARACTER")

    def print_dump_flag(self, c: list) -> tuple:
        return ("format", "DUMP")

    def print_hex_flag(self, c: list) -> tuple:
        return ("format", "HEX")

    # -- PRINT assembly -------------------------------------------------------
    def print(self, c: list) -> Print:
        items = [item for item in c if item is not None]

        formats = [value for key, value in items if key == "format"]
        if len(formats) > 1:
            raise ValueError(
                f"PRINT: {formats[0]} and {formats[1]} are mutually "
                "exclusive, both were specified"
            )

        range_start_kinds = [value.kind for key, value in items if key == "range_start"]
        if len(range_start_kinds) > 1:
            raise ValueError(
                f"PRINT: {range_start_kinds[0]} and {range_start_kinds[1]} "
                "are mutually exclusive, both were specified"
            )
        range_end_kinds = [value.kind for key, value in items if key == "range_end"]
        if len(range_end_kinds) > 1:
            raise ValueError(
                f"PRINT: {range_end_kinds[0]} and {range_end_kinds[1]} "
                "are mutually exclusive, both were specified"
            )

        fields = self._fields_dict(items)

        self._check_pair_group(
            fields, "PRINT", "infile", "INFILE", "indataset", "INDATASET", required=True
        )
        self._check_pair_group(
            fields,
            "PRINT",
            "insert_shift",
            "INSERTSHIFT",
            "insert_all",
            "INSERTALL",
            required=False,
        )
        self._check_pair_group(
            fields,
            "PRINT",
            "skip_dbcs_check",
            "SKIPDBCSCHECK",
            "no_dbcs_check",
            "NODBCSCHECK",
            required=False,
        )

        return Print(**fields)

    # -- LISTCAT-specific params -----------------------------------------------
    def listcat_param(self, c: list) -> tuple | None:
        return c[0]

    def listcat_entrytype_param(self, c: list) -> tuple:
        return ("entry_type", str(c[0]))

    def libraryentries_param(self, c: list) -> tuple:
        return ("library_entries", str(c[0]))

    def creation_param(self, c: list) -> tuple:
        return ("creation_days", _int(c[0]))

    def expiration_param(self, c: list) -> tuple:
        return ("expiration_days", _int(c[0]))

    def cdilvl_flag(self, c: list) -> tuple:
        return ("cdilvl", True)

    def nocdilvl_flag(self, c: list) -> tuple:
        return ("cdilvl", False)

    def prefix_flag(self, c: list) -> tuple:
        return ("prefix", True)

    def noprefix_flag(self, c: list) -> tuple:
        return ("prefix", False)

    def listcat_detail_param(self, c: list) -> tuple:
        return ("detail", str(c[0]))

    def library_param(self, c: list) -> tuple:
        return ("library", str(c[0]))

    # -- LISTCAT assembly -------------------------------------------------------
    def listcat(self, c: list) -> Listcat:
        items = [item for item in c if item is not None]

        details = [value for key, value in items if key == "detail"]
        if len(details) > 1:
            raise ValueError(
                f"LISTCAT: {details[0]} and {details[1]} are mutually "
                "exclusive, both were specified"
            )

        entry_types = tuple(value for key, value in items if key == "entry_type")
        rest = [item for item in items if item[0] != "entry_type"]

        fields = self._fields_dict(rest)
        fields["entry_types"] = entry_types

        self._check_pair_group(
            fields, "LISTCAT", "entries", "ENTRIES", "level", "LEVEL", required=False
        )

        return Listcat(**fields)

    # -- EXPORT-specific params -----------------------------------------------
    def export_param(self, c: list) -> tuple | None:
        return c[0]

    def export_cimode_flag(self, c: list) -> tuple:
        return ("mode", "CIMODE")

    def export_recordmode_flag(self, c: list) -> tuple:
        return ("mode", "RECORDMODE")

    def inhibitsource_flag(self, c: list) -> tuple:
        return ("inhibit_source", True)

    def noinhibitsource_flag(self, c: list) -> tuple:
        return ("inhibit_source", False)

    def inhibittarget_flag(self, c: list) -> tuple:
        return ("inhibit_target", True)

    def noinhibittarget_flag(self, c: list) -> tuple:
        return ("inhibit_target", False)

    def export_temporary_flag(self, c: list) -> tuple:
        return ("temporary", True)

    def export_permanent_flag(self, c: list) -> tuple:
        return ("temporary", False)

    # -- EXPORT assembly -------------------------------------------------------
    def export(self, c: list) -> Export:
        entry_tok, *rest = c
        items = [item for item in rest if item is not None]

        modes = [value for key, value in items if key == "mode"]
        if len(modes) > 1:
            raise ValueError(
                f"EXPORT: {modes[0]} and {modes[1]} are mutually "
                "exclusive, both were specified"
            )
        temporary_vals = [value for key, value in items if key == "temporary"]
        if len(temporary_vals) > 1:
            raise ValueError(
                "EXPORT: TEMPORARY and PERMANENT are mutually exclusive, "
                "both were specified"
            )

        fields = self._fields_dict(items)
        fields["entry"] = _name(entry_tok)

        self._check_pair_group(
            fields,
            "EXPORT",
            "outfile",
            "OUTFILE",
            "outdataset",
            "OUTDATASET",
            required=True,
        )

        return Export(**fields)

    # -- IMPORT-specific params -------------------------------------------------
    def import_param(self, c: list) -> tuple | None:
        return c[0]

    def alias_flag(self, c: list) -> tuple:
        return ("alias", True)

    def noalias_flag(self, c: list) -> tuple:
        return ("alias", False)

    def intoempty_flag(self, c: list) -> tuple:
        return ("into_empty", True)

    def savrac_flag(self, c: list) -> tuple:
        return ("save_racf", True)

    def nosavrac_flag(self, c: list) -> tuple:
        return ("save_racf", False)

    def import_object_param(self, c: list) -> tuple | None:
        return c[0]

    def import_object(self, c: list) -> ImportObject:
        entry_tok, *param_list = c
        fields = self._fields_dict(param_list)
        fields["entry"] = _name(entry_tok)
        return ImportObject(**fields)

    def objects_param(self, c: list) -> tuple:
        return ("objects", tuple(c))

    # -- IMPORT assembly ---------------------------------------------------------
    def import_cmd(self, c: list) -> Import:
        items = [item for item in c if item is not None]
        fields = self._fields_dict(items)

        self._check_pair_group(
            fields,
            "IMPORT",
            "infile",
            "INFILE",
            "indataset",
            "INDATASET",
            required=True,
        )
        self._check_pair_group(
            fields,
            "IMPORT",
            "outfile",
            "OUTFILE",
            "outdataset",
            "OUTDATASET",
            required=True,
        )

        return Import(**fields)

    # -- VERIFY-specific params -------------------------------------------------
    def verify_param(self, c: list) -> tuple | None:
        return c[0]

    def verify_dataset_param(self, c: list) -> tuple:
        return ("dataset", _name(c[0]))

    def verify_recover_flag(self, c: list) -> tuple:
        return ("recover", True)

    # -- VERIFY assembly ---------------------------------------------------------
    def verify(self, c: list) -> Verify:
        items = [item for item in c if item is not None]
        fields = self._fields_dict(items)

        self._check_pair_group(
            fields, "VERIFY", "file", "FILE", "dataset", "DATASET", required=True
        )

        return Verify(**fields)

    # -- BLDINDEX-specific params -------------------------------------------------
    def bldindex_param(self, c: list) -> tuple | None:
        return c[0]

    def bldindex_outfiles_param(self, c: list) -> tuple:
        return ("outfiles", tuple(str(tok) for tok in c))

    def bldindex_outdatasets_param(self, c: list) -> tuple:
        return ("outdatasets", tuple(_name(tok) for tok in c))

    def externalsort_flag(self, c: list) -> tuple:
        return ("sort_kind", "EXTERNALSORT")

    def internalsort_flag(self, c: list) -> tuple:
        return ("sort_kind", "INTERNALSORT")

    def sortcall_flag(self, c: list) -> tuple:
        return ("sort_call", True)

    def nosortcall_flag(self, c: list) -> tuple:
        return ("sort_call", False)

    def sortdevicetype_param(self, c: list) -> tuple:
        return ("sort_device_type", str(c[0]))

    def sortfilenumber_param(self, c: list) -> tuple:
        return ("sort_file_number", _int(c[0]))

    def sortmessagedd_param(self, c: list) -> tuple:
        return ("sort_message_dd", str(c[0]))

    def sortmessagelevel_param(self, c: list) -> tuple:
        return ("sort_message_level", str(c[0]))

    def workfiles_param(self, c: list) -> tuple:
        return ("work_files", tuple(str(tok) for tok in c))

    # -- BLDINDEX assembly ---------------------------------------------------------
    def bldindex(self, c: list) -> Bldindex:
        items = [item for item in c if item is not None]

        sort_kinds = [value for key, value in items if key == "sort_kind"]
        if len(sort_kinds) > 1:
            raise ValueError(
                f"BLDINDEX: {sort_kinds[0]} and {sort_kinds[1]} are "
                "mutually exclusive, both were specified"
            )
        sort_calls = [value for key, value in items if key == "sort_call"]
        if len(sort_calls) > 1:
            raise ValueError(
                "BLDINDEX: SORTCALL and NOSORTCALL are mutually exclusive, "
                "both were specified"
            )

        fields = self._fields_dict(items)

        self._check_pair_group(
            fields,
            "BLDINDEX",
            "infile",
            "INFILE",
            "indataset",
            "INDATASET",
            required=True,
        )
        self._check_pair_group(
            fields,
            "BLDINDEX",
            "outfiles",
            "OUTFILE",
            "outdatasets",
            "OUTDATASET",
            required=True,
        )

        return Bldindex(**fields)

    def command(self, c: list) -> object:
        return c[0]

    # -- MODAL COMMANDS (Task 11): IF/THEN/ELSE/DO/END, SET, CANCEL --------
    def maxcc_field(self, c: list) -> str:
        return "MAXCC"

    def lastcc_field(self, c: list) -> str:
        return "LASTCC"

    def op_eq(self, c: list) -> str:
        return "EQ"

    def op_ne(self, c: list) -> str:
        return "NE"

    def op_gt(self, c: list) -> str:
        return "GT"

    def op_lt(self, c: list) -> str:
        return "LT"

    def op_ge(self, c: list) -> str:
        return "GE"

    def op_le(self, c: list) -> str:
        return "LE"

    def clause_single(self, c: list) -> tuple:
        return (c[0],)

    def clause_do(self, c: list) -> tuple:
        return tuple(c)

    def clause_null(self, c: list) -> tuple:
        return ()

    @staticmethod
    def _if_nesting_depth(cmd: object) -> int:
        """Depth of the deepest IF nested (directly or transitively) inside
        `cmd`'s THEN/ELSE clauses, plus one for `cmd` itself if it is an
        IfCommand -- 0 for any non-modal command. Used to enforce the IBM
        manual's 10-level nesting cap in the transformer (see if_command's
        grammar comment in ams.lark for why this can't be a grammar-level
        check)."""
        if not isinstance(cmd, IfCommand):
            return 0
        children = cmd.then + (cmd.else_ or ())
        return 1 + max((_Build._if_nesting_depth(ch) for ch in children), default=0)

    def _build_if(
        self,
        field: str,
        op: str,
        value_tok: Token,
        then_clause: tuple,
        else_clause: tuple | None,
    ) -> IfCommand:
        cmd = IfCommand(
            field=field,
            op=op,
            value=_int(value_tok),
            then=then_clause,
            else_=else_clause,
        )
        depth = self._if_nesting_depth(cmd)
        if depth > 10:
            raise ValueError(
                f"IF: nesting exceeds the IDCAMS manual's maximum depth of "
                f"10 levels (got {depth})"
            )
        return cmd

    def if_with_else(self, c: list) -> IfCommand:
        field, op, value_tok, then_clause, else_clause = c
        return self._build_if(field, op, value_tok, then_clause, else_clause)

    def if_without_else(self, c: list) -> IfCommand:
        field, op, value_tok, then_clause = c
        return self._build_if(field, op, value_tok, then_clause, None)

    def modal_command(self, c: list) -> IfCommand:
        return c[0]

    def set_command(self, c: list) -> SetCommand:
        field, value_tok = c
        return SetCommand(field=field, value=_int(value_tok))

    def cancel_command(self, c: list) -> CancelCommand:
        return CancelCommand()


_PARSER = Lark.open(_GRAMMAR_PATH, start="start", parser="earley")


def parse_ams(text: str) -> tuple[AmsCommand, ...]:
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
