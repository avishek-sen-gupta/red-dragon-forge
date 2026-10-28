# 3. Runtime evidence: the app really runs

Static facts are claims about the code. Running the code checks them.

## The real screens (about 1 minute)

**On screen:** CardDemo's 3270 screens, driven by c3270: sign on, view an account, update it; an
admin adds, updates and deletes a user.

```bash
. ./bridge-env.sh
bash docs/presentation/capture/carddemo_3270_video.sh   # writes docs/presentation/artifacts/cics/carddemo-3270.mp4
```

Play the MP4. Say only that this is CardDemo running under an interpreter on this laptop: no
mainframe. Keep the focus on the application, not the runtime.

## Headless tests that assert on data (about 6 minutes)

**On screen:** the test runs, then one test's source.

```bash
. ./bridge-env.sh
cd cicada && uv run --no-sync python -m pytest tests/integration/cics/test_carddemo_terminal_screen.py -v -n0
```

```bash
cd ..
. ./carddemo-env.sh && . tests/integration/db2_env.sh
uv run --no-sync python -m pytest tests/integration/test_carddemo_db2_headless.py -v
```

**Talking points**
- The same programs, driven by a script instead of a person: type into a screen, press Enter,
  read the next screen.
- Each test asserts on data at a stage: what the screen shows, what the file or table holds
  afterwards. That is the runtime version of the video's idea: facts, checked.
- Open one test and read an assertion aloud, e.g. the expected screen text after sign-on.

`docs/presentation/capture/headless.sh` runs both and captures them as a terminal screenshot, if a
still is easier to edit in.
