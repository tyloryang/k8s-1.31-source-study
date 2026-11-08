# 运维转 Go 开发：用知识图谱学 Kubernetes 1.31 源码

这份路线写给有 Kubernetes 运维经验、刚开始写 Go 的人。核心方法只有一句话：**从你熟悉的运维现象出发，用图谱找到代码，读最关键的几十行，再用调试器看它真实地跑一遍。**

你已经知道每个对象是干什么的、出问题时长什么样，缺的只是现象背后的代码。所以不要从 `main()` 开始顺着读，也不要想着先把 Go 学完再来看 k8s。

## 三件工具

| 工具 | 用来做什么 | 说明 |
| --- | --- | --- |
| 网页图谱 | 看全局、点节点看摘要和调用关系、按导览顺序学 | [README · 在网页里看调用关系](../README.md#2-在网页里看调用关系) |
| `ua-query.py` | 命令行快速查函数、展开调用树、查接口实现 | [README · 在命令行查调用链](../README.md#3-在命令行查调用链) |
| Delve 调试器 | 在真实运行的组件里一步步走调用链 | [调试指南](debug-guide.md) |

想先看一遍第一周怎么准备、GoLand 怎么单步调试，可以看 [视频](video/)（7 分钟，中文配音）。

下文的命令都在 kubernetes 源码根目录执行，并已按 README 把 `.ua/` 复制进去。

## 阶段 0：把学习模式打开

- 网页右上角的角色选择选 **「学习」**（完整仪表盘与导览学习），页面会按适合学习的详细程度展示。
- 点开节点后，除了中文摘要，有 753 个节点带 **Go 语言说明**，专门解释这段代码用到的 Go 写法。命令行里 `ua-query.py show` 也会显示它。初学阶段这部分比摘要更有用。
- 学习面板里的 **14 步导览** 就是推荐阅读顺序，不知道从哪开始就按它走：`python3 .ua/ua-query.py tour`。

**达标**：能在网页上找到 `Scheduler.ScheduleOne`，说出它调用了哪几个函数。

## 阶段 1：拿 k8s 代码学 Go 惯用法

Go 语法可以用官方的 [A Tour of Go](https://go.dev/tour/) 一两周过一遍。真正难的是下面这些惯用法，而 k8s 里每个都有现成的范例：

| Go 知识点 | k8s 里的范例 | 查看命令 |
| --- | --- | --- |
| struct、方法、interface；实现接口不需要声明 | CPU 管理器的 `Policy` 接口，`nonePolicy` 和 `staticPolicy` 两个实现 | `ua-query.py impl Policy` |
| goroutine + channel + `select` | kubelet 主循环的 `select` 有 8 个分支：Pod 配置变更、PLEG 事件、定时同步、三种探针结果、容器管理器更新、定期清理 | `ua-query.py show Kubelet.syncLoopIteration` |
| `context` 取消 | `ScheduleOne` 用 `context.WithCancel` 给调度周期和绑定周期各建一个 ctx | `ua-query.py show Scheduler.ScheduleOne` |
| 泛型 | workqueue 的 `Typed[T comparable]` | `ua-query.py pkg staging/src/k8s.io/client-go/util/workqueue` |
| 哨兵错误 `errors.New` | `ErrImagePullBackOff`、`ErrCrashLoopBackOff` 都是包级错误变量 | 打开 `pkg/kubelet/images/types.go`、`pkg/kubelet/container/sync_result.go` |
| `sync.Cond`、并发安全的数据结构 | workqueue 用 `dirty` / `processing` 两个集合保证同一个 key 不会被并发处理 | `ua-query.py show staging/src/k8s.io/client-go/util/workqueue/queue.go` |

**练习**：每看懂一个点，就在本地写一个 20 行左右的小程序模仿它。例如照着 `syncLoopIteration` 写一个同时监听两个 channel 和一个 `time.Ticker` 的循环，用 `context` 控制退出。

**达标**：不看代码，能解释「为什么 kubelet 用 `select` 而不是依次读每个 channel」。

## 阶段 2：写第一个 client-go 程序

client-go 是所有组件共用的底座，也是转开发后最先用到的库。

1. 按导览第 7、8 步，在网页上点开 `reflector.go`、`delta_fifo.go`、`shared_informer.go`、`queue.go`，看摘要和调用关系。
2. 用 `ua-query.py chain Reflector.ListAndWatch 2` 展开 informer 的数据流：`ListAndWatch → DeltaFIFO → HandleDeltas → 你的 EventHandler`。
3. 写一个程序：用 SharedInformer 监听 Pod，把增删改事件的 key 放进 workqueue，再起一个 worker 从队列取 key、从 Lister 读对象并打印。这就是所有控制器的骨架。
4. 按[调试指南](debug-guide.md#4-场景-a跟一个-pod-走完调度周期)里「顺带看 informer」的做法，在 `Reflector.ListAndWatch`、`sharedIndexInformer.HandleDeltas` 上停住，对照自己写的代码看底层发生了什么。

**达标**：程序能在 kind 集群上跑起来；能讲清楚 informer 本地缓存和直接请求 apiserver 有什么区别。

## 阶段 3：跟一个请求走完一生

用 `kubectl create deployment` 这一条请求，把所有组件串起来。

1. 读[学习文档](k8s-1.31-architecture-guide.md)的「端到端」一节和那张 8 跳的图，先知道请求会经过哪些组件。
2. 按导览第 2～6 步看 apiserver：过滤器链、`createHandler`、`Store.create`、Cacher、etcd3。
3. 按导览第 9 步看控制器：`syncDeployment → rolloutRolling`，以及 ReplicaSet 控制器用 `slowStartBatch` 按 1、2、4、8… 分批创建 Pod。
4. 按导览第 10、11 步看调度器，第 12、13 步看 kubelet。
5. 用调试指南的场景 A（调度器）和场景 B（Deployment / ReplicaSet）各完整跟一遍。

**达标**：能在白板上画出这 8 跳，每一跳说出入口函数名。

## 阶段 4：从运维现象反查代码

这是最适合运维背景的读法。每次挑一个你在生产里见过的现象：

| 你见过的现象 | 代码入口 | 建议的查法 |
| --- | --- | --- |
| Pod 一直 Pending，事件里写 `0/3 nodes are available` | `FitError.Error`（`pkg/scheduler/framework/types.go:407`），往上是 `findNodesThatFitPod` | `chain Scheduler.schedulingCycle 2` |
| ImagePullBackOff | `imageManager.EnsureImageExists`（`pkg/kubelet/images/image_manager.go:102`） | `show imageManager.EnsureImageExists` 看调用者 |
| CrashLoopBackOff | `kubeGenericRuntimeManager.doBackOff`（`kuberuntime_manager.go:1423`） | 在这里打断点，看退避时间怎么算出来 |
| 滚动更新卡住、`ProgressDeadlineExceeded` | `DeploymentController.syncRolloutStatus`（`pkg/controller/deployment/progress.go:36`） | 调试指南场景 B |
| Service 访问不通 | `pkg/proxy/iptables/proxier.go:Proxier.syncProxyRules` 生成的 `KUBE-SVC-*` / `KUBE-SEP-*` 链 | 对照 `iptables-save -t nat` 读 `show pkg/proxy/iptables/proxier.go:Proxier.syncProxyRules` |
| 节点 NotReady 后 Pod 被驱逐 | `Controller.monitorNodeHealth`（`pkg/controller/nodelifecycle/node_lifecycle_controller.go:668`） | `pkg pkg/controller/nodelifecycle` 先看包总结 |

每个现象都走同一个套路：

1. 网页里搜入口函数，看摘要、Go 语言说明和连接列表。
2. `ua-query.py chain <入口> 2` 展开两层调用树。
3. `ua-query.py dlv <入口> 1 > /tmp/x.dlv` 生成断点，在 kind 集群里复现这个现象，看代码怎么一步步走到那里。
4. 用自己的话写下「这个现象是哪段代码、在什么条件下产生的」。

**达标**：至少走完表里 3 个现象，每个都能在源码里指出产生它的那一行。

## 阶段 5：写一个能跑的扩展

能读懂之后，用最小的改动验证自己真懂了：

- **调度器插件**：参考最简单的内置插件 `NodeName.Filter`（`pkg/scheduler/framework/plugins/nodename/node_name.go:56`），写一个 Filter 插件，拒绝带某个标签的节点。在调试指南场景 A 的环境里跑起来，用 `kubectl describe pod` 看到你的插件给出的拒绝原因。
- **控制器**：照着 Deployment 控制器的结构（informer → workqueue → worker → sync），写一个监听 ConfigMap 变化、自动滚动重启引用它的 Deployment 的小控制器。这是运维里很常见的真实需求。
- **读测试**：看对应包里的 `*_test.go`。测试是最好的用法文档，也是学 Go 单元测试和表驱动测试写法最快的途径。

**达标**：你的插件或控制器在 kind 集群上按预期工作，并配有单元测试。

## 学习方法与常见坑

- **每次只带一个问题去读。** 例如「为什么 Deployment 扩容时 Pod 是一批批出来的」，答案在 `slowStartBatch`。带着问题读，比漫无目的地浏览收获大得多。
- **别一开始就想读完 kubelet。** 图里 kubelet 有 321 个文件，先只跟一条调用链，其余点到为止。
- **`staging/src/k8s.io/` 不是第三方代码。** 它就是 client-go、apiserver 等库的源头，`vendor/` 里的是它的副本。
- **接口调用要查实现。** 静态阅读看不到接口背后是哪个实现，用 `ua-query.py impl <接口名>` 查，或者在调试器里停住看真实类型。
- **图谱摘要是 AI 读代码写的。** 核心函数已人工抽查过，但遇到关键逻辑还是以源码为准，正好借机锻炼读码能力。
- **把读到的东西写下来。** 每个阶段写一篇自己的笔记或画一张图，比多读十个文件更能巩固。

## 进度清单

- [ ] 阶段 0：网页、命令行、导览都能用
- [ ] 阶段 1：6 个 Go 惯用法各写了一个模仿小程序
- [ ] 阶段 2：client-go Pod 事件程序在 kind 上跑通
- [ ] 阶段 3：用调试器跟完调度器和 Deployment 两条链，能画出 8 跳
- [ ] 阶段 4：至少 3 个运维现象定位到源码
- [ ] 阶段 5：写出一个调度插件或控制器，并带单元测试
