# Issues 与记录归档

本目录集中归档本项目的问题记录，便于协作者（含香橙派侧，派上无法直连 GitHub）离线查阅。**线上状态以 GitHub / GitCode 为准。**

## 内容

| 文件 | 说明 |
| --- | --- |
| `github-issues.md` | GitHub Issues / PR 全量离线快照（自动生成，来源与拉取时间见文件头） |
| `issue-*.md` | GitHub 不可用期间写下的本地 issue 草稿，GitHub 恢复后应搬运为正式 Issue |
| `light-sensor-binary-plan.md` | 光照“暗/亮”二态联动实现计划 |

## 重新生成快照

```bash
curl -s "https://api.github.com/repos/Attenna/Arduino-Uno-3-Smart-Home/issues?state=all&per_page=100" -o /tmp/gh_issues.json
# 然后按 github-issues.md 文件头的格式重新生成
```