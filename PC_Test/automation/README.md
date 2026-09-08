# AST 自动化引擎 DSL 语法手册

面向智能家居的轻量级**自定义自动化**方案：用接近自然语言的 `.auto` 脚本描述「计时、条件、分支、操作、状态」，
由自制的 **词法分析器（lexer）→ 语法解析器（parser，生成 AST）→ 运行时（runtime）** 三级流水线执行，
最终把动作映射成 Module B 的串口命令（当前降级为文本命令 `B:XXX`，见下方说明）。

> 本文是**语法参考手册**，写脚本时查这里。运行方式与工具选型见上级 [PC_Test/README.md](../README.md)。

## 为什么用它

- 不用改 Python 代码，直接写脚本文件（`.auto`）就能定义联动规则；
- 中英文关键字均可，贴近自然语言；
- 逻辑（条件/分支/计时/循环/状态变量）与硬件命令解耦，脚本可读、可复用。

## 快速开始

```bash
cd PC_Test
# 连接双板后
py -3.13 run_automation.py automation/examples/smoke_alarm.auto            # 自动探测串口
py -3.13 run_automation.py automation/examples/smoke_alarm.auto --port-a COM7 --port-b COM6
py -3.13 run_automation.py automation/examples/smoke_alarm.auto --once     # 只跑一轮（调试）
py -3.13 run_automation.py automation/examples/smoke_alarm.auto --interval 1
```

运行机制：程序周期性读取 A 板数据 → 更新运行时状态 → 重新执行脚本。脚本里满足条件的 `执行` 会映射成 B 板命令发出。

## 语法一览

### 规则与语句块

```
规则 "名称" {
    ...语句...
}
```

### 条件与分支

```
当 data.smoke == true { ... }        # 满足才执行
如果 data.temperature > 30 { ... } 否则 { ... }   # 分支
如果 a { ... } 否则 如果 b { ... } 否则 { ... }   # 多分支
```

### 计时

```
等待 2 秒
等待 500 毫秒
等待 1.5 分钟
等待 3            # 默认秒
```

> ⚠️ `等待` 是**阻塞式**的，会暂停主循环（含串口读取）。避免在 `当`/`边沿` 块里长时间 `等待`，
> 延时触发请优先用下面的「定时器事件」。

### 操作（映射到 B 板命令）

```
执行 蜂鸣器.开
执行 红灯
执行 开窗
执行 蜂鸣器.beep(count=3, on_ms=200, off_ms=200)
执行 oled.text(line=2, text="T: 25 C")
```

### 状态（变量 + 传感器读取）

```
设置 提示次数 = 2          # 定义本地变量
当 data.soil_dry == true { ... }   # 读取 A 板数据字段
当 event.rfid == true { ... }      # 读取事件字段
```

### 循环

```
循环 3 {
    ...
}
```

### 边沿触发（去重）

只在字段**变化**时触发一次，避免周期数据每轮重复触发：

```
边沿 data.smoke {              # 上升沿：false -> true 触发一次
    执行 蜂鸣器.开
}

边沿 下降 data.smoke {         # 下降沿：true -> false 触发一次
    执行 蜂鸣器.关
}
```

方向可选：默认上升沿；`下降` / `falling` 表示下降沿，`上升` / `rising` 表示上升沿。

> ⚠️ **最佳实践**：开关类联动（如蜂鸣器/灯）务必用 `边沿` 把「开」和「关」拆成两条规则，
> 而**不要**写成 `当 x == true { 开 ... 等待 ... 关 }`。后者因 `等待` 阻塞 + `当` 每轮重复触发，
> 会导致命令时序错乱、蜂鸣器「关不掉」。示例见 `examples/smoke_alarm.auto`。

### 定时器事件

```
每 5 秒 {                      # 周期定时器：每 5 秒执行一次
    执行 oled.text(line=0, text="tick")
}

定时 10 秒 {                   # 一次性定时器：启动后 10 秒执行一次
    执行 关灯
}
```

## 表达式

| 类型 | 写法 |
|------|------|
| 比较 | `==` `!=` `>` `>=` `<` `<=` |
| 逻辑 | `&&` `\|\|` `!` |
| 值 | 数字 `30`、小数 `1.5`、字符串 `"文本"`、布尔 `true`/`false` |
| 取值 | `data.temperature`、`data.smoke`、`event.rfid`、变量名 `提示次数` |

`data.*` 对应 A 板周期数据字段；`event.*` 对应 A 板事件字段；无前缀的标识符先查用户变量，再查数据/事件。

## 操作映射表（动作名 → B 板文本命令）

> 说明：B 板固件当前存在 JSON 解析 bug（所有 JSON 命令返回 `parse_error`），
> 因此动作统一降级为**旧文本命令**（`B:XXX` 格式），已验证全部正常返回 `ok`。

| DSL 动作 | B 板文本命令 |
|----------|----------|
| `light.on` / `开灯` | `B:LIGHT:ON` |
| `light.red` / `红灯` | `B:LIGHT:RED` |
| `door.open` / `开门` | `B:DOOR:OPEN` |
| `window.open` / `开窗` | `B:WINDOW:OPEN` |
| `fan.on` / `开风扇` | `B:FAN:ON` |
| `fan.set(value=180)` | `B:FAN:180` |
| `buzzer.beep` / `蜂鸣` | `B:BUZZER:BEEP:<count>:<on_ms>:<off_ms>` |
| `oled.text(line=0, text="tick")` | `B:OLED:SHOW:0:tick` |
| `oled.clear` | `B:OLED:CLEAR` |
| ... | 完整见 `runtime.py` 的 `ACTION_MAP` |

带参数的动作（如 `蜂鸣器.beep(count=3, on_ms=200, off_ms=200)` → `B:BUZZER:BEEP:3:200:200`）会把参数填充进文本命令模板。

## OLED 多行轮播显示

让 OLED 屏幕按时间间隔轮换显示传感器 / 执行器状态。运行自动化脚本时加 `--carousel` 即可：

```bash
python run_automation.py automation/examples/smoke_alarm.auto --carousel
python run_automation.py automation/examples/smoke_alarm.auto --carousel --carousel-interval 5
```

- 默认每 3 秒切换一页，`--carousel-interval` 可调；
- 默认三页：环境（温度/湿度/光）、安防（烟/雨/人/距离/土）、执行器（门/窗/扇/灯/蜂鸣）；
- 占位符从数据源取值，格式化为「是/否」等友好形式；
- 字段冲突处理：B 板字段带 `b_` 前缀（如 `b_door`），B 板灯光亮度用 `light_lv`（避免与 A 板光敏 `light` 冲突）。

自定义页面模板：编辑 `oled_carousel.py` 中的 `DEFAULT_PAGES`，或代码里传入自定义 `pages` 列表。占位符键即 A 板 `data.*` 字段名 + B 板 `b_*` 字段名。

## 模块结构

```
PC_Test/
├── run_automation.py    # 入口：解析脚本 + 连串口 + 主循环
├── oled_carousel.py     # OLED 多行轮播模块（独立于 AST 引擎）
└── automation/          # AST 引擎核心库
    ├── __init__.py      # 包入口
    ├── lexer.py         # 词法分析：文本 -> Token
    ├── parser.py        # 语法分析：Token -> AST（递归下降）
    ├── runtime.py       # 运行时：遍历 AST 执行 + 动作映射
    └── examples/        # 示例脚本（.auto）
```

## 扩展

- 新增动作：在 `runtime.py` 的 `ACTION_MAP` 加一行别名映射即可；
- 新增语句：在 `parser.py` 加 AST 节点 + 解析分支，在 `runtime.py` 加 `_exec` 处理；
- 新增传感器字段：直接写 `data.<字段名>`，无需改代码（字段见 `docs/serial-protocol.md`）。
