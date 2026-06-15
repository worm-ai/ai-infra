# Attractor: 工业级 Agent 协同编排架构

## Metadata

- ID: attractor-industrial-agent-orchestration
- Version: 0.1.0
- Status: active
- Scope: repo
- Owner: architecture

## Intent

AI Agent 架构应收敛到一种分层、可控、可审计、可演进的 Agentic System，而不是停留在 "Agent vs Workflow" 的二元对立。

系统第一性目标不是追求全动态自主，而是在业务复杂度、流程稳定性、合规要求、成本和可维护性之间取得工程化收敛。

## Invariants

- Workflow 不是 Agent 的反面，而是 Agentic System 的结构化形态。
- 工业级多智能体系统应优先采用 "外层固定编排 + 内层智能决策" 的混合模式。
- DAG Workflow 是标准化业务、强合规业务、可枚举流程的默认主力架构。
- ReAct 单智能体只作为原子执行单元，不应承载复杂长流程。
- 高阶自动编排 Agent 只用于流程不确定、链路超长、探索性强的任务。
- Super-Agent 只用于跨团队、跨系统、分布式、多角色协作场景。
- 架构升级必须逐级发生：ReAct -> DAG Workflow -> PlanExec 长智能体 -> Super-Agent。
- 验证架构选择时，优先看可追溯性、故障定位、成本控制和治理能力，而不是 "看起来是否更智能"。

## Boundary Rules

- 不用 "决策权归谁" 作为 Agent / Workflow 的核心划分标准。
- 不把固定流程等同于低级，也不把动态规划等同于高级。
- 不为普通标准化业务引入 Super-Agent。
- 不让纯动态 Agent 承担强合规、强审计、强稳定性的生产主链路。
- 不把多个 Agent 简单拼接当作 Multi-Agent 架构，必须有统一编排、通信和异常处理。
- 不把框架选型等同于架构成熟度；成熟度来自边界、治理、验证和可维护性。

## Dependency Rules

- ReAct 是最小执行单元。
- DAG Workflow 依赖 ReAct 节点完成局部智能任务。
- PlanExec 长智能体可调用 DAG Workflow 作为关键节点兜底。
- Super-Agent 依赖下层 Agent / Workflow / 长任务 Agent 作为可调度子能力。
- MCP 负责工具和数据源复用。
- A2A 负责分布式 Agent 间协作通信。

逻辑顺序：

```text
ReAct 单智能体 -> DAG Workflow -> PlanExec 长智能体 -> Super-Agent
```

## Anti-Patterns

- 无视分层，直接把所有任务交给高阶 Agent。
- 把 Workflow 当成低级自动化脚本，而不是 Agentic System 的结构化形态。
- 把多个 Agent 拼接起来却没有统一编排、通信、状态和异常治理。
- 用 "模型能动态规划" 替代架构边界、验证证据和故障可追踪性。
- 在标准化、强合规、可枚举流程中优先使用纯动态 Agent。
- 为展示效果提前引入 Super-Agent、A2A、分布式治理等高复杂度能力。

## Precedence

- 本吸引子是 `ai-infra` 项目的最高结构基线。
- 项目功能、技术栈、MVP 范围、计划拆分、验证标准都必须服从本吸引子。
- 如果后续设计与本吸引子冲突，优先修改设计；只有在多次计划或审计证明吸引子失效时，才允许修订吸引子。

## Change Policy

修改本吸引子必须满足至少一个条件：

- 多个真实实现计划暴露出同一结构规则失效。
- 审计发现当前不变量阻碍项目真实收敛。
- 新的核心能力改变了 ReAct、DAG Workflow、PlanExec、Super-Agent 之间的依赖关系。

修改时必须记录：

- 变更原因
- 影响范围
- 新旧版本差异
- 迁移策略

## Evidence

- `docs/Agent与Workflow区别-四层Agent协同编排引擎.md`
