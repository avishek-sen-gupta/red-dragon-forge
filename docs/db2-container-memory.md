# The Db2 container needs a VM with at least 6 GiB

Squall's Db2 backend and `red-dragon-forge`'s one live-Db2 end-to-end test run against the
`squall-db2` container (`cd squall && make db2-up`). On a memory-starved VM it fails in a way
that does not look like a memory problem — this is that failure and what to do about it.

`icr.io/db2_community/db2` is amd64-only, so on Apple Silicon it runs under emulation, and
`db2sysc` maps roughly **3 GB of virtual memory**. Give the container VM **6 GiB or more**.
A second Db2 container sharing the VM doubles the requirement.

Starved of memory, Db2 fails in a way that does not look like a memory problem: the
*container stays up and reports no restart*, while the database manager is killed underneath
it. Tests then fail with `SQL30081N` (communication error), and a local connect reports
`SQL1032N  No start database manager command was issued`. `docker stats` looks innocent —
it reports resident memory, not the mapping that triggers the kill. The real evidence is the
kernel log:

```bash
docker exec squall-db2 dmesg | grep -i oom
# Out of memory: Killed process ... (db2sysc) total-vm:3128012kB
# oom-kill: constraint=CONSTRAINT_NONE ... global_oom
```

`global_oom` means the VM ran out, not the container's cgroup — so a per-container
`mem_limit` will not help.

**Raising the VM alone does not fix this.** `INSTANCE_MEMORY` defaults to
`AUTOMATIC`, so Db2 sizes itself to a share of whatever memory it can see and grows
into it over a session's worth of connections: a 2 GiB VM died within minutes, a
6 GiB VM ran five hours and then died the same way with the container holding
5.4 GiB. Give the VM headroom **and** cap the instance:

```bash
colima stop && colima start --cpu 4 --memory 6   # colima; Docker Desktop: Settings -> Resources
docker exec squall-db2 bash -lc \
  "su - db2inst1 -c 'db2 update dbm cfg using INSTANCE_MEMORY 262144'"
cd squall && make db2-restart
```

262144 pages is 1 GiB, ample for these test databases. The setting lives in the
container's `dbm cfg`, so `make db2-clean` or a rebuilt container loses it.

**The cap alone is still not sufficient** — it bounds database manager shared
memory, not agent private memory or the process's total footprint, which is what
the kernel kills on. A capped instance has been observed OOM-killed at ~4.8 GiB
resident / ~9 GiB mapped after 23 hours, with the container still reporting
`(healthy)`. Treat the cap as reducing the frequency, not eliminating the failure;
see bead forge-zka.

`cd squall && make db2-restart` revives a killed instance in about fifteen seconds without a
re-init, which is the fast way out when it happens mid-run.
