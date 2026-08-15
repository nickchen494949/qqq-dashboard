# test-safe-adapter-v5
AI_OS_TEST_MODE=1
AI_OS_TEST_FORCE_EXIT_CODE=17
Task:
Create SAFE_ADAPTER_WORKS.txt in the root of the workspace directory.
Do NOT create an artifact. Write a normal plain text file directly to the workspace directory.

Exact required content:
Production integration successful

Acceptance:
- file_exists: SAFE_ADAPTER_WORKS.txt
- exact_content: Production integration successful
