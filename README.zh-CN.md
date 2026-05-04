# Echolon

[![PyPI](https://img.shields.io/pypi/v/echolon.svg)](https://pypi.org/project/echolon/)
[![Python](https://img.shields.io/pypi/pyversions/echolon.svg)](https://pypi.org/project/echolon/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-beta-yellow.svg)](https://pypi.org/project/echolon/)
[![By DolphinQuant](https://img.shields.io/badge/by-DolphinQuant-005f87)](https://dolphinquant.com)

> 📖 [English](README.md) · [简体中文](README.zh-CN.md)

> 一个面向期货交易研究的 Python 工具包,从设计之初就考虑让 LLM Agent 直接驱动:搭建策略骨架、校验、回测,出错时读到的是结构化错误信息。当前聚焦于上期所(SHFE)日线期货。

如果你让 Claude Code 或 Cursor 用 `backtrader` 或 `vectorbt` 写过回测,你大概知道结果会怎样:Agent 会编造指标名、瞎猜回调函数签名、把异常静默吞掉。Echolon 就是围绕这种失败模式构建的:错误码稳定、配置全部是带类型的 Pydantic 模型,并且包内自带一个 MCP 服务器,让 Agent 调用结构化工具,而不是对着散文式文档幻觉。

## Install and run a backtest

## 快速上手

Echolon 提供三条顶层命令,对应一个新用户的自然学习路径:

| 命令 | 用途 | 耗时 |
|---|---|---|
| `echolon hello` | 第一印象。通过 akshare 下载 SHFE 铝期货数据(近 2 年)+ 搭建策略 + 自动回测。需要联网。 | ~30 秒 |
| `echolon init <workspace> --market SHFE --instrument <i> --start <d> --end <d>` | 真实项目。通过 akshare 下载行情数据(免费,无需注册),从内置模板搭建策略骨架,写入工作区标记文件。 | ~1–5 分钟 |
| `echolon backtest single <strategy_dir>` | 迭代。从 `strategy_dir` 向上查找工作区标记并自动恢复上下文,重新计算指标并运行回测,无需任何参数。 | ~5–10 秒 |

### 看一眼效果 — `echolon hello`

```bash
pip install echolon
mkdir -p ~/echolon-playground && cd ~/echolon-playground
echolon hello
```

这会下载近 2 年的 SHFE 铝期货数据(via akshare),搭建 `momentum_breakout` 策略模板,写入 `.echolon-workspace.json` 标记文件,并立刻运行回测:

```
./echolon-hello/
├── .echolon-workspace.json     ← 标记文件 — `echolon backtest` 从这里恢复上下文
├── data/                       ← 你的输入(curation) — 见 data/README.md
│   └── SHFE/al/main_contract.csv  ← 换月规则;编辑此文件即可改变规则
├── workspace/
│   ├── data/                   ← 管线输出(可重建) — 见 workspace/data/README.md
│   │   └── market_data/SHFE/aluminum/{sort_by_contract/,sort_by_date.csv,trading_calendar.csv}
│   └── current/backtest/       ← 回测产物落在这里(日志 + 指标)
└── strategy/baseline/          ← 可编辑模板 — 在这里填入你的逻辑
```

两棵树对应两种生命周期:`data/` 是**你的**(跨多次运行持久化);`workspace/` 是**派生的**(管线可重建)。两棵树各有一份 `README.md` 解释这个区分。

**接下来试试:** 打开 `./echolon-hello/strategy/baseline/entry.py`,改一个参数(比如在 `strategy_params.py` 里调整 breakout 的回望窗口),然后重跑:

```bash
echolon backtest single ./echolon-hello/strategy/baseline/
```

观察 Sharpe 比率的变化。

### 启动一个真实项目 — `echolon init`

```bash
pip install echolon      # akshare 默认包含
echolon init my-zinc-strategy --market SHFE --instrument zinc \
                              --start 2022-01-01 --end 2024-12-31 \
                              --template momentum_breakout
```

通过 akshare(新浪财经的免费镜像 — 无需注册、无需 token)下载锌期货 OHLCV 数据,运行 echolon 的标准化管线,从 akshare 的主力合约连续序列推导 `main_contract.csv`,并在 `my-zinc-strategy/strategy/baseline/` 下搭建策略骨架。在已有的骨架里填入业务逻辑即可 — echolon 的框架结构(类名、方法签名、import)已经正确就位。

### 迭代 — `echolon backtest single`

```bash
echolon backtest single my-zinc-strategy/strategy/baseline/
```

从 `strategy/baseline/` 向上查找 `.echolon-workspace.json`,自动恢复 `--market` / `--instrument` / `--start` / `--end`,重算指标,运行回测,打印指标。完全无需任何参数。

供 Agent / CI 消费的结构化输出:

```bash
echolon backtest single my-zinc-strategy/strategy/baseline/ --json
# {
#   "ok": true,
#   "sharpe": 1.04,
#   "max_drawdown": -0.082,
#   "annual_return": 0.18,
#   "total_trades": 142,
#   ...
# }
```

### 探索可用功能

| 命令 | 显示内容 |
|---|---|
| `echolon`(无参数) | 三条命令的快速上手 |
| `echolon --version` | 已安装的 echolon 版本 |
| `echolon doctor` | 依赖预检(ta-lib、akshare)— 行为异常时先跑这个 |
| `echolon examples --list` | 内置策略模板及说明 |
| `echolon indicators list` | 指标目录(给 Agent 用 `--format json`) |
| `echolon schema BacktestConfig` | 导出 Pydantic JSON schema(供 Agent 从零写配置) |
| `echolon validate <strategy_dir>` | 用 echolon 的契约校验一个策略目录(`--json` 给 Agent) |

## Echolon 当前能力

v0.1.1 是刻意收窄的版本。当前端到端可用的是 **SHFE 日线期货研究**:数据采集、对照 217 项指标目录的指标计算、通过 Backtrader 的回测、Optuna TPE 优化(单目标 + 多目标)、带部署就绪打分的滚动窗口分析(walk-forward analysis)、基于 KMeans 的鲁棒试验筛选,以及下文描述的 Agent 接口层。

正在路上的能力,大致按优先级排列:

- SHFE 日内回测(数据管线已支持,引擎链路在稳定中)
- 通过 MiniQMT 实盘部署到 SHFE — `deploy` CLI 在早期内部版本里已经存在,正在重写一个干净的公开版本
- 加密货币永续合约(CCXT 适配器骨架已搭好,但回测和实盘都不在近期路线图上)
- CME 期货和股票(架构插槽已留出,尚无实现)

如果你的工作是 SHFE 期货研究并且让 LLM 在循环里跑,今天就能用。如果你需要加密货币、美国市场、或实盘交易,你来得有点早 — 提一个 issue 告诉我们你想推动哪一块,我们再聊时间线。

## Echolon 之上跑的是什么

Echolon 是 [Qorka](https://dolphinquant.com) 内部的研究引擎 — Qorka 是 [DolphinQuant](https://dolphinquant.com) 旗下的 AI 原生策略生成产品。Qorka 在 echolon 之上驱动一条迭代回路:设计 → 编码 → 回测 → 分析 → 评估 → 精化 — 通过这条回路存活下来的策略会真实部署到上期所。你可以在 [DolphinQuant 投资组合实时看板](https://dolphinquant.com)上看到它们正在运行;Qorka 本身处于私有内测阶段,可在同一站点加入公开候补名单。

这对你意味着两件事:

- **Echolon 每天被真金白银在真实市场上反复打磨。** 错误码、校验器、合约约定 — 它们之所以是现在这个样子,是因为产线上某次失败正是按照那个具体形状摔过的。我们没条件交付不严谨的代码。
- **Echolon 单独使用就是完整的产品。** 如果你来这里是做自己的研究,这个开源引擎就是全部产品,不是一个被阉割的演示版。Qorka 那一侧的工作(范式编排、模式决策策略、策略注册中心)在我们的私有 monorepo 里 — 任何人拿到这个引擎都能自己重新写一份。

## 它哪里是 AI 原生的

包内交付了四样东西,Agent 不需要读散文就能直接触达:

- **一个 MCP 服务器** — `echolon-mcp` 通过 stdio 暴露 22 个工具:策略校验、完整指标目录、骨架生成、错误码查询、参数代码生成。任何兼容 MCP 的运行时都能接入。
- **wheel 包内的 23 个技能包(skill)** — 快速上手、组件契约、指标命名规则、参数架构、五种规范的策略形态,加上每个 API 的使用守则。索引在 `echolon/native/skills/SKILLS.md`,由 Agent 的技能运行时按需加载。
- **31 个分类编目的错误码** — 每个 `EchelonError` 都带一个错误码、一段参数化的修复字符串、一个文档 URL。Traceback 是结构化的,Agent 可以直接据此行动。
- **三个可工作的策略模板** — `minimal`、`momentum_breakout`、`rsi_mean_reversion`。Agent 复制其中一个并修改,而不是从零写文件。

当你让一个连上 `echolon-mcp` 的 Claude Code 会话「在铜上做一个趋势跟随策略」时,真实的流程是这样:Agent 调 `list_skills`、挑出 `patterns` 和 `quick_start`,调 `load_template("momentum_breakout")`,调 `list_indicators(has_lookback=True)` 确认可用指标,改 `entry.py` 和 `exit.py`,反复调 `validate_strategy_full(strategy_dir)` 直到全部通过,然后跑回测。如果哪里出错,它从 traceback 里解析 `[CODE-NNN]` 并调 `get_error_doc(code)`。整个回路里没有一处需要它去猜。

## 接入你的 Agent 运行时

| 运行时 | 配置方式 |
|---|---|
| Claude Code | `claude mcp add echolon echolon-mcp` |
| Cursor | 设置 → MCP Servers → 添加 `{"echolon": {"command": "echolon-mcp"}}` |
| OpenAI Codex CLI | 在 `~/.codex/config.toml` 里添加 `echolon` 服务器 |
| OpenAI Agents SDK (Python) | `MCPServerStdio(command="echolon-mcp")` |
| LangChain / LangGraph | 通过 [`langchain-mcp-adapters`](https://pypi.org/project/langchain-mcp-adapters/) |
| CrewAI / AutoGen / 其他 | 任何[兼容 MCP 的](https://modelcontextprotocol.io/) 客户端适配器 |

Agent 的入门导引是 [`llms.txt`](./llms.txt) — 让你的 Agent 看一次,它就知道其他东西去哪儿找。

## 在哪里找东西

对 Agent 重要的所有东西都打包在 wheel 内。`pip install` 之后,Agent 拥有同等访问权 — 不需要再去抓一个独立的文档站。

| 接口 | 位置 |
|---|---|
| MCP 服务器 | `echolon-mcp` 控制台脚本 — 调 `list_tools` 做实时反射 |
| 技能包(23 个) | `echolon/native/skills/` — 调 MCP `list_skills` / `get_skill(name)` |
| 错误码(31 个) | `echolon/native/errors/codes/` — 调 MCP `get_error_doc(code)` |
| 模板(3 个) | `echolon/native/templates/` — 调 MCP `list_templates` / `load_template(name)` |
| 模式(5 个) | 调 MCP `list_patterns` / `get_pattern(name)` |
| CLI 参考 | `echolon --help`(每个子命令也有 `--help`) |
| Pydantic schema | `echolon schema BacktestConfig`(或任何其他配置) |
| LLM 入门导引 | [`llms.txt`](./llms.txt) |
| 版本历史 | [CHANGELOG.md](./CHANGELOG.md) |

Python 的公共接口在顶层重新导出了常用对象 — `echolon.quick_start`、`echolon.BacktestConfig`、`echolon.OptunaConfig`、`echolon.TradingContext`、`echolon.EchelonError`。`api_reference` 和 `config_reference` 这两个技能包里有带类型的签名。

## 现在还做不了什么

把话说具体,免得你被坑:

- 只有 SHFE 日线回测是产线状态。加密货币、日内、CME、股票都不是。
- 实盘交易尚未公开发布。下一个实盘目标是通过 MiniQMT 接入 SHFE(仅 Windows 的券商集成);加密货币和美国市场的实盘不在短期路线图上。
- 仅支持 Optuna TPE。无网格搜索、无随机搜索、无贝叶斯预算。
- 单机。Optuna 并行使用本地核心,无分布式编排。
- 需要 Python 3.11+。
- 1.0 之前,公共 API 在 minor 版本之间可能变动。Breaking changes 会记录在 [CHANGELOG.md](./CHANGELOG.md)。

## 自带数据

如果你已经有原始的 SHFE XLS 文件(从 shfe.com.cn 下载),直接用 `SHFEFileDayExtractor` 替代 akshare 即可。如果你的数据是另一种格式(券商 CSV、tushare 拉取、自建数据库),需要把三个文件落到 `{workspace}/workspace/data/market_data/SHFE/{instrument}/` 下:

| 文件 | Schema |
|---|---|
| `sort_by_contract/{contract}.csv` | `contract, date, prev_close, prev_settlement, open, high, low, close, settlement, price_change, settlement_change, volume, turnover, open_interest` |
| `sort_by_date.csv` | 同样的列,所有行按日期合并并排序。 |
| `trading_calendar.csv` | `date, is_trading_day`(布尔)。 |

另外在 `{workspace}/data/SHFE/{instrument_code}/` 下(注意是**短代码**,例如 `al` 而不是 `aluminum`):

| 文件 | Schema |
|---|---|
| `main_contract.csv` | `date, main_contract`,其中 `main_contract` 是带 `.SF` 后缀的合约代码(例如 `al2401.SF`)。每次主力合约换月一行。 |

Echolon **不会**从原始 OHLCV 自动推导 `main_contract.csv` — 这是一份**用户输入**,编码了你的换月规则(成交量 / 持仓量 / 距离到期日的逻辑)。SHFE 走 akshare 路径时,`echolon init` 会替你推导;否则请自己产出该文件并放到指定位置。

## 不想用 LLM 的策略思路

如果你不想配置 LLM Agent,只想读代码学习,echolon 在 `echolon/native/templates/` 下提供三个模板策略。每个都是完整可运行的参考实现,可以直接研究或 fork。

- **`minimal`** — 可能存在的最小策略。空骨架,返回「永远 hold」的输出。最适合在加任何逻辑之前先理解框架的类形态和方法契约。
- **`momentum_breakout`** — 20 根 K 线的 Donchian 突破入场,ATR 移动止损出场。趋势跟随的「Hello World」。任何「价格 vs 滚动窗口比较」类入场逻辑都可以以此为模板。
- **`rsi_mean_reversion`** — RSI(14) 跌破 30 入多 / 突破 70 入空,时间退出。任何基于震荡指标的均值回归策略都可以以此为模板。

复制一个到你的工作区并迭代:

```bash
echolon examples copy momentum_breakout my-strategy/strategy/baseline/
echolon backtest single my-strategy/strategy/baseline/
```

或者在 `echolon init` / `echolon hello` 后传 `--template <name>`,从一个比 `minimal` 更丰富的基准开始。

## 安装疑难排查

`pip install echolon` 在以下平台开箱即用:
- Linux x86_64(manylinux2014)
- macOS x86_64 + arm64(M1/M2/M3)
- Windows x86_64
- Python 3.11–3.12

在这些平台上,所有依赖(包括 ta-lib)都以预编译 wheel 形式分发 — 不需要本地编译器。

在其他平台(Linux ARM64、Alpine/musl、FreeBSD、Python 3.13+),唯一可能需要源码编译的依赖是 **ta-lib 的 C 库**。各平台安装方法:

```bash
# Debian / Ubuntu(包括树莓派):
sudo apt install ta-lib0 ta-lib-dev
pip install --force-reinstall TA-Lib

# macOS(Homebrew):
brew install ta-lib
pip install --force-reinstall TA-Lib

# 任意平台从源码安装:
# https://ta-lib.org/install.html
```

安装完后,跑 `echolon doctor` 确认一切就位:

```
$ echolon doctor
  ✓ ta-lib              talib import works (version 0.6.7)
  ✓ akshare             not installed (optional — only needed for `echolon init` data download)
  ✓ backtrader          available
  ✓ optuna              available
```

## 许可证

Apache 2.0 — 见 [LICENSE](LICENSE)。可自由使用,商用或非商用均可。

## 引用

如果 echolon 出现在学术工作中:

```bibtex
@software{echolon,
  title = {Echolon: AI-native quantitative trading engine},
  author = {DolphinQuant},
  year = {2026},
  url = {https://github.com/dolphinquant/echolon},
}
```

## 状态

v0.1.1,beta,2026 年。活跃开发中。由 [DolphinQuant](https://dolphinquant.com) 构建并维护 — 同一支团队在 SHFE 上运营 Qorka。欢迎在 [github.com/dolphinquant/echolon](https://github.com/dolphinquant/echolon) 提 issue 和 pull request。
