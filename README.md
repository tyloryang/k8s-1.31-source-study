# k8s-1.31-source-study

Kubernetes v1.31 核心源码的架构学习资料：一份用 [Understand-Anything](https://github.com/Egonex-AI/Understand-Anything) 的 `/understand --full` 流程生成的中文知识图谱，加上一篇按调用链讲解各组件的学习文档。

- 源码版本：[kubernetes `release-1.31`](https://github.com/kubernetes/kubernetes/tree/release-1.31)，commit `fa33e07f`（v1.31.14）
- 覆盖范围：kube-apiserver、client-go、kube-scheduler、kube-controller-manager、kubelet、kube-proxy 的入口与核心包

## 仓库内容

| 路径 | 内容 |
| --- | --- |
| [`docs/learning-path.md`](docs/learning-path.md) | **从这里开始**：运维转 Go 开发的学习路线，6 个阶段，每阶段有练习和达标标准 |
| [`docs/k8s-1.31-architecture-guide.md`](docs/k8s-1.31-architecture-guide.md) | 学习文档：整体架构、各组件启动链路与主循环、`kubectl create deployment` 端到端 8 跳、学习路线 |
| [`docs/video/`](docs/video/) | 视频：第一周怎么准备 + 用 GoLand 一步一步 debug（中文配音，7 分钟），附重新生成配音的脚本 |
| [`docs/debug-guide.md`](docs/debug-guide.md) | 单步调试指南：用图谱生成 Delve 断点，在真实进程里一步步跟调度、控制器、apiserver、kubelet 的调用链 |
| `.ua/knowledge-graph.json` | 知识图谱（Understand-Anything 格式），10509 个节点、21681 条边 |
| `.ua/ua-query.py` | 命令行查询工具，只依赖 Python 3 标准库 |
| `.ua/meta.json`、`.ua/config.json`、`.ua/intermediate/scan-result.json` | 插件元数据：对应 commit、输出语言（zh）、文件清单 |

## 快速开始

### 1. 准备（只需一次）

把图谱放进 kubernetes 源码目录。网页里看代码、调试器下断点，都要读取图谱旁边的源码。

```bash
git clone -b release-1.31 --depth 1 https://github.com/kubernetes/kubernetes.git
git clone https://github.com/tyloryang/k8s-1.31-source-study.git
cp -r k8s-1.31-source-study/.ua kubernetes/      # Windows PowerShell: Copy-Item -Recurse k8s-1.31-source-study\.ua kubernetes\
cd kubernetes
```

以后更新：`git -C ../k8s-1.31-source-study pull && cp -r ../k8s-1.31-source-study/.ua .`

### 2. 在网页里看调用关系

只需要 Node.js 18 或更高版本，不需要 Claude Code，也不需要 API key。在 kubernetes 目录执行：

```bash
npx https://github.com/Egonex-AI/Understand-Anything/releases/download/v2.9.8/understand-anything-viewer.tgz .
```

终端会打印 `Dashboard URL: http://127.0.0.1:5173/?token=...` 并自动打开浏览器；没自动打开就复制整行地址，**一定要带上 `?token=`**。版本固定在 v2.9.8，与生成图谱的插件版本一致。端口被占用会自动换下一个，加 `--port 8080` 可指定端口，`--no-open` 不自动开浏览器。数据只在本机读取，按 Ctrl+C 停止。

页面上：

- **看函数调用了谁、被谁调用**：搜索 `ScheduleOne`、`syncLoopIteration` 等，点击节点，右侧面板显示中文摘要、源码和连接列表。
- **只看调用边**：筛选面板里边类型只保留 behavioral（即 calls）。
- **追两点之间的调用路径**：用路径查找，选起点和终点。
- **按顺序学习**：学习面板里是 14 步中文导览；颜色图例对应 9 个架构层。

图里有 1 万多个节点，建议先从导览进入，或按层、按类型筛选后再看。

已安装 Understand-Anything 插件的话（Claude Code：`/plugin marketplace add Egonex-AI/Understand-Anything`），在 kubernetes 目录运行 `/understand-dashboard` 效果相同，`/understand-chat` 可以直接对图谱提问。

### 3. 在命令行查调用链

```bash
python3 .ua/ua-query.py tour                          # 14 步学习导览，按顺序列出要读的文件
python3 .ua/ua-query.py show Scheduler.ScheduleOne    # 中文摘要 + 调用了谁 / 被谁调用
python3 .ua/ua-query.py chain Kubelet.syncLoopIteration 2   # 展开调用树
python3 .ua/ua-query.py impl Policy                   # 某接口有哪些实现（含包内私有 struct）
python3 .ua/ua-query.py pkg pkg/kubelet/pleg          # 包的中文总结及包内文件
python3 .ua/ua-query.py find Reflector                # 按名称搜索节点
```

查询工具只读 `.ua/knowledge-graph.json`，不需要源码也能运行；输出里的 `文件:行号` 可直接跳转阅读。

### 4. 用调试器一步一步跟

用图谱把调用链变成 Delve 断点，在真实运行的组件里单步执行：

```bash
make WHAT=cmd/kube-scheduler DBG=1                                   # 关闭优化编译
python3 .ua/ua-query.py dlv Scheduler.ScheduleOne 1 > /tmp/sched.dlv # 调用树上每个函数一个断点
dlv exec _output/bin/kube-scheduler --init /tmp/sched.dlv -- --config /tmp/sched.yaml
```

完整步骤见 [docs/debug-guide.md](docs/debug-guide.md)：kind 集群准备、调度器跟一个 Pod 的调度周期、Deployment → ReplicaSet 控制器调谐、client-go informer、用 local-up-cluster 调 apiserver 与 kubelet、VS Code 配置和 Delve 速查。

## 图谱概况

| 项目 | 数量 |
| --- | --- |
| 节点 | 1035 文件、326 包、7894 函数、1254 类型；9340 个带中文摘要 |
| 边 | 6435 调用、1562 包导入、431 接口实现、536 运行时依赖、212 概念关联 |
| 架构层 | 组件入口、API Server 核心、请求处理与准入、注册表与存储、client-go、调度器、控制器、Kubelet、kube-proxy |
| 校验 | 插件内置校验器：0 问题、0 孤立节点 |

节点 id 规则：`file:<路径>`、`function:<路径>:<类型.方法>`、`class:<路径>:<类型>`、`module:<包目录>`。

## 生成方式

1. **结构抽取**：用 Go 标准库 `go/ast` 解析 1035 个 Go 文件，得到文件、函数、类型、包导入和同包内直接调用。插件原本的 tree-sitter 抽取脚本在生成环境里装不上依赖，所以用它替代，输出格式与插件一致。
2. **语义分析**：按 82 批派发 file-analyzer 子代理，每个代理读完源码后写中文摘要、标签，并补充跨文件调用、接口分发等语义边。每批输出都对照输入核验节点完整性；有一批因只读了部分源码被打回重做。
3. **接口实现**：用 `go/types` 对 326 个包做类型检查，精确计算 struct 与 interface 的实现关系（427 条），包括包内私有 struct。
4. **合并与校验**：使用插件自带的 `merge-batch-graphs.py` 合并、规范化 id、丢弃悬空边，再用插件内置校验器检查。
5. **包级总结**：根据每个包内文件的中文摘要，为 326 个包写中文总结。

## 已知局限

- 1169 个短小的私有函数没有经过语义分析，摘要沿用源码里的英文注释。
- 53 条指向解析范围外包（如 `apiserver/pkg/warning`、`util/flowcontrol`）的边在合并时被丢弃。
- 没有生成插件做增量更新所需的 fingerprints，源码变化后需要整体重跑 `/understand`。
- 摘要由 AI 读码生成，核心函数已人工对照源码抽查；阅读时请以源码为准。

## 许可

Kubernetes 源码以 Apache License 2.0 发布。本仓库只包含对其源码的分析结果与说明文字，不包含源码本身；引用的文件路径、函数名与行号均指向上游仓库。
