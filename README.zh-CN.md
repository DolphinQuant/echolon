# Echolon

[![PyPI](https://img.shields.io/pypi/v/echolon.svg)](https://pypi.org/project/echolon/)
[![Python](https://img.shields.io/pypi/pyversions/echolon.svg)](https://pypi.org/project/echolon/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-beta-yellow.svg)](https://pypi.org/project/echolon/)
[![By DolphinQuant](https://img.shields.io/badge/by-DolphinQuant-005f87)](https://dolphinquant.com)

> 📖 [English](README.md) · [简体中文](README.zh-CN.md)

> 一个面向期货交易研究的 Python 工具包,从一开始就是为「让 LLM Agent 直接上手」设计的:搭策略骨架、跑校验、做回测,出错时返回的是结构化的错误信息。当前主要做上期所(SHFE)的日线期货。

## 快速上手

Echolon 在顶层提供三条命令,刚好对应一个新用户的上手顺序:

| 命令 | 用途 | 耗时 |
|---|---|---|
| `echolon hello` | 看一眼效果。用 akshare 下载近 2 年的 SHFE 铝期货数据,再加策略骨架 + 自动回测,需要联网。 | ~30 秒 |
| `echolon init <workspace> --market SHFE --instrument <i> --start <d> --end <d>` | 起一个真实项目。用 akshare 拉行情(免费,不用注册),从内置模板生成策略骨架,顺便写好工作区标记文件。 | ~1–5 分钟 |
| `echolon backtest single <strategy_dir>` | 改完之后再跑。从 `strategy_dir` 一路向上找工作区标记并自动恢复上下文,重算指标后跑回测,一个参数都不用传。 | ~5–10 秒 |

### 看一眼效果 — `echolon hello`

```bash
pip install echolon
mkdir -p ~/echolon-playground && cd ~/echolon-playground
echolon hello
```

这条命令会通过 akshare 拉近 2 年的 SHFE 铝期货数据,基于 `momentum_breakout` 模板搭好策略,写入 `.echolon-workspace.json` 标记文件,然后立刻跑一次回测:

```
./echolon-hello/
├── .echolon-workspace.json     ← 工作区标记 — `echolon backtest` 从这里恢复上下文
├── data/                       ← 你提供的数据(需要你自己维护) — 见 data/README.md
│   └── SHFE/al/main_contract.csv  ← 换月规则;改这个文件就能改规则
├── workspace/
│   ├── data/                   ← 管线产生的派生数据(随时可重建) — 见 workspace/data/README.md
│   │   └── market_data/SHFE/aluminum/{sort_by_contract/,sort_by_date.csv,trading_calendar.csv}
│   └── current/backtest/       ← 回测产物落在这里(日志 + 指标)
└── strategy/baseline/          ← 可改的策略模板 — 业务逻辑写在这里
```

两棵目录树承担两种角色:`data/` 是**你自己的数据**(跨多次运行长期保留),`workspace/` 是**派生产物**(管线随时能重新算出来)。两边各有一份 `README.md` 解释这层区分。

**接下来可以试试**:打开 `./echolon-hello/strategy/baseline/entry.py`,改一个参数(比如把 `strategy_params.py` 里 breakout 的回看窗口调一下),再跑一次:

```bash
echolon backtest single ./echolon-hello/strategy/baseline/
```

看 Sharpe 比率怎么变。

### 起一个真实项目 — `echolon init`

```bash
pip install echolon      # akshare 已经默认包含
echolon init my-zinc-strategy --market SHFE --instrument zinc \
                              --start 2022-01-01 --end 2024-12-31 \
                              --template momentum_breakout
```

这条命令通过 akshare(走的是新浪财经的免费镜像,不用注册、也不要 token)下载锌期货 OHLCV,跑 echolon 的标准化管线,从主力合约连续序列推导出 `main_contract.csv`,并在 `my-zinc-strategy/strategy/baseline/` 下搭好策略骨架。剩下的事就是往骨架里填业务逻辑 — 类名、方法签名、import 这些 echolon 都帮你摆好了。

### 改完再跑 — `echolon backtest single`

```bash
echolon backtest single my-zinc-strategy/strategy/baseline/
```

这条命令从 `strategy/baseline/` 一路向上找 `.echolon-workspace.json`,自动恢复 `--market` / `--instrument` / `--start` / `--end`,重新算指标,跑回测,打印结果。一个参数都不用传。

如果是给 Agent 或 CI 用,加 `--json` 拿结构化输出:

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

### 看看还有什么命令

| 命令 | 输出 |
|---|---|
| `echolon`(不带参数) | 三条命令的快速上手提示 |
| `echolon --version` | 当前安装的 echolon 版本 |
| `echolon doctor` | 依赖预检(ta-lib、akshare)— 行为不对劲时先跑这个 |
| `echolon examples --list` | 内置策略模板和说明 |
| `echolon indicators list` | 指标目录(给 Agent 用就加 `--format json`) |
| `echolon schema BacktestConfig` | 导出 Pydantic JSON schema(供 Agent 从零写配置) |
| `echolon validate <strategy_dir>` | 拿 echolon 的契约校验一个策略目录(`--json` 给 Agent) |

## Echolon 现在能做什么

v0.1.1 的范围是故意做窄的。当前真正端到端能用的是 **SHFE 日线期货研究**:数据采集、覆盖 217 个指标的计算引擎、跑在 Backtrader 上的回测、Optuna TPE 优化(单目标和多目标都支持)、带部署就绪打分的滚动窗口分析(walk-forward analysis)、基于 KMeans 的鲁棒试验筛选,加上下面要讲的 Agent 接入层。

后面要做的事,大致按优先级:

- SHFE 日内回测(数据管线已经支持,引擎链路还在收尾)
- 通过 MiniQMT 实盘到 SHFE — `deploy` CLI 在内部早期版本里已经能跑,现在在重写一个干净的公开版本
- 加密货币永续合约(CCXT 适配器骨架已经有了,但回测和实盘都不在近期排期里)
- CME 期货和股票(架构上的位子留好了,但还没实现)

如果你的活就是 SHFE 期货研究 + 让 LLM 在迭代回路里跑,那现在就能用。如果你想要的是加密货币、美国市场或者实盘交易,那你来得有点早 — 提个 issue 告诉我们你最想推进哪一块,我们再聊时间表。

## Echolon 之上跑的是什么

Echolon 是 [Qorka](https://dolphinquant.com) 内部的研究引擎 — Qorka 是 [DolphinQuant](https://dolphinquant.com) 旗下的 AI 原生策略生成产品。Qorka 在 echolon 之上跑一条迭代回路:设计 → 编码 → 回测 → 分析 → 评估 → 精化 — 在这条回路里活下来的策略,会真的上线到上期所。你可以在 [DolphinQuant 投资组合实时看板](https://dolphinquant.com)上看到它们正在跑;Qorka 本身处于私有内测阶段,可在同一站点报名公开候补名单。

这件事对你的意义有两点:

- **Echolon 每天都在用真金白银在真实市场上磨**。错误码、校验器、合约约定这些东西长成现在这个样子,是因为产线上有过一次正好踩中那个形状的翻车。我们没条件交付不严谨的代码。
- **Echolon 单独用就是完整的产品**。如果你来这里是为了自己做研究,这个开源引擎就是产品全部,不是一个剥皮版的演示。Qorka 那一侧的事情(范式编排、模式决策策略、策略注册中心)在我们的私有 monorepo 里 — 拿到这个引擎,谁都能自己写一份。

## AI 原生体现在哪里

包里给 Agent 准备了四样东西,不用读大段文档就能直接调:

- **一个 MCP 服务器** — `echolon-mcp` 通过 stdio 暴露 22 个工具:策略校验、完整指标目录、骨架生成、错误码查询、参数代码生成。任何兼容 MCP 的运行时都能接进来。
- **wheel 包里的 23 个技能包(skill)** — 快速上手、组件契约、指标命名规则、参数架构、五种规范的策略形态,加上每个 API 的使用守则。索引在 `echolon/native/skills/SKILLS.md`,Agent 的技能运行时按需加载。
- **31 个分类编目的错误码** — 每个 `EchelonError` 都自带错误码、参数化的修复字符串和文档 URL。Traceback 是结构化的,Agent 可以直接照着办。
- **三个能跑的策略模板** — `minimal`、`momentum_breakout`、`rsi_mean_reversion`。Agent 拷一个改一改,而不是从零写文件。

当你给一个连上 `echolon-mcp` 的 Claude Code 会话扔一句「在铜上做一个趋势跟随策略」,实际发生的事大概是这样:Agent 调 `list_skills`,挑出 `patterns` 和 `quick_start`;调 `load_template("momentum_breakout")`;调 `list_indicators(has_lookback=True)` 确认可用指标;改 `entry.py` 和 `exit.py`;反复调 `validate_strategy_full(strategy_dir)` 直到全部通过;然后跑回测。中途哪里出错,它从 traceback 里解析 `[CODE-NNN]`,调 `get_error_doc(code)` 查文档。整条路上没有一处需要它瞎猜。

## 接到你的 Agent 运行时上

`pip install echolon` 之后,`echolon-mcp` 这条命令就在你的 `PATH` 上了。在你的 Agent 运行时里注册一次就行:

| 运行时 | 配置方式 |
|---|---|
| **Claude Code** | `claude mcp add -s user echolon -- echolon-mcp` |
| Cursor | 设置 → MCP Servers → 添加 `{"echolon": {"command": "echolon-mcp"}}` |
| OpenAI Codex CLI | 在 `~/.codex/config.toml` 里加一个 `echolon` 服务器 |
| OpenAI Agents SDK (Python) | `MCPServerStdio(command="echolon-mcp")` |
| LangChain / LangGraph | 通过 [`langchain-mcp-adapters`](https://pypi.org/project/langchain-mcp-adapters/) |
| CrewAI / AutoGen / 其他 | 任何[兼容 MCP 的](https://modelcontextprotocol.io/) 客户端适配器 |

**Claude Code 用户特别说一句**:`-s user`(也就是 `--scope user`)把注册写到用户级配置里,这样你**所有项目**里都能用;不加这个参数,Claude Code 默认是 `local` 作用域,只对当前项目生效。命令里那个 `--` 是用来把注册名(`echolon`)和启动命令(`echolon-mcp`)分开的。注册一次之后,跑 `claude mcp list` 应该能看到 `echolon` 是已连接的 stdio 服务器。**记得重启 Claude Code 会话**,新工具(前缀是 `mcp__echolon__*`)才会加载进来。

Agent 的入门导引在 [`llms.txt`](./echolon/llms.txt) — 让你的 Agent 看一遍,它就知道别的东西去哪儿找了。(`echolon init` 和 `echolon hello` 也会把这份文件的副本写到生成的 workspace 根目录里,这样 Agent 即便没接 MCP,也能在本地找到。)

## 东西放在哪

Agent 需要的所有东西都打包在 wheel 里。`pip install` 之后,Agent 立刻就有同等的访问能力 — 不用再去找一个单独的文档站。

| 接口 | 位置 |
|---|---|
| MCP 服务器 | `echolon-mcp` 控制台脚本 — 调 `list_tools` 实时反射 |
| 技能包(23 个) | `echolon/native/skills/` — 调 MCP `list_skills` / `get_skill(name)` |
| 错误码(31 个) | `echolon/native/errors/codes/` — 调 MCP `get_error_doc(code)` |
| 模板(3 个) | `echolon/native/templates/` — 调 MCP `list_templates` / `load_template(name)` |
| 模式(5 个) | 调 MCP `list_patterns` / `get_pattern(name)` |
| CLI 参考 | `echolon --help`(每个子命令也有自己的 `--help`) |
| Pydantic schema | `echolon schema BacktestConfig`(其他配置同理) |
| LLM 入门导引 | [`llms.txt`](./echolon/llms.txt)(`echolon init`/`hello` 也会把副本写到 workspace 根目录) |
| 版本历史 | [CHANGELOG.md](./CHANGELOG.md) |

Python 公共接口在顶层重新导出了几个常用对象 — `echolon.quick_start`、`echolon.BacktestConfig`、`echolon.OptunaConfig`、`echolon.TradingContext`、`echolon.EchelonError`。`api_reference` 和 `config_reference` 这两个技能包里有带类型的签名。

## 现在还做不了什么

把丑话说在前头,免得踩坑:

- 只有 SHFE 日线回测是生产可用的。加密货币、日内、CME、股票都不是。
- 实盘还没公开发布。下一步实盘目标是通过 MiniQMT 接 SHFE(只能在 Windows 上跑的券商集成);加密货币和美国市场的实盘不在短期排期里。
- 优化只支持 Optuna TPE。没有网格搜索、随机搜索、贝叶斯预算控制。
- 单机跑。Optuna 用本地多核并行,没有分布式编排。
- 需要 Python 3.11+。
- 1.0 之前公共 API 在 minor 版本之间可能会变。Breaking changes 都会记到 [CHANGELOG.md](./CHANGELOG.md)。

## 用自己的数据

如果你已经有原始的 SHFE XLS 文件(从 shfe.com.cn 下载的),直接用 `SHFEFileDayExtractor` 替掉 akshare 那一路就行。如果你的数据是别的格式(券商 CSV、tushare 拉取、自建数据库等等),需要按照下面的约定把三个文件落到 `{workspace}/workspace/data/market_data/SHFE/{instrument}/` 下:

| 文件 | Schema |
|---|---|
| `sort_by_contract/{contract}.csv` | `contract, date, prev_close, prev_settlement, open, high, low, close, settlement, price_change, settlement_change, volume, turnover, open_interest` |
| `sort_by_date.csv` | 列同上,所有合约的行按日期合并并排序。 |
| `trading_calendar.csv` | `date, is_trading_day`(布尔)。 |

外加一份在 `{workspace}/data/SHFE/{instrument_code}/` 下(注意这里是**短代码**,例如 `al` 而不是 `aluminum`):

| 文件 | Schema |
|---|---|
| `main_contract.csv` | `date, main_contract`,其中 `main_contract` 是带 `.SF` 后缀的合约代码(例如 `al2401.SF`)。每次主力换月一行。 |

Echolon **不会**自动从原始 OHLCV 推导 `main_contract.csv` — 这份文件算作**用户输入**,里面写的是你自己的换月规则(成交量 / 持仓量 / 离到期日多少天之类的逻辑)。走 SHFE + akshare 那条路时,`echolon init` 会替你推一份;其他情况下请自己产出这个文件,放到上面的位置。

## 不想用 LLM,只想读代码学习

如果你不打算配 LLM Agent,只想读代码学,echolon 在 `echolon/native/templates/` 下放了三份模板策略。每一份都是完整能跑的参考实现,可以直接读,也可以 fork 下来改。

- **`minimal`** — 最简单的策略骨架。空壳子,逻辑就是「永远 hold」。最适合在加业务逻辑之前先把框架的类形态和方法契约理顺。
- **`momentum_breakout`** — 20 根 K 线的 Donchian 突破入场,ATR 移动止损出场。趋势跟随的「Hello World」。任何「价格 vs 滚动窗口」类的入场逻辑都能套这个模板。
- **`rsi_mean_reversion`** — RSI(14) 跌破 30 入多 / 突破 70 入空,按时间退出。任何基于震荡指标的均值回归策略都能套这个模板。

拷一份到你的工作区,然后开始改:

```bash
echolon examples copy momentum_breakout my-strategy/strategy/baseline/
echolon backtest single my-strategy/strategy/baseline/
```

或者在 `echolon init` / `echolon hello` 后面加 `--template <name>`,起步就是比 `minimal` 更丰富的基线。

## 安装常见问题

`pip install echolon` 在下面这些平台上是开箱即用的:
- Linux x86_64(manylinux2014)
- macOS x86_64 + arm64(M1/M2/M3)
- Windows x86_64
- Python 3.11–3.12

在这些平台上,所有依赖(包括 ta-lib)都是预编译的 wheel,本地不用再装编译器。

其他平台(Linux ARM64、Alpine/musl、FreeBSD、Python 3.13+)上,可能要从源码编译的就只有一个 **ta-lib 的 C 库**。各平台装法:

```bash
# Debian / Ubuntu(包括树莓派):
sudo apt install ta-lib0 ta-lib-dev
pip install --force-reinstall TA-Lib

# macOS(Homebrew):
brew install ta-lib
pip install --force-reinstall TA-Lib

# 任意平台从源码装:
# https://ta-lib.org/install.html
```

装完之后跑一下 `echolon doctor` 确认一切就位:

```
$ echolon doctor
  ✓ ta-lib              talib import works (version 0.6.7)
  ✓ akshare             not installed (optional — only needed for `echolon init` data download)
  ✓ backtrader          available
  ✓ optuna              available
```

## 许可证

Apache 2.0 — 见 [LICENSE](LICENSE)。可以自由使用,商用非商用都行。

## 引用

如果你在学术工作里用到了 echolon:

```bibtex
@software{echolon,
  title = {Echolon: AI-native quantitative trading engine},
  author = {DolphinQuant},
  year = {2026},
  url = {https://github.com/dolphinquant/echolon},
}
```

## 状态

v0.1.1,beta,2026 年。还在活跃开发中。由 [DolphinQuant](https://dolphinquant.com) 开发并维护 — 同一支团队也在 SHFE 上运营 Qorka。欢迎到 [github.com/dolphinquant/echolon](https://github.com/dolphinquant/echolon) 提 issue 和 pull request。
