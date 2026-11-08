# 调试环境怎么选：kind 还是 kubeadm

**结论：学源码、调试代码用 kind 就够了，不需要先用 kubeadm 搭集群。**

调试关心的是组件内部的代码怎么走，集群只负责提供一个能连的 apiserver。kind 一条命令几十秒就能建好，删了重建同样快。kubeadm 要准备虚拟机、关 swap、装容器运行时和 CNI，第一次搭往往要半天，而这些都是运维层面的事，和读代码关系不大。

## 一、kind 和 kubeadm 是什么关系

一句话：**kubeadm 是把 Kubernetes 装到机器上的官方工具；kind 把 Docker 容器当成节点，在容器里调用 kubeadm 装集群。** 两者不在同一层，kind 底层用的就是 kubeadm。

### kubeadm

Kubernetes 官方的集群引导工具，源码就在 kubernetes 仓库的 `cmd/kubeadm`。它在物理机或虚拟机上做这些事：

- `kubeadm init`：生成 CA 和各组件证书、kubeconfig；把 apiserver、controller-manager、scheduler、etcd 的静态 Pod 清单写进 `/etc/kubernetes/manifests`，由 kubelet 拉起；再装 CoreDNS 和 kube-proxy。
- `kubeadm join`：用 bootstrap token 把新节点加入集群。

它**不负责**安装容器运行时（containerd）、kubelet 和 CNI 网络插件，这些要你事先装好。

### kind（Kubernetes IN Docker）

Kubernetes SIG 维护的独立项目（[sigs.k8s.io/kind](https://kind.sigs.k8s.io/)），最初是为了在 CI 里测试 Kubernetes 本身。它的工作方式：

- 每个节点是一个 Docker 容器，镜像是 `kindest/node`，里面装好了 containerd、kubelet 和 kubeadm。
- `kind create cluster` 先启动这些容器，再**在容器里执行 `kubeadm init` / `join`**。
- 自动配好 kindnet 网络插件和 local-path 存储，并把 kubeconfig 写到本机。

因此 kind 节点里的布局和 kubeadm 装出来的机器一样。`docker exec -it <集群名>-control-plane bash` 进入节点，能看到同样的 `/etc/kubernetes/manifests` 和证书目录，`crictl ps` 能看到控制面容器，运维经验可以直接用上。

### 对比

| | kind | kubeadm |
| --- | --- | --- |
| 节点 | Docker 容器 | 物理机 / 虚拟机 |
| 前置准备 | 只要 Docker | 每台机器关 swap、改内核参数、装 containerd 和 kubelet、选 CNI |
| 建一个集群 | 一条命令，几十秒 | 熟练也要十几分钟，第一次往往半天 |
| 资源 | 笔记本 2 核 4 GB 能跑多节点 | 每个节点建议 2 核 2 GB 起 |
| 网络 | 容器网络模拟；Service 的 LoadBalancer 要另装 MetalLB 或 cloud-provider-kind | 真实网络，CNI 可任选（Calico、Cilium 等） |
| 升级与运维 | 不考虑升级，换版本就删了重建 | `kubeadm upgrade`、证书轮换、etcd 备份等全套运维 |
| 用途 | 本地开发、CI 测试、学习、调试 | 生产或接近生产的自建集群 |
| 指定版本 | `kind create cluster --image kindest/node:v1.31.x` | 安装对应版本的二进制 |

## 二、按调试对象选环境

| 调什么 | 环境 | 做法（详见[调试指南](debug-guide.md)） |
| --- | --- | --- |
| 自己写的 client-go 程序（第 1 周） | kind | 程序在 GoLand / Delve 里运行，通过 `KUBECONFIG` 连 kind |
| kube-scheduler | kind | 本地跑调试版调度器连 kind 的 apiserver；Pod 指定 `schedulerName: debug-scheduler` 交给它处理，不和 kind 自带的调度器冲突（调试指南「场景 A」） |
| kube-controller-manager | kind | 先进节点容器把 `/etc/kubernetes/manifests/kube-controller-manager.yaml` 移走，停掉自带的控制器；再在本地用 `--controllers=deployment-controller,replicaset-controller --leader-elect=false` 只跑想看的控制器（「场景 B」） |
| kube-apiserver、kubelet | `hack/local-up-cluster.sh` | 不用 kind 也不用 kubeadm。在一台 Linux 机器上把全部组件作为本地进程拉起，`DBG=1` 关闭优化，再用 Delve 或 GoLand attach 到进程（「场景 C」） |

两个前提：

- **版本对齐。** kind 节点镜像用 v1.31.x（kind v0.30.0 对应的是 `kindest/node:v1.31.12`，镜像摘要见调试指南），练习程序的 client-go 用 v0.31.14，否则单步进去的源码和集群里实际运行的对不上。
- **操作系统。** Windows 上，第 1 周用 GoLand 加 Docker Desktop 里的 kind 就够了；后面用 local-up-cluster 调 apiserver 和 kubelet 需要 Linux（WSL2 或 Linux 虚拟机）。

## 三、什么时候才值得用 kubeadm

- **学 kubeadm 本身的源码**（`cmd/kubeadm`）：init / join 流程、证书怎么生成。这部分在 kind 里也能跟：节点里跑的就是 kubeadm，`kind create cluster --retain -v 5` 能看到它执行的 kubeadm 命令和配置。
- **研究多节点真实网络下的行为**：kube-proxy 跨机器的 iptables / ipvs 规则、CNI、节点宕机后的驱逐。kind 也能建多节点，但网络是容器模拟的。
- **练接近生产的远程调试**：用调试版二进制替换节点上的组件，`dlv exec --headless --listen :2345 --api-version 2 <二进制> -- <参数>` 启动，GoLand 用 **Go Remote** 配置连上去。

这些放在第 3、4 周之后。建议先用 kind 跟通调度器和控制器两条链，到[学习路线](learning-path.md)阶段 4「从运维现象反查代码」需要真实网络时，再按需搭一个 kubeadm 集群。

如果你做运维时用 kubeadm 装过集群，可以这样理解 kind：它把装集群的那几台机器换成了容器，流程基本没变。
