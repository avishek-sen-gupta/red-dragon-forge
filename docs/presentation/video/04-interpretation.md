# 4. Interpretation: an agent that answers from the artifacts

**On screen:** Claude Code at the repo root. The `cobble-artifacts` skill tells it what every
artifact holds, which tool reads it, and how to judge a surprising hop. It reasons live, so each
take differs; record a couple and keep the clearest.

Start each question with the run it should use, e.g. "Using `$RUN`, …" with the directory spelled
out.

## Q1: where does the balance come from, and who can change it?

> Using `<RUN>`: where does the current balance on the account-view screen come from, and which
> programs can change it?

What a good answer contains, so you can tell a good take:
- the screen label "Current Balance" is field `ACURBAL` on map `CACTVWA` (screen metadata);
- a backward trace from `COACTVWC.ACURBALO` reaches `ACCT-CURR-BAL`, read from the account file;
- that CICS file and the batch jobs' DDs are one dataset, `ACCTDATA.VSAM.KSDS`, where the balance
  is bytes 12 to 24 (partition graph);
- the programs writing those bytes: interest posting (CBACT04C), daily transaction posting
  (CBTRN02C), bill payment (COBIL00C) and the account-update screen (COACTUPC);
- every step cites the artifact it came from; no source was read to get there.

**Talking point:** the chain crosses a screen, two programs, a CICS file name and a batch DD name.
No single file of source contains it.

## Q2: if the card number widens, what breaks?

> Using `<RUN>`: if the card number widens from 16 to 19 digits, what has to change?

What a good answer contains:
- it finds the files holding a card number and walks every copy of those 16 bytes
  (`cobble-experimental-partition-copies`): roughly 90 places in about 20 programs, across the
  card, cross-reference (and its alternate index), transaction, daily-transaction, reject and
  system-transaction files, the export program's record buffers, the commarea and the screens;
- it flags at least one copy a name search would miss: COTRN02C's `CDEMO-CT02-TRN-SELECTED`
  carries a card number;
- it says what the walk cannot see: key lookups (`RIDFLD`, `KEY IS`), table rows written through a
  computed subscript (the card list screen), and records with several layouts in one file
  (the export file read by CBIMPORT).

**Talking points**
- The artifacts did the counting; the agent chose where to start, checked the odd hops, and said
  where the facts run out.
- Those last points are where judgement is needed, and the honest answer names them instead of
  smoothing them over.

## Optional: one question it should refuse

> Using `<RUN>`: what is the balance of account 00000000001 right now?

A good answer says no artifact holds runtime values, and points at the headless tests (segment 3)
as where data is checked.
