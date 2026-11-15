# 研序 · 本机科研工作台

在原项目新增独立的 `backend/app/scientific_research` 模块，旧行业代码保持可用。浏览器新任务默认使用有界研究 Agent 循环、并发精读、提纲与分节写作、局部审核修订、网页正文与原文阅读；支持取消/手动恢复、Markdown/JSON 导出和只读 MCP 服务。

这是本机单用户版本，使用 SQLite 持久化队列、事件、结果和论文分析缓存；只绑定 127.0.0.1，不依赖旧行业数据库、Docker 或 Node 构建。`completed` 表示本次流水线无已报告错误，不表示科学结论正确或方向创新。引文定位通过不等于语义支持成立，最终需要研究者检查。

## 模块优化与学习路线（2026-11-08）

新增调用边界上下文投影/预算、仅用于检索规划的跨任务研究线索记忆、工具循环来源身份与停止原因、报告结构诊断；修复可选嵌入/LangSmith配置未加载的问题。先阅读 [模块优化计划](docs/scientific/2026-11-08-module-upgrade-plan.md) 和 [源码学习与面试路线](docs/scientific/2026-11-08-source-study-and-interview.md)。

记忆可经鉴权 GET /api/research-memory?query=... 查看相关线索，DELETE /api/research-memory/{run_id} 仅删除线索，不删除研究历史。历史不是证据，任务恢复固定其初始记忆快照。报告新增 report_diagnostics，循环新增 loop_metrics，均不代表科学结论或自动质量评测认证。

## 统一主图与证据检索（2026-11-04）

两种入口现已接入 discover/index/analyze/assess/write/audit/finalize 主图，任务内支持 BM25 与可选 bge-m3 混合检索，提供可选 LangSmith 摘要追踪。页面底部展开“查看完整工作流与运行诊断”查看实际主图与阶段指标。操作、配置和真实验证边界见 [统一研究说明](docs/scientific/unified-research-guide.md)。当前恢复仍使用 SQLite 工件复用；后文较早的固定循环说明按对应入口理解。

## 两种研究入口

当前支持以题找文与以文找文。以题模式填写研究问题即可开始；以文模式上传或选择 1–3 篇文字型论文，研究目标可留空。使用有页码和内容哈希的真实片段规划与筛选相关工作，共用后续证据整理和网页报告。关联基于文本判断，尚未核验引用/被引关系；种子身份去重受可用标识限制。

操作、原文范围、检索排序及交付边界见 [双入口使用说明](docs/scientific/paper-search-guide.md)。趋势模式使用有界收集器；精读的以题入口保留自主研究循环。本文后续部分较早的循环与固定写作说明主要针对精读入口。

## 浏览器启动（推荐）

双击项目根目录的 `start-scientific.cmd`，或执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-scientific.ps1 -OpenBrowser
```

默认地址为 `http://127.0.0.1:8765`。启动脚本自动打开带一次性连接片段的浏览器链接，页面立即移除 URL 中的访问令牌，并存入 sessionStorage。没有自动打开时，输入启动终端显示的本机访问令牌。

首次可点击“先体验合成演示”，无需密钥或在线检索。真实分析需按下文配置独立模型环境变量、重启服务，然后填写研究问题和预算并点击“开始研究”。Agent 默认主动找论文，已有文献可以作为补充。密钥不会返回页面，也不会自动读取旧项目密钥。

**默认入口已纠正为 Agent 自动找论文：填写研究问题即可点击“开始研究”，不需要先上传或手动选择论文。** 默认勾选“由 Agent 自动检索、筛选论文并尝试获取全文”。右侧上传、手动检索仅是可选补充；取消自动检索时才要求提供材料。

自动流程为：Planner 组织检索计划 → Controller 根据候选与最近工具结果选择检索、查看元数据、获取全文、读片段或结束选文 → 并发 Reader 提取可定位证据 → 综合与方向生成/审核 → 规划四节提纲 → 分节写作 → 报告审核与最多一轮局部修订。新任务默认选择两篇参考论文，不强凑数量。Controller 通过结构化 JSON 选择程序内工具，不是任意代码执行，也没有接入外部论文 MCP。

研究循环默认最多 10 步，手动恢复不重置任务总步数和累计模型调用；每任务最多 4 次搜索尝试、2 次全文获取尝试。重复已成功动作、未知工具/论文、未经阅读就选文均会被拦截，错误回写观察上下文。三次连续无进展或达到步数上限时停止；只保留已读材料并标注选文尚未完成。规划、工具决策、分析、写作与审核均计入调用预算。

报告固定为四节：选题结论与推荐依据、方向比较与证据缺口、参考论文为什么值得读、最小验证方案与下一步。段落区分事实、推断、建议与局限；事实/推断/建议须引用提供给该节的证据 ID，点击正文编号查看原文。研究建议可以尚未验证，但不能写成已证实结果。资料不足时说明缺口，不制造顶刊资格或实验成绩。

写作中可查看已完成章节的未审核草稿。结束后直接显示网页正文，无需下载；导出仍可选。已完成研究循环、可复用分析和各节草稿保存到任务中，恢复时继续缺失章节或失败审核；分析本身失败时重新分析，并保留成功论文的阅读缓存。单节失败不抹去其他章节。超时、调用预算或审核未通过时交付明确标记的部分报告。

全文获取失败时，明确降级为摘要，不能声称已核验全文实验。检索无结果、网络不可用或筛选未找到合适资料时，显示失败原因，不生成论文。已完成的检索/获取阶段持久化，恢复可跳过；种子摘要与自动获取的同一论文全文合并，优先保留全文。

研究循环与完整写作的功能验证使用固定模型与来源夹具，以及浏览器合成演示；不代表真实科研质量已经通过评测。arXiv 检索不能单独证明顶会录用，顶会条件需核验来源元数据。正式评测按用户要求留到 Agent 功能稳定之后。

数据默认保存在 `backend/data/scientific/research.sqlite`，通过 `SCIENTIFIC_DATA_DIR` 可指定另一目录。一个数据目录只允许一个 worker；不要用多进程参数启动本应用。队列上限 20 个任务。

Ctrl+C 停止后，原正在运行的任务、以及遗留的 queued 真实模型任务，在下次启动时标为 interrupted，需要在页面显式恢复。已经完成的论文证据按文档、研究要求、模型和 Skill 缓存；恢复不重置累计调用预算。阶段内部未完成的模型调用可能需要重做，不承诺逐次调用恰好一次。

页面每 1.2 秒读取快照与持久事件，也提供带身份校验的 SSE 接口。历史任务与结果可在服务重启后查看。导出使用同站 HttpOnly 下载 cookie，其他 API 仍需要 Bearer 令牌。

在线检索与相似工作查询使用 arXiv，失败或无结果时自动切换 OpenAlex。OpenAlex 结果保留期刊、DOI 和来源信息；摘要不能支持全文实验判断，元数据也不能直接证明顶刊资格。已在当前网络通过真实 API 和浏览器搜索验证，返回 10 篇 OpenAlex 文献。arXiv 全文下载和真实模型研究质量仍需单独验证。

## 命令行与测试

从项目 `backend` 目录，在 PowerShell 中执行：

```powershell
$env:PYTHONPATH = (Resolve-Path .\app).Path
$env:PYTHONIOENCODING = 'utf-8'
.\.venv\Scripts\python.exe -B -m unittest discover -s test_scientific -v
.\.venv\Scripts\python.exe -B -m scientific_research.cli --demo --output .\eval\scientific_demo
```

`--demo` 使用合成论文和固定模型响应，不调用搜索或模型 API。输出 UUID 命名的 `.json` 和 `.md`，两者均标明合成演示。

启动器自动读取项目根目录 `.env.scientific`，显式 PowerShell 环境变量优先。Ollama 配置例子为 `http://127.0.0.1:11434/v1` 与 `qwen3.5:4b`；配置了名称并不意味着本地已安装该模型。页面现在检查本机 11434 端口的模型列表：服务未启动或模型缺失时提示原因，并在创建/恢复研究前拦截，不自动下载模型。可用 `ollama list` 检查本机实际模型，保持配置名称一致。远程兼容接口仅显示已配置，不宣称已验证可用。

配置示例为 `.env.scientific.example`，不读取旧项目密钥。双击入口保留运行窗口，使用时请勿关闭；重复启动会打开现有服务。需要后台模式时可显式传入 -Background，日志保存在 logs/scientific.*.log。未设置本地令牌时会在数据目录保存访问令牌，供重新打开页面使用。也可以显式设置环境变量：

```powershell
$env:SCIENTIFIC_LLM_API_KEY = '<你的密钥>'
$env:SCIENTIFIC_LLM_MODEL = '<支持 JSON 对象输出的模型名>'
$env:SCIENTIFIC_LLM_BASE_URL = '<兼容接口的 base URL，可选>'
.\.venv\Scripts\python.exe -B -m scientific_research.cli --topic '多 Agent 长期记忆的研究问题与方法' --pdf .\papers\paper1.pdf --pdf .\papers\paper2.pdf --output .\eval\scientific_runs
```

真实模式会调用模型并消耗额度。默认最高 60 次调用、并发 3 篇、10 篇全文、3 个方向、900 秒超时；关闭 SDK 隐式重试，避免调用次数超出预算。模型供应商必须支持 `response_format=json_object`。不自动补齐文献元数据，也不保证每个模型都能遵守格式。

Reader 每次读取最多 12000 字符的原文块。单次模型上下文 JSON 上限为 60000 字符；综合证据超限会返回 `context_budget_exhausted`，保留已完成证据并降级交付，不静默截断或发送无限上下文。分层证据压缩将在后续阶段补充。运行超时保留已完成阶段结果；浏览器版本通过缓存复用已完成论文，独立 CLI 默认不接入持久队列。

PDF 优先使用 `pypdf`，当前环境可退回已安装的 `PyPDF2`。扫描件没有可提取文本时明确报 OCR 错误；物理页码从 1 开始，跳过空页但不重新编号。每个 PDF 不超过 25 MiB / 500 页，提取文本不超过 20 万字符。PDF 解析不能完整还原所有表格与公式。

也可用 JSON 输入，在 `backend/examples/scientific_input.json` 查看示例：

```powershell
.\.venv\Scripts\python.exe -B -m scientific_research.cli --input .\examples\scientific_input.json --output .\eval\scientific_runs
```

该示例文本是合成资料；用真实模式分析它仍不能视为真实论文研究。自定义 JSON 可将 `brief` 的 `max_calls`、`max_papers`、`max_concurrency`、`max_directions`、`timeout_seconds` 调低，不能突破服务器上限。`pages` 填原文与物理页；`access_level=abstract` 时只提取作者主张，不分析全文实验或局限。

退出码：0 表示 completed，2 表示 degraded/failed 且已有结果文件，1 表示输入或配置错误。

## 并发、工具、上下文、MCP、Skill 的具体位置

| 能力 | 实现 | 当前应用 |
|---|---|---|
| 并发 | `workflow.py` | 每篇一个 Reader 协程；Semaphore 限制并发，同一篇分块顺序读取；按输入顺序归并，单篇失败保留其他成果 |
| 工具权限 | `agent_loop.py` / `policy.py` | Controller 从检索、元数据、全文、片段阅读中选择动作；程序校验白名单、参数、次数、重复与已读选文；没有执行代码或任意文件读取工具 |
| 上下文 | `policy.py` / `context_builder.py` | 按角色投影；Controller 获得候选摘要和最近 6 次观察，Reader 获得当前论文块；写作采用跨论文交错的最多 8 项证据包，保留来源和资料范围，审核看到全部可引用证据 |
| MCP | `mcp_server.py` | 外部 MCP 客户端可查询选定结果中的论文、证据和方向；不提供任意路径、写入或执行工具 |
| Skill | `skills.py` / `skills/*/SKILL.md` | 规划、控制、阅读、综合、选题、分析审核、提纲、写作/修订、报告审核各加载受信规范 |

MCP 是具体的外部只读访问入口。内部 Controller 已实现对程序内工具的自主选择循环；没有实现远程 MCP 工具选择，也不宣称已接入第三方论文 MCP。

项目中的 Skill 是应用侧加载的研究规范，不会安装到全局 Codex 技能目录。论文或用户提供的路径不能新增或覆盖 Skill。权限由程序执行，不依赖模型自觉遵守。

## MCP 接入

先运行一次 CLI 获得结果 JSON，再将绝对路径填入你的 MCP 客户端配置：

```json
{
  "mcpServers": {
    "scientific-evidence": {
      "command": "D:/llm7-1/第八周 deepresearch/industry_information_assistant/backend/.venv/Scripts/python.exe",
      "args": ["-B", "-m", "scientific_research.mcp_server", "--result", "<结果JSON绝对路径>"],
      "env": {
        "PYTHONPATH": "D:/llm7-1/第八周 deepresearch/industry_information_assistant/backend/app",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

这是通用 MCP 客户端配置示例，具体宿主配置格式可能不同。本次不会修改用户的全局 MCP 配置。

工具：

- `list_papers({})`：列出此快照的文献。
- `get_evidence({"evidence_id":"..."})`：返回确切引文和原文位置。
- `list_directions({})`：返回未经过在线查新的方向候选。

只支持本地单用户 stdio；由启动者选择结果文件，之后所有调用都绑定这个快照，不接受文件路径参数。不要将其包装成无鉴权的网络服务。实现初始化握手、工具发现和调用，未提供资源订阅或 HTTP transport。

协议依据：https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle 与 https://modelcontextprotocol.io/specification/2025-06-18/server/tools 。

## 后续阶段

1. 用真实论文与用户明确配置的模型开展质量评测，量化引用支持和方向可执行性。
2. 扩充学术来源与可靠全文获取，完善证据包覆盖、表格公式处理和更细粒度的失败阶段恢复。
3. 如需多人部署，迁移到原项目鉴权与 PostgreSQL/Redis，并替换单用户本地令牌。
4. OCR、表格/公式精读、自动实验执行和完整系统综述仍未实现。

本次浏览器自动化已覆盖演示、结果标签、证据抽屉、历史回看、移动端布局和导出 HTTP 响应。自动化沙箱将浏览器落盘下载标记为 canceled；报告附件已通过鉴权 HTTP 读取保存并核对，但不把浏览器自动落盘算作已验证通过。真实模型兼容性与科研结论质量尚未验证，也没有消耗真实模型额度。


## 2026-10-30：千问真实功能试跑

已通过项目模型适配器连接用户实际运行的 Ollama，确认 `qwen3.5:4b` 可推理，无需重新下载。此前受限/临时环境中的连接与空目录检查不能代表用户未安装模型。

本次完成三次真实功能试跑及故障修复，不是正式质量评测：最后一次选出两篇文献，形成八项可定位证据和四节中文正文，20 次模型调用，163.56 秒；命中了一篇已有试跑 Reader 缓存。正文仍为 `partial`，模型审核存在语义和日期误判，部分研究建议也缺少充分依据，不能作为最终科研推荐。文献来自 OpenAlex 回退检索，仅获得摘要，没有证明满足顶刊资格。

新增修正：

- Controller 每轮收到当前允许的动作/论文编号；读过的同一版本不能重复读，取得新全文后允许重新读。预算最后两步已有足够材料时只允许完成选文。
- 明确排除主题在标题/原文材料上进行保守关键词检查，冲突材料不能被自动选入；该规则不是语义相关性判断，可能偏保守。
- 写作使用短编号，程序严格映射回原始证据；本节的综合结论/方向/笔记若依赖本节之外的证据，就不放入该节上下文。完整 evidence_ids 不截断。
- 格式修订接收真实失败草稿、错误和合法编号；不再向模型只发送空草稿或笼统错误。
- 分析只接收 paper_metadata 书目信息，不接收完整论文；报告角色接收明确 as_of_date。书目信息变化会使报告检查点失效，分析上下文契约变化也会重做分析。
- 模型审核意见明确标为可能有误、待核验，阻断未解决问题时仍交付部分草稿，不靠取消审核制造成功。
- OpenAlex 返回有效 arXiv DOI 时可恢复其严格校验后的 arXiv 编号，尝试既有全文工具；本次真实全文请求遇到 RemoteProtocolError，未宣称全文下载通过。

工程回归：122 项测试通过（31.483 秒），JavaScript 语法检查通过；真实报告 HTML 四节、引用目标、390px 手机布局与无脚本错误检查通过。正式评测、消融、人工质量标注依用户要求仍留到后面。


## 科研任务书与条件核验

新任务支持 publication_policy（auto/any/prefer_journal/journal_only/verified_top_only）、year_from、year_to 与 target_papers。结构化字段优先；auto 识别明确中文年份、区间和发表语气。“优先”属于偏好，“必须核验顶刊”属于硬条件。复杂自然语言条件应在任务书预览中核对并用字段明确，不能视为通用自然语言约束求解器。

点击“查看任务书”使用鉴权 POST /api/requirements/preview，不调用模型、不创建研究任务。元数据硬条件通过只表示可以进入相关性分析；资源可行性、全文效果、创新性与期刊级别并未因此得到证实。journal/preprint 分类来自索引类型，不等于独立核验录用。

条件门同时用于 Agent 循环、保留的 legacy 检索路径及导入分析。缺少硬性年份/类型元数据或无法核验等级时不会算作满足。未得到合格材料时正常交付条件核验结果，保存候选与原因，不花模型调用生成假推荐；调整条件或补资料后应新建研究。

delivery 将元数据条件完成情况、参考数量、摘要/全文范围、资源可行性未知与运行状态分开。旧任务没有这些字段时保留原结果展示，不重写历史。

写作中新增有界章节连续性上下文：后续章节可以看到已有章节最多 240 字符的摘要用于避免重复；它标为结构参考，不能替代本节证据包。借鉴开源章节编排概念，没有复制外部代码、克隆外部仓库或新增模型/检索依赖。正式质量评测仍后置。


## 方向趋势调研（2026-11-03）

新增趋势模式、版本化刊物名单、历史/近期分层收集、定向段落检索、论点证据清单与重点阅读候选。使用步骤与准确能力边界见 docs/scientific/trend-guide.md。


## 逐篇分支报告（2026-11-04）

趋势写作改为隔离的逐篇证据解读，再组织研究分支、方法对照表与阅读路线。缺项保留为空，避免跨领域拼接；参考 docs/scientific/branch-report-ledger.md。新写作流程在重启后端后用于后续任务。
