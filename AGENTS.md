# Repository workflow

For every requested code change in this repository:

1. Start from `main` and fetch `origin/main` before editing.
2. Keep credentials, `.env`, models, runtime databases, face data, archives, and deployment-only authentication files out of Git.
3. Run the tests relevant to the change. For `PC_Test` service changes, run `python -m unittest discover -s PC_Test/tests -v` in an isolated environment without real serial devices.
4. Commit the reviewed source changes to `main` and push `main` to `origin`.
5. Synchronize the same commit to the Orange Pi with `scripts/sync_orangepi.sh`, then verify Docker health and `/api/ready` without issuing actuator commands.
6. Report the local commit, GitHub commit, Orange Pi deployed commit, test result, and service health together.

The active Orange Pi runtime is `/home/HwHiAiUser/smart-home`. Its persistent `data/`, `models/`, `.env`, `.auth*.env`, and credential files must be preserved during deployments.
