# QTrader

一个**轻量化**的量化回测与模拟交易框架：专注策略研究与执行闭环，**与数据完全解耦**。

很多现有的量化回测/模拟系统要么过度重量化，要么将核心能力绑定到收费数据服务（甚至“挂羊头卖狗肉”）。QTrader 的设计目标是反过来：

- 框架只负责：事件驱动回测/模拟、撮合、账户/持仓、绩效分析、报告与可视化
- 数据完全外置：通过 **Data Contract（数据合约/接口）**获取回测所需的最小数据集
- 可按需求伸缩：你可以替换数据源实现（CSV / 数据库 / 在线 API / 你自己的数据服务），而不用改框架核心

> 适合：想要一个“干净、可控、可扩展”的研究框架；不想把策略研究绑死在某个数据平台或庞大系统里的开发者。

---

## 特性

- **事件驱动架构**：贴近真实交易流程（按日 / 分钟 / Tick 事件循环）
- **策略与框架分离**：策略只写交易逻辑，底层撮合/记账由框架完成
- **状态持久化（可暂停/恢复/分叉）**：支持在回测过程中保存状态并继续
- **数据接入可插拔**：通过标准接口接入任意数据源
- **结果报告**：生成包含净值曲线、交易记录、关键指标（夏普、回撤等）的报告
- **内置监控/可视化**：便于观察回测过程与结果

---

## 截图

> 这些截图来自 `screenshot/` 目录。

![Screenshot 1](screenshot/screenshot1.png)
![Screenshot 2](screenshot/screenshot2.png)
![Screenshot 3](screenshot/screenshot3.png)
![Screenshot 4](screenshot/screenshot4.png)

---

## 快速开始

### 1) 环境

- Python >= 3.9

建议使用虚拟环境（venv/conda 均可）。

### 2) 安装依赖

本项目是一个标准的 Python package（含 `pyproject.toml`）。

你可以用 pip 安装（建议在虚拟环境中）：

```bash
python -m pip install -U pip
python -m pip install -e .
```

> 注意：不同发行版的 Python 可能默认不带 pip，需要先安装 `python3-pip`。

### 3) 跑一个示例回测

代码示例在 `examples/` 目录中（以及用户文档里有更完整的端到端示例）。

---

## 数据合约（Data Contract）理念

QTrader 不内置任何“数据平台绑定”。框架只依赖一个抽象的数据提供者接口（Data Provider），策略/回测引擎在运行时通过该接口拉取：

- 交易日历
- 当前/历史价格（按频率）
- 标的基础信息（停牌、名称等）

你可以实现自己的 `DataProvider`：

- 直接读取 CSV
- 访问本地数据库
- 连接你自己的行情/因子服务
- 接入第三方 API

框架本身不关心数据从哪里来，只关心“合约是否兑现”。

---

## 文档

- 完整用户文档：`USER_GUIDE.md`

---

## 项目结构

```
.
├── src/              # 框架源码
├── examples/         # 示例
├── tests/            # 测试
├── screenshot/       # README 截图
├── pyproject.toml
└── USER_GUIDE.md
```

---

## License

MIT License. See `LICENSE`.
