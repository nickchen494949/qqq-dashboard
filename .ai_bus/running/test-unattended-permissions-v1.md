# test-unattended-permissions-v1
Task:
You are in a fully automated unattended environment. You must complete the following steps exactly as described, without requiring any manual permissions or user interaction:
1. Read the `package.json` file in the root of the workspace directory.
2. Create a file named `PERMISSION_TEST.txt` in the root of the workspace directory containing exactly the text `AI_OS_PERMISSION_OK`.
3. Edit the same file `PERMISSION_TEST.txt` and append a newline and the text `EDIT_OK`.
4. Run the terminal command `git status --short`.
5. Run the terminal command `python3 -c "print('COMMAND_OK')"`.

Important: You MUST run the python command exactly as `python3 -c "print('COMMAND_OK')"` so the output `COMMAND_OK` is visible in your terminal stream output.
