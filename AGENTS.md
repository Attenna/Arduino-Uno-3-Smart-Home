# Repository workflow

For every requested code change in this repository:

1. Follow `docs/git-workflow.md`. Each independent problem uses its own issue, branch, and worktree created from the latest `origin/main`; do not share a working directory between concurrent tasks.
2. Keep credentials, `.env`, models, runtime databases, face data, archives, and deployment-only authentication files out of Git.
3. Run the tests relevant to the change. For `PC_Test` service changes, run `python -m unittest discover -s PC_Test/tests -v` in an isolated environment without real serial devices.
4. Push the task branch and merge it through a reviewed Pull Request. Do not push feature or fix commits directly to `main`, rewrite shared history, or deploy an unmerged branch.
5. After merge, update local `main` with `git pull --ff-only origin main`. One deployer then synchronizes that exact commit from Windows to the Orange Pi with `powershell -File scripts/sync_orangepi.ps1`. The script transfers a Git bundle because the Orange Pi may not have direct GitHub access. It verifies Docker health, `/api/ready`, and anonymous API rejection without issuing actuator commands. `scripts/sync_orangepi.sh` is the remote deployment implementation.
6. Report the local commit, GitHub commit, Orange Pi deployed commit, test result, and service health together.

The active Orange Pi runtime is `/home/HwHiAiUser/smart-home`. Its persistent `data/`, `models/`, `.env`, `.auth*.env`, and credential files must be preserved during deployments.
