# Vibecoding Guardpack v2.3.7

## Why this exists — self-conditioning collapses the answer space

An LLM feeds its own just-written tokens back in as input for the next one. Because of this
self-conditioning, **the direction it commits to early gets reinforced as it goes.** Write
"this is a caching problem" in the first paragraph, and the rest of the reasoning tends to
justify that premise rather than test it. Attention being *able* to see the whole context is
not the same as actually looking widely across it.

The result is a single answer that reads fluent and confident. The problem is that it is
often **not one candidate chosen over others, but the first slip carried all the way to the
end.** Repeated patching, misdiagnosis stuck at one function, plausible prose standing in for
evidence, "it's done" when it isn't — these come from that structure, not from laziness.

**This pack is not about constraining Claude to make it less creative. It is the opposite.**
It interrupts the collapse toward one branch: separate observation from interpretation, keep
more than one candidate alive, and decide between them with evidence. It pushes *back* against
narrowing.

| What self-conditioning does | How the guardpack reverses it |
|---|---|
| Keeps justifying the first hypothesis | Separates observation, interpretation, speculation; allows `unknown` |
| Vision stuck at a single function | Widens to the **relevant system boundary** that separates cause from propagation |
| Plausible prose substitutes for proof | Requires execution evidence per claim, and states unverified scope |
| Patches in the same direction repeatedly | Halts auto-repair when no new discriminating information appeared |
| Fills in facts from memory | Requires current official sources for facts that change |

The same conclusion repeated by several agents is still one piece of evidence. Consensus count
is not evidence — that principle runs through the whole pack.

---

Behavioral guidelines and verification playbooks for Claude Code — reducing over-editing,
local-scope misdiagnosis, false completion claims, repeated patching, evidence laundering,
and risky external actions.

> **The playbooks themselves are written in Korean.** This page explains what the pack does
> and how to install it; the canonical rule files (`00`–`09`) that Claude reads are Korean.
> If you work with Claude Code in Korean, this pack is built for you.
> · [한국어 README](README.md)

## What it prevents

Situations that come up constantly in vibe coding:

| What happens | What the guardpack does |
|---|---|
| You ask for a one-line fix; it rewrites half the file | Restricts changes to the **minimum relevant scope** for the request |
| "All done!" — but it isn't | Requires **execution evidence** per claim and forces unverified scope to be stated |
| The same bug gets patched a different way each time | **Stops auto-repair** when attempts repeat without new discriminating information |
| Plausible-sounding filler in place of reasons | Separates **observation, interpretation, and speculation** |
| Commits, deploys, or deletes without asking | Requires **confirmation** before hard-to-reverse actions |
| Answers about versions, model names, and APIs from memory | Requires **checking current official sources** for facts that change |

## What it is based on

The pack reflects practical principles that Andrej Karpathy has publicly emphasized about
coding with LLMs. The term "vibe coding" comes from him, and the failure modes he pointed
to — changing too much at once, moving on without verification, trusting model output as-is —
are what this pack is built to reduce.

| Principle | Where it lands |
|---|---|
| Small steps, minimum change | `00` §5 — change only the **minimum relevant scope**; narrow bugs to minimum causal scope |
| Surface your assumptions | `00` §2 — state reasonable assumptions and proceed · `06-되묻기-기록` |
| Verifiable success conditions | `00` §6 · `02-완료-검증-가드` — map claims to evidence 1:1 |
| Don't trust model output at face value | `05-정직-보고` — provenance and decidability over confidence |

**This is not an official release by Karpathy or Anthropic.** It is a third-party Korean
implementation of publicly stated principles, and it does not generalize any single
statement into a universal law.

## Quick start

Python 3 is the only requirement. Installation has **two stages** — stage 1 alone does not
install the skills.

```bash
git clone https://github.com/ssd7830-cmyk/vibecoding-guardpack.git
cd vibecoding-guardpack

# Stage 1 — global core. Prints a plan only; writes nothing.
python3 -B install_guardpack.py

# Check CONFIG_ROOT and the listed changes. If there is no BLOCK,
# copy the NEXT_APPLY command from the output and run it verbatim.
```

If you see `BLOCK`, **nothing was written.** Do not delete or overwrite anything — find the
cause first. `installed hash differs` or `installed file missing` means a different build
already exists at the same version path; confirm the release origin and version, then follow
the per-cause steps in [docs/INSTALL.md](docs/INSTALL.md).

```bash
# Stage 2 — task routing skills (inside Claude Code)
claude plugin marketplace add "<absolute path to this folder>"
# then install vibecoding-guardpack from the registered marketplace
```

After installation, writing **"가드팩 기준으로"** ("by guardpack standards") in a conversation
routes the request to the matching playbook.

To uninstall, run `python3 -B rollback_guardpack.py`.

## How it is organized

`00-글로벌-코어.md` is the always-on core. `01`–`09` are playbooks loaded only when their
task boundary applies, through six routing skills:

| Skill | Loads when |
|---|---|
| `guardpack` | Phrase trigger — routes to the right playbook below |
| `guardpack-completion-check` | Verifying whether something is actually done |
| `guardpack-debug-evidence` | Unclear root cause, repeated failures, high-impact fixes |
| `guardpack-context-intent` | Untrusted external material, long-session drift, handoffs |
| `guardpack-evidence-review` | Source-based research, product facts that change |
| `guardpack-safety-audit` | Manual only — permissions/sandbox/hooks audit |

`09-행동-회귀-테스트.md` pins the intended behavior as fixtures T01–T30, applied to the pack
itself as well as to reviewers.

## Limits

This pack **lowers the chance of accidents; it is not a security boundary.** `CLAUDE.md` is
context the model reads, not an enforced policy. If deletion, secrets, deployment, payments,
or outbound messages must be blocked, configure `permissions`, `sandbox`, and `hooks`
separately and run real blocking tests. LLM behavior is probabilistic — identical guidance
does not produce identical actions every time.

## Verification

```bash
python3 -B verify_guardpack.py          # config/manifest audit
python3 -B -m unittest discover -s tests # 197 deterministic regression tests
```

The verifier reports `PASS (partial)` by design: static reachability, user global memory,
and actual enforcement each need separate audits, and it says so rather than overstating.

## Documentation

| | |
|---|---|
| [README.md](README.md) | Korean README (canonical) |
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | Two-stage install and invocation, for learners |
| [docs/INSTALL.md](docs/INSTALL.md) | What the installer changes, BLOCK handling, rollback |
| [docs/EVALUATION.md](docs/EVALUATION.md) | Running the behavioral regression suite |
| [docs/MAINTAINERS.md](docs/MAINTAINERS.md) | Version history, PDF/ZIP builds |

## License

[MIT](LICENSE)
