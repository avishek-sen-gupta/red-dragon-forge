/**
 * The values bytes can hold where a node reads them, and why the values may be short, as
 * cobble's fixpoint gives them, piece by piece as it cuts a read. A write contributes what
 * it puts in bytes that contain the piece: a literal, fitted as cobble fits it, or the
 * values a MOVE carries from its source at that node, refitted. A write that does not
 * contain the piece, or a MOVE carrying only doubt about its source, gives no value, only
 * that the bytes were written. The program's start gives the initial image where it
 * contains the piece, else says the bytes were never written. Bytes in LINKAGE with no
 * value come from a caller.
 */

import cobol.Definers

private string definersOf(GraphNode n, Atom a) {
  readAtom(n, _, a) and result = concat(GraphNode d | definer(n, a, d) | d.getId(), " ")
}

private predicate cut(GraphNode n, Field f, int b) {
  exists(Atom a | readAtom(n, f, a) |
    b = a.getLo() and
    not exists(Atom p | readAtom(n, f, p) and p.getHi() = b and definersOf(n, p) = definersOf(n, a))
    or
    b = a.getHi() and
    not exists(Atom q | readAtom(n, f, q) and q.getLo() = b and definersOf(n, q) = definersOf(n, a))
    or
    exists(int lo, int hi | slicedAccess(n.getStmt(), f, lo, hi) | b = [lo, hi] and a.getLo() = b)
  )
}

/**
 * Bytes `lo` up to `hi` of `f` that the node `n` reads, cut where the writes that can
 * reach them change and where a slice of it begins or ends, as cobble's fixpoint cuts a
 * read into pieces.
 */
predicate piece(GraphNode n, Field f, int lo, int hi) {
  exists(int i |
    lo = rank[i](int b | cut(n, f, b)) and
    hi = rank[i + 1](int b | cut(n, f, b)) and
    exists(Atom a | readAtom(n, f, a) and a.getLo() = lo)
  )
}

/** Bytes `lo` up to `hi` of record `rec` that the node `n` reads: a piece, what a jump reads whole, or a MOVE's carried source. */
predicate readBytes(GraphNode n, string rec, int lo, int hi) {
  exists(Field f | piece(n, f, lo, hi) and rec = f.getRecord())
  or
  exists(Field f | jumpExtent(n, _, _, _, f, lo, hi) and rec = f.getRecord())
  or
  carriedWrite(n, _, _, _, rec, lo, hi, _)
}

bindingset[c, offset, length]
private predicate placed(Field c, int offset, int length, string rec, int lo, int hi) {
  rec = c.getRecord() and lo = c.getStart() + offset and hi = lo + length
}

private predicate literalWrite(GraphNode d, string rec, int lo, int hi, string v) {
  exists(Field c, int offset, int length |
    cfg_value(d, c, offset, length, v) and placed(c, offset, length, rec, lo, hi)
  )
}

private predicate reasonWrite(GraphNode d, string rec, int lo, int hi, string r) {
  exists(Field c, int offset, int length |
    cfg_value_reason(d, c, offset, length, r) and placed(c, offset, length, rec, lo, hi)
  )
}

private predicate carriedWrite(
  GraphNode d, string rec, int lo, int hi, string srec, int slo, int shi, boolean right
) {
  exists(Field c, int offset, int length, Field s, int soffset, int slength |
    cfg_carries(d, c, offset, length, s, soffset, slength, right) and
    placed(c, offset, length, rec, lo, hi) and
    placed(s, soffset, slength, srec, slo, shi)
  )
}

bindingset[rec, lo, hi, wrec, wlo, whi]
private predicate covers(string wrec, int wlo, int whi, string rec, int lo, int hi) {
  wrec = rec and wlo <= lo and hi <= whi
}

/** Some write at `d` holds all of the bytes, with a value or a reason of its own. */
private predicate contains(GraphNode d, string rec, int lo, int hi) {
  readBytes(_, rec, lo, hi) and
  exists(string wrec, int wlo, int whi |
    literalWrite(d, wrec, wlo, whi, _) or
    reasonWrite(d, wrec, wlo, whi, _) or
    carriedWrite(d, wrec, wlo, whi, _, _, _, _)
  |
    covers(wrec, wlo, whi, rec, lo, hi)
  )
}

bindingset[a, rec, lo, hi]
private predicate overlaps(Atom a, string rec, int lo, int hi) {
  a.getRecord() = rec and a.getLo() < hi and lo < a.getHi()
}

private predicate reaches(GraphNode n, string rec, int lo, int hi, GraphNode d) {
  exists(Atom a | definer(n, a, d) and readBytes(n, rec, lo, hi) and overlaps(a, rec, lo, hi))
}

private predicate readAtom(GraphNode n, string rec, int lo, int hi, Atom a) {
  readBytes(n, rec, lo, hi) and
  overlaps(a, rec, lo, hi) and
  (definer(n, a, _) or startReaches(n, a))
}

/**
 * The write at `d` can be what all of the bytes hold where `n` reads them: a write a later
 * one partly overwrote holds none of them whole, so it lends them no value.
 */
private predicate holds(GraphNode n, string rec, int lo, int hi, GraphNode d) {
  reaches(n, rec, lo, hi, d) and
  not exists(Atom a | readAtom(n, rec, lo, hi, a) and not definer(n, a, d))
}

/** The write at `d` can be what some of the bytes hold where `n` reads them. */
predicate writer(GraphNode n, string rec, int lo, int hi, GraphNode d) { reaches(n, rec, lo, hi, d) }

private predicate fromStart(GraphNode n, string rec, int lo, int hi) {
  exists(Atom a | startReaches(n, a) and readBytes(n, rec, lo, hi) and overlaps(a, rec, lo, hi))
}

private predicate inLinkage(GraphNode n, string rec) {
  exists(Field f | f.getProgram() = n.getProgram() and f.getRecord() = rec |
    field_region(f, "linkage")
  )
}

/** Why written bytes with no value of their own have none, as the read at `n` sees them. */
bindingset[n, rec]
private predicate written(GraphNode n, string rec, string r) {
  if inLinkage(n, rec) then r = "inbound-linkage" else r = "not-a-literal"
}

bindingset[sv, width, right]
private string fitted(string sv, int width, boolean right) {
  if sv.length() >= width
  then
    if right = true then result = sv.suffix(sv.length() - width) else result = sv.prefix(width)
  else
    exists(string pad | pad = concat(int i | i in [1 .. width - sv.length()] | " ") |
      if right = true then result = pad + sv else result = sv + pad
    )
}

/** A value the bytes can hold where `n` reads them. */
predicate value(GraphNode n, string rec, int lo, int hi, string v) {
  exists(GraphNode d | holds(n, rec, lo, hi, d) |
    exists(string wrec, int wlo, int whi, string w |
      literalWrite(d, wrec, wlo, whi, w) and covers(wrec, wlo, whi, rec, lo, hi)
    |
      v = w.substring(lo - wlo, hi - wlo)
    )
    or
    exists(string wrec, int wlo, int whi, string srec, int slo, int shi, boolean right, string sv |
      carriedWrite(d, wrec, wlo, whi, srec, slo, shi, right) and
      covers(wrec, wlo, whi, rec, lo, hi) and
      value(d, srec, slo, shi, sv)
    |
      v = fitted(sv, whi - wlo, right).substring(lo - wlo, hi - wlo)
    )
  )
  or
  fromStart(n, rec, lo, hi) and
  exists(Field c, int offset, int length, string iv, string wrec, int wlo, int whi |
    initial_value(c, offset, length, iv) and
    c.getProgram() = n.getProgram() and
    placed(c, offset, length, wrec, wlo, whi) and
    covers(wrec, wlo, whi, rec, lo, hi)
  |
    v = iv.substring(lo - wlo, hi - wlo)
  )
}

/** Why the bytes have no value of their own where `n` reads them, carried values aside. */
private predicate ownReason(GraphNode n, string rec, int lo, int hi, string r) {
  exists(GraphNode d | reaches(n, rec, lo, hi, d) |
    holds(n, rec, lo, hi, d) and
    exists(string wrec, int wlo, int whi |
      reasonWrite(d, wrec, wlo, whi, r) and covers(wrec, wlo, whi, rec, lo, hi)
    )
    or
    not (contains(d, rec, lo, hi) and holds(n, rec, lo, hi, d)) and
    written(n, rec, r)
  )
  or
  fromStart(n, rec, lo, hi) and
  not exists(Field c, int offset, int length, string wrec, int wlo, int whi |
    initial_value(c, offset, length, _) and
    c.getProgram() = n.getProgram() and
    placed(c, offset, length, wrec, wlo, whi) and
    covers(wrec, wlo, whi, rec, lo, hi)
  ) and
  if inLinkage(n, rec) then r = "inbound-linkage" else r = "uninitialised"
}

/** A MOVE at `d`, reaching the bytes where `n` reads them, carries them from these. */
private predicate carriedFrom(
  GraphNode n, string rec, int lo, int hi, GraphNode d, string srec, int slo, int shi
) {
  holds(n, rec, lo, hi, d) and
  exists(string wrec, int wlo, int whi |
    carriedWrite(d, wrec, wlo, whi, srec, slo, shi, _) and covers(wrec, wlo, whi, rec, lo, hi)
  )
}

private predicate carriedReason(GraphNode n, string rec, int lo, int hi, string r) {
  ownReason(n, rec, lo, hi, r)
  or
  exists(GraphNode d, string srec, int slo, int shi |
    carriedFrom(n, rec, lo, hi, d, srec, slo, shi) and carriedReason(d, srec, slo, shi, r)
  )
}

/** The bytes have a value where `n` reads them, or a reason that is more than doubt about whether they were written. */
private predicate informative(GraphNode n, string rec, int lo, int hi) {
  value(n, rec, lo, hi, _)
  or
  exists(string r | carriedReason(n, rec, lo, hi, r) | not r = ["not-a-literal", "uninitialised"])
}

/**
 * Why the values the bytes can hold where `n` reads them may be short. A MOVE carries its
 * source's reasons, but one carrying only doubt about whether the source was written
 * leaves bytes that are written with no value.
 */
predicate reason(GraphNode n, string rec, int lo, int hi, string r) {
  ownReason(n, rec, lo, hi, r)
  or
  exists(GraphNode d, string srec, int slo, int shi, string sr |
    carriedFrom(n, rec, lo, hi, d, srec, slo, shi) and reason(d, srec, slo, shi, sr)
  |
    if sr = ["not-a-literal", "uninitialised"] and not informative(d, srec, slo, shi)
    then written(n, rec, r)
    else r = sr
  )
}
