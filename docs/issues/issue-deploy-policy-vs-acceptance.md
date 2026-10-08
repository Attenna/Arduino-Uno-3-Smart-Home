# 部署流程规范与真机验收冲突：禁止部署未合并分支导致无法验收

> 本地 issue 草稿（GitHub 暂时不可用，恢复后搬运为正式 Issue）。

## 问题

`AGENTS.md` 第 4 条与 `docs/git-workflow.md` 第 1.6 条要求「不得部署未合并分支」「只有已合并到 `main` 的提交才能部署到香橙派」。但部分修复（如光照极性/二态）必须先在真机验证（捂传感器→灯亮、松开→灯灭），而验收时改动尚未合并，形成死锁：不部署就无法验收，未验收又不敢合并。

## 本轮实际做法（已完成，可用作流程参考）

- 备份 runtime：`/home/HwHiAiUser/smart-home-backups/pre-hotfix-light-<ts>/`（含 4 个改动文件 + `.deployed-git-commit` + `docker-compose.yml`）。
- web 代码为**镜像内置**（非 bind mount），故仅同步改动的 4 个文件到 `/home/HwHiAiUser/smart-home`，再 `docker compose build web && docker compose up -d web`。
- 验收通过后**未更新** `.deployed-git-commit`，标记仍为 `b383c69`，与 runtime 实际代码不一致。

## 结论（2026-10-08 已定规范）

规范由仓库所有者规定如下，并已写入 `AGENTS.md` 与 `docs/git-workflow.md`：

- 新功能/修复先在**任务分支**上做真机测试，`main` 保持不动；
- 每次测试前必须备份当前运行时（`/home/HwHiAiUser/smart-home`）与香橙派仓库（`/home/HwHiAiUser/Arduino-Uno-3-Smart-Home`）的 `main` 头；
- 分支测试通过后才并入 `main` 与运行时，刷新运行状态（重建受影响容器、更新 `.deployed-git-commit`）。

取代原先「只有合并到 `main` 的提交才能部署到香橙派」的表述。

## 状态

已解决。规范已合并并推送 GitHub（`main=e07c8f4`）。本条可关闭，或在 GitHub 恢复后搬运为正式 Issue 存档。

## 附带风险（仍适用）

热部署不更新 `.deployed-git-commit` 会导致部署标记失真；并发部署可能用旧 DB/旧镜像覆盖新改动。
