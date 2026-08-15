# test-unattended-worker-v1
Task:
Create UNATTENDED_WORKER_WORKS.txt in the root of the workspace directory.
Do NOT create an artifact. Write a normal plain text file directly to the workspace directory.

Exact content:
Unattended execution successful

Acceptance:
- file_exists: UNATTENDED_WORKER_WORKS.txt
- exact_content: Unattended execution successful
