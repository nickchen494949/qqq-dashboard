# test-safe-adapter-v4-fail
Task:
1. Create SAFE_ADAPTER_WORKS.txt in the root of the workspace directory. Write a normal plain text file directly to the workspace directory.
2. The exact required content for SAFE_ADAPTER_WORKS.txt must be:
Production integration successful
3. AFTER writing the file successfully, you MUST output exactly the word "QUOTA_EXHAUSTED" in your response.

Acceptance:
- file_exists: SAFE_ADAPTER_WORKS.txt
- exact_content: Production integration successful
