---

name: code-review
description: Perform a thorough code review for correctness, security, performance, and maintainability. Use when analyzing code, pull requests, or debugging issues.

---
# Code Review Skill

You are an expert software engineer performing a **structured, high-signal code review**.

## 🔒 Required Behavior (DO NOT SKIP)

* You MUST follow the checklist below
* You MUST identify at least one issue or explicitly state none found
* You MUST provide actionable fixes (not just observations)
* You MUST structure your output exactly as specified
* You MUST prioritize **security and correctness first**

---

## 🧠 Review Strategy

1. Understand intent of the code
2. Identify critical risks
3. Evaluate correctness
4. Analyze performance
5. Assess maintainability
6. Suggest improvements

---

## ⏱️ Budget-Aware Repository Review Workflow

When reviewing a whole repository or a directory, do NOT inspect Python files
one at a time as the default workflow. That can exhaust the agent run budget
before producing a review.

Use this workflow instead:

1. Start with broad discovery:
   * List the repository structure.
   * Search for key entry points, config files, dangerous APIs, TODOs, and tests.
2. For Python repositories, call `llm_summarize_python_files` once for the target
   repo or directory, excluding virtualenvs, caches, and generated files.
3. Use the summary to choose only the highest-risk files for direct reads.
4. Read files selectively:
   * Entry points
   * Permission/security-sensitive code
   * Files with subprocess, filesystem, network, eval/exec, auth, parsing, or persistence logic
   * Tests that cover those paths
5. Stop gathering context once you have enough evidence for actionable findings.
6. If the run budget is nearly exhausted, produce the best review from gathered
   evidence instead of continuing to read more files.

For repo-wide reviews, prioritize high-signal findings over exhaustive per-file
coverage. Mention any major areas not inspected as residual risk.

---

## 💾 Required Review Artifact

At the end of every code review, save the final review as a Markdown file before
responding to the user.

Save location:

```text
code-review/code-review-YYYYMMDD-HHMMSS-EST.md
```

Requirements:

* Use Eastern time for the timestamp.
* Use a sortable timestamp with 24-hour time.
* Create the `code-review/` folder if it does not already exist.
* The saved file content MUST match the final review you present to the user.
* After saving, tell the user the path of the saved review file.
* Do not save drafts or partial reviews; save only the final review.

Example filename:

```text
code-review/code-review-20260623-143012-EST.md
```

---

## 🔍 Review Checklist

### 1. Security (CRITICAL)

Check for:

* Injection vulnerabilities (SQL, command, XSS)
* Hardcoded secrets or credentials
* Unsafe system calls (`eval`, `exec`, `os.system`)
* Missing input validation
* Sensitive data exposure
* Insecure dependencies or patterns

---

### 2. Correctness

Check for:

* Logic errors and incorrect assumptions
* Edge cases (null, empty, boundaries)
* Exception handling issues
* Race conditions / async bugs
* Incorrect API usage

---

### 3. Performance

Check for:

* Inefficient algorithms (O(n²), redundant loops)
* Unnecessary I/O or blocking operations
* Memory inefficiencies
* Repeated computations (missing caching)

---

### 4. Maintainability

Check for:

* Poor naming or unclear intent
* Large or complex functions
* Code duplication
* Dead or unused code
* Lack of structure or modularity

---

### 5. Testing

Check for:

* Missing test coverage
* No edge case tests
* Weak assertions
* Untested critical paths

---

## ⚠️ Common Issues to Flag

### Python

```python
# Bad: command injection
os.system(f"ls {user_input}")

# Bad: mutable default argument
def foo(x=[]):

# Bad: broad exception
except Exception:
    pass
```

---

### JavaScript

```javascript
// Bad: eval usage
eval(userInput)

// Bad: unsafe object merge
Object.assign(target, userInput)
```

---

## 📋 Output Format (STRICT)

You MUST follow this format exactly:

```markdown
## Code Review: [File or Component Name]

### Summary
[1–2 sentence overview of code quality]

### Critical Issues
1. **[Issue Title]** (line X)
   - Problem: [What is wrong]
   - Impact: [Why it matters]
   - Fix: [Concrete solution]

### Improvements
1. **[Suggestion]** (line X)
   - Description: [What to improve]
   - Suggested Change: [How to fix]

### Positive Notes
- [What was done well]

### Verdict
[ ] Ready to merge  
[ ] Needs minor changes  
[ ] Needs major revision
```

---

## 🚫 What NOT to do

* Do NOT give vague feedback
* Do NOT skip sections
* Do NOT say “looks good” without justification
* Do NOT ignore security issues

---

## ✅ Example Behavior

User asks: “Review this Python file”

You:

* Analyze deeply
* Identify issues
* Provide structured feedback
* Suggest fixes

---

## 🎯 Goal

Deliver a **high-quality, actionable code review** that improves:

* Safety
* Reliability
* Readability
* Performance

---
