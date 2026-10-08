# Git 多人协作规范

本规范用于多人或多个自动化任务同时处理不同问题。目标是让每项工作拥有独立目录和分支，减少文件覆盖、合并冲突与重复部署。

## 1. 基本原则

1. `main` 始终保持可构建、可测试、可部署。
2. 一个问题对应一个 GitHub Issue、一个分支和一个工作目录。
3. 不在共享工作目录中同时开发。每位开发者使用独立 clone，或使用 `git worktree`。
4. 不直接向 `main` 提交业务修改。修改通过 Pull Request 合并。
5. 一个 Pull Request 只解决一个问题；不要加入无关重构。
6. 新功能或修复先在**任务分支**上做真机测试，`main` 保持不动；每次测试前必须备份当前运行时与香橙派仓库的 `main` 头。
7. 分支测试通过后才并入 `main` 并同步到运行时，刷新运行状态（重建受影响容器、更新 `.deployed-git-commit`）。
8. 同一时间只能有一个人执行香橙派部署。

## 2. 开始工作

先在 GitHub Issue 中写清楚：

- 问题和复现方法；
- 计划修改的模块与文件；
- 验收条件；
- 是否涉及串口协议、数据库结构、Docker 编排或设备部署。

从最新的 `origin/main` 创建分支和独立 worktree：

```bash
git fetch origin --prune
git worktree add ../smarthome-fix-login -b fix/123-login origin/main
cd ../smarthome-fix-login
```

分支命名格式：

```text
<类型>/<Issue编号>-<简短说明>
```

| 类型 | 用途 | 示例 |
|---|---|---|
| `feat` | 新功能 | `feat/128-scene-mode` |
| `fix` | 缺陷修复 | `fix/123-login-timeout` |
| `refactor` | 不改变行为的重构 | `refactor/131-serial-parser` |
| `test` | 测试改进 | `test/135-camera-reconnect` |
| `docs` | 文档修改 | `docs/140-api-example` |
| `ops` | Docker、部署和运维 | `ops/142-healthcheck` |

没有 Issue 编号时可以省略编号，例如 `docs/git-workflow`。

## 3. 修改范围与冲突管理

开始编码前，在 Issue 或 Pull Request 中声明主要修改文件。以下文件容易产生冲突，修改前必须确认没有其他进行中的工作：

- `PC_Test/docker-compose*.yml`；
- `PC_Test/web/app.py`、`PC_Test/web/database.py`；
- `PC_Test/web/automation/engine.py`；
- `module-a-sensor/include/Config.h`；
- `module-b-output/include/Config.h`；
- 串口协议文档和协议实现；
- 数据库迁移、认证配置和部署脚本。

如果两项工作必须修改同一文件，由双方先约定接口和合并顺序。先合并基础改动，后续分支再执行 `rebase`。

禁止提交以下内容：

- 密码、Token、API Key、私钥和 `.env`；
- 运行数据库、人脸数据、模型、日志和备份；
- 编辑器缓存、构建产物和部署专用认证文件。

## 4. 提交规范

提交标题格式：

```text
<类型>(<范围>): <简短说明>
```

常用范围包括 `web`、`voice`、`camera`、`automation`、`gateway`、`module-a`、`module-b`、`docker` 和 `docs`。

```text
fix(web): reject expired hardware commands
feat(automation): add rain sensor trigger
docs(git): document concurrent development workflow
ops(docker): add web readiness probe
```

每个提交应满足：

- 可以单独理解和审查；
- 不混入全仓库格式化等无关变化；
- 代码与对应测试放在同一提交或同一 Pull Request；
- 标题使用祈使语气，正文说明原因、风险和兼容性影响。

## 5. 同步主分支

开发过程中定期同步主分支：

```bash
git fetch origin
git rebase origin/main
```

只允许对自己的功能分支执行：

```bash
git push --force-with-lease
```

禁止使用 `git push --force`，禁止改写共享分支和 `main` 的历史。

解决冲突后必须重新运行相关测试。不要使用 `ours` 或 `theirs` 整体覆盖文件，除非已经逐段核对差异。

## 6. 测试要求

| 修改范围 | 必须检查 |
|---|---|
| 文档 | 链接、命令和路径检查 |
| Python/Web | 相关单元测试与 `python -m compileall` |
| `PC_Test` 服务 | `python -m unittest discover -s PC_Test/tests -v`，不得连接真实执行器 |
| Arduino 固件 | 对应 PlatformIO 环境编译 |
| Docker/依赖 | `docker compose config` 和受影响镜像构建 |
| 串口协议 | A/B 板、网关和协议文档的一致性检查 |

测试失败不得合并。因环境缺少硬件而无法执行的检查，必须在 Pull Request 中写明，并提供替代验证结果。

## 7. Pull Request

创建 Pull Request 前：

```bash
git fetch origin
git rebase origin/main
git push -u origin <分支名>
```

Pull Request 描述必须包含：

- 具体问题和触发条件；
- 修改后的行为；
- 主要文件和设计选择；
- 测试命令与结果；
- 配置、数据库、硬件和部署影响；
- 回滚方法。

合并条件：

- 自动检查通过；
- 至少一名未参与实现的人完成审查；
- 没有未解决的评审意见；
- 分支已包含最新 `origin/main`；
- 没有凭据或运行数据进入 Git。

默认使用 **Squash and merge**，让一个问题在 `main` 中对应一个清晰提交。需要保留多步迁移历史时可以使用普通 merge。

## 8. 部署规范

### 分支真机测试（合并前）

新功能或修复在合并前先做真机测试，`main` 保持不动：

1. 备份当前运行时（`/home/HwHiAiUser/smart-home`，至少包含 `.deployed-git-commit`、`docker-compose.yml` 和将被修改的源文件）到 `/home/HwHiAiUser/smart-home-backups/<任务>-<时间戳>/`；
2. 记录香橙派仓库 `main` 头：`git -C /home/HwHiAiUser/Arduino-Uno-3-Smart-Home rev-parse main`（必要时用 `git bundle` 快照）；
3. 只把任务分支的必要改动部署到运行时并重建受影响容器，验证功能；
4. 测试通过后按下方流程合并到 `main` 并同步运行时；失败则从备份恢复运行时，并按需回滚仓库 `main`。

### 合并后部署

合并后由一名部署负责人执行：

```powershell
git switch main
git pull --ff-only origin main
powershell -File scripts/sync_orangepi.ps1
```

部署前在团队沟通渠道声明“正在部署”和目标提交。其他人不得同时运行部署脚本或手动执行 `docker compose up/down`。

部署完成后记录：

- 本地、GitHub 和香橙派的完整提交哈希；
- 测试结果；
- Web、Camera、Voice 容器状态；
- `/api/ready` 结果；
- 回滚提交。

生产故障需要回滚时，从最后一个已验证提交创建 `hotfix/<Issue编号>-<说明>`，修复仍通过 Pull Request。紧急恢复服务后必须补齐 Issue、测试和复盘记录。

## 9. 完成后的清理

Pull Request 合并并部署成功后：

```bash
git worktree remove ../smarthome-fix-login
git branch -d fix/123-login
git push origin --delete fix/123-login
git fetch origin --prune
```

删除 worktree 前确认其中没有未提交修改。不要用 `-D` 或手工删除目录跳过检查。

## 10. 每日协作检查清单

- [ ] 当前工作有独立 Issue、分支和 worktree。
- [ ] 已声明主要修改文件，没有与他人重叠。
- [ ] 已同步最新 `origin/main`。
- [ ] 提交中没有凭据、运行数据和无关修改。
- [ ] 已运行与修改范围匹配的测试。
- [ ] Pull Request 描述包含影响和回滚方法。
- [ ] 合并后仅由一人部署。
- [ ] 本地、GitHub 和香橙派提交一致。
