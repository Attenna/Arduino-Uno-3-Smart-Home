# Repository workflow

For every requested code change in this repository:

1. Follow `docs/git-workflow.md`. Each independent problem uses its own issue, branch, and worktree created from the latest `origin/main`; do not share a working directory between concurrent tasks.
2. Keep credentials, `.env`, models, runtime databases, face data, archives, and deployment-only authentication files out of Git.
3. Run the tests relevant to the change. For `PC_Test` service changes, run `python -m unittest discover -s PC_Test/tests -v` in an isolated environment without real serial devices.
4. Push the task branch and merge it through a reviewed Pull Request. Do not push feature or fix commits directly to `main` or rewrite shared history.
5. New behavior is verified on the real Orange Pi **on the task branch, leaving `main` untouched**. Before every such test, back up the current runtime (`/home/HwHiAiUser/smart-home`) and record the `main` head of the Orange Pi repository (`/home/HwHiAiUser/Arduino-Uno-3-Smart-Home`).
6. Only after the branch test passes may the branch be merged into `main` and applied to the runtime, refreshing the running state by rebuilding the affected containers and writing the deployed commit to `.deployed-git-commit`.
7. After merge, update local `main` with `git pull --ff-only origin main`. One deployer then synchronizes that exact commit to the Orange Pi with `scripts/sync_orangepi.sh` (or `powershell -File scripts/sync_orangepi.ps1`). The script transfers a Git bundle because the Orange Pi may not have direct GitHub access. It verifies Docker health, `/api/ready`, and anonymous API rejection without issuing actuator commands.
8. Report the local commit, GitHub commit, Orange Pi deployed commit, test result, and service health together.

9. Every change to the face-recognition subsystem or its direct API/UI/data path must update
   `PC_Test/web/face/changes_log.md` in Chinese. Add a version, release date (or `未发布`),
   categorized entries, and concise impact/migration notes for each change.

The active Orange Pi runtime is `/home/HwHiAiUser/smart-home`. Its persistent `data/`, `models/`, `.env`, `.auth*.env`, and credential files must be preserved during deployments.
