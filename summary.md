# LLM Python File Summary: /path/to/code-harness

Total Python files: 26
Completed: 26
Failed: 0
Cache hits: 0
Prompt version: `python-file-summary-v2`

| # | File | Status | Kind | Lines | Summary |
|---:|---|---|---:|---:|---|
| 1 | __init__.py | ok | module | 0 | Marks the directory as a Python package. |
| 2 | core/__init__.py | ok | module | 1 | Core runtime modules for code_harness. |
| 3 | core/compaction.py | ok | module | 0 | The file is an empty placeholder module with no executable code. |
| 4 | core/evaluators.py | ok | module | 0 | The module contains no executable code. |
| 5 | core/hooks.py | ok | module | 0 | An empty or metadata-only Python module. |
| 6 | core/llm_client.py | ok | class_module | 107 | Provides an asynchronous LLM client that wraps litellm with configurable retry, timeout, and exponential backoff logic. |
| 7 | core/loop.py | ok | class_module | 160 | The file implements a loop for running conversational interactions with an LLM, handling tool execution, permissions, and conversation state. |
| 8 | core/permissions.py | ok | module | 349 | The file provides a permission engine to control tool usage (especially bash commands) via rule-based decisions and LLM-assisted safety reviews. |
| 9 | core/sessions.py | ok | module | 0 | The file is empty or contains only metadata. |
| 10 | core/tracing.py | ok | function_module | 62 | Provides tracing utilities for recording LLM interactions, generating timestamps, and persisting trace data to JSON files. |
| 11 | main.py | ok | script | 126 | The file implements an interactive coding agent loop that processes user input using a language model and tools, saves conversation traces to disk, and provides a utility to print agent history. |
| 12 | memory/__init__.py | ok | module | 0 | Serves as an empty package initializer for the memory module. |
| 13 | memory/context.py | ok | class_module | 423 | Manages conversation messages, estimates token counts, stores conversation history, and builds LLM context by summarizing old messages when token budgets are exceeded. |
| 14 | memory/message_summarizer.py | ok | class_module | 149 | Provides asynchronous methods to generate and update conversation summaries using a language model. |
| 15 | models.py | ok | module | 7 | Defines constant identifiers for various LLM models used by the application. |
| 16 | tools/__init__.py | ok | module | 1 | Makes the tools directory a Python package so its modules can be imported. |
| 17 | tools/bash.py | ok | class_module | 35 | Defines a tool for asynchronously executing shell commands and capturing their output. |
| 18 | tools/edit_file.py | ok | class_module | 38 | Defines a tool that replaces a specified substring with new text in a given file. |
| 19 | tools/llm_summarize_python_files.py | ok | module | 483 | The file defines a tool that uses an LLM to generate structured summaries of Python files in a codebase, with caching and concurrency controls. |
| 20 | tools/read_file.py | ok | class_module | 21 | Provides a tool to read and return the contents of a file given a path. |
| 21 | tools/summarize_python_files.py | ok | function_module | 216 | Provides utilities to traverse directories, parse Python files, and generate structural summaries of their content. |
| 22 | tools/task.py | ok | class_module | 102 | Defines a Tool for spawning a subagent with isolated context, executing a prompted task under configurable limits, and returning a structured result while tracing the interaction. |
| 23 | tools/to_do.py | ok | class_module | 56 | Provides a simple todo list manager that validates tasks, tracks progress, and renders a formatted status summary. |
| 24 | tools/tools.py | ok | module | 208 | Defines a framework for creating, registering, and executing tools in an agent system, including base classes, a tool registry, and utilities for project-scoped argument validation. |
| 25 | tools/write_file.py | ok | class_module | 23 | Provides a tool to write string content to a specified file path, creating directories as needed. |
| 26 | ui_config.py | ok | module | 3 | Defines a global Rich Console instance for styled terminal output. |

## Details

### `__init__.py`
- Kind: `module`
- Status: `ok`
- File index: 1 of 26
- Cache hit: False
- Lines: 0
- Summary: Marks the directory as a Python package.
- Responsibilities: `Enable the directory to be imported as a package`, `Allow submodules to be accessed via the package`, `Serve as a placeholder for package-level initialization`
- Key objects: none
- Side effects: `none`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `core/__init__.py`
- Kind: `module`
- Status: `ok`
- File index: 2 of 26
- Cache hit: False
- Lines: 1
- Summary: Core runtime modules for code_harness.
- Responsibilities: `Provide module-level documentation`, `Mark the core directory as a Python package`
- Key objects: none
- Side effects: `none`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `core/compaction.py`
- Kind: `module`
- Status: `ok`
- File index: 3 of 26
- Cache hit: False
- Lines: 0
- Summary: The file is an empty placeholder module with no executable code.
- Responsibilities: none
- Key objects: none
- Side effects: `none`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `core/evaluators.py`
- Kind: `module`
- Status: `ok`
- File index: 4 of 26
- Cache hit: False
- Lines: 0
- Summary: The module contains no executable code.
- Responsibilities: none
- Key objects: none
- Side effects: `none`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `core/hooks.py`
- Kind: `module`
- Status: `ok`
- File index: 5 of 26
- Cache hit: False
- Lines: 0
- Summary: An empty or metadata-only Python module.
- Responsibilities: none
- Key objects: none
- Side effects: `none`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `core/llm_client.py`
- Kind: `class_module`
- Status: `ok`
- File index: 6 of 26
- Cache hit: False
- Lines: 107
- Summary: Provides an asynchronous LLM client that wraps litellm with configurable retry, timeout, and exponential backoff logic.
- Responsibilities: `Execute LLM completion requests via litellm asynchronously`, `Apply retry logic with configurable attempts and timeout`, `Implement exponential backoff with jitter between retries`, `Determine which exceptions are retryable based on status codes and error messages`, `Allow customization of retry behavior through a RetryConfig dataclass`
- Key objects: `RetryConfig dataclass`, `LLMClient class`, `LLMClient.send method`, `LLMClient._retry_delay method`, `LLMClient._is_retryable_error method`
- Side effects: `Makes network requests to external LLM APIs`, `Performs asynchronous sleeping during retry delays`, `Uses random number generation for jitter`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `core/loop.py`
- Kind: `class_module`
- Status: `ok`
- File index: 7 of 26
- Cache hit: False
- Lines: 160
- Summary: The file implements a loop for running conversational interactions with an LLM, handling tool execution, permissions, and conversation state.
- Responsibilities: `Managing the main loop that interacts with the LLM and processes tool calls`, `Enforcing limits on the number of runs and tool calls`, `Checking permissions for tool execution and handling user input for permission requests`, `Updating the conversation store with messages from the user, LLM, and tool executions`, `Handling special tool cases and providing reminders for todo updates`
- Key objects: `LoopResult`, `LoopStatus`, `Loop`
- Side effects: `I/O`, `persistence`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `core/permissions.py`
- Kind: `module`
- Status: `ok`
- File index: 8 of 26
- Cache hit: False
- Lines: 349
- Summary: The file provides a permission engine to control tool usage (especially bash commands) via rule-based decisions and LLM-assisted safety reviews.
- Responsibilities: `Loading and managing permission rules from a JSON settings file`, `Deciding whether a tool invocation is allowed, denied, or requires user input based on rules`, `Detecting and preventing bash commands that reference paths outside the project or denied read paths`, `Using an LLM to review the safety of ambiguous (gray area) bash commands when rule-based decisions are inconclusive`
- Key objects: `Rule`, `PermissionDecision`, `CommandSafetyReview`, `PermissionEngine`, `normalize_tool_name`, `is_gray_area_command`, `parse_safety_review`, `review_command_with_llm`, `GRAY_AREA_PATTERNS`, `PATH_FIELD_NAMES`, `PROJECT_ROOT`, `TOOL_NAME_ALIASES`
- Side effects: `File I/O (reading settings.json)`, `Network (LLM API calls for safety review)`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `core/sessions.py`
- Kind: `module`
- Status: `ok`
- File index: 9 of 26
- Cache hit: False
- Lines: 0
- Summary: The file is empty or contains only metadata.
- Responsibilities: none
- Key objects: none
- Side effects: none
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `core/tracing.py`
- Kind: `function_module`
- Status: `ok`
- File index: 10 of 26
- Cache hit: False
- Lines: 62
- Summary: Provides tracing utilities for recording LLM interactions, generating timestamps, and persisting trace data to JSON files.
- Responsibilities: `Generate ISO-formatted timestamps in Eastern Time`, `Record and retrieve nested LLM call events using a context variable`, `Ensure the trace directory exists and write trace JSON files to disk`, `Collect metadata and nested calls into a structured trace and save it`
- Key objects: `utc_now_iso`, `record_nested_llm_call`, `pop_nested_llm_calls`, `save_trace`, `EASTERN_TIME`, `TRACE_DIR`, `_NESTED_LLM_CALLS`
- Side effects: `Creates the trace directory if it does not exist (file system)`, `Writes trace JSON files to the trace directory (persistence I/O)`, `Modifies the context variable _NESTED_LLM_CALLS to store and clear nested call events (process state)`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `main.py`
- Kind: `script`
- Status: `ok`
- File index: 11 of 26
- Cache hit: False
- Lines: 126
- Summary: The file implements an interactive coding agent loop that processes user input using a language model and tools, saves conversation traces to disk, and provides a utility to print agent history.
- Responsibilities: `Load environment variables and configure the LiteLLM API key`, `Set up workspace and trace storage directories`, `Initialize conversation store, tool registry, permission agent, and agent loop`, `Run an interactive loop to process user input, invoke the agent, and save traces of each interaction`, `Provide a function to print formatted agent message history with role-based styling`
- Key objects: `TRACE_DIR`, `async main`, `print_agent_history`
- Side effects: `I/O`, `network`, `environment`, `persistence`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `memory/__init__.py`
- Kind: `module`
- Status: `ok`
- File index: 12 of 26
- Cache hit: False
- Lines: 0
- Summary: Serves as an empty package initializer for the memory module.
- Responsibilities: `Marks the memory directory as a Python package`, `Provides a location for package-level metadata if needed`
- Key objects: none
- Side effects: none
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `memory/context.py`
- Kind: `class_module`
- Status: `ok`
- File index: 13 of 26
- Cache hit: False
- Lines: 423
- Summary: Manages conversation messages, estimates token counts, stores conversation history, and builds LLM context by summarizing old messages when token budgets are exceeded.
- Responsibilities: `Define message types and estimate token counts for messages.`, `Create and store message records with unique identifiers and metadata.`, `Retrieve conversation history, active summaries, and system prompts.`, `Build a context window for LLMs by compacting old messages via summarization when token limits are approached.`
- Key objects: `MessageType`, `TokenEstimator`, `MessageRecord`, `ConversationStore`, `ContextBuilder`, `MAX_TOOL_OUTPUT`, `SYSTEM_PROMPT_BUDGET`, `TOTAL_CONTEXT_BUDGET`
- Side effects: `network`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `memory/message_summarizer.py`
- Kind: `class_module`
- Status: `ok`
- File index: 14 of 26
- Cache hit: False
- Lines: 149
- Summary: Provides asynchronous methods to generate and update conversation summaries using a language model.
- Responsibilities: `Merge existing summaries with new messages to produce updated summaries via LLM`, `Format input data as JSON for LLM processing`, `Utilize an LLM client to generate summaries based on predefined prompts`, `Handle summarization of conversation components (user, assistant, tool) into a cohesive summary`
- Key objects: none
- Side effects: `network`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `models.py`
- Kind: `module`
- Status: `ok`
- File index: 15 of 26
- Cache hit: False
- Lines: 7
- Summary: Defines constant identifiers for various LLM models used by the application.
- Responsibilities: `Store model names as constants for easy reference`, `Centralize model configuration to facilitate updates`, `Provide a single source of truth for LLM identifiers`, `Enable consistent model selection across modules`
- Key objects: `DEEPSEEK_V4_PRO`, `GEMMA_4_31_B`, `NVIDIA_NEMOTRON_3_SUPER_120B_A12B`, `RING_26_1T`, `ROUTER_MODEL`, `XIAOMI_MIMO_V25_PRO`
- Side effects: `none`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `tools/__init__.py`
- Kind: `module`
- Status: `ok`
- File index: 16 of 26
- Cache hit: False
- Lines: 1
- Summary: Makes the tools directory a Python package so its modules can be imported.
- Responsibilities: `Mark the tools directory as a package`, `Enable relative and absolute imports from the tools package`, `Provide a placeholder for future package‑level definitions`, `Allow the tools package to be imported as a module`
- Key objects: none
- Side effects: `none`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `tools/bash.py`
- Kind: `class_module`
- Status: `ok`
- File index: 17 of 26
- Cache hit: False
- Lines: 35
- Summary: Defines a tool for asynchronously executing shell commands and capturing their output.
- Responsibilities: `Define a Pydantic model for shell command input (command and optional working directory)`, `Provide an asynchronous tool to run shell commands via subprocess`, `Execute commands with a configurable timeout (default 30 seconds)`, `Capture and return combined standard output and error as a string`, `Use the project root as the default working directory if none is specified`
- Key objects: `BashInput`, `BashTool`
- Side effects: `process`, `I/O`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `tools/edit_file.py`
- Kind: `class_module`
- Status: `ok`
- File index: 18 of 26
- Cache hit: False
- Lines: 38
- Summary: Defines a tool that replaces a specified substring with new text in a given file.
- Responsibilities: `Validate input arguments via a Pydantic model`, `Expand user‑provided file paths`, `Read the target file's content`, `Check that the text to replace exists in the content`, `Perform the replacement and write the updated content back to the same file`, `Return a status message indicating success or failure`
- Key objects: `EditFileInput`, `EditFile`
- Side effects: `Reads and writes the specified file (file system I/O)`, `Uses os.path.expanduser to interpret environment‑dependent paths`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `tools/llm_summarize_python_files.py`
- Kind: `module`
- Status: `ok`
- File index: 19 of 26
- Cache hit: False
- Lines: 483
- Summary: The file defines a tool that uses an LLM to generate structured summaries of Python files in a codebase, with caching and concurrency controls.
- Responsibilities: `Discover and filter Python files based on include/exclude globs`, `Summarize each file using an LLM with bounded concurrency and optional content-hash caching`, `Handle errors per file and provide structured error information in the output`, `Render summaries in JSON or Markdown format and optionally write to an output file`
- Key objects: `LLMSummarizePythonFilesInput`, `LLMSummarizePythonFiles`, `_summarize_files`, `_summarize_one_file`, `PROMPT_VERSION`
- Side effects: `Reads Python source files from the filesystem`, `Writes cache and output files to the filesystem`, `Makes network requests to an LLM API`, `Prints progress to the console`, `Uses asyncio for concurrent task management`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `tools/read_file.py`
- Kind: `class_module`
- Status: `ok`
- File index: 20 of 26
- Cache hit: False
- Lines: 21
- Summary: Provides a tool to read and return the contents of a file given a path.
- Responsibilities: `Define a Pydantic model for the file path input`, `Implement the BaseTool interface to read file content`, `Expand user‑relative paths before reading the file`
- Key objects: `ReadFileInput`, `ReadFile`
- Side effects: `file system read`, `environment variable expansion via os.path.expanduser`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `tools/summarize_python_files.py`
- Kind: `function_module`
- Status: `ok`
- File index: 21 of 26
- Cache hit: False
- Lines: 216
- Summary: Provides utilities to traverse directories, parse Python files, and generate structural summaries of their content.
- Responsibilities: `Identify and collect Python files in a directory tree while excluding specified directories and optionally test files`, `Parse Python files to extract imports, classes, functions, top-level assignments, and entrypoint status`, `Generate a summary dictionary for each file containing metadata and a natural language summary`, `Provide helper functions to break down AST nodes into usable data (e.g., class summaries, function names)`, `Determine the kind of Python file (e.g., test, script, module) based on its content and location`
- Key objects: `EXCLUDED_DIRS`, `_python_files`, `_summarize_file`, `_imports`, `_class_summary`
- Side effects: `file system I/O`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `tools/task.py`
- Kind: `class_module`
- Status: `ok`
- File index: 22 of 26
- Cache hit: False
- Lines: 102
- Summary: Defines a Tool for spawning a subagent with isolated context, executing a prompted task under configurable limits, and returning a structured result while tracing the interaction.
- Responsibilities: `Validate and encapsulate subagent invocation parameters via the TaskInput model`, `Set up a fresh conversation store, permission engine, and tool registry for the subagent`, `Run the subagent's execution loop with specified max runs and tool call limits`, `Capture and return the subagent's outcome as a JSON-serializable summary`, `Persist execution trace and conversation records for auditing and debugging`
- Key objects: `TaskInput`, `Task`, `run`
- Side effects: `Prints to stdout`, `Reads and writes conversation store (in-memory persistence)`, `Loads permission settings from JSON (file I/O)`, `Saves trace data (persistence)`, `Spawns a subagent execution loop (process/CPU usage)`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `tools/to_do.py`
- Kind: `class_module`
- Status: `ok`
- File index: 23 of 26
- Cache hit: False
- Lines: 56
- Summary: Provides a simple todo list manager that validates tasks, tracks progress, and renders a formatted status summary.
- Responsibilities: `Validate and store todo items using Pydantic models`, `Enforce that at most one task can be in progress at a time`, `Render the todo list as a human‑readable string with markers and completion count`, `Accept updates via a TodoInput payload and apply them through the update method`, `Maintain internal state of the current todo list for rendering`
- Key objects: `Item`, `TodoInput`, `TodoManager`
- Side effects: `none`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `tools/tools.py`
- Kind: `module`
- Status: `ok`
- File index: 24 of 26
- Cache hit: False
- Lines: 208
- Summary: Defines a framework for creating, registering, and executing tools in an agent system, including base classes, a tool registry, and utilities for project-scoped argument validation.
- Responsibilities: `Define an abstract base class (BaseTool) for tools with schema generation and execution methods`, `Provide a ToolResult dataclass to capture tool execution outcomes`, `Manage a tool registry (ToolRegistry) for loading, storing, and retrieving tools`, `Offer functions to get agent-specific tool registries and run tool calls asynchronously`, `Include utilities to resolve project-relative paths and enforce project scope on tool arguments`
- Key objects: `EmptyInput`, `BaseTool`, `ToolResult`, `ToolRegistry`, `get_tools`, `run_tool`, `_all_tool_subclasses`, `resolve_in_project`, `enforce_project_scope`
- Side effects: `I/O`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `tools/write_file.py`
- Kind: `class_module`
- Status: `ok`
- File index: 25 of 26
- Cache hit: False
- Lines: 23
- Summary: Provides a tool to write string content to a specified file path, creating directories as needed.
- Responsibilities: `Validate input fields (content and path) using a Pydantic model`, `Ensure the target file's parent directory exists`, `Write the provided content to the file`, `Return a confirmation message indicating bytes written and destination path`
- Key objects: `WriteFileInput`, `WriteFile`
- Side effects: `File system I/O: creates directories and writes files`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`

### `ui_config.py`
- Kind: `module`
- Status: `ok`
- File index: 26 of 26
- Cache hit: False
- Lines: 3
- Summary: Defines a global Rich Console instance for styled terminal output.
- Responsibilities: `Create a global Console object`, `Provide access to Rich formatting utilities`, `Encapsulate console configuration in a single location`
- Key objects: `console`
- Side effects: `none`
- Model: `openrouter/nvidia/nemotron-3-super-120b-a12b:free`
