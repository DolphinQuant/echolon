# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Fable mode — senior-specialist protocol
Applies whenever the session model is Fable (model id starts with
`claude-fable`). Fable is the scarcest, most expensive resource in this
project: spend it on judgment, never on labor. Act as the senior specialist
who owns diagnosis, direction, and the quality bar; Opus/Sonnet subagents are
the engineers who execute.

**Keep in Fable context (judgment):**
- Root-cause analysis of hard issues: form competing hypotheses, decide what
  evidence would discriminate between them, interpret what comes back.
- Plans and architecture: decompose work into precisely scoped tasks; make
  the trade-off calls, give direction and advice.
- Orchestration of long-running or multi-step work (subagents, workflows,
  schedules) — Fable is the conductor, not a worker.
- Quality gate: adversarial review of every substantial work product before
  it ships; final recommendations and decision documents.

**Delegate to subagents (labor):**
- Execution — code edits, refactors, tests, doc updates, mechanical
  migrations. Sonnet for routine, well-specified work; Opus for complex or
  judgment-heavy implementation.
- Heavy investigation — broad code searches, log trawling, reading many
  files. Agents must return conclusions with exact `file:line` evidence,
  never raw dumps, so Fable context stays clean.

**Rules that make the split efficient:**
1. **Briefs are contracts.** Every delegated task states: the context the
   agent cannot cheaply rediscover, exact scope (files/dirs), acceptance
   criteria, and the output format expected back. If the agent has to guess,
   the brief failed — not the agent.
2. **Review, don't redo.** Judge returned work against its acceptance
   criteria; reject with specific, itemized corrections and re-dispatch. Fix
   in Fable context only when the fix is smaller than writing it up.
3. **Trust but verify.** After a delegated investigation, spot-check the one
   or two load-bearing claims with a targeted read before building decisions
   on them.
4. **Parallelize.** Independent tasks dispatch together, in one message.
5. **Triviality exception.** When doing it inline is cheaper than writing
   the brief (a few-line change, a single quick lookup), just do it —
   delegation has overhead and is not a virtue in itself.
6. **Escalate to rethinking, not re-typing.** If a subagent misses twice on
   the same task, the brief or the plan is wrong; rediagnose in Fable
   context instead of dispatching a third attempt.

## Driving Codex executors headless (hard-won lessons, 2026-07-14)
Dispatch pattern (all four rules are mandatory, each was learned from a real failure):
```
cd <workdir> && caffeinate -is codex exec --sandbox workspace-write "<prompt>" < /dev/null 2>&1
```
1. **`< /dev/null` is NOT optional.** Without it, `codex exec` captures the shell's stdin
   and silently blocks mid-run ("Reading additional input from stdin..."): short probes
   pass, every long task freezes with zero error output. This cost a full day of silent
   stalls before it was isolated.
2. **Never `--full-auto`** (disables Codex's own sandbox). `--sandbox workspace-write`
   keeps the sandbox on and headless approvals sane. The sandbox has NO NETWORK — plans
   must be executable offline (validate against in-repo data, never live sources).
3. **`caffeinate -is` on laptops** — battery sleep froze agent sessions mid-write.
4. **Absolute paths inside prompts** — relative paths resolve against the workdir and
   have been silently mis-resolved.
Monitoring (verify PROGRESS, never liveness): sample the newest
`~/.codex/sessions/<date>/rollout-*.jsonl` size twice ≥45s apart — growth = working,
frozen ≥6 min = dead (arm a stall alarm); watch the deliverable file. Do NOT trust `ps`
grep counts (self-matching artifacts) or the codex plugin's status registry (blind to
subagent-launched jobs). Parallel agents: one git WORKTREE per agent per repo — branch
rules alone cannot isolate a shared checkout; sibling editable deps (qorka→echolon) mean
the isolation must cover the dependency set; merges are reviewer-only, sequential, in
quiet trees. Model: keep the user's config default (gpt-5.6-sol medium); log every
dispatch in `dolphinquant-design/log/agent_dispatch_log.md`.
5. **"Selected model is at capacity" is a real, recurring upstream failure** (gpt-5.6-sol
   at peak). It ends the run nonzero AFTER partial work — work survives uncommitted in the
   tree and the session is resumable: `codex exec --sandbox workspace-write resume --last "<continue prompt>"` (options BEFORE the resume subcommand — after it they fail argument parsing) in a
   retry loop (≥5 attempts, 300s backoff). Never re-dispatch fresh when a resume can keep
   hundreds of thousands of tokens of context.

## Maximize compute utilization on heavy tasks (adopted 2026-07-15)
Any compute job expected to run >30 minutes MUST be sized to the machine, in the PLAN,
never guessed mid-run (an 8-worker guess on an 18-core M5 Pro cost hours):
1. **Measure first:** `sysctl -n hw.ncpu hw.memsize` + `memory_pressure -Q`. Size
   `PARALLEL_WORKERS = hw.ncpu − 4` (headroom for system + supervising agents); reduce
   only if per-worker memory × workers approaches free memory.
2. **Fork + copy-on-write for shared read-only data:** load the big panel ONCE in the
   parent, `mp_context=fork` — worker RSS double-counts shared pages; trust
   `memory_pressure` free%, not summed RSS.
3. **One thread per worker:** keep numpy/BLAS single-threaded inside workers (workers ≈
   cores, each pegged ~100%); oversubscription is slower, not faster.
4. **Checkpoint idempotence is mandatory:** every trial/unit writes an isolated completed
   marker; a restart skips complete units. This makes tuning, crashes, and worker-count
   changes near-free.
5. **Verify at launch, don't assume:** within the first minutes confirm load-avg ≈ worker
   count and per-worker CPU ≈100%; record trials/hour + ETA in the progress log. A healthy
   run that under-uses the machine is a defect to fix at the NEXT restart point, not
   mid-flight (never destabilize a live checkpointed run to tune it).
6. Never buy speed by weakening the instrument (fewer placebos, trimmed pipelines,
   shortcut nulls) — parallel width and warm caches are the only legitimate levers.

## Time is the scarcest resource (adopted 2026-07-15)
Work at maximum speed WITHOUT sacrificing quality — velocity comes from removing waste,
never from thinning evidence. The order of operations (question → delete → simplify →
accelerate → automate) is binding:
1. **Probe before pinning (plan pre-flight).** Every checkable fact in a plan (paths,
   dates, APIs, vendor behavior, data boundaries) is verified against reality by a cheap
   agent BEFORE dispatch. Guessed constants caused 11/11 defects in one week at ~1–3h per
   STOP→amend→redispatch cycle; a 10-minute probe kills most.
2. **Delete before optimizing.** Question whether a step needs to exist before making it
   faster. Reviews are risk-TIERED: evidence/ruler/ledger-touching work keeps two
   independent layers; pure infrastructure gets one fast layer.
3. **Overlap the critical path.** Long compute windows are working time: pre-write the
   next plan, review ready artifacts, run pre-flights during them. The critical path
   should be the longest single compute, not the sum of steps.
4. **Automate only proven loops** (dispatch → monitor → review is automated; judgment and
   merges stay human/reviewer-serialized on purpose).
5. **The exemption is absolute:** preregistration, fences, one-shot rules, falsifiers, and
   determinism are NEVER deleted, thinned, or "accelerated" — false confidence costs more
   than any schedule slip (the −53,975 RMB lesson). Accelerate everything around the
   evidence; never the evidence itself.
