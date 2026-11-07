# 用 Delve 单步调试 Kubernetes 1.31 调用链

图谱告诉你「调用链是什么」，调试器让你看到「这条链在真实进程里怎么走」。本指南的做法是：

1. 用 `ua-query.py chain` 在图谱里找到要跟的调用链；
2. 用 `ua-query.py dlv` 把这条链上的每个函数生成成 Delve 断点；
3. 编译关闭优化的组件，在 Delve 里加载断点运行，触发一次真实请求，按 `continue` / `next` / `step` 一步步看。

所有命令都在 kubernetes 源码根目录执行，并假设你已经按 [README](../README.md) 把 `.ua/` 复制进去。

## 1. 准备环境

| 工具 | 说明 |
| --- | --- |
| Go | 源码的 `.go-version` 指定 Go 1.24.9。`make` 默认会自动下载这个版本的工具链；离线时可以加 `FORCE_HOST_GO=1` 用本机已装的 Go |
| Delve | `go install github.com/go-delve/delve/cmd/dlv@latest` |
| kind + kubectl | 场景 A、B 用 kind 起一个本地集群。kind v0.30.0 对应的 1.31 镜像是 `kindest/node:v1.31.12@sha256:0f5cc49c5e73c0c2bb6e2df56e7df189240d83cf94edfa30946482eb08ec57d2`（补丁版本和源码的 v1.31.14 略有差别，调试调度器、控制器不受影响） |
| Docker | kind 依赖 Docker |

场景 A、B 在 Linux 和 macOS 上都能跑；场景 D（apiserver、kubelet）只能在 Linux 上用 root 运行。

## 2. 编译调试版组件

```bash
make WHAT="cmd/kube-scheduler cmd/kube-controller-manager" DBG=1
```

`DBG=1` 会以 `-gcflags all=-N -l` 编译：关闭优化和内联，保留调试信息，否则断点会打不上或变量显示 `optimized away`。产物在 `_output/bin/`（指向 `_output/local/bin/<os>/<arch>/`）。如果 `_output/bin/` 是空的（构建最后一步用 rsync 复制，系统没装 rsync 时会跳过），二进制在 `_output/local/go/bin/`。

确认是调试版：`go version -m _output/bin/kube-scheduler | grep gcflags` 应输出 `-gcflags=" all=-N -l"`。

## 3. 用图谱生成断点

```bash
python3 .ua/ua-query.py chain Scheduler.ScheduleOne 2        # 先看调用树，决定跟多深
python3 .ua/ua-query.py dlv Scheduler.ScheduleOne 1 > /tmp/sched.dlv
```

`dlv <函数> [深度] [上限]` 从该函数出发沿 `calls` 边展开，每个函数生成一行 `break 名字 文件:行号`，上一行注释是图谱里的中文摘要，默认最多 50 个断点。生成的文件形如：

```text
# 调度主循环单次迭代：从队列取 Pod、选 profile、同步执行 schedulingCycle……
break bp_Scheduler_ScheduleOne pkg/scheduler/schedule_one.go:65
# 调度周期：SchedulePod 选节点；失败时跑 PostFilter 抢占；成功则 assume 到缓存……
break bp_Scheduler_schedulingCycle pkg/scheduler/schedule_one.go:138
```

断点打在函数声明行，命中时停在函数入口（已用调试版 kube-scheduler 核对过：`ScheduleOne`、`schedulingCycle`、`bind`、`Reflector.ListAndWatch`、`sharedIndexInformer.HandleDeltas` 的入口指令正好对应生成的行号）。staging 包（client-go、apiserver）的路径从 `k8s.io/...` 写起，Delve 按路径后缀匹配，所以无论二进制里记录的是 `staging/src/k8s.io/...` 还是 `vendor/k8s.io/...` 都能命中。

## 4. 场景 A：跟一个 Pod 走完调度周期

目标：看 `ScheduleOne → schedulingCycle → findNodesThatFitPod → prioritizeNodes → assume → bindingCycle → bind`。

为了不和 kind 自带的调度器抢 Pod，本地调度器用一个独立的 `schedulerName`，只处理声明了它的 Pod。

```bash
kind create cluster --name k8s-debug \
  --image kindest/node:v1.31.12@sha256:0f5cc49c5e73c0c2bb6e2df56e7df189240d83cf94edfa30946482eb08ec57d2
kind get kubeconfig --name k8s-debug > /tmp/kind.kubeconfig

cat > /tmp/sched.yaml <<'EOF'
apiVersion: kubescheduler.config.k8s.io/v1
kind: KubeSchedulerConfiguration
clientConnection:
  kubeconfig: /tmp/kind.kubeconfig
leaderElection:
  leaderElect: false
profiles:
  - schedulerName: debug-scheduler
EOF

python3 .ua/ua-query.py dlv Scheduler.ScheduleOne 1 > /tmp/sched.dlv
python3 .ua/ua-query.py dlv Scheduler.bind 0 >> /tmp/sched.dlv

dlv exec _output/bin/kube-scheduler --init /tmp/sched.dlv -- \
  --config /tmp/sched.yaml \
  --authentication-kubeconfig /tmp/kind.kubeconfig \
  --authorization-kubeconfig /tmp/kind.kubeconfig
```

进入 Delve 后输入 `continue` 让调度器跑起来。在另一个终端创建一个指定该调度器的 Pod：

```bash
kubectl --kubeconfig /tmp/kind.kubeconfig apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: debug-pod
spec:
  schedulerName: debug-scheduler
  containers:
    - name: nginx
      image: nginx
EOF
```

Delve 会停在 `ScheduleOne`。之后每按一次 `continue` 就跳到链上的下一个函数；想逐行看就用 `next`，进入被调函数用 `step`，跑完当前函数用 `stepout`。

`ScheduleOne` 入口处 Pod 还没从队列取出，`next` 几行越过 `NextPod` 之后才能看到它；停在 `schedulingCycle` 时它已经是参数：

```text
(dlv) print podInfo.Pod.Name          # 在 schedulingCycle 里
(dlv) print assumed.Name, targetNode  # 在 bind 里：要绑定的 Pod 和选中的节点
(dlv) args
(dlv) locals
(dlv) bt
```

注意 `bindingCycle` 在新的 goroutine 里执行，停下后可以用 `goroutine` 查看当前所在 goroutine。

**顺带看 informer（client-go）**：在启动前追加 informer 相关断点，调度器一启动就会停在全量 LIST 和增量分发上。

```bash
python3 .ua/ua-query.py dlv Reflector.ListAndWatch 1 >> /tmp/sched.dlv
python3 .ua/ua-query.py dlv sharedIndexInformer.HandleDeltas 1 >> /tmp/sched.dlv
```

## 5. 场景 B：Deployment → ReplicaSet → Pod 的调谐

目标：看 `syncDeployment → rolloutRolling → reconcileNewReplicaSet`，再看 `syncReplicaSet → manageReplicas → slowStartBatch`。

控制器不能和 kind 集群里的 kube-controller-manager 同时工作，所以先把集群里的停掉（kubelet 会在静态 Pod 清单消失后自动停止它）：

```bash
docker exec k8s-debug-control-plane \
  mv /etc/kubernetes/manifests/kube-controller-manager.yaml /root/

python3 .ua/ua-query.py dlv DeploymentController.syncDeployment 1 > /tmp/kcm.dlv
python3 .ua/ua-query.py dlv ReplicaSetController.manageReplicas 0 >> /tmp/kcm.dlv

dlv exec _output/bin/kube-controller-manager --init /tmp/kcm.dlv -- \
  --kubeconfig /tmp/kind.kubeconfig \
  --authentication-kubeconfig /tmp/kind.kubeconfig \
  --authorization-kubeconfig /tmp/kind.kubeconfig \
  --leader-elect=false \
  --controllers=deployment-controller,replicaset-controller
```

`continue` 后在另一个终端执行：

```bash
kubectl --kubeconfig /tmp/kind.kubeconfig create deployment web --image=nginx --replicas=2
```

调试完恢复集群自带的控制器：

```bash
docker exec k8s-debug-control-plane \
  mv /root/kube-controller-manager.yaml /etc/kubernetes/manifests/
```

## 6. 场景 C：用 local-up-cluster 调试 apiserver 和 kubelet

apiserver、kubelet 不方便单独跑，最省事的是用仓库自带脚本在本机起一个单节点集群（需要 Linux、root、containerd，以及 `hack/install-etcd.sh` 装好的 etcd），然后把 Delve 附加到运行中的进程：

```bash
DBG=1 hack/local-up-cluster.sh        # 脚本内部调用 make，会继承 DBG=1

# 另开终端
python3 .ua/ua-query.py dlv Store.create 1 > /tmp/apiserver.dlv
python3 .ua/ua-query.py dlv Cacher.Watch 0 >> /tmp/apiserver.dlv
sudo dlv attach "$(pgrep -x kube-apiserver)" --init /tmp/apiserver.dlv

python3 .ua/ua-query.py dlv Kubelet.syncLoopIteration 1 > /tmp/kubelet.dlv
python3 .ua/ua-query.py dlv kubeGenericRuntimeManager.SyncPod 1 >> /tmp/kubelet.dlv
sudo dlv attach "$(pgrep -x kubelet)" --init /tmp/kubelet.dlv
```

附加后进程处于暂停状态，先 `continue`，再用 `kubectl` 创建资源触发。apiserver 停在断点期间所有请求都会挂起，调完记得 `continue` 或 `detach`。

## 7. 在编辑器里调试

VS Code（Go 扩展）或 GoLand 也可以用同样的调试版二进制。编辑器不读取 `.dlv` 文件，用 `ua-query.py show` 或 `chain` 输出的 `文件:行号` 在编辑器里点断点即可。VS Code 的 `launch.json` 示例：

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "kube-scheduler (debug)",
      "type": "go",
      "request": "launch",
      "mode": "exec",
      "program": "${workspaceFolder}/_output/bin/kube-scheduler",
      "args": [
        "--config", "/tmp/sched.yaml",
        "--authentication-kubeconfig", "/tmp/kind.kubeconfig",
        "--authorization-kubeconfig", "/tmp/kind.kubeconfig"
      ]
    }
  ]
}
```

## 8. Delve 速查

| 命令 | 作用 |
| --- | --- |
| `continue` / `c` | 运行到下一个断点 |
| `next` / `n` | 执行下一行，不进入函数 |
| `step` / `s` | 进入当前行调用的函数 |
| `stepout` / `so` | 跑完当前函数并返回调用者 |
| `breakpoints` / `bp` | 列出断点 |
| `clear <名字>` / `clearall` | 删除断点 |
| `print <表达式>` / `p` | 打印变量 |
| `args` / `locals` | 当前函数的参数 / 局部变量 |
| `stack` / `bt` | 调用栈 |
| `goroutines` / `goroutine <id>` | 列出 / 切换 goroutine |
| `restart` / `exit` | 重启 / 退出 |

## 9. 常见问题

- **断点提示找不到文件或行号**：确认二进制是用 `DBG=1` 编译的；确认函数确实在这个组件里（例如 kubelet 的函数不会出现在调度器进程中）。
- **变量显示 `optimized away`**：没有用 `DBG=1` 编译。
- **断点太多停个不停**：降低 `dlv` 子命令的深度，或在 Delve 里 `clear` 不需要的断点，或给以 Pod 为参数的函数加条件，只在你的 Pod 上停：`condition bp_Scheduler_schedulingCycle podInfo.Pod.Name == "debug-pod"`。
- **调度器/控制器停住后集群里出现超时日志**：断点暂停的是整个进程，这是预期现象；场景 A、B 都关闭了选主，不会因为续约失败而退出。
