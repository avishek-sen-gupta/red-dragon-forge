"""ANTLR4 visitor for EXEC CICS parse trees → (verb, opts).

The grammar is the mapa CICSzParser/CICSzLexer grammar adapted for Python3;
see cics_grammar/CICSzParser.g4 for the grammar source and regeneration notes.
"""

from __future__ import annotations

import re

from antlr4 import CommonTokenStream, InputStream, TerminalNode
from antlr4.error.ErrorListener import ErrorListener

from dataclasses import dataclass

from port.cics.cics_grammar.CICSzLexer import CICSzLexer
from port.cics.cics_grammar.CICSzParser import CICSzParser
from port.interpreter.cobol.cobol_expression import ExprNode, FieldRefNode, LiteralNode
from port.interpreter.cobol.ref_mod import RefModExpr, RefModLiteral, RefModReference


@dataclass(frozen=True)
class CicsOperand:
    """A parsed EXEC CICS option value.

    is_literal=True  -> a quoted string literal (text is the inner content, no quotes).
    is_literal=False -> a bare operand: data-name, subscripted/reference-modified ref,
                        or numeric literal (text preserved verbatim).

    ``subscripts`` carries each index as a structured ExprNode: a bare data-name
    becomes a FieldRefNode, an unsigned integer becomes a LiteralNode.
    Arithmetic CICS subscripts raise ValueError at parse time.

    Relocated from RedDragon (red-dragon commit b54471dc's DialectParser
    migration) — lives here, not cics/statements.py, to avoid a circular
    import (statements.py already needs parse_exec_cics_text from this
    module; this module needs CicsOperand for its own operand construction).
    """

    text: str
    is_literal: bool
    subscripts: tuple[ExprNode, ...] = ()
    ref_mod_start: ExprNode | None = None
    ref_mod_length: ExprNode | None = None


class _FailFastErrorListener(ErrorListener):
    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        raise ValueError(f"EXEC CICS parse error at {line}:{column}: {msg}")


# Maps rule class names (with "Context" stripped) → canonical CICS verb string.
# Compound-verb components that appear as bare option keywords (e.g. SEND, MAP for
# SEND MAP) are filtered from opts after collection; the verb string here is what
# the strategy layer and downstream consumers see.
_CONTEXT_TO_VERB: dict[str, str] = {
    "Abend": "ABEND",
    "Acquire": "ACQUIRE",
    "AddSubevent": "ADD SUBEVENT",
    "Address": "ADDRESS",
    "AddressSet": "ADDRESS SET",
    "AllocateAPPC": "ALLOCATE",
    "AllocateLU61": "ALLOCATE",
    "AllocateMRO": "ALLOCATE",
    "Asktime": "ASKTIME",
    "Assign": "ASSIGN",
    "BifDeedit": "BIF DEEDIT",
    "BifDigest": "BIF DIGEST",
    "BuildAttachLU61": "BUILD ATTACH",
    "BuildAttachMRO": "BUILD ATTACH",
    "Cancel": "CANCEL",
    "CancelBTS": "CANCEL",
    "ChangePhrase": "CHANGE PHRASE",
    "ChangePassword": "CHANGE PASSWORD",
    "ChangeTask": "CHANGE TASK",
    "CheckAcqprocess": "CHECK ACQPROCESS",
    "CheckActivity": "CHECK ACTIVITY",
    "CheckTimer": "CHECK TIMER",
    "ConnectProcess": "CONNECT PROCESS",
    "ConversezOSCommServer": "CONVERSE",
    "ConverseNonzOSCommServer": "CONVERSE",
    "Converttime": "CONVERTTIME",
    "DefineActivity": "DEFINE ACTIVITY",
    "DefineCompositeEvent": "DEFINE COMPOSITE EVENT",
    "DefineCounter": "DEFINE COUNTER",
    "DefineDcounter": "DEFINE DCOUNTER",
    "DefineInputEvent": "DEFINE INPUT EVENT",
    "DefineProcess": "DEFINE PROCESS",
    "DefineTimer": "DEFINE TIMER",
    "Delay": "DELAY",
    "Delete": "DELETE",
    "DeleteActivity": "DELETE ACTIVITY",
    "DeleteChannel": "DELETE CHANNEL",
    "DeleteContainerBTS": "DELETE CONTAINER",
    "DeleteContainer": "DELETE CONTAINER",
    "DeleteCounter": "DELETE COUNTER",
    "DeleteDcounter": "DELETE DCOUNTER",
    "DeleteEvent": "DELETE EVENT",
    "DeleteTimer": "DELETE TIMER",
    "DeleteqTd": "DELETEQ TD",
    "DeleteqTs": "DELETEQ TS",
    "Deq": "DEQ",
    "DocumentCreate": "DOCUMENT CREATE",
    "DocumentDelete": "DOCUMENT DELETE",
    "DocumentInsert": "DOCUMENT INSERT",
    "DocumentRetrieve": "DOCUMENT RETRIEVE",
    "DocumentSet": "DOCUMENT SET",
    "Dump": "DUMP",
    "DumpTransaction": "DUMP TRANSACTION",
    "Endbr": "ENDBR",
    "EndbrowseActivity": "ENDBROWSE ACTIVITY",
    "Endbrowse": "ENDBROWSE",
    "EndbrowseEvent": "ENDBROWSE EVENT",
    "EndbrowseProcess": "ENDBROWSE PROCESS",
    "EndbrowseTimer": "ENDBROWSE TIMER",
    "Enq": "ENQ",
    "EnterTraceid": "ENTER TRACEID",
    "EnterTracenum": "ENTER TRACENUM",
    "ExtractAttachLU61": "EXTRACT ATTACH",
    "ExtractAttachMRO": "EXTRACT ATTACH",
    "ExtractAttributesAPPC": "EXTRACT ATTRIBUTES",
    "ExtractAttributesMRO": "EXTRACT ATTRIBUTES",
    "ExtractCertificate": "EXTRACT CERTIFICATE",
    "ExtractLogonmsg": "EXTRACT LOGONMSG",
    "ExtractProcess": "EXTRACT PROCESS",
    "ExtractTcpip": "EXTRACT TCPIP",
    "ExtractTct": "EXTRACT TCT",
    "ExtractWebAsHost": "EXTRACT WEB",
    "ExtractWebAsClient": "EXTRACT WEB",
    "FetchAny": "FETCH ANY",
    "FetchChild": "FETCH CHILD",
    "ForceTimer": "FORCE TIMER",
    "Formattime": "FORMATTIME",
    "Free": "FREE",
    "FreeAPPC": "FREE",
    "FreeLU61": "FREE",
    "FreeMRO": "FREE",
    "FreeChild": "FREE CHILD",
    "Freemain": "FREEMAIN",
    "Freemain64": "FREEMAIN",
    "GdsAllocate": "GDS ALLOCATE",
    "GdsAssign": "GDS ASSIGN",
    "GdsConnectProcess": "GDS CONNECT PROCESS",
    "GdsExtractAttributes": "GDS EXTRACT ATTRIBUTES",
    "GdsExtractProcess": "GDS EXTRACT PROCESS",
    "GdsFree": "GDS FREE",
    "GdsIssueAbend": "GDS ISSUE ABEND",
    "GdsIssueConfirmation": "GDS ISSUE CONFIRMATION",
    "GdsIssueError": "GDS ISSUE ERROR",
    "GdsIssuePrepare": "GDS ISSUE PREPARE",
    "GdsIssueSignal": "GDS ISSUE SIGNAL",
    "GdsReceive": "GDS RECEIVE",
    "GdsSend": "GDS SEND",
    "GdsWait": "GDS WAIT",
    "GetContainerBTS": "GET CONTAINER",
    "GetContainer": "GET CONTAINER",
    "GetCounter": "GET COUNTER",
    "GetDcounter": "GET DCOUNTER",
    "Getmain": "GETMAIN",
    "Getmain64": "GETMAIN",
    "GetnextActivity": "GETNEXT ACTIVITY",
    "GetnextContainer": "GETNEXT CONTAINER",
    "GetnextEvent": "GETNEXT EVENT",
    "GetnextProcess": "GETNEXT PROCESS",
    "GetnextTimer": "GETNEXT TIMER",
    "Get64Container": "GET64 CONTAINER",
    "HandleAbend": "HANDLE ABEND",
    "HandleAid": "HANDLE AID",
    "HandleCondition": "HANDLE CONDITION",
    "IgnoreCondition": "IGNORE CONDITION",
    "InquireActivityid": "INQUIRE",
    "InquireContainer": "INQUIRE",
    "InquireEvent": "INQUIRE",
    "InquireProcess": "INQUIRE",
    "InquireTimer": "INQUIRE",
    "InvokeApplication": "INVOKE APPLICATION",
    "InvokeService": "INVOKE SERVICE",
    "InvokeWebservice": "INVOKE WEBSERVICE",
    "IssueAbend": "ISSUE ABEND",
    "IssueAbort": "ISSUE ABORT",
    "IssueAdd": "ISSUE ADD",
    "IssueConfirmation": "ISSUE CONFIRMATION",
    "IssueCopy": "ISSUE COPY",
    "IssueDisconnect": "ISSUE DISCONNECT",
    "IssueDisconnectLU61": "ISSUE DISCONNECT",
    "IssueEnd": "ISSUE END",
    "IssueEndfile": "ISSUE ENDFILE",
    "IssueEndoutput": "ISSUE ENDOUTPUT",
    "IssueEods": "ISSUE EODS",
    "IssueErase": "ISSUE ERASE",
    "IssueEraseaup": "ISSUE ERASEAUP",
    "IssueError": "ISSUE ERROR",
    "IssueLoad": "ISSUE LOAD",
    "IssueNote": "ISSUE NOTE",
    "IssuePass": "ISSUE PASS",
    "IssuePrepare": "ISSUE PREPARE",
    "IssuePrint": "ISSUE PRINT",
    "IssueQuery": "ISSUE QUERY",
    "IssueReceive": "ISSUE RECEIVE",
    "IssueReplace": "ISSUE REPLACE",
    "IssueReset": "ISSUE RESET",
    "IssueSend": "ISSUE SEND",
    "IssueSignal": "ISSUE SIGNAL",
    "IssueSignalLU61": "ISSUE SIGNAL",
    "IssueWait": "ISSUE WAIT",
    "Journal": "JOURNAL",
    "Link": "LINK",
    "LinkAcqprocess": "LINK",
    "LinkActivity": "LINK",
    "Load": "LOAD",
    "Monitor": "MONITOR",
    "MoveContainerBTS": "MOVE CONTAINER",
    "MoveContainer": "MOVE CONTAINER",
    "Point": "POINT",
    "PopHandle": "POP HANDLE",
    "Post": "POST",
    "PurgeMessage": "PURGE MESSAGE",
    "PushHandle": "PUSH HANDLE",
    "PutContainerBTS": "PUT CONTAINER",
    "PutContainer": "PUT CONTAINER",
    "Put64Container": "PUT64 CONTAINER",
    "QueryChannel": "QUERY CHANNEL",
    "QueryCounter": "QUERY COUNTER",
    "QueryDcounter": "QUERY DCOUNTER",
    "QuerySecurity": "QUERY SECURITY",
    "Read": "READ",
    "Readnext": "READNEXT",
    "Readprev": "READPREV",
    "ReadqTd": "READQ TD",
    "ReadqTs": "READQ TS",
    "ReceivezOSCommServer": "RECEIVE",
    "ReceiveNonzOSCommServer": "RECEIVE",
    "ReceiveMap": "RECEIVE MAP",
    "ReceiveMapMappingdev": "RECEIVE MAP",
    "ReceivePartn": "RECEIVE PARTN",
    "Release": "RELEASE",
    "RemoveSubevent": "REMOVE SUBEVENT",
    "RequestEncryptptkt": "REQUEST ENCRYPTPTKT",
    "RequestPassticket": "REQUEST PASSTICKET",
    "ResetAcqprocess": "RESET ACQPROCESS",
    "ResetActivity": "RESET ACTIVITY",
    "Resetbr": "RESETBR",
    "Resume": "RESUME",
    "Retrieve": "RETRIEVE",
    "RetrieveReattach": "RETRIEVE",
    "RetrieveSubevent": "RETRIEVE",
    "Return": "RETURN",
    "RewindCounter": "REWIND COUNTER",
    "RewindDcounter": "REWIND DCOUNTER",
    "Rewrite": "REWRITE",
    "Route": "ROUTE",
    "Run": "RUN",
    "RunTransid": "RUN TRANSID",
    "SendzOSCommServer": "SEND",
    "SendNonzOSCommServer": "SEND",
    "SendControl": "SEND CONTROL",
    "SendMap": "SEND MAP",
    "SendMapMappingdev": "SEND MAP",
    "SendPage": "SEND PAGE",
    "SendPartnset": "SEND PARTN",
    "SendText": "SEND TEXT",
    "SendTextMapped": "SEND TEXT",
    "SendTextNoedit": "SEND TEXT",
    "SignalEvent": "SIGNAL EVENT",
    "Signoff": "SIGNOFF",
    "Signon": "SIGNON",
    "SignonToken": "SIGNON",
    "SoapfaultAdd": "SOAPFAULT ADD",
    "SoapfaultCreate": "SOAPFAULT CREATE",
    "SoapfaultDelete": "SOAPFAULT DELETE",
    "Spoolclose": "SPOOLCLOSE",
    "SpoolopenInput": "SPOOLOPEN INPUT",
    "SpoolopenOutput": "SPOOLOPEN OUTPUT",
    "Spoolread": "SPOOLREAD",
    "Spoolwrite": "SPOOLWRITE",
    "SpoolopenReport": "SPOOLOPEN REPORT",
    "SpoolwriteReport": "SPOOLWRITE REPORT",
    "SpoolcloseReport": "SPOOLCLOSE REPORT",
    "SpoolopenResume": "SPOOLOPEN RESUME",
    "Start": "START",
    "StartAttach": "START",
    "StartBrexit": "START",
    "StartChannel": "START CHANNEL",
    "Startbr": "STARTBR",
    "StartbrowseActivity": "STARTBROWSE ACTIVITY",
    "StartbrowseContainerBTS": "STARTBROWSE CONTAINER",
    "StartbrowseContainer": "STARTBROWSE CONTAINER",
    "StartbrowseEvent": "STARTBROWSE EVENT",
    "StartbrowseProcess": "STARTBROWSE PROCESS",
    "StartbrowseTimer": "STARTBROWSE TIMER",
    "Suspend": "SUSPEND",
    "SuspendBTS": "SUSPEND",
    "Syncpoint": "SYNCPOINT",
    "SyncpointRollback": "SYNCPOINT ROLLBACK",
    "TestEvent": "TEST EVENT",
    "TransformDatatojson": "TRANSFORM DATATOJSON",
    "TransformDatatoxml": "TRANSFORM DATATOXML",
    "TransformJsontodata": "TRANSFORM JSONTODATA",
    "TransformXmltodata": "TRANSFORM XMLTODATA",
    "Unlock": "UNLOCK",
    "UpdateCounter": "UPDATE COUNTER",
    "UpdateDcounter": "UPDATE DCOUNTER",
    "VerifyPassword": "VERIFY PASSWORD",
    "VerifyPhrase": "VERIFY PHRASE",
    "VerifyToken": "VERIFY TOKEN",
    "WaitConvid": "WAIT CONVID",
    "WaitEvent": "WAIT EVENT",
    "WaitExternal": "WAIT EXTERNAL",
    "WaitJournal": "WAIT JOURNAL",
    "WaitJournalname": "WAIT JOURNALNAME",
    "WaitJournalnum": "WAIT JOURNALNUM",
    "WaitSignal": "WAIT SIGNAL",
    "WaitTerminal": "WAIT TERMINAL",
    "Waitcics": "WAITCICS",
    "WebClose": "WEB CLOSE",
    "WebConverse": "WEB CONVERSE",
    "WebEndbrowseFormfield": "WEB ENDBROWSE FORMFIELD",
    "WebEndbrowseHttpheader": "WEB ENDBROWSE HTTPHEADER",
    "WebEndbrowseQueryparm": "WEB ENDBROWSE QUERYPARM",
    "WebExtractServer": "WEB EXTRACT",
    "WebExtractClient": "WEB EXTRACT",
    "WebOpen": "WEB OPEN",
    "WebParse": "WEB PARSE",
    "WebReadFormfield": "WEB READ FORMFIELD",
    "WebReadHttpheader": "WEB READ HTTPHEADER",
    "WebReadQueryparm": "WEB READ QUERYPARM",
    "WebReadnextFormfield": "WEB READNEXT FORMFIELD",
    "WebReadnextHttpheader": "WEB READNEXT HTTPHEADER",
    "WebReadnextQueryparm": "WEB READNEXT QUERYPARM",
    "WebReceiveServerWithBuffer": "WEB RECEIVE",
    "WebReceiveServerWithContainer": "WEB RECEIVE",
    "WebReceiveClientWithBuffer": "WEB RECEIVE",
    "WebReceiveClientWithContainer": "WEB RECEIVE",
    "WebRetrieve": "WEB RETRIEVE",
    "WebSendServer": "WEB SEND",
    "WebSendClient": "WEB SEND",
    "WebStartbrowseFormfield": "WEB STARTBROWSE FORMFIELD",
    "WebStartbrowseHttpheader": "WEB STARTBROWSE HTTPHEADER",
    "WebStartbrowseQueryparm": "WEB STARTBROWSE QUERYPARM",
    "WebWriteHttpheader": "WEB WRITE HTTPHEADER",
    "Write": "WRITE",
    "WriteJournalname": "WRITE JOURNALNAME",
    "WriteJournalnum": "WRITE JOURNALNUM",
    "WriteOperator": "WRITE OPERATOR",
    "WriteqTd": "WRITEQ TD",
    "WriteqTs": "WRITEQ TS",
    "WsacontextBuild": "WSACONTEXT BUILD",
    "WsacontextDelete": "WSACONTEXT DELETE",
    "WsacontextGet": "WSACONTEXT GET",
    "WsaeprCreate": "WSAEPR CREATE",
    "Xctl": "XCTL",
}


def _get_verb(cmd_ctx) -> str:
    class_name = type(cmd_ctx).__name__
    rule_name = (
        class_name[: -len("Context")] if class_name.endswith("Context") else class_name
    )
    if rule_name in _CONTEXT_TO_VERB:
        return _CONTEXT_TO_VERB[rule_name]
    # SPI Inquire* family: resource name goes into opts, not into the verb
    if rule_name.startswith("Inquire"):
        return "INQUIRE"
    # Fallback: camelCase → UPPER SPACED (handles SPI commands not listed above)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", rule_name)
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", spaced)
    return spaced.upper()


def _extract_options(ctx) -> list[tuple[str, CicsOperand | None]]:
    result: list[tuple[str, CicsOperand | None]] = []
    for i in range(ctx.getChildCount()):
        child = ctx.getChild(i)
        if isinstance(child, TerminalNode):
            continue
        result.extend(_extract_from_option(child))
    return result


def _extract_from_option(ctx) -> list[tuple[str, CicsOperand | None]]:
    """Return (KEYWORD, operand?) for a leaf option rule; recurse into wrappers."""
    if ctx.getChildCount() == 0:
        return []
    first_child = ctx.getChild(0)
    if isinstance(first_child, TerminalNode):
        keyword = first_child.getText().upper()
        arg_ctx = None
        for i in range(ctx.getChildCount()):
            c = ctx.getChild(i)
            if isinstance(c, CICSzParser.ArgContext):
                arg_ctx = c
                break
        return [(keyword, _build_operand(arg_ctx) if arg_ctx else None)]
    # Wrapper context (*Options): recurse into its non-terminal children
    result: list[tuple[str, CicsOperand | None]] = []
    for i in range(ctx.getChildCount()):
        c = ctx.getChild(i)
        if not isinstance(c, TerminalNode):
            result.extend(_extract_from_option(c))
    return result


def _build_operand(arg_ctx: CICSzParser.ArgContext) -> CicsOperand:
    parts = arg_ctx.argContent().argPart()
    return _parts_to_operand(parts)


def _parts_to_operand(parts: list) -> CicsOperand:
    significant = [p for p in parts if not isinstance(p, CICSzParser.ArgWsContext)]

    if not significant:
        return CicsOperand("", False)

    # Single quoted string literal
    if len(significant) == 1 and isinstance(
        significant[0], CICSzParser.ArgStringContext
    ):
        raw = significant[0].ARG_STRING().getText()
        return CicsOperand(text=raw[1:-1], is_literal=True)

    # Reference modification: ARG_CHARS base + ArgRefMod(start:length)
    if (
        len(significant) == 2
        and isinstance(significant[0], CICSzParser.ArgCharsContext)
        and isinstance(significant[1], CICSzParser.ArgRefModContext)
    ):
        base = significant[0].ARG_CHARS().getText()
        refmod = significant[1]
        start = _build_refmod_side(refmod.argRefmodSide(0))
        length = _build_refmod_side(refmod.argRefmodSide(1))
        return CicsOperand(
            text=base, is_literal=False, ref_mod_start=start, ref_mod_length=length
        )

    # Subscripted: ARG_CHARS base followed by one or more ArgNested subscripts
    if (
        len(significant) >= 2
        and isinstance(significant[0], CICSzParser.ArgCharsContext)
        and all(isinstance(p, CICSzParser.ArgNestedContext) for p in significant[1:])
    ):
        base = significant[0].ARG_CHARS().getText()
        subscripts = tuple(_build_subscript(n) for n in significant[1:])
        return CicsOperand(text=base, is_literal=False, subscripts=subscripts)

    # Plain data-name, numeric, or multi-word reference (e.g. "APPLIDO OF COSGN0AO")
    text = "".join(p.getText() for p in parts).strip()
    return CicsOperand(text=text, is_literal=False)


def _build_subscript(nested_ctx: CICSzParser.ArgNestedContext) -> ExprNode:
    parts = nested_ctx.argPart()
    non_ws = [p for p in parts if not isinstance(p, CICSzParser.ArgWsContext)]
    if len(non_ws) != 1 or not isinstance(non_ws[0], CICSzParser.ArgCharsContext):
        raise ValueError(
            "Arithmetic CICS subscripts are not supported: only a bare data-name "
            "or integer is valid inside a subscript group"
        )
    text = non_ws[0].ARG_CHARS().getText()
    if text.isdigit():
        return LiteralNode(value=text)
    return FieldRefNode(name=text)


def _build_refmod_side(ctx: CICSzParser.ArgRefmodSideContext) -> RefModExpr:
    text = ctx.ARG_CHARS().getText()
    if text.isdigit():
        return RefModLiteral(value=text)
    return RefModReference(name=text)


def parse_exec_cics_text(text: str) -> tuple[str, dict[str, CicsOperand | None]]:
    """Parse 'EXEC CICS VERB OPT(val) FLAG END-EXEC' → (verb, {OPT: CicsOperand, FLAG: None}).

    Raises ValueError on parse errors or unsupported constructs (arithmetic subscripts).
    Empty / whitespace-only input returns ("", {}).
    """
    if not text.strip():
        return "", {}

    input_stream = InputStream(text)
    lexer = CICSzLexer(input_stream)
    # The @lexer::members block in CICSzLexer.g4 generates local vars in __init__,
    # not instance attrs, so sempred can't find them. Set them here for all modes.
    lexer.pliCode = False
    lexer.classicCOBOLCode = False
    lexer.freeFormCOBOLCode = False
    lexer.cCode = False
    lexer.removeErrorListeners()
    lexer.addErrorListener(_FailFastErrorListener())

    token_stream = CommonTokenStream(lexer)
    parser = CICSzParser(token_stream)
    parser.removeErrorListeners()
    parser.addErrorListener(_FailFastErrorListener())

    tree = parser.startRule()

    cmd_ctx = tree.cicsCommand(0)
    api_or_spi = cmd_ctx.cicsAPI() or cmd_ctx.cicsSPI()
    if api_or_spi is None:
        raise ValueError(f"Cannot parse EXEC CICS text: {text!r}")

    matched_cmd = api_or_spi.getChild(0)
    verb = _get_verb(matched_cmd)

    pairs = _extract_options(matched_cmd)
    opts: dict[str, CicsOperand | None] = {}
    for key, val in pairs:
        opts[key] = val

    # Strip bare verb-constituent keywords from opts.
    # MAP with a value in SEND MAP(name) stays; bare MAP is removed.
    verb_words = set(verb.split())
    opts = {k: v for k, v in opts.items() if not (v is None and k in verb_words)}

    return verb, opts
