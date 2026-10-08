# jackal

jackal runs mainframe JCL batch jobs on the red-dragon interpreter: it parses JCL, sequences
steps with `COND=`, tracks datasets in a job-scoped catalog, runs COBOL steps on the VM and
emulates IEFBR14 and IDCAMS.

- Architecture: [../docs/reference/jackal/architecture.md](../docs/reference/jackal/architecture.md)
- Running a job: [../docs/how-to/run-jcl-job.md](../docs/how-to/run-jcl-job.md)
