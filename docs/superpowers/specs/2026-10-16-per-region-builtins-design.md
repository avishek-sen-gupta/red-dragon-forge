# One builtins table per region, passed to each run (red-dragon-xaah)

Date: 2026-10-16. Decided by the user; implemented in red-dragon `a0bf052f` and the forge commit
that bumps `vendor/red-dragon` to it.

## Before

red-dragon kept every builtin in one process-global, mutable class attribute,
`Builtins.TABLE: dict[FuncName, Any]`. squall's `install_sql_runtime` and cicada's
`install_cics_runtime` wrote into it; cicada's `register_default` kept squall's hooks whichever
installed first; LINK swapped `__cics_task_end_hook` out and back. One runtime per process, tests
that snapshot and restore the table by hand, and an `Any` value type.

## Decisions

1. **The table is passed to the run.** `run_linked`, `run_linked_resumable`, `resume_linked` and
   `run_linked_traced` take a required keyword-only `builtins: Mapping[FuncName, Builtin]`. It
   travels through `VMConfig.builtins` into `HandlerContext.builtins`, the way
   `permit_unresolved_call_targets` does; `CALL_FUNCTION` looks builtins up there. `run()` uses
   `core_builtins()`. It is not on `VMState`.
2. **`Builtins.TABLE` is gone.** `core_builtins()` returns a fresh read-only core table.
   `METHOD_TABLE` is a read-only module constant typed `Mapping[FuncName, MethodBuiltin]`.
3. **`Builtin` protocol** (`interpreter/vm/builtin.py`): `(args: list[TypedValue], vm: VMState, /)
   -> BuiltinResult`. `MethodBuiltin` adds the receiver. No `Any`.
4. **Composition refuses duplicates.** `compose_builtins(*tables)` raises `DuplicateBuiltinError`
   naming the `FuncName` two tables share. Nothing overwrites by name.
5. **Runtimes return entries; hooks are passed explicitly.**
   - squall: `install_sql_runtime` returns `SqlRuntime(entries, reset_session, syncpoint,
     rollback)`; `entries` holds `__exec_sql` only. squall names no `__cics_*` builtin.
     `squall/strategy_stores.py` is deleted.
   - cicada: `install_cics_runtime(..., hooks: TransactionHooks = NO_HOOKS, other_builtins={})`
     returns `CicsRuntime(entries, builtins, start_queue)`. `TransactionHooks` (frozen; `task_end`,
     `syncpoint`, `rollback`, each a no-op by default) puts exactly one entry under each
     `__cics_*_hook` name. `builtins` is `compose_builtins(core_builtins(), entries,
     other_builtins)`. `register`, `register_default`, `swap` and `restore` are gone.
   - forge: `if "sql" in package.manifest.coprocessors` decides whether `Db2Connection.install`
     runs; it returns a `Coprocessing` with squall's hooks packed into `TransactionHooks`, squall's
     entries and the backend's rollback. `[cics]` passes them to `assemble_region`, whose region
     gives the table to every task (dispatcher, conversational, START, XCTL); `[plain]`/`[jcl]`
     give `JobRunner` `compose_builtins(core_builtins(), entries)`, which reaches every step,
     the Db2/TSO step included.
   - LINK runs its target with the region table and `__cics_task_end_hook` replaced by the no-op,
     in a new mapping. The region table is never changed.
6. Tests build their own tables; the root suite's autouse `_reset_builtins_table` and every
   manual snapshot/restore of `Builtins.TABLE` are deleted.

## LINK reaching its own table

The LINK builtin is an entry of the table it must pass on. Ruling: **a closure, not a Holder.**
`install_cics_runtime` defines `region_builtins()` returning the local `table`, builds the
entries (LINK given `region_builtins`), then binds `table = compose_builtins(...)`. Python closes
over the variable, so LINK reads the composed table when it runs; nothing is assigned after the
table is built, and no caller has to fill a holder. This is why cicada composes the region table
(given forge's `other_builtins`) rather than forge composing after the fact.
