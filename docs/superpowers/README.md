# Specs and plans

Dated design specs and TDD execution plans. Frozen: never edited after they are written.
New specs go in `specs/`, new plans in `plans/`, in the package subfolder when they concern one package.

## Specs

### Forge

- 2026-07-05 — [Monorepo Migration Design: Cicada/Squall/Jackal → red-dragon-forge](specs/2026-07-05-monorepo-migration-design.md)
- 2026-07-07 — [COBOL/CICS/JCL Knowledge Graph Design](specs/2026-07-07-cobol-knowledge-graph-design.md)
- 2026-07-07 — [Config-Driven Knowledge Graph Driver Design](specs/2026-07-07-knowledge-graph-config-driven-driver-design.md)
- 2026-07-09 — [Graph-Analysis-Core Decoupling — Design](specs/2026-07-09-graph-analysis-core-decoupling-design.md)
- 2026-07-10 — [Knowledge-Graph AST Store + Streaming Graph JSONL — Design](specs/2026-07-10-kg-ast-store-and-streaming-graph-design.md)
- 2026-08-29 — [Consolidating cobble into red-dragon-forge](specs/2026-08-29-cobble-consolidation-design.md)
- 2026-09-01 — [Deleting the stale graph stack ahead of the cobble consolidation](specs/2026-09-01-delete-stale-graph-stack-design.md)
- 2026-09-02 — [CICS interval control: START and RETRIEVE](specs/2026-09-02-cics-interval-control-design.md)
- 2026-09-02 — [Reconciling cobble's divergences: one canonical version of each module](specs/2026-09-02-cobble-divergence-reconciliation-design.md)
- 2026-09-03 — [CICS condition raising and HANDLE CONDITION dispatch](specs/2026-09-03-cics-condition-handling-design.md)
- 2026-09-05 — [Field-level byte dataflow for cobble](specs/2026-09-05-field-level-byte-dataflow-design.md)
- 2026-09-07 — [Cross-program byte dataflow across a commarea](specs/2026-09-07-cross-program-commarea-dataflow-design.md)
- 2026-09-07 — [Path-sampling byte trace — design](specs/2026-09-07-path-sampling-trace-design.md)
- 2026-09-14 — [Capabilities Presentation — Design](specs/2026-09-14-capabilities-presentation-design.md)
- 2026-09-17 — [TN3270 Green-Screen Terminal for Cicada — Design](specs/2026-09-17-tn3270-terminal-design.md)
- 2026-09-18 — [Serving the Db2 CardDemo screens over TN3270 — design](specs/2026-09-18-carddemo-db2-tn3270-design.md)
- 2026-09-28 — [cobble-viz-pathwalk — CFG Path-Walk Animation](specs/2026-09-28-pathwalk-animation-design.md)
- 2026-09-30 — [Resolving dynamic call targets in cobble — Unit 1, intra-program](specs/2026-09-30-cobble-dynamic-call-resolution-design.md)
- 2026-09-30 — [EXEC SQL WHENEVER in cobble's source CFG](specs/2026-09-30-cobble-exec-sql-whenever-cfg-design.md)
- 2026-10-01 — [Algorithm explainers — Design](specs/2026-10-01-algorithm-explainers-design.md)
- 2026-10-01 — [cobble: one tagged graph file instead of nodes.jsonl + edges.jsonl — Design](specs/2026-10-01-cobble-single-graph-file-design.md)
- 2026-10-02 — [Unmodelled writes, and values at every write source — Design](specs/2026-10-02-cobble-unmodelled-writes-and-read-values-design.md)
- 2026-10-02 — [Design: reachability from a PERFORM site, with return and abort semantics](specs/2026-10-02-execution-order-walk-design.md)
- 2026-10-02 — [Design: src-cfg files as JSONL](specs/2026-10-02-srccfg-jsonl-design.md)
- 2026-10-05 — [Cross-program dataflow: linking the per-program results](specs/2026-10-05-cross-program-dataflow-combine-design.md)
- 2026-10-07 — [Fixpoint restricted to call targets — design](specs/2026-10-07-call-target-restricted-fixpoint-design.md)
- 2026-10-08 — [Docs consolidation — design](specs/2026-10-08-docs-consolidation-design.md)
- 2026-10-08 — [Per-Program Area Need — Design](specs/2026-10-08-per-program-area-need-design.md)
- 2026-10-10 — [jackal: job-level domain model (blueprint)](specs/2026-10-10-jackal-job-level-domain-model-design.md)
- 2026-10-10 — [Building jackal's JCL object model](specs/2026-10-10-jackal-jcl-object-model-build-design.md)

### cicada

- 2026-06-12 — [Cicada Architecture Presentation — Design Spec](specs/cicada/2026-06-12-cicada-architecture-presentation-design.md)
- 2026-06-26 — [cicada VsamEngine → Shared Access-Method Engine Integration — Design](specs/cicada/2026-06-26-vsam-engine-integration-design.md)
- 2026-07-03 — [Dispatcher RETURN TRANSID wait timeout — design](specs/cicada/2026-07-03-dispatcher-return-transid-timeout-design.md)
- 2026-07-03 — [EXEC CICS WRITEQ TD operand resolution — design](specs/cicada/2026-07-03-writeq-td-operands-design.md)
- 2026-07-03 — [EXEC CICS WRITEQ TD RESP/EIBRESP writeback — design](specs/cicada/2026-07-03-writeq-td-resp-writeback-design.md)

### squall

- 2026-06-15 — [Richer SQL Model Types — Design](specs/squall/2026-06-15-sql-model-rich-types-design.md)
- 2026-06-27 — [squall DB2 Test Infrastructure (local + CI) — Design](specs/squall/2026-06-27-db2-ci-setup-design.md)

### jackal

- 2026-06-20 — [jackal — JCL Execution Layer (v1) — Design](specs/jackal/2026-06-20-jackal-jcl-runner-design.md)
- 2026-06-21 — [jackal v2 — run a real CardDemo batch job end-to-end — Design](specs/jackal/2026-06-21-jackal-v2-idcams-design.md)
- 2026-06-21 — [jackal — JCL parser via ANTLR grammar behind a Java bridge — Design](specs/jackal/2026-06-21-jcl-antlr-bridge-design.md)
- 2026-06-24 — [jackal — COND= conditional step execution — Design](specs/jackal/2026-06-24-cond-step-execution-design.md)
- 2026-06-26 — [jackal — PARM= → COBOL LINKAGE — Design](specs/jackal/2026-06-26-parm-linkage-design.md)
- 2026-06-27 — [jackal-vxb: Dataset Catalog — Generalized Allocation + Access Face](specs/jackal/2026-06-27-jackal-vxb-dataset-catalog-design.md)
- 2026-06-27 — [jackal — Temporary Datasets (&&NAME) — Design](specs/jackal/2026-06-27-temp-datasets-design.md)
- 2026-06-29 — [jackal — Backward References (DSN=*.STEP.DD) — Design](specs/jackal/2026-06-29-backward-refs-design.md)
- 2026-07-08 — [IDCAMS Comprehensive Grammar Design](specs/jackal/2026-07-08-idcams-comprehensive-grammar-design.md)
- 2026-07-08 — [JCL PROC expansion — design](specs/jackal/2026-07-08-jcl-proc-expansion-design.md)

### cobble

- 2026-07-11 — [Config-driven corpus extraction](specs/cobble/2026-07-11-corpus-config-design.md)
- 2026-09-04 — [Source CFG with reaching conditions and primitive data dependencies](specs/cobble/2026-09-04-src-cfg-reaching-conditions-design.md)

## Plans

### Forge

- 2026-07-04 — [CICS + EXEC SQL Composition Implementation Plan](plans/2026-07-04-cics-sql-composition.md)
- 2026-07-05 — [Monorepo Migration (Cicada/Squall/Jackal → red-dragon-forge) Implementation Plan](plans/2026-07-05-monorepo-migration.md)
- 2026-07-07 — [COBOL/CICS/JCL Knowledge Graph Implementation Plan](plans/2026-07-07-cobol-knowledge-graph.md)
- 2026-07-09 — [Graph-Analysis-Core Decoupling Implementation Plan](plans/2026-07-09-graph-analysis-core-decoupling.md)
- 2026-07-10 — [KG AST-Store + Streaming Graph JSONL — Implementation Plan](plans/2026-07-10-kg-ast-store-and-streaming-graph.md)
- 2026-09-01 — [Index items, SEARCH and the unknown-name policy — Implementation Plan](plans/2026-09-01-index-items-and-search.md)
- 2026-09-02 — [CICS Interval Control (START + RETRIEVE) Implementation Plan](plans/2026-09-02-cics-interval-control.md)
- 2026-09-03 — [CICS Condition Handling Implementation Plan](plans/2026-09-03-cics-condition-handling.md)
- 2026-09-05 — [Field-Level Byte Dataflow — Prerequisites Implementation Plan](plans/2026-09-05-field-level-byte-dataflow-prerequisites.md)
- 2026-09-06 — [Field-level byte dataflow — intra-program slice — Implementation Plan](plans/2026-09-06-field-level-byte-dataflow-intraprogram.md)
- 2026-09-07 — [Cross-program byte dataflow across a commarea — Implementation Plan](plans/2026-09-07-cross-program-commarea-dataflow.md)
- 2026-09-07 — [Path-Sampling Byte Trace Implementation Plan](plans/2026-09-07-path-sampling-trace.md)
- 2026-09-17 — [TN3270 Green-Screen Terminal Implementation Plan](plans/2026-09-17-tn3270-terminal.md)
- 2026-09-18 — [CardDemo Db2 over TN3270 Implementation Plan](plans/2026-09-18-carddemo-db2-tn3270.md)
- 2026-09-19 — [CardDemo Db2 Tier Implementation Plan](plans/2026-09-19-carddemo-db2-tier.md)
- 2026-09-28 — [cobble-viz-pathwalk Implementation Plan](plans/2026-09-28-pathwalk-animation.md)
- 2026-09-30 — [Dynamic Call Target Resolution (Unit 1) Implementation Plan](plans/2026-09-30-cobble-dynamic-call-resolution-unit-1.md)
- 2026-10-01 — [Algorithm explainers — Implementation Plan](plans/2026-10-01-algorithm-explainers.md)
- 2026-10-01 — [Dynamic CICS Operands (red-dragon-forge-gra) Implementation Plan](plans/2026-10-01-cobble-dynamic-cics-operands.md)
- 2026-10-01 — [cobble: one tagged graph file instead of nodes.jsonl + edges.jsonl — Implementation Plan](plans/2026-10-01-cobble-single-graph-file.md)
- 2026-10-02 — [src-cfg files as JSONL Implementation Plan](plans/2026-10-02-srccfg-jsonl.md)
- 2026-10-02 — [Reachability from a PERFORM site Implementation Plan](plans/2026-10-02-srccfg-reach.md)
- 2026-10-06 — [Cross-program Dataflow Combine Implementation Plan](plans/2026-10-06-cross-program-dataflow-combine.md)
- 2026-10-07 — [Call-target restricted fixpoint — implementation plan](plans/2026-10-07-call-target-restricted-fixpoint.md)
- 2026-10-10 — [JCL object model, unit 1: acceptance suite and CardDemo snapshot — implementation plan](plans/2026-10-10-jcl-object-model-unit1-acceptance.md)

### cicada

- 2026-06-26 — [cicada VsamEngine → Shared Engine Integration — Implementation Plan (Phase 2)](plans/cicada/2026-06-26-vsam-engine-integration.md)
- 2026-06-27 — [Cicada Transaction Flow Map — Implementation Plan](plans/cicada/2026-06-27-cicada-transaction-flow-map.md)
- 2026-07-03 — [Dispatcher RETURN TRANSID Wait Timeout Implementation Plan](plans/cicada/2026-07-03-dispatcher-return-transid-timeout.md)
- 2026-07-03 — [WRITEQ TD Operand Resolution Implementation Plan](plans/cicada/2026-07-03-writeq-td-operands.md)
- 2026-07-03 — [WRITEQ TD RESP/EIBRESP Writeback Implementation Plan](plans/cicada/2026-07-03-writeq-td-resp-writeback.md)

### squall

- 2026-06-13 — [RedDragon EXEC SQL Extension Seam — Implementation Plan](plans/squall/2026-06-13-reddragon-exec-sql-seam.md)
- 2026-06-14 — [Squall — Directive Grammar + SELECT INTO Vertical (slices 0–1)](plans/squall/2026-06-14-exec-sql-slice1.md)
- 2026-06-14 — [EXEC SQL Slice 2 Implementation Plan — INCLUDE→COPY preprocessing + typed codec](plans/squall/2026-06-14-exec-sql-slice2.md)
- 2026-06-15 — [Faithful CONNECT — Connection Registry + Lifecycle Implementation Plan](plans/squall/2026-06-15-faithful-connect.md)
- 2026-06-15 — [dclgen / data_layout Category Validation Implementation Plan](plans/squall/2026-06-15-field-meta-validation.md)
- 2026-06-15 — [Richer SQL Model Types Implementation Plan](plans/squall/2026-06-15-sql-model-rich-types.md)
- 2026-06-15 — [WHENEVER (SQLERROR / NOT FOUND) Implementation Plan](plans/squall/2026-06-15-whenever-sqlerror.md)
- 2026-06-27 — [squall DB2 Test Infrastructure Implementation Plan](plans/squall/2026-06-27-db2-ci-setup.md)

### jackal

- 2026-06-20 — [jackal JCL Runner (v1) Implementation Plan](plans/jackal/2026-06-20-jackal-jcl-runner.md)
- 2026-06-21 — [jackal v2 (IDCAMS + real CardDemo job) Implementation Plan](plans/jackal/2026-06-21-jackal-v2-idcams.md)
- 2026-06-21 — [JCL Parser via ANTLR Grammar behind a Java Bridge — Implementation Plan](plans/jackal/2026-06-21-jcl-antlr-bridge.md)
- 2026-06-24 — [COND= Conditional Step Execution — Implementation Plan](plans/jackal/2026-06-24-cond-step-execution.md)
- 2026-06-27 — [jackal-vxb: Dataset Catalog — Generalized Allocation + Access Face](plans/jackal/2026-06-27-jackal-vxb-dataset-catalog.md)
- 2026-06-27 — [PARM= → COBOL LINKAGE Implementation Plan](plans/jackal/2026-06-27-parm-linkage.md)
- 2026-06-27 — [Temporary Datasets (&&NAME) Implementation Plan](plans/jackal/2026-06-27-temp-datasets.md)
- 2026-06-29 — [Backward References (DSN=*.STEP.DD) Implementation Plan](plans/jackal/2026-06-29-backward-refs.md)
- 2026-07-08 — [Comprehensive IDCAMS Grammar Implementation Plan](plans/jackal/2026-07-08-idcams-comprehensive-grammar.md)
- 2026-07-08 — [JCL PROC Expansion Implementation Plan](plans/jackal/2026-07-08-jcl-proc-expansion.md)
- 2026-07-08 — [JCL Symbolic Value Type (Literal/Symbol) Implementation Plan](plans/jackal/2026-07-08-jcl-symbolic-value-type.md)

### cobble

- 2026-07-11 — [Config-Driven Corpus Extraction Implementation Plan](plans/cobble/2026-07-11-corpus-config.md)
- 2026-09-04 — [Source CFG with Reaching Conditions Implementation Plan](plans/cobble/2026-09-04-src-cfg-reaching-conditions.md)
