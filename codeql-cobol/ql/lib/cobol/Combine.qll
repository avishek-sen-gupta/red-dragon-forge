/**
 * What a jump's target, its transaction or a file site's operand can hold once programs are
 * linked, as cobble's combine answers it, and the links that answer grows. Within a program a
 * question walks back from its bytes through the writers that copy into them, taking the
 * values and the reasons each node's facts give; it stops where bytes were received from a
 * caller, returned by a callee or retrieved from a START. A stop crosses over the links: a
 * caller's area, a callee's exits, a starter's FROM. A link joins a jump to each program its
 * target, or its transaction's program, can name, area to received area, so the links and
 * the answers are one least fixpoint; reasons are read off it once it is settled.
 */

import cobol.Values

private predicate linkageRecord(Program p, string rec) {
  exists(Field f | f.getProgram() = p and f.getRecord() = rec and field_region(f, "linkage"))
}

/** The bytes of `f` an operand of `s` names: its constant slice, else the cell. */
bindingset[s, f]
private predicate accessed(Stmt s, Field f, int lo, int hi) {
  if slicedAccess(s, f, _, _)
  then slicedAccess(s, f, lo, hi)
  else (
    lo = f.getStart() and hi = f.getEnd()
  )
}

/** The node `w` copies bytes `slo` up to `shi` of `srec` into bytes `tlo` up to `thi` of `trec`. */
private predicate copyFlow(GraphNode w, string srec, int slo, int shi, string trec, int tlo, int thi) {
  exists(Stmt s, Field src, Field dst |
    s = w.getStmt() and transfer(s, src, dst)
    or
    exists(string site | s = w.getSiteOf(site) and loopTransfer(s, site, src, dst))
  |
    srec = src.getRecord() and
    trec = dst.getRecord() and
    accessed(s, src, slo, shi) and
    accessed(s, dst, tlo, thi)
  )
}

/** The node `w` writes bytes `tlo` up to `thi` of `trec` from no field. */
private predicate originFlow(GraphNode w, string trec, int tlo, int thi) {
  exists(Stmt s, Field dst |
    s = w.getStmt() and originWrite(s, _, dst)
    or
    exists(string site | s = w.getSiteOf(site) and loopOriginWrite(s, site, _, dst))
  |
    trec = dst.getRecord() and accessed(s, dst, tlo, thi)
  )
}

/** The node `n` records what holds bytes `lo` up to `hi` of `rec`: a copied read's piece, a jump's operand or area cell, a file site's operand. */
private predicate fact(GraphNode n, string rec, int lo, int hi) {
  exists(Field f | piece(n, f, lo, hi) and graphCopies(n, f) and rec = f.getRecord())
  or
  exists(Field f | factExtent(n, _, _, _, f, lo, hi) and rec = f.getRecord())
}

bindingset[r]
private predicate writerExplained(string r) { r = ["not-a-literal", "from-callee", "from-file"] }

/** The reason `r` of a fact is answered by walking its writers rather than kept. */
bindingset[r]
private predicate explained(GraphNode n, string rec, int flo, int fhi, string r) {
  writer(n, rec, flo, fhi, _) and
  (
    writerExplained(r)
    or
    r = "inbound-linkage" and not linkageRecord(n.getProgram(), rec)
  )
}

private predicate keptReason(GraphNode n, string rec, int flo, int fhi, string r) {
  fact(n, rec, flo, fhi) and reason(n, rec, flo, fhi, r) and not explained(n, rec, flo, fhi, r)
}

/** Bytes of a fact read in LINKAGE that came from a caller. */
private predicate receivedFact(GraphNode n, string rec, int flo, int fhi) {
  linkageRecord(n.getProgram(), rec) and
  (
    keptReason(n, rec, flo, fhi, "inbound-linkage")
    or
    fact(n, rec, flo, fhi) and
    not writer(n, rec, flo, fhi, _) and
    not value(n, rec, flo, fhi, _)
  )
}

/** The first parameter the program was entered with whose area holds the bytes. */
bindingset[lo, hi]
private int receivedParam(Program p, string rec, int lo, int hi) {
  result =
    min(int param, Field a |
      received_area(p, param, a) and a.getRecord() = rec and a.getStart() <= lo and hi <= a.getEnd()
    |
      param
    )
}

/** The first parameter of the CALL or LINK at `w` whose area holds the bytes. */
bindingset[lo, hi]
private int returnedParam(GraphNode w, string rec, int lo, int hi) {
  result =
    min(int param, Field a |
      jumpArea(w.getStmt(), param, a) and
      a.getRecord() = rec and
      a.getStart() <= lo and
      hi <= a.getEnd()
    |
      param
    )
}

/** Bytes `lo` up to `hi` of `rec` the jump at `n` asks about: its target or transaction, or its file, by one extent. */
private predicate question(GraphNode n, string part, string rec, int lo, int hi) {
  part = ["target", "transid", "file"] and
  strictcount(Field f, int l, int h | factExtent(n, part, _, _, f, l, h)) = 1 and
  exists(Field f | factExtent(n, part, _, _, f, lo, hi) and rec = f.getRecord())
}

/** A fact at the vertex's node holding some of its bytes, and those bytes. */
private predicate overlap(
  GraphNode n, string rec, int lo, int hi, int flo, int fhi, int plo, int phi
) {
  vertex(n, rec, lo, hi) and
  fact(n, rec, flo, fhi) and
  flo < hi and
  lo < fhi and
  plo = lo.maximum(flo) and
  phi = hi.minimum(fhi)
}

/** Bytes a writer of the fact wrote, from no field. */
private predicate synthetic(
  GraphNode n, string rec, int lo, int hi, int flo, int fhi, GraphNode w, int wlo, int whi
) {
  exists(int plo, int phi, int tlo, int thi |
    overlap(n, rec, lo, hi, flo, fhi, plo, phi) and
    writer(n, rec, flo, fhi, w) and
    originFlow(w, rec, tlo, thi) and
    tlo < phi and
    plo < thi and
    wlo = plo.maximum(tlo) and
    whi = phi.minimum(thi)
  )
}

/** Bytes a CALL or LINK at `w` wrote that came back from its callee, through its parameter `param`. */
private predicate returnedStop(GraphNode w, string rec, int lo, int hi, int param) {
  exists(GraphNode n, string r, int l, int h, int flo, int fhi |
    synthetic(n, r, l, h, flo, fhi, w, lo, hi) and r = rec
  |
    jump(w.getStmt(), ["CALL", "LINK"], _) and param = returnedParam(w, rec, lo, hi)
  )
}

/** Bytes the RETRIEVE at `w` filled. */
private predicate retrievedStop(GraphNode w, string rec, int lo, int hi) {
  exists(GraphNode n, int l, int h, int flo, int fhi |
    synthetic(n, rec, l, h, flo, fhi, w, lo, hi) and jump(w.getStmt(), "RETRIEVE", _)
  )
}

/** Bytes the walk asks about, from a question on. */
private predicate vertex(GraphNode n, string rec, int lo, int hi) {
  question(n, _, rec, lo, hi)
  or
  exists(GraphNode m, string r, int l, int h | vertex(m, r, l, h) |
    step(m, r, l, h, n, rec, lo, hi)
  )
}

/** A walk from the first bytes goes on to the second: back through a copy, or across a link. */
private predicate step(
  GraphNode n, string rec, int lo, int hi, GraphNode m, string mrec, int mlo, int mhi
) {
  exists(int flo, int fhi, int plo, int phi, int slo, int shi, int tlo, int thi, int wlo, int whi |
    overlap(n, rec, lo, hi, flo, fhi, plo, phi) and
    writer(n, rec, flo, fhi, m) and
    copyFlow(m, mrec, slo, shi, rec, tlo, thi) and
    tlo < phi and
    plo < thi and
    wlo = plo.maximum(tlo) and
    whi = phi.minimum(thi) and
    mlo = wlo + slo - tlo and
    mhi = shi.minimum(whi + slo - tlo) and
    mlo < mhi
  )
  or
  exists(int flo, int fhi | vertex(n, rec, lo, hi) |
    exists(int plo, int phi, int param |
      overlap(n, rec, lo, hi, flo, fhi, plo, phi) and
      receivedFact(n, rec, flo, fhi) and
      param = receivedParam(n.getProgram(), rec, plo, phi) and
      fromCaller(n.getProgram(), param, rec, plo, phi, m, mrec, mlo, mhi)
    )
    or
    exists(GraphNode w, int wlo, int whi, int param |
      synthetic(n, rec, lo, hi, flo, fhi, w, wlo, whi) and
      returnedStop(w, rec, wlo, whi, param) and
      fromCallee(w, param, rec, wlo, whi, m, mrec, mlo, mhi)
    )
    or
    exists(GraphNode w, int wlo, int whi |
      synthetic(n, rec, lo, hi, flo, fhi, w, wlo, whi) and
      retrievedStop(w, rec, wlo, whi) and
      fromStarter(w, rec, wlo, whi, m, mrec, mlo, mhi)
    )
  )
}

/** A link into the program `p` as parameter `param` gives the caller's bytes for the received ones, unless they name the program itself. */
bindingset[lo, hi]
private predicate fromCaller(
  Program p, int param, string rec, int lo, int hi, GraphNode m, string mrec, int mlo, int mhi
) {
  exists(int clo, int chi, int elo, int ehi, string nrec, int nlo, int nhi |
    edge(m, p, param, mrec, clo, chi, rec, elo, ehi, nrec, nlo, nhi) and
    elo <= lo and
    hi <= ehi and
    mlo = clo + lo - elo and
    mhi = clo + hi - elo and
    not (nrec = mrec and nlo <= mlo and mhi <= nhi)
  )
}

/** The name a link's target holds in the caller's bytes, when the bytes the callee received are its own name. */
bindingset[lo, hi]
private predicate calleeName(Program p, int param, string rec, int lo, int hi, string v) {
  exists(
    GraphNode m, string crec, int clo, int chi, int elo, int ehi, int mlo, int mhi, int nlo, int nhi
  |
    edge(m, p, param, crec, clo, chi, rec, elo, ehi, crec, nlo, nhi) and
    elo <= lo and
    hi <= ehi and
    mlo = clo + lo - elo and
    mhi = clo + hi - elo and
    nlo <= mlo and
    mhi <= nhi and
    v = paddedTo(p.getName(), nhi - nlo).substring(mlo - nlo, mhi - nlo)
  )
}

bindingset[s, width]
private string paddedTo(string s, int width) {
  if s.length() >= width
  then result = s
  else result = s + concat(int i | i in [1 .. width - s.length()] | " ")
}

/** The callee of a link out of the CALL or LINK at `w` hands back the bytes at each of its exits. */
bindingset[lo, hi]
private predicate fromCallee(
  GraphNode w, int param, string rec, int lo, int hi, GraphNode m, string mrec, int mlo, int mhi
) {
  exists(Program callee, string crec, int clo, int chi, string erec, int elo, int ehi |
    entering(w, callee, param, crec, clo, chi, erec, elo, ehi) and
    crec = rec and
    clo <= lo and
    hi <= chi and
    m.getProgram() = callee and
    jump(m.getStmt(), "EXIT", _) and
    mrec = erec and
    mlo = elo + lo - clo and
    mhi = elo + hi - clo
  )
}

/** A START linked to the RETRIEVE at `w` gives its FROM bytes for the retrieved ones. */
bindingset[lo, hi]
private predicate fromStarter(
  GraphNode w, string rec, int lo, int hi, GraphNode m, string mrec, int mlo, int mhi
) {
  exists(string crec, int clo, int chi, string erec, int elo, int ehi |
    starting(m, w, crec, clo, chi, erec, elo, ehi) and
    erec = rec and
    elo <= lo and
    hi <= ehi and
    mrec = crec and
    mlo = clo + lo - elo and
    mhi = clo + hi - elo
  )
}

/** A value the walk from these bytes can find. */
private predicate heldValue(GraphNode n, string rec, int lo, int hi, string v) {
  exists(int flo, int fhi, int plo, int phi, string w |
    overlap(n, rec, lo, hi, flo, fhi, plo, phi) and
    value(n, rec, flo, fhi, w) and
    v = w.substring(plo - flo, phi - flo)
  )
  or
  exists(int flo, int fhi, int plo, int phi, int param |
    overlap(n, rec, lo, hi, flo, fhi, plo, phi) and
    receivedFact(n, rec, flo, fhi) and
    param = receivedParam(n.getProgram(), rec, plo, phi) and
    calleeName(n.getProgram(), param, rec, plo, phi, v)
  )
  or
  exists(GraphNode m, string mrec, int mlo, int mhi |
    step(n, rec, lo, hi, m, mrec, mlo, mhi) and heldValue(m, mrec, mlo, mhi, v)
  )
}

/** A value the jump or file site at `n` asks about can hold, its `part` the target, transaction or file. */
predicate answerValue(GraphNode n, string part, string v) {
  part = "target" and jumpTargetName(n.getStmt(), v)
  or
  part = "transid" and jumpTransidText(n.getStmt(), v)
  or
  exists(Field f, int lo, int hi | factExtent(n, part, _, _, f, lo, hi) |
    if question(n, part, _, _, _)
    then heldValue(n, f.getRecord(), lo, hi, v)
    else value(n, f.getRecord(), lo, hi, v)
  )
}

bindingset[v]
private string trimmed(string v) { result = v.regexpReplaceAll("\\s+$", "") }

/** A program the jump at `n` can go to, and whether only linking found it. */
private predicate callee(GraphNode n, Program callee, boolean discovered) {
  exists(string kind, string name | jump(n.getStmt(), kind, _) |
    kind = ["XCTL", "LINK", "CALL"] and
    exists(string v |
      answerValue(n, "target", v) and name = trimmed(v) and canName("program", name)
    ) and
    callee.getName() = name and
    if exists(string v | ownValue(n, "target", v) and trimmed(v) = name)
    then discovered = false
    else discovered = true
    or
    kind = ["RETURN_TRANSID", "START"] and
    exists(string t, string v |
      answerValue(n, "transid", v) and t = trimmed(v) and canName("program", t)
    |
      csd_transaction(t, name) and
      callee.getName() = name and
      if exists(string w | ownValue(n, "transid", w) and trimmed(w) = t)
      then discovered = false
      else discovered = true
    )
  )
}

/** A value the program's own walk gives the jump's operand, before linking. */
private predicate ownValue(GraphNode n, string part, string v) {
  part = "target" and jumpTargetName(n.getStmt(), v)
  or
  part = "transid" and jumpTransidText(n.getStmt(), v)
  or
  exists(Field f, int lo, int hi | factExtent(n, part, _, _, f, lo, hi) |
    value(n, f.getRecord(), lo, hi, v)
  )
}

/** The caller's area and the callee's, cut to the shorter. */
bindingset[clo, chi, elo, ehi]
private predicate linedUp(int clo, int chi, int elo, int ehi, int lchi, int lehi) {
  exists(int shared | shared = (chi - clo).minimum(ehi - elo) |
    lchi = clo + shared and lehi = elo + shared
  )
}

/**
 * The jump at `n` enters `callee` as its parameter `param`: the caller's bytes `clo` up to
 * `chi` of `crec` are the callee's `elo` up to `ehi` of `erec`. A RETURN with TRANSID enters
 * the next transaction's program as an XCTL does.
 */
predicate entering(
  GraphNode n, Program callee, int param, string crec, int clo, int chi, string erec, int elo,
  int ehi
) {
  edge(n, callee, param, crec, clo, chi, erec, elo, ehi, _, _, _)
}

/**
 * A link as `entering` gives it, with the bytes `nlo` up to `nhi` of `nrec` among the caller's
 * that hold the target's name, or no record when the caller's bytes do not cover the target.
 */
private predicate edge(
  GraphNode n, Program callee, int param, string crec, int clo, int chi, string erec, int elo,
  int ehi, string nrec, int nlo, int nhi
) {
  exists(Field mine, Field theirs, int chi0, int ehi0 |
    callee(n, callee, _) and
    jump(n.getStmt(), ["XCTL", "LINK", "CALL", "RETURN_TRANSID"], _) and
    jumpArea(n.getStmt(), param, mine) and
    received_area(callee, param, theirs) and
    crec = mine.getRecord() and
    clo = mine.getStart() and
    chi0 = mine.getEnd() and
    erec = theirs.getRecord() and
    elo = theirs.getStart() and
    ehi0 = theirs.getEnd() and
    linedUp(clo, chi0, elo, ehi0, chi, ehi) and
    if named(n, crec, clo, chi, _, _)
    then named(n, crec, clo, chi, nlo, nhi) and nrec = crec
    else (
      nrec = "" and nlo = 0 and nhi = 0
    )
  )
}

/** The target of the jump at `n` names its program by bytes `nlo` up to `nhi` of `rec`, within the caller's bytes `clo` up to `chi`. */
bindingset[rec, clo, chi]
private predicate named(GraphNode n, string rec, int clo, int chi, int nlo, int nhi) {
  jump(n.getStmt(), ["XCTL", "LINK", "CALL"], _) and
  question(n, "target", rec, nlo, nhi) and
  clo <= nlo and
  nhi <= chi
}

/** The START at `n` hands its FROM to the RETRIEVE at `r` of the program its transaction starts. */
predicate starting(
  GraphNode n, GraphNode r, string crec, int clo, int chi, string erec, int elo, int ehi
) {
  exists(Program callee, Field mine, Field theirs, int chi0, int ehi0 |
    callee(n, callee, _) and
    jump(n.getStmt(), "START", _) and
    jumpArea(n.getStmt(), _, mine) and
    r.getProgram() = callee and
    theirs =
      min(Field a, int p |
        jumpArea(r.getStmt(), p, a) and jump(r.getStmt(), "RETRIEVE", _)
      |
        a order by p
      ) and
    crec = mine.getRecord() and
    clo = mine.getStart() and
    chi0 = mine.getEnd() and
    erec = theirs.getRecord() and
    elo = theirs.getStart() and
    ehi0 = theirs.getEnd() and
    linedUp(clo, chi0, elo, ehi0, chi, ehi)
  )
}

/** A link from the jump at `n` was found only by linking. */
predicate discovered(GraphNode n, Program callee) { callee(n, callee, true) }

/** Why the walk from these bytes may be short of values, at these bytes alone. */
private predicate stepReason(GraphNode n, string rec, int lo, int hi, string r) {
  vertex(n, rec, lo, hi) and
  (
    not exists(int flo, int fhi, int plo, int phi | overlap(n, rec, lo, hi, flo, fhi, plo, phi)) and
    r = "not-recorded"
    or
    exists(int flo, int fhi, int plo, int phi | overlap(n, rec, lo, hi, flo, fhi, plo, phi) |
      keptReason(n, rec, flo, fhi, r) and
      not (r = "inbound-linkage" and receivedFact(n, rec, flo, fhi))
      or
      receivedFact(n, rec, flo, fhi) and
      r = "inbound-linkage" and
      (
        not exists(receivedParam(n.getProgram(), rec, plo, phi))
        or
        exists(int param | param = receivedParam(n.getProgram(), rec, plo, phi) |
          not entering(_, n.getProgram(), param, _, _, _, _, _, _)
          or
          exists(GraphNode c, string erec, int elo, int ehi |
            entering(c, n.getProgram(), param, _, _, _, erec, elo, ehi) and
            not (erec = rec and elo <= plo and phi <= ehi)
          )
        )
      )
    )
    or
    exists(int flo, int fhi, GraphNode w, int wlo, int whi |
      synthetic(n, rec, lo, hi, flo, fhi, w, wlo, whi)
    |
      not jump(w.getStmt(), ["CALL", "LINK", "RETRIEVE"], _) and
      reason(n, rec, flo, fhi, r) and
      writerExplained(r)
      or
      jump(w.getStmt(), ["CALL", "LINK"], _) and
      not exists(returnedParam(w, rec, wlo, whi)) and
      reason(n, rec, flo, fhi, r) and
      writerExplained(r)
      or
      exists(int param | returnedStop(w, rec, wlo, whi, param) |
        r = "from-callee" and
        (
          not entering(w, _, param, _, _, _, _, _, _)
          or
          exists(Program callee, string crec, int clo, int chi |
            entering(w, callee, param, crec, clo, chi, _, _, _)
          |
            not exists(GraphNode e | e.getProgram() = callee and jump(e.getStmt(), "EXIT", _))
            or
            not (crec = rec and clo <= wlo and whi <= chi)
          )
        )
      )
      or
      retrievedStop(w, rec, wlo, whi) and
      r = "not-a-literal" and
      (
        not starting(_, w, _, _, _, _, _, _)
        or
        exists(string erec, int elo, int ehi |
          starting(_, w, _, _, _, erec, elo, ehi) and
          not (erec = rec and elo <= wlo and whi <= ehi)
        )
      )
    )
  )
}

private predicate heldReason(GraphNode n, string rec, int lo, int hi, string r) {
  stepReason(n, rec, lo, hi, r)
  or
  exists(GraphNode m, string mrec, int mlo, int mhi |
    step(n, rec, lo, hi, m, mrec, mlo, mhi) and heldReason(m, mrec, mlo, mhi, r)
  )
}

/** Why the values the jump or file site at `n` asks about may be short, once programs are linked. */
predicate answerReason(GraphNode n, string part, string r) {
  exists(string rec, int lo, int hi | question(n, part, rec, lo, hi) |
    heldReason(n, rec, lo, hi, r)
  )
  or
  not question(n, part, _, _, _) and
  exists(Field f, int lo, int hi | factExtent(n, part, _, _, f, lo, hi) |
    reason(n, f.getRecord(), lo, hi, r)
  )
}
