---
name: harness-smoke-test
description: Test the harness skill pipeline with a small, deterministic workflow. Use when asked to test skills, verify harness skill loading, run a smoke test, or check that tools and permissions are wired correctly.
---
# Harness Smoke Test Skill

Use this skill to verify the harness can load a skill, run allowed tools, write an
artifact, and return a final answer without doing expensive repository analysis.

## Workflow

1. State that the harness smoke test is starting.
2. Run `pwd` with the bash tool.
3. Read `settings.json`.
4. Get an Eastern time timestamp with:

```text
TZ=America/New_York date "+%Y%m%d-%H%M%S-%Z"
```

5. Write a Markdown report to:

```text
harness-smoke-test/harness-smoke-test-YYYYMMDD-HHMMSS-EST.md
```

6. Final response must include:
   * PASS or FAIL
   * The saved report path
   * Which tools ran successfully
   * Any permission prompts or denied actions

## Report Template

```markdown
# Harness Smoke Test

Status: PASS
Timestamp: YYYYMMDD-HHMMSS-EST

## Checks

- Skill loaded: PASS
- bash pwd: PASS
- read_file settings.json: PASS
- EST timestamp: PASS
- write_file report: PASS

## Notes

[Brief notes about any unexpected behavior.]
```

## Constraints

* Do not inspect the full repository.
* Do not call `llm_summarize_python_files`.
* Do not use subagents.
* Stop after saving the report and giving the final response.
