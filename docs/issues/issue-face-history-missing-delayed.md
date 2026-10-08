# 人脸识别历史记录入库不及时、有丢失

> 本地 issue 草稿（`gh` 未安装，GitHub 恢复后搬运为正式 Issue）。来源：对
> `PC_Test/web/` 人脸链路（`face_watcher.py` / `access_guard.py` / `face/engine.py` /
> `api/face.py` / `database.py` / `static/js/access.js`）的只读静态审计。行号以当前
> `main` 为准。

## 问题与复现

门禁页「人脸识别事件」表（`GET /api/face/events`）与实际发生的识别对不上：

- 同一人在门口被连续识别的多条结果只留下一条；
- 陌生人（未匹配到身份）连续出现时，8 秒内只记一条；
- 人在 `cooldown`（默认 60 秒）窗口内再次出现完全不记录；
- 「太远 / 取帧那轮被节流 / 没有 PIR 唤醒 / 摄像头失败」这几种情况完全不产生历史；
- 一次性单帧识别接口 `/api/face/recognize` 的结果**从不入库**；
- 已入库的新记录，状态在一段时间内仍显示「已拒绝」（实际应为「已通过」），要手动点
  「刷新」才纠正。

复现（分别对应上面几条）：

1. 站到摄像头前保持 8 秒以上 → 事件表只出现一条（去抖）。
2. 同一人在 `cooldown` 内（默认 60 秒）走开再回来 → 不再出现新行。
3. `POST /api/face/recognize` 传一帧 → 返回识别结果，但 `face_events` 无新行。
4. 放行瞬间抓 `/api/access` 页面：结果面板/表格先显示「已拒绝」，直到 2 秒一次轮询
   的「新事件」触发重渲染前状态可能一直不对。

## 根因（代码证据）

全部写入路径只有一处：`AccessGuard.handle_face_result()`
（`access_guard.py:141-176`），由 `FaceWatcher.inspect_once()`
（`face_watcher.py:203`）和 `POST /api/face/notify`（`api/face.py:106`）调用。
问题就集中在这条路径与其上游判定。

### 1. 去抖发生在写库之前，且陌生人共用空 `face_id`（丢失主因）
- 位置：`access_guard.py:159-166`
- `merge_repeat("face", face_id)` 在 `add_face_event()` **之前**判断；窗口
  `REPEAT_WINDOW_S = 8.0`（`access_guard.py:32`），key 是 `(method, credential)`，
  即 `("face", face_id)`。
- `face_id` 为空表示陌生人（`access_guard.py:150/157`）。于是**所有陌生人在 8 秒内
  共用同一个 key**，只落一条；同一已录身份 8 秒内的重复识别也不落。
- 去抖被显式关闭的只有文档里提到的 `debounce=False`，当前运行代码**无任何调用方使用**
  （`grep` 全仓库仅文档出现），所以两条真实写入路径都受此限制。

### 2. 哨兵在写库前大量 early-return，不产生任何历史
- 位置：`face_watcher.py:164-219`（`inspect_once`）
- 下列分支都在调用 `handle_face_result()` 之前返回，因此**不写 `face_events`**：
  `idle`（PIR 门控未开）、`no_camera`、`no_identity`、`no_face`、
  `throttled`（`engine.py:606-608`，与 `RequestThrottler` 共用节流窗口）、
  `too_far`、`cooldown`、`duplicate`。
- `cooldown`（默认 60 秒，`face_watcher.py:30/210`）只对「放行」设防，窗口内再出现
  直接 `return self._note("cooldown")`，不落库。
- 取帧是 2 秒一轮的轮询（`face.watcher.interval` 默认 2.0）：快速路过者可能在两轮之间
  出现并离开，整条记录丢失。

### 3. 先插 `pending` 行、后更新状态：两步非原子，前端把 `pending` 当「拒绝」
- 位置：`access_guard.py:163-173`；`database.py:186`（`status TEXT DEFAULT 'pending'`）、
  `database.py:640-645`（`update_face_event_status`）
- `add_face_event()` 先插入一行 `status='pending'`，随后才在 `grant()`/`deny()` 之后
  用**另一条事务**写回 `granted`/`denied`。
- `grant()` 内部会 `broadcast()` → 积木引擎同步执行规则（开门、延时、抓拍、串口下发），
  这中间的 `pending` 窗口可达数百毫秒到数秒；若进程在此期间退出或写回抛错，行将**永久
  停留在 `pending`**。
- 前端把「非 granted」一律渲染为拒绝：`access.js:663-666`
  （`evt.status === 'granted' ? 'granted' : 'denied'`），所以 `pending` 被显示成
  「已拒绝」。

### 4. 前端轮询按 event id 去重，会锁死中间态
- 位置：`access.js:151-169`、`250-252`、`645-687`
- `pollLatestFaceEvent()` 只在 `lastEventId !== event.id` 且 `age_s <= 90` 时调用
  `updateFaceResultDisplay()`，后者才顺带 `loadFaceEvents()` 刷新表格
  （`access.js:250-252`）。
- 若某次轮询恰好取到第 3 点的 `pending` 行，`lastEventId` 已被该 id 占用，之后 id 不变
  → 结果面板与表格都不再纠正，直到用户手动刷新或下一条新事件到来。

### 5. `/api/face/recognize` 只识别、不落库
- 位置：`api/face.py:15-26`
- 单帧识别接口直接返回 `face_engine.recognize_from_base64()`，不调用
  `handle_face_result()`，因此不写 `face_events`。而 `docs/api.md:546-548` 又把
  `device_source='web'` 描述为「网页自测/单帧识别」的来源，与实现不一致。

### 6. 写库异常被哨兵吞掉（偶发丢失）
- 位置：`face_watcher.py:156-162`（`_loop` 捕获所有异常）
- `add_face_event()` 若抛 `sqlite3.OperationalError: database is locked`
  （与每小时的历史维护 `BEGIN IMMEDIATE` + 批量 `DELETE` 竞争，`database.py:334-374`），
  这一条事件直接丢失，只留一行 warning，无重试、无补偿。

## 计划修改（建议，待定）

1. **去抖与写库解耦**：`merge_repeat` 只用于抑制「开门的重复动作」，不再决定是否
   `add_face_event`；或对陌生人改用「未匹配 + 时间桶」而非空 `face_id` 做 key，避免把
   不同陌生人合并。
2. **判定结果一次性写入**：`handle_face_result` 先算好 `reason/matched`，用**单条**
   `INSERT ... (status, verified, deny_reason)` 落库；或把 `add_face_event` +
   `update_face_event_status` 放进同一事务。
3. **明确「哪些判定要留痕」**：`too_far` / `throttled` / `no_face` 是否也算历史，按产品
   预期决定；若要留痕，就把哨兵的观测结果也落一条 `face_events`（带 `kind`）。
4. **前端**：不在 id 去重后停止刷新；对 `status='pending'` 显示为「判定中」并按
   短间隔重取，直到终态；`pending` 不应渲染为「已拒绝」。
5. **一致性**：让 `/api/face/recognize` 与文档二选一 —— 要么落库（`device_source='web'`），
   要么修正 `docs/api.md` 的说明。
6. **写库健壮性**：对 `face_events` 写入加有限重试；历史维护与实时写入避免长时间
   互斥（可考虑缩短事务或在低峰执行）。

## 验收条件

- 同一个人在门口停留 30 秒：事件条数与「识别轮次」可解释（去抖规则写入文档且可配置），
  不再出现「完全无记录」的轮次。
- 陌生人连续出现：不同陌生人各自成行（不再被空 `face_id` 合并）。
- 放行后 1 秒内 `/api/face/events/latest` 的 `status` 即为 `granted`，前端面板不出现
  先「拒绝」后不纠正的现象。
- `/api/face/recognize` 与 `docs/api.md` 行为一致。

## 影响

涉及 `PC_Test/web/access_guard.py`、`PC_Test/web/face_watcher.py`、
`PC_Test/web/api/face.py`、`PC_Test/web/static/js/access.js`，以及（如改 schema 说明）
`docs/api.md`。**不涉及数据库结构变更**（`face_events` 表已齐备），改动可通过
`PC_Test/tests/` 单测 + 门禁页真机复核验证。
