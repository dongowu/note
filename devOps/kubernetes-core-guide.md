# Kubernetes核心技术指南

## 目录

1. [Kubernetes概述](#kubernetes概述)
2. [Kubernetes架构设计](#kubernetes架构设计)
3. [Kubernetes核心原理](#kubernetes核心原理)
4. [Kubernetes核心组件](#kubernetes核心组件)
5. [Kubernetes核心能力](#kubernetes核心能力)
6. [Kubernetes使用场景](#kubernetes使用场景)
7. [Kubernetes优化方案](#kubernetes优化方案)
8. [Kubernetes常见问题](#kubernetes常见问题)
9. [Kubernetes最佳实践](#kubernetes最佳实践)
10. [Kubernetes生产环境部署](#kubernetes生产环境部署)

---

## 1. Kubernetes概述

### 1.1 什么是Kubernetes

Kubernetes（K8s）是一个开源的容器编排平台，用于自动化部署、扩展和管理容器化应用程序。它提供了一个可移植、可扩展的平台，用于管理容器化的工作负载和服务。

### 1.2 Kubernetes核心概念

#### 集群（Cluster）
```yaml
# 集群基本信息
apiVersion: v1
kind: ConfigMap
metadata:
  name: cluster-info
  namespace: kube-public
data:
  cluster-name: "production-cluster"
  cluster-region: "us-west-2"
  cluster-version: "v1.28.0"
```

#### 节点（Node）
```yaml
# 节点资源配置
apiVersion: v1
kind: Node
metadata:
  name: worker-node-1
  labels:
    kubernetes.io/hostname: worker-node-1
    node-role.kubernetes.io/worker: ""
    zone: us-west-2a
spec:
  capacity:
    cpu: "4"
    memory: "8Gi"
    storage: "100Gi"
  allocatable:
    cpu: "3.8"
    memory: "7.5Gi"
    storage: "95Gi"
```

#### Pod
```yaml
# Pod基本配置
apiVersion: v1
kind: Pod
metadata:
  name: web-app
  labels:
    app: web
    version: v1
spec:
  containers:
  - name: web-container
    image: nginx:1.21
    ports:
    - containerPort: 80
    resources:
      requests:
        memory: "64Mi"
        cpu: "250m"
      limits:
        memory: "128Mi"
        cpu: "500m"
    livenessProbe:
      httpGet:
        path: /health
        port: 80
      initialDelaySeconds: 30
      periodSeconds: 10
    readinessProbe:
      httpGet:
        path: /ready
        port: 80
      initialDelaySeconds: 5
      periodSeconds: 5
```

### 1.3 Kubernetes优势

1. **自动化部署和扩展**：自动处理应用的部署、更新和扩展
2. **服务发现和负载均衡**：内置服务发现和负载均衡机制
3. **存储编排**：自动挂载存储系统
4. **自我修复**：自动重启失败的容器，替换和重新调度节点
5. **密钥和配置管理**：安全地管理敏感信息
6. **批处理执行**：支持批处理和CI工作负载

---

## 2. Kubernetes架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                       │
├─────────────────────────────────────────────────────────────┤
│                     Control Plane                          │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐           │
│  │ API Server  │ │    etcd     │ │ Scheduler   │           │
│  └─────────────┘ └─────────────┘ └─────────────┘           │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐           │
│  │Controller   │ │Cloud        │ │   DNS       │           │
│  │Manager      │ │Controller   │ │             │           │
│  └─────────────┘ └─────────────┘ └─────────────┘           │
├─────────────────────────────────────────────────────────────┤
│                      Worker Nodes                          │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Node 1                                              │   │
│  │ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐     │   │
│  │ │ kubelet │ │kube-proxy│ │Container│ │  Pods   │     │   │
│  │ │         │ │         │ │Runtime  │ │         │     │   │
│  │ └─────────┘ └─────────┘ └─────────┘ └─────────┘     │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Node 2                                              │   │
│  │ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐     │   │
│  │ │ kubelet │ │kube-proxy│ │Container│ │  Pods   │     │   │
│  │ │         │ │         │ │Runtime  │ │         │     │   │
│  │ └─────────┘ └─────────┘ └─────────┘ └─────────┘     │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 控制平面（Control Plane）

#### API Server
```yaml
# API Server配置
apiVersion: v1
kind: Pod
metadata:
  name: kube-apiserver
  namespace: kube-system
spec:
  containers:
  - name: kube-apiserver
    image: k8s.gcr.io/kube-apiserver:v1.28.0
    command:
    - kube-apiserver
    - --advertise-address=10.0.0.1
    - --allow-privileged=true
    - --authorization-mode=Node,RBAC
    - --client-ca-file=/etc/kubernetes/pki/ca.crt
    - --enable-admission-plugins=NodeRestriction
    - --enable-bootstrap-token-auth=true
    - --etcd-servers=https://127.0.0.1:2379
    - --kubelet-client-certificate=/etc/kubernetes/pki/apiserver-kubelet-client.crt
    - --kubelet-client-key=/etc/kubernetes/pki/apiserver-kubelet-client.key
    - --runtime-config=api/all=true
    - --service-account-issuer=https://kubernetes.default.svc.cluster.local
    - --service-account-key-file=/etc/kubernetes/pki/sa.pub
    - --service-account-signing-key-file=/etc/kubernetes/pki/sa.key
    - --service-cluster-ip-range=10.96.0.0/12
    - --tls-cert-file=/etc/kubernetes/pki/apiserver.crt
    - --tls-private-key-file=/etc/kubernetes/pki/apiserver.key
    ports:
    - containerPort: 6443
      name: https
    volumeMounts:
    - mountPath: /etc/kubernetes/pki
      name: k8s-certs
      readOnly: true
    - mountPath: /etc/ssl/certs
      name: ca-certs
      readOnly: true
```

#### etcd集群
```yaml
# etcd配置
apiVersion: v1
kind: Pod
metadata:
  name: etcd
  namespace: kube-system
spec:
  containers:
  - name: etcd
    image: k8s.gcr.io/etcd:3.5.9-0
    command:
    - etcd
    - --advertise-client-urls=https://10.0.0.1:2379
    - --cert-file=/etc/kubernetes/pki/etcd/server.crt
    - --client-cert-auth=true
    - --data-dir=/var/lib/etcd
    - --initial-advertise-peer-urls=https://10.0.0.1:2380
    - --initial-cluster=master=https://10.0.0.1:2380
    - --key-file=/etc/kubernetes/pki/etcd/server.key
    - --listen-client-urls=https://127.0.0.1:2379,https://10.0.0.1:2379
    - --listen-metrics-urls=http://127.0.0.1:2381
    - --listen-peer-urls=https://10.0.0.1:2380
    - --name=master
    - --peer-cert-file=/etc/kubernetes/pki/etcd/peer.crt
    - --peer-client-cert-auth=true
    - --peer-key-file=/etc/kubernetes/pki/etcd/peer.key
    - --peer-trusted-ca-file=/etc/kubernetes/pki/etcd/ca.crt
    - --snapshot-count=10000
    - --trusted-ca-file=/etc/kubernetes/pki/etcd/ca.crt
    ports:
    - containerPort: 2379
      name: client
    - containerPort: 2380
      name: peer
    volumeMounts:
    - mountPath: /var/lib/etcd
      name: etcd-data
    - mountPath: /etc/kubernetes/pki/etcd
      name: etcd-certs
```

### 2.3 工作节点（Worker Node）

#### kubelet配置
```yaml
# kubelet配置文件
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
address: 0.0.0.0
port: 10250
readOnlyPort: 0
authentication:
  anonymous:
    enabled: false
  webhook:
    enabled: true
  x509:
    clientCAFile: /etc/kubernetes/pki/ca.crt
authorization:
  mode: Webhook
clusterDNS:
- 10.96.0.10
clusterDomain: cluster.local
cpuManagerPolicy: none
evictionHard:
  imagefs.available: 15%
  memory.available: 100Mi
  nodefs.available: 10%
  nodefs.inodesFree: 5%
failSwapOn: false
hairpinMode: promiscuous-bridge
healthzBindAddress: 127.0.0.1
healthzPort: 10248
imageGCHighThresholdPercent: 85
imageGCLowThresholdPercent: 80
kubeAPIQPS: 50
kubeAPIBurst: 100
maxPods: 110
serializeImagePulls: false
staticPodPath: /etc/kubernetes/manifests
```

---

## 3. Kubernetes核心原理

### 3.1 声明式API

Kubernetes采用声明式API设计，用户描述期望状态，系统负责达到该状态。

```go
// 声明式API示例
package main

import (
    "context"
    "fmt"
    "log"
    
    appsv1 "k8s.io/api/apps/v1"
    corev1 "k8s.io/api/core/v1"
    metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
    "k8s.io/client-go/kubernetes"
    "k8s.io/client-go/rest"
)

type DeploymentManager struct {
    clientset *kubernetes.Clientset
}

func NewDeploymentManager() (*DeploymentManager, error) {
    config, err := rest.InClusterConfig()
    if err != nil {
        return nil, err
    }
    
    clientset, err := kubernetes.NewForConfig(config)
    if err != nil {
        return nil, err
    }
    
    return &DeploymentManager{
        clientset: clientset,
    }, nil
}

func (dm *DeploymentManager) CreateDeployment(name, namespace, image string, replicas int32) error {
    deployment := &appsv1.Deployment{
        ObjectMeta: metav1.ObjectMeta{
            Name:      name,
            Namespace: namespace,
            Labels: map[string]string{
                "app": name,
            },
        },
        Spec: appsv1.DeploymentSpec{
            Replicas: &replicas,
            Selector: &metav1.LabelSelector{
                MatchLabels: map[string]string{
                    "app": name,
                },
            },
            Template: corev1.PodTemplateSpec{
                ObjectMeta: metav1.ObjectMeta{
                    Labels: map[string]string{
                        "app": name,
                    },
                },
                Spec: corev1.PodSpec{
                    Containers: []corev1.Container{
                        {
                            Name:  name,
                            Image: image,
                            Ports: []corev1.ContainerPort{
                                {
                                    ContainerPort: 80,
                                },
                            },
                            Resources: corev1.ResourceRequirements{
                                Requests: corev1.ResourceList{
                                    corev1.ResourceCPU:    "100m",
                                    corev1.ResourceMemory: "128Mi",
                                },
                                Limits: corev1.ResourceList{
                                    corev1.ResourceCPU:    "500m",
                                    corev1.ResourceMemory: "512Mi",
                                },
                            },
                        },
                    },
                },
            },
        },
    }
    
    _, err := dm.clientset.AppsV1().Deployments(namespace).Create(
        context.TODO(), deployment, metav1.CreateOptions{},
    )
    
    return err
}

func (dm *DeploymentManager) UpdateDeployment(name, namespace, newImage string) error {
    deployment, err := dm.clientset.AppsV1().Deployments(namespace).Get(
        context.TODO(), name, metav1.GetOptions{},
    )
    if err != nil {
        return err
    }
    
    // 更新镜像
    deployment.Spec.Template.Spec.Containers[0].Image = newImage
    
    _, err = dm.clientset.AppsV1().Deployments(namespace).Update(
        context.TODO(), deployment, metav1.UpdateOptions{},
    )
    
    return err
}

func (dm *DeploymentManager) ScaleDeployment(name, namespace string, replicas int32) error {
    scale, err := dm.clientset.AppsV1().Deployments(namespace).GetScale(
        context.TODO(), name, metav1.GetOptions{},
    )
    if err != nil {
        return err
    }
    
    scale.Spec.Replicas = replicas
    
    _, err = dm.clientset.AppsV1().Deployments(namespace).UpdateScale(
        context.TODO(), name, scale, metav1.UpdateOptions{},
    )
    
    return err
}
```

### 3.2 控制器模式

控制器通过控制循环不断监控集群状态，确保实际状态与期望状态一致。

```go
// 自定义控制器示例
package main

import (
    "context"
    "fmt"
    "time"
    
    appsv1 "k8s.io/api/apps/v1"
    corev1 "k8s.io/api/core/v1"
    metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
    "k8s.io/apimachinery/pkg/fields"
    "k8s.io/apimachinery/pkg/util/runtime"
    "k8s.io/apimachinery/pkg/util/wait"
    "k8s.io/client-go/kubernetes"
    "k8s.io/client-go/tools/cache"
    "k8s.io/client-go/util/workqueue"
)

type Controller struct {
    clientset    *kubernetes.Clientset
    indexer      cache.Indexer
    queue        workqueue.RateLimitingInterface
    informer     cache.Controller
}

func NewController(clientset *kubernetes.Clientset) *Controller {
    queue := workqueue.NewRateLimitingQueue(workqueue.DefaultControllerRateLimiter())
    
    listWatcher := cache.NewListWatchFromClient(
        clientset.AppsV1().RESTClient(),
        "deployments",
        metav1.NamespaceAll,
        fields.Everything(),
    )
    
    indexer, informer := cache.NewIndexerInformer(
        listWatcher,
        &appsv1.Deployment{},
        0,
        cache.ResourceEventHandlerFuncs{
            AddFunc: func(obj interface{}) {
                key, err := cache.MetaNamespaceKeyFunc(obj)
                if err == nil {
                    queue.Add(key)
                }
            },
            UpdateFunc: func(old interface{}, new interface{}) {
                key, err := cache.MetaNamespaceKeyFunc(new)
                if err == nil {
                    queue.Add(key)
                }
            },
            DeleteFunc: func(obj interface{}) {
                key, err := cache.DeletionHandlingMetaNamespaceKeyFunc(obj)
                if err == nil {
                    queue.Add(key)
                }
            },
        },
        cache.Indexers{},
    )
    
    return &Controller{
        clientset: clientset,
        indexer:   indexer,
        queue:     queue,
        informer:  informer,
    }
}

func (c *Controller) Run(threadiness int, stopCh chan struct{}) {
    defer runtime.HandleCrash()
    defer c.queue.ShutDown()
    
    fmt.Println("Starting controller")
    
    go c.informer.Run(stopCh)
    
    if !cache.WaitForCacheSync(stopCh, c.informer.HasSynced) {
        runtime.HandleError(fmt.Errorf("Timed out waiting for caches to sync"))
        return
    }
    
    for i := 0; i < threadiness; i++ {
        go wait.Until(c.runWorker, time.Second, stopCh)
    }
    
    <-stopCh
    fmt.Println("Stopping controller")
}

func (c *Controller) runWorker() {
    for c.processNextItem() {
    }
}

func (c *Controller) processNextItem() bool {
    key, quit := c.queue.Get()
    if quit {
        return false
    }
    defer c.queue.Done(key)
    
    err := c.syncHandler(key.(string))
    c.handleErr(err, key)
    
    return true
}

func (c *Controller) syncHandler(key string) error {
    obj, exists, err := c.indexer.GetByKey(key)
    if err != nil {
        return err
    }
    
    if !exists {
        fmt.Printf("Deployment %s deleted\n", key)
        return nil
    }
    
    deployment := obj.(*appsv1.Deployment)
    fmt.Printf("Processing deployment %s\n", deployment.Name)
    
    // 自定义业务逻辑
    return c.processDeployment(deployment)
}

func (c *Controller) processDeployment(deployment *appsv1.Deployment) error {
    // 检查部署状态
    if deployment.Status.ReadyReplicas != *deployment.Spec.Replicas {
        fmt.Printf("Deployment %s not ready: %d/%d replicas\n",
            deployment.Name,
            deployment.Status.ReadyReplicas,
            *deployment.Spec.Replicas,
        )
    }
    
    // 添加自定义标签
    if deployment.Labels == nil {
        deployment.Labels = make(map[string]string)
    }
    
    if _, exists := deployment.Labels["managed-by"]; !exists {
        deployment.Labels["managed-by"] = "custom-controller"
        
        _, err := c.clientset.AppsV1().Deployments(deployment.Namespace).Update(
            context.TODO(), deployment, metav1.UpdateOptions{},
        )
        if err != nil {
            return err
        }
        
        fmt.Printf("Added managed-by label to deployment %s\n", deployment.Name)
    }
    
    return nil
}

func (c *Controller) handleErr(err error, key interface{}) {
    if err == nil {
        c.queue.Forget(key)
        return
    }
    
    if c.queue.NumRequeues(key) < 5 {
        fmt.Printf("Error syncing deployment %v: %v\n", key, err)
        c.queue.AddRateLimited(key)
        return
    }
    
    c.queue.Forget(key)
    runtime.HandleError(err)
    fmt.Printf("Dropping deployment %q out of the queue: %v\n", key, err)
}
```

### 3.3 调度原理

Kubernetes调度器负责将Pod分配到合适的节点上。

```go
// 调度器扩展示例
package main

import (
    "context"
    "fmt"
    "math"
    
    corev1 "k8s.io/api/core/v1"
    metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
    "k8s.io/apimachinery/pkg/runtime"
    "k8s.io/client-go/kubernetes"
    "k8s.io/kubernetes/pkg/scheduler/framework"
)

// 自定义调度插件
type CustomSchedulerPlugin struct {
    handle framework.Handle
}

func (p *CustomSchedulerPlugin) Name() string {
    return "CustomSchedulerPlugin"
}

// 过滤阶段：过滤不符合条件的节点
func (p *CustomSchedulerPlugin) Filter(ctx context.Context, state *framework.CycleState, pod *corev1.Pod, nodeInfo *framework.NodeInfo) *framework.Status {
    node := nodeInfo.Node()
    
    // 检查节点标签
    if requiredZone, exists := pod.Spec.NodeSelector["zone"]; exists {
        if nodeZone, exists := node.Labels["zone"]; !exists || nodeZone != requiredZone {
            return framework.NewStatus(framework.Unschedulable, "Node zone mismatch")
        }
    }
    
    // 检查资源需求
    if !p.checkResourceRequirements(pod, nodeInfo) {
        return framework.NewStatus(framework.Unschedulable, "Insufficient resources")
    }
    
    return framework.NewStatus(framework.Success, "")
}

// 评分阶段：为节点打分
func (p *CustomSchedulerPlugin) Score(ctx context.Context, state *framework.CycleState, pod *corev1.Pod, nodeName string) (int64, *framework.Status) {
    nodeInfo, err := p.handle.SnapshotSharedLister().NodeInfos().Get(nodeName)
    if err != nil {
        return 0, framework.NewStatus(framework.Error, fmt.Sprintf("getting node %q from Snapshot: %v", nodeName, err))
    }
    
    score := p.calculateNodeScore(pod, nodeInfo)
    return score, framework.NewStatus(framework.Success, "")
}

func (p *CustomSchedulerPlugin) checkResourceRequirements(pod *corev1.Pod, nodeInfo *framework.NodeInfo) bool {
    node := nodeInfo.Node()
    
    // 计算Pod资源需求
    var cpuRequest, memoryRequest int64
    for _, container := range pod.Spec.Containers {
        if cpu := container.Resources.Requests[corev1.ResourceCPU]; !cpu.IsZero() {
            cpuRequest += cpu.MilliValue()
        }
        if memory := container.Resources.Requests[corev1.ResourceMemory]; !memory.IsZero() {
            memoryRequest += memory.Value()
        }
    }
    
    // 检查节点可用资源
    allocatable := node.Status.Allocatable
    availableCPU := allocatable[corev1.ResourceCPU].MilliValue() - nodeInfo.Requested.MilliCPU
    availableMemory := allocatable[corev1.ResourceMemory].Value() - nodeInfo.Requested.Memory
    
    return cpuRequest <= availableCPU && memoryRequest <= availableMemory
}

func (p *CustomSchedulerPlugin) calculateNodeScore(pod *corev1.Pod, nodeInfo *framework.NodeInfo) int64 {
    node := nodeInfo.Node()
    
    // 基础分数
    score := int64(50)
    
    // 根据资源利用率调整分数
    allocatable := node.Status.Allocatable
    cpuUtilization := float64(nodeInfo.Requested.MilliCPU) / float64(allocatable[corev1.ResourceCPU].MilliValue())
    memoryUtilization := float64(nodeInfo.Requested.Memory) / float64(allocatable[corev1.ResourceMemory].Value())
    
    // 偏好资源利用率适中的节点
    avgUtilization := (cpuUtilization + memoryUtilization) / 2
    if avgUtilization > 0.8 {
        score -= 20 // 高利用率降分
    } else if avgUtilization < 0.2 {
        score -= 10 // 低利用率轻微降分
    } else {
        score += 10 // 适中利用率加分
    }
    
    // 根据节点标签调整分数
    if nodeType, exists := node.Labels["node-type"]; exists {
        switch nodeType {
        case "high-performance":
            score += 20
        case "standard":
            score += 10
        case "spot":
            score -= 10
        }
    }
    
    // 根据Pod亲和性调整分数
    if p.checkPodAffinity(pod, nodeInfo) {
        score += 15
    }
    
    return int64(math.Max(0, math.Min(100, float64(score))))
}

func (p *CustomSchedulerPlugin) checkPodAffinity(pod *corev1.Pod, nodeInfo *framework.NodeInfo) bool {
    if pod.Spec.Affinity == nil || pod.Spec.Affinity.PodAffinity == nil {
        return false
    }
    
    // 检查Pod亲和性规则
    for _, term := range pod.Spec.Affinity.PodAffinity.PreferredDuringSchedulingIgnoredDuringExecution {
        if p.matchAffinityTerm(term.PodAffinityTerm, nodeInfo) {
            return true
        }
    }
    
    return false
}

func (p *CustomSchedulerPlugin) matchAffinityTerm(term corev1.PodAffinityTerm, nodeInfo *framework.NodeInfo) bool {
    // 简化的亲和性匹配逻辑
    for _, pod := range nodeInfo.Pods {
        if p.matchLabels(term.LabelSelector, pod.Labels) {
            return true
        }
    }
    return false
}

func (p *CustomSchedulerPlugin) matchLabels(selector *metav1.LabelSelector, labels map[string]string) bool {
    if selector == nil {
        return true
    }
    
    for key, value := range selector.MatchLabels {
        if labels[key] != value {
            return false
        }
    }
    
    return true
}

// 插件工厂函数
func NewCustomSchedulerPlugin(obj runtime.Object, h framework.Handle) (framework.Plugin, error) {
    return &CustomSchedulerPlugin{
        handle: h,
    }, nil
}
```

---

## 4. Kubernetes核心组件

### 4.1 API Server

API Server是Kubernetes的核心组件，提供RESTful API接口。

#### API Server功能
```go
// API Server客户端示例
package main

import (
    "context"
    "fmt"
    "log"
    
    corev1 "k8s.io/api/core/v1"
    metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
    "k8s.io/client-go/kubernetes"
    "k8s.io/client-go/rest"
)

type APIClient struct {
    clientset *kubernetes.Clientset
}

func NewAPIClient() (*APIClient, error) {
    config, err := rest.InClusterConfig()
    if err != nil {
        return nil, err
    }
    
    clientset, err := kubernetes.NewForConfig(config)
    if err != nil {
        return nil, err
    }
    
    return &APIClient{
        clientset: clientset,
    }, nil
}

// 获取集群信息
func (c *APIClient) GetClusterInfo() error {
    // 获取节点信息
    nodes, err := c.clientset.CoreV1().Nodes().List(context.TODO(), metav1.ListOptions{})
    if err != nil {
        return err
    }
    
    fmt.Printf("Cluster has %d nodes:\n", len(nodes.Items))
    for _, node := range nodes.Items {
        fmt.Printf("- %s (%s)\n", node.Name, node.Status.NodeInfo.KubeletVersion)
    }
    
    // 获取命名空间
    namespaces, err := c.clientset.CoreV1().Namespaces().List(context.TODO(), metav1.ListOptions{})
    if err != nil {
        return err
    }
    
    fmt.Printf("\nCluster has %d namespaces:\n", len(namespaces.Items))
    for _, ns := range namespaces.Items {
        fmt.Printf("- %s\n", ns.Name)
    }
    
    return nil
}

// 监听资源变化
func (c *APIClient) WatchPods(namespace string) error {
    watcher, err := c.clientset.CoreV1().Pods(namespace).Watch(context.TODO(), metav1.ListOptions{})
    if err != nil {
        return err
    }
    defer watcher.Stop()
    
    fmt.Printf("Watching pods in namespace %s...\n", namespace)
    
    for event := range watcher.ResultChan() {
        pod, ok := event.Object.(*corev1.Pod)
        if !ok {
            continue
        }
        
        fmt.Printf("Pod %s %s: %s\n", event.Type, pod.Name, pod.Status.Phase)
    }
    
    return nil
}

// 创建资源
func (c *APIClient) CreateNamespace(name string) error {
    namespace := &corev1.Namespace{
        ObjectMeta: metav1.ObjectMeta{
            Name: name,
            Labels: map[string]string{
                "created-by": "api-client",
            },
        },
    }
    
    _, err := c.clientset.CoreV1().Namespaces().Create(context.TODO(), namespace, metav1.CreateOptions{})
    if err != nil {
        return err
    }
    
    fmt.Printf("Namespace %s created successfully\n", name)
    return nil
}

// 更新资源
func (c *APIClient) UpdateNamespaceLabels(name string, labels map[string]string) error {
    namespace, err := c.clientset.CoreV1().Namespaces().Get(context.TODO(), name, metav1.GetOptions{})
    if err != nil {
        return err
    }
    
    if namespace.Labels == nil {
        namespace.Labels = make(map[string]string)
    }
    
    for key, value := range labels {
        namespace.Labels[key] = value
    }
    
    _, err = c.clientset.CoreV1().Namespaces().Update(context.TODO(), namespace, metav1.UpdateOptions{})
    if err != nil {
        return err
    }
    
    fmt.Printf("Namespace %s labels updated\n", name)
    return nil
}

// 删除资源
func (c *APIClient) DeleteNamespace(name string) error {
    err := c.clientset.CoreV1().Namespaces().Delete(context.TODO(), name, metav1.DeleteOptions{})
    if err != nil {
        return err
    }
    
    fmt.Printf("Namespace %s deleted\n", name)
    return nil
}
```

### 4.2 etcd

etcd是Kubernetes的分布式键值存储，存储集群的所有数据。

#### etcd操作
```bash
#!/bin/bash
# etcd管理脚本

# etcd集群健康检查
check_etcd_health() {
    echo "Checking etcd cluster health..."
    
    ETCDCTL_API=3 etcdctl \
        --endpoints=https://127.0.0.1:2379 \
        --cacert=/etc/kubernetes/pki/etcd/ca.crt \
        --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
        --key=/etc/kubernetes/pki/etcd/healthcheck-client.key \
        endpoint health
}

# 备份etcd数据
backup_etcd() {
    local backup_dir="/var/backups/etcd"
    local backup_file="etcd-backup-$(date +%Y%m%d-%H%M%S).db"
    
    mkdir -p "$backup_dir"
    
    echo "Creating etcd backup: $backup_file"
    
    ETCDCTL_API=3 etcdctl \
        --endpoints=https://127.0.0.1:2379 \
        --cacert=/etc/kubernetes/pki/etcd/ca.crt \
        --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
        --key=/etc/kubernetes/pki/etcd/healthcheck-client.key \
        snapshot save "$backup_dir/$backup_file"
    
    echo "Backup completed: $backup_dir/$backup_file"
}

# 恢复etcd数据
restore_etcd() {
    local backup_file="$1"
    local data_dir="/var/lib/etcd-restore"
    
    if [ ! -f "$backup_file" ]; then
        echo "Backup file not found: $backup_file"
        exit 1
    fi
    
    echo "Restoring etcd from backup: $backup_file"
    
    # 停止etcd服务
    systemctl stop etcd
    
    # 清理现有数据
    rm -rf "$data_dir"
    
    # 恢复数据
    ETCDCTL_API=3 etcdctl snapshot restore "$backup_file" \
        --data-dir="$data_dir" \
        --name=master \
        --initial-cluster=master=https://10.0.0.1:2380 \
        --initial-advertise-peer-urls=https://10.0.0.1:2380
    
    # 更新etcd配置
    sed -i "s|--data-dir=/var/lib/etcd|--data-dir=$data_dir|g" /etc/kubernetes/manifests/etcd.yaml
    
    echo "Restore completed. Please restart etcd service."
}

# 查看etcd成员
list_etcd_members() {
    echo "Listing etcd cluster members..."
    
    ETCDCTL_API=3 etcdctl \
        --endpoints=https://127.0.0.1:2379 \
        --cacert=/etc/kubernetes/pki/etcd/ca.crt \
        --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
        --key=/etc/kubernetes/pki/etcd/healthcheck-client.key \
        member list
}

# 压缩etcd数据
compact_etcd() {
    echo "Compacting etcd data..."
    
    # 获取当前版本
    local current_rev=$(ETCDCTL_API=3 etcdctl \
        --endpoints=https://127.0.0.1:2379 \
        --cacert=/etc/kubernetes/pki/etcd/ca.crt \
        --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
        --key=/etc/kubernetes/pki/etcd/healthcheck-client.key \
        endpoint status --write-out="table" | grep -oE '[0-9]+' | tail -1)
    
    # 压缩到当前版本
    ETCDCTL_API=3 etcdctl \
        --endpoints=https://127.0.0.1:2379 \
        --cacert=/etc/kubernetes/pki/etcd/ca.crt \
        --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
        --key=/etc/kubernetes/pki/etcd/healthcheck-client.key \
        compact "$current_rev"
    
    # 整理碎片
    ETCDCTL_API=3 etcdctl \
        --endpoints=https://127.0.0.1:2379 \
        --cacert=/etc/kubernetes/pki/etcd/ca.crt \
        --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
        --key=/etc/kubernetes/pki/etcd/healthcheck-client.key \
        defrag
    
    echo "Compaction completed"
}

# 主函数
main() {
    case "$1" in
        "health")
            check_etcd_health
            ;;
        "backup")
            backup_etcd
            ;;
        "restore")
            restore_etcd "$2"
            ;;
        "members")
            list_etcd_members
            ;;
        "compact")
            compact_etcd
            ;;
        *)
            echo "Usage: $0 {health|backup|restore <backup_file>|members|compact}"
            exit 1
            ;;
    esac
}

main "$@"
```

### 4.3 Scheduler

调度器负责将Pod分配到合适的节点。

#### 调度器配置
```yaml
# scheduler-config.yaml
apiVersion: kubescheduler.config.k8s.io/v1beta3
kind: KubeSchedulerConfiguration
profiles:
- schedulerName: default-scheduler
  plugins:
    score:
      enabled:
      - name: NodeResourcesFit
      - name: NodeAffinity
      - name: PodTopologySpread
      - name: InterPodAffinity
      disabled:
      - name: NodeResourcesLeastAllocated
    filter:
      enabled:
      - name: NodeUnschedulable
      - name: NodeName
      - name: TaintToleration
      - name: NodeAffinity
      - name: NodePorts
      - name: NodeResourcesFit
      - name: VolumeRestrictions
      - name: EBSLimits
      - name: GCEPDLimits
      - name: NodeVolumeLimits
      - name: AzureDiskLimits
      - name: VolumeBinding
      - name: VolumeZone
      - name: PodTopologySpread
      - name: InterPodAffinity
  pluginConfig:
  - name: NodeResourcesFit
    args:
      scoringStrategy:
        type: LeastAllocated
        resources:
        - name: cpu
          weight: 1
        - name: memory
          weight: 1
  - name: PodTopologySpread
    args:
      defaultConstraints:
      - maxSkew: 1
        topologyKey: zone
        whenUnsatisfiable: ScheduleAnyway
      - maxSkew: 1
        topologyKey: node
        whenUnsatisfiable: ScheduleAnyway
```

### 4.4 Controller Manager

控制器管理器运行各种控制器。

#### 自定义控制器
```go
// 自定义资源控制器
package main

import (
    "context"
    "fmt"
    "time"
    
    appsv1 "k8s.io/api/apps/v1"
    corev1 "k8s.io/api/core/v1"
    "k8s.io/apimachinery/pkg/api/errors"
    metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
    "k8s.io/apimachinery/pkg/runtime"
    "k8s.io/apimachinery/pkg/util/intstr"
    "k8s.io/apimachinery/pkg/util/wait"
    "k8s.io/client-go/kubernetes"
    "k8s.io/client-go/tools/cache"
    "k8s.io/client-go/util/workqueue"
    "sigs.k8s.io/controller-runtime/pkg/controller"
    "sigs.k8s.io/controller-runtime/pkg/handler"
    "sigs.k8s.io/controller-runtime/pkg/manager"
    "sigs.k8s.io/controller-runtime/pkg/reconcile"
    "sigs.k8s.io/controller-runtime/pkg/source"
)

// WebAppController 管理WebApp资源
type WebAppController struct {
    client kubernetes.Interface
}

// WebApp 自定义资源定义
type WebApp struct {
    metav1.TypeMeta   `json:",inline"`
    metav1.ObjectMeta `json:"metadata,omitempty"`
    Spec              WebAppSpec   `json:"spec,omitempty"`
    Status            WebAppStatus `json:"status,omitempty"`
}

type WebAppSpec struct {
    Image    string `json:"image"`
    Replicas int32  `json:"replicas"`
    Port     int32  `json:"port"`
}

type WebAppStatus struct {
    AvailableReplicas int32 `json:"availableReplicas"`
    Conditions        []WebAppCondition `json:"conditions"`
}

type WebAppCondition struct {
    Type   string `json:"type"`
    Status string `json:"status"`
    Reason string `json:"reason"`
}

// Reconcile 实现调和逻辑
func (r *WebAppController) Reconcile(ctx context.Context, req reconcile.Request) (reconcile.Result, error) {
    // 获取WebApp资源
    webapp := &WebApp{}
    err := r.Get(ctx, req.NamespacedName, webapp)
    if err != nil {
        if errors.IsNotFound(err) {
            return reconcile.Result{}, nil
        }
        return reconcile.Result{}, err
    }
    
    // 创建或更新Deployment
    deployment := r.createDeployment(webapp)
    err = r.createOrUpdateDeployment(ctx, deployment)
    if err != nil {
        return reconcile.Result{}, err
    }
    
    // 创建或更新Service
    service := r.createService(webapp)
    err = r.createOrUpdateService(ctx, service)
    if err != nil {
        return reconcile.Result{}, err
    }
    
    // 更新状态
    err = r.updateStatus(ctx, webapp)
    if err != nil {
        return reconcile.Result{}, err
    }
    
    return reconcile.Result{RequeueAfter: time.Minute * 5}, nil
}

func (r *WebAppController) createDeployment(webapp *WebApp) *appsv1.Deployment {
    return &appsv1.Deployment{
        ObjectMeta: metav1.ObjectMeta{
            Name:      webapp.Name,
            Namespace: webapp.Namespace,
            OwnerReferences: []metav1.OwnerReference{
                {
                    APIVersion: webapp.APIVersion,
                    Kind:       webapp.Kind,
                    Name:       webapp.Name,
                    UID:        webapp.UID,
                    Controller: &[]bool{true}[0],
                },
            },
        },
        Spec: appsv1.DeploymentSpec{
            Replicas: &webapp.Spec.Replicas,
            Selector: &metav1.LabelSelector{
                MatchLabels: map[string]string{
                    "app": webapp.Name,
                },
            },
            Template: corev1.PodTemplateSpec{
                ObjectMeta: metav1.ObjectMeta{
                    Labels: map[string]string{
                        "app": webapp.Name,
                    },
                },
                Spec: corev1.PodSpec{
                    Containers: []corev1.Container{
                        {
                            Name:  "webapp",
                            Image: webapp.Spec.Image,
                            Ports: []corev1.ContainerPort{
                                {
                                    ContainerPort: webapp.Spec.Port,
                                },
                            },
                            Resources: corev1.ResourceRequirements{
                                Requests: corev1.ResourceList{
                                    corev1.ResourceCPU:    "100m",
                                    corev1.ResourceMemory: "128Mi",
                                },
                                Limits: corev1.ResourceList{
                                    corev1.ResourceCPU:    "500m",
                                    corev1.ResourceMemory: "512Mi",
                                },
                            },
                            LivenessProbe: &corev1.Probe{
                                ProbeHandler: corev1.ProbeHandler{
                                    HTTPGet: &corev1.HTTPGetAction{
                                        Path: "/health",
                                        Port: intstr.FromInt(int(webapp.Spec.Port)),
                                    },
                                },
                                InitialDelaySeconds: 30,
                                PeriodSeconds:       10,
                            },
                            ReadinessProbe: &corev1.Probe{
                                ProbeHandler: corev1.ProbeHandler{
                                    HTTPGet: &corev1.HTTPGetAction{
                                        Path: "/ready",
                                        Port: intstr.FromInt(int(webapp.Spec.Port)),
                                    },
                                },
                                InitialDelaySeconds: 5,
                                PeriodSeconds:       5,
                            },
                        },
                    },
                },
            },
        },
    }
}

func (r *WebAppController) createService(webapp *WebApp) *corev1.Service {
    return &corev1.Service{
        ObjectMeta: metav1.ObjectMeta{
            Name:      webapp.Name + "-service",
            Namespace: webapp.Namespace,
            OwnerReferences: []metav1.OwnerReference{
                {
                    APIVersion: webapp.APIVersion,
                    Kind:       webapp.Kind,
                    Name:       webapp.Name,
                    UID:        webapp.UID,
                    Controller: &[]bool{true}[0],
                },
            },
        },
        Spec: corev1.ServiceSpec{
            Selector: map[string]string{
                "app": webapp.Name,
            },
            Ports: []corev1.ServicePort{
                {
                    Port:       80,
                    TargetPort: intstr.FromInt(int(webapp.Spec.Port)),
                    Protocol:   corev1.ProtocolTCP,
                },
            },
            Type: corev1.ServiceTypeClusterIP,
        },
    }
}

func (r *WebAppController) createOrUpdateDeployment(ctx context.Context, deployment *appsv1.Deployment) error {
    existing := &appsv1.Deployment{}
    err := r.Get(ctx, client.ObjectKey{
        Namespace: deployment.Namespace,
        Name:      deployment.Name,
    }, existing)
    
    if err != nil {
        if errors.IsNotFound(err) {
            return r.Create(ctx, deployment)
        }
        return err
    }
    
    // 更新现有Deployment
    existing.Spec = deployment.Spec
    return r.Update(ctx, existing)
}

func (r *WebAppController) createOrUpdateService(ctx context.Context, service *corev1.Service) error {
    existing := &corev1.Service{}
    err := r.Get(ctx, client.ObjectKey{
        Namespace: service.Namespace,
        Name:      service.Name,
    }, existing)
    
    if err != nil {
        if errors.IsNotFound(err) {
            return r.Create(ctx, service)
        }
        return err
    }
    
    // 更新现有Service
    existing.Spec.Ports = service.Spec.Ports
    existing.Spec.Selector = service.Spec.Selector
    return r.Update(ctx, existing)
}

func (r *WebAppController) updateStatus(ctx context.Context, webapp *WebApp) error {
    // 获取Deployment状态
    deployment := &appsv1.Deployment{}
    err := r.Get(ctx, client.ObjectKey{
        Namespace: webapp.Namespace,
        Name:      webapp.Name,
    }, deployment)
    if err != nil {
        return err
    }
    
    // 更新WebApp状态
    webapp.Status.AvailableReplicas = deployment.Status.AvailableReplicas
    
    // 更新条件
    condition := WebAppCondition{
        Type:   "Ready",
        Status: "False",
        Reason: "DeploymentNotReady",
    }
    
    if deployment.Status.AvailableReplicas == webapp.Spec.Replicas {
        condition.Status = "True"
        condition.Reason = "DeploymentReady"
    }
    
    webapp.Status.Conditions = []WebAppCondition{condition}
    
    return r.Status().Update(ctx, webapp)
}

// SetupWithManager 设置控制器
func (r *WebAppController) SetupWithManager(mgr manager.Manager) error {
    return ctrl.NewControllerManagedBy(mgr).
        For(&WebApp{}).
        Owns(&appsv1.Deployment{}).
        Owns(&corev1.Service{}).
        Complete(r)
}
```

---

## 5. Kubernetes核心能力

### 5.1 服务发现与负载均衡

#### Service配置
```yaml
# ClusterIP Service
apiVersion: v1
kind: Service
metadata:
  name: web-service
  namespace: default
spec:
  selector:
    app: web
  ports:
  - port: 80
    targetPort: 8080
    protocol: TCP
  type: ClusterIP

---
# NodePort Service
apiVersion: v1
kind: Service
metadata:
  name: web-nodeport
  namespace: default
spec:
  selector:
    app: web
  ports:
  - port: 80
    targetPort: 8080
    nodePort: 30080
    protocol: TCP
  type: NodePort

---
# LoadBalancer Service
apiVersion: v1
kind: Service
metadata:
  name: web-loadbalancer
  namespace: default
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-type: nlb
    service.beta.kubernetes.io/aws-load-balancer-cross-zone-load-balancing-enabled: "true"
spec:
  selector:
    app: web
  ports:
  - port: 80
    targetPort: 8080
    protocol: TCP
  type: LoadBalancer

---
# Headless Service
apiVersion: v1
kind: Service
metadata:
  name: web-headless
  namespace: default
spec:
  selector:
    app: web
  ports:
  - port: 80
    targetPort: 8080
    protocol: TCP
  clusterIP: None
```

#### Ingress配置
```yaml
# Ingress配置
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: web-ingress
  namespace: default
  annotations:
    kubernetes.io/ingress.class: nginx
    nginx.ingress.kubernetes.io/rewrite-target: /
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/rate-limit: "100"
    nginx.ingress.kubernetes.io/rate-limit-window: "1m"
spec:
  tls:
  - hosts:
    - web.example.com
    - api.example.com
    secretName: web-tls
  rules:
  - host: web.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: web-service
            port:
              number: 80
  - host: api.example.com
    http:
      paths:
      - path: /api
        pathType: Prefix
        backend:
          service:
            name: api-service
            port:
              number: 80
      - path: /health
        pathType: Exact
        backend:
          service:
            name: health-service
            port:
              number: 8080
```

### 5.2 自动扩缩容

#### HPA配置
```yaml
# Horizontal Pod Autoscaler
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: web-hpa
  namespace: default
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: web-deployment
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  - type: Pods
    pods:
      metric:
        name: http_requests_per_second
      target:
        type: AverageValue
        averageValue: "100"
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 10
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
      - type: Percent
        value: 50
        periodSeconds: 60
      - type: Pods
        value: 2
        periodSeconds: 60
      selectPolicy: Max
```

#### VPA配置
```yaml
# Vertical Pod Autoscaler
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: web-vpa
  namespace: default
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: web-deployment
  updatePolicy:
    updateMode: "Auto"
  resourcePolicy:
    containerPolicies:
    - containerName: web-container
      minAllowed:
        cpu: 100m
        memory: 128Mi
      maxAllowed:
        cpu: 2
        memory: 2Gi
      controlledResources: ["cpu", "memory"]
```

#### Cluster Autoscaler配置
```yaml
# Cluster Autoscaler
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-autoscaler
  namespace: kube-system
  labels:
    app: cluster-autoscaler
spec:
  selector:
    matchLabels:
      app: cluster-autoscaler
  template:
    metadata:
      labels:
        app: cluster-autoscaler
    spec:
      serviceAccountName: cluster-autoscaler
      containers:
      - image: k8s.gcr.io/autoscaling/cluster-autoscaler:v1.21.0
        name: cluster-autoscaler
        resources:
          limits:
            cpu: 100m
            memory: 300Mi
          requests:
            cpu: 100m
            memory: 300Mi
        command:
        - ./cluster-autoscaler
        - --v=4
        - --stderrthreshold=info
        - --cloud-provider=aws
        - --skip-nodes-with-local-storage=false
        - --expander=least-waste
        - --node-group-auto-discovery=asg:tag=k8s.io/cluster-autoscaler/enabled,k8s.io/cluster-autoscaler/production-cluster
        - --balance-similar-node-groups
        - --skip-nodes-with-system-pods=false
        env:
        - name: AWS_REGION
          value: us-west-2
```

### 5.3 存储管理

#### PersistentVolume配置
```yaml
# PersistentVolume
apiVersion: v1
kind: PersistentVolume
metadata:
  name: mysql-pv
spec:
  capacity:
    storage: 20Gi
  volumeMode: Filesystem
  accessModes:
  - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: fast-ssd
  awsElasticBlockStore:
    volumeID: vol-1234567890abcdef0
    fsType: ext4
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values:
          - worker-node-1

---
# PersistentVolumeClaim
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: mysql-pvc
  namespace: default
spec:
  accessModes:
  - ReadWriteOnce
  volumeMode: Filesystem
  resources:
    requests:
      storage: 20Gi
  storageClassName: fast-ssd
  selector:
    matchLabels:
      app: mysql
```

#### StorageClass配置
```yaml
# StorageClass for AWS EBS
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fast-ssd
provisioner: ebs.csi.aws.com
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
parameters:
  type: gp3
  iops: "3000"
  throughput: "125"
  encrypted: "true"
  kmsKeyId: arn:aws:kms:us-west-2:123456789012:key/12345678-1234-1234-1234-123456789012

---
# StorageClass for NFS
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: nfs-storage
provisioner: nfs.csi.k8s.io
parameters:
  server: nfs-server.example.com
  share: /data/nfs
volumeBindingMode: Immediate
allowVolumeExpansion: true
mountOptions:
  - hard
  - nfsvers=4.1
```

### 5.4 配置管理

#### ConfigMap配置
```yaml
# ConfigMap
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
  namespace: default
data:
  # 简单键值对
  database_host: "mysql.default.svc.cluster.local"
  database_port: "3306"
  log_level: "info"
  
  # 配置文件
  app.properties: |
    server.port=8080
    server.servlet.context-path=/api
    
    # Database configuration
    spring.datasource.url=jdbc:mysql://mysql:3306/appdb
    spring.datasource.username=app_user
    spring.datasource.driver-class-name=com.mysql.cj.jdbc.Driver
    
    # Redis configuration
    spring.redis.host=redis
    spring.redis.port=6379
    spring.redis.timeout=2000ms
    
    # Logging configuration
    logging.level.com.example=DEBUG
    logging.pattern.console=%d{yyyy-MM-dd HH:mm:ss} - %msg%n
  
  nginx.conf: |
    user nginx;
    worker_processes auto;
    error_log /var/log/nginx/error.log;
    pid /run/nginx.pid;
    
    events {
        worker_connections 1024;
    }
    
    http {
        log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                        '$status $body_bytes_sent "$http_referer" '
                        '"$http_user_agent" "$http_x_forwarded_for"';
        
        access_log /var/log/nginx/access.log main;
        
        sendfile on;
        tcp_nopush on;
        tcp_nodelay on;
        keepalive_timeout 65;
        types_hash_max_size 2048;
        
        include /etc/nginx/mime.types;
        default_type application/octet-stream;
        
        upstream backend {
            server app-service:8080;
        }
        
        server {
            listen 80;
            server_name _;
            
            location / {
                proxy_pass http://backend;
                proxy_set_header Host $host;
                proxy_set_header X-Real-IP $remote_addr;
                proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                proxy_set_header X-Forwarded-Proto $scheme;
            }
        }
    }
```

#### Secret配置
```yaml
# Secret
apiVersion: v1
kind: Secret
metadata:
  name: app-secrets
  namespace: default
type: Opaque
data:
  # Base64编码的值
  database_password: cGFzc3dvcmQxMjM=  # password123
  api_key: YWJjZGVmZ2hpams=  # abcdefghijk
  jwt_secret: bXlfc3VwZXJfc2VjcmV0X2tleQ==  # my_super_secret_key

---
# TLS Secret
apiVersion: v1
kind: Secret
metadata:
  name: tls-secret
  namespace: default
type: kubernetes.io/tls
data:
  tls.crt: LS0tLS1CRUdJTi... # Base64编码的证书
  tls.key: LS0tLS1CRUdJTi... # Base64编码的私钥

---
# Docker Registry Secret
apiVersion: v1
kind: Secret
metadata:
  name: registry-secret
  namespace: default
type: kubernetes.io/dockerconfigjson
data:
  .dockerconfigjson: eyJhdXRocyI6eyJyZWdpc3RyeS5leGFtcGxlLmNvbSI6eyJ1c2VybmFtZSI6InVzZXIiLCJwYXNzd29yZCI6InBhc3MiLCJhdXRoIjoiZFhObGNqcHdZWE56In19fQ==
```

---

## 6. Kubernetes使用场景

### 6.1 微服务架构

#### 微服务部署示例
```yaml
# 用户服务
apiVersion: apps/v1
kind: Deployment
metadata:
  name: user-service
  namespace: microservices
spec:
  replicas: 3
  selector:
    matchLabels:
      app: user-service
  template:
    metadata:
      labels:
        app: user-service
        version: v1
    spec:
      containers:
      - name: user-service
        image: user-service:v1.0.0
        ports:
        - containerPort: 8080
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: user-db-secret
              key: url
        - name: REDIS_URL
          valueFrom:
            configMapKeyRef:
              name: redis-config
              key: url
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5

---
# 订单服务
apiVersion: apps/v1
kind: Deployment
metadata:
  name: order-service
  namespace: microservices
spec:
  replicas: 2
  selector:
    matchLabels:
      app: order-service
  template:
    metadata:
      labels:
        app: order-service
        version: v1
    spec:
      containers:
      - name: order-service
        image: order-service:v1.0.0
        ports:
        - containerPort: 8080
        env:
        - name: USER_SERVICE_URL
          value: "http://user-service:8080"
        - name: PAYMENT_SERVICE_URL
          value: "http://payment-service:8080"
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
```

### 6.2 CI/CD流水线

#### GitLab CI配置
```yaml
# .gitlab-ci.yml
stages:
  - build
  - test
  - deploy-staging
  - deploy-production

variables:
  DOCKER_REGISTRY: registry.example.com
  KUBE_NAMESPACE_STAGING: staging
  KUBE_NAMESPACE_PROD: production

build:
  stage: build
  image: docker:20.10.16
  services:
    - docker:20.10.16-dind
  before_script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
    - docker tag $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA $CI_REGISTRY_IMAGE:latest
    - docker push $CI_REGISTRY_IMAGE:latest
  only:
    - main
    - develop

test:
  stage: test
  image: golang:1.19
  script:
    - go mod download
    - go test -v ./...
    - go test -race -coverprofile=coverage.out ./...
    - go tool cover -html=coverage.out -o coverage.html
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
    paths:
      - coverage.html
  coverage: '/coverage: \d+\.\d+% of statements/'

deploy-staging:
  stage: deploy-staging
  image: bitnami/kubectl:latest
  before_script:
    - kubectl config use-context $KUBE_CONTEXT_STAGING
  script:
    - envsubst < k8s/deployment.yaml | kubectl apply -f -
    - kubectl set image deployment/app app=$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA -n $KUBE_NAMESPACE_STAGING
    - kubectl rollout status deployment/app -n $KUBE_NAMESPACE_STAGING
  environment:
    name: staging
    url: https://staging.example.com
  only:
    - develop

deploy-production:
  stage: deploy-production
  image: bitnami/kubectl:latest
  before_script:
    - kubectl config use-context $KUBE_CONTEXT_PROD
  script:
    - envsubst < k8s/deployment.yaml | kubectl apply -f -
    - kubectl set image deployment/app app=$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA -n $KUBE_NAMESPACE_PROD
    - kubectl rollout status deployment/app -n $KUBE_NAMESPACE_PROD
  environment:
    name: production
    url: https://app.example.com
  when: manual
  only:
    - main
```

### 6.3 大数据处理

#### Spark on Kubernetes
```yaml
# Spark Driver
apiVersion: apps/v1
kind: Deployment
metadata:
  name: spark-driver
  namespace: big-data
spec:
  replicas: 1
  selector:
    matchLabels:
      app: spark-driver
  template:
    metadata:
      labels:
        app: spark-driver
    spec:
      serviceAccountName: spark
      containers:
      - name: spark-driver
        image: apache/spark:3.4.0
        command:
        - "/opt/spark/bin/spark-submit"
        args:
        - "--master"
        - "k8s://https://kubernetes.default.svc:443"
        - "--deploy-mode"
        - "client"
        - "--name"
        - "data-processing-job"
        - "--conf"
        - "spark.executor.instances=3"
        - "--conf"
        - "spark.kubernetes.container.image=apache/spark:3.4.0"
        - "--conf"
        - "spark.kubernetes.namespace=big-data"
        - "--conf"
        - "spark.kubernetes.authenticate.driver.serviceAccountName=spark"
        - "/opt/spark/examples/jars/spark-examples_2.12-3.4.0.jar"
        - "1000"
        resources:
          requests:
            memory: "1Gi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "1"
        volumeMounts:
        - name: spark-data
          mountPath: /data
      volumes:
      - name: spark-data
        persistentVolumeClaim:
          claimName: spark-data-pvc
```

---

## 7. Kubernetes优化方案

### 7.1 资源优化

#### 资源请求和限制优化
```yaml
# 优化的资源配置
apiVersion: apps/v1
kind: Deployment
metadata:
  name: optimized-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: optimized-app
  template:
    metadata:
      labels:
        app: optimized-app
    spec:
      containers:
      - name: app
        image: app:latest
        resources:
          requests:
            # 基于实际使用情况设置
            memory: "128Mi"
            cpu: "100m"
          limits:
            # 限制设置为请求的2-4倍
            memory: "512Mi"
            cpu: "500m"
        # 启用资源监控
        env:
        - name: GOMAXPROCS
          valueFrom:
            resourceFieldRef:
              resource: limits.cpu
              divisor: "1"
        - name: GOMEMLIMIT
          valueFrom:
            resourceFieldRef:
              resource: limits.memory
              divisor: "1"
```

#### 节点亲和性优化
```yaml
# 节点亲和性配置
apiVersion: apps/v1
kind: Deployment
metadata:
  name: high-performance-app
spec:
  replicas: 2
  selector:
    matchLabels:
      app: high-performance-app
  template:
    metadata:
      labels:
        app: high-performance-app
    spec:
      # 节点亲和性
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
            - matchExpressions:
              - key: node-type
                operator: In
                values:
                - high-performance
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            preference:
              matchExpressions:
              - key: zone
                operator: In
                values:
                - us-west-2a
        # Pod亲和性
        podAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchExpressions:
                - key: app
                  operator: In
                  values:
                  - cache
              topologyKey: kubernetes.io/hostname
        # Pod反亲和性
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
          - labelSelector:
              matchExpressions:
              - key: app
                operator: In
                values:
                - high-performance-app
            topologyKey: kubernetes.io/hostname
      containers:
      - name: app
        image: app:latest
        resources:
          requests:
            memory: "1Gi"
            cpu: "1"
          limits:
            memory: "2Gi"
            cpu: "2"
```

### 7.2 网络优化

#### CNI性能优化
```yaml
# Calico网络策略优化
apiVersion: projectcalico.org/v3
kind: NetworkPolicy
metadata:
  name: optimized-network-policy
  namespace: production
spec:
  selector: app == 'web'
  types:
  - Ingress
  - Egress
  ingress:
  - action: Allow
    protocol: TCP
    source:
      selector: app == 'frontend'
    destination:
      ports:
      - 8080
  - action: Allow
    protocol: TCP
    source:
      nets:
      - 10.0.0.0/8
    destination:
      ports:
      - 8080
  egress:
  - action: Allow
    protocol: TCP
    destination:
      selector: app == 'database'
      ports:
      - 3306
  - action: Allow
    protocol: UDP
    destination:
      ports:
      - 53
```

### 7.3 存储优化

#### 存储性能优化
```go
// 存储性能监控
package main

import (
    "context"
    "fmt"
    "time"
    
    "k8s.io/api/core/v1"
    metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
    "k8s.io/client-go/kubernetes"
    "k8s.io/metrics/pkg/client/clientset/versioned"
)

type StorageMonitor struct {
    clientset        *kubernetes.Clientset
    metricsClientset *versioned.Clientset
}

func (sm *StorageMonitor) MonitorPVCUsage(namespace string) error {
    pvcs, err := sm.clientset.CoreV1().PersistentVolumeClaims(namespace).List(
        context.TODO(), metav1.ListOptions{},
    )
    if err != nil {
        return err
    }
    
    for _, pvc := range pvcs.Items {
        fmt.Printf("PVC: %s\n", pvc.Name)
        fmt.Printf("  Capacity: %s\n", pvc.Status.Capacity[v1.ResourceStorage])
        fmt.Printf("  Access Modes: %v\n", pvc.Status.AccessModes)
        fmt.Printf("  Storage Class: %s\n", *pvc.Spec.StorageClassName)
        
        // 检查PVC使用情况
        if err := sm.checkPVCPerformance(&pvc); err != nil {
            fmt.Printf("  Warning: %v\n", err)
        }
        
        fmt.Println()
    }
    
    return nil
}

func (sm *StorageMonitor) checkPVCPerformance(pvc *v1.PersistentVolumeClaim) error {
    // 检查存储类型
    if pvc.Spec.StorageClassName != nil {
        sc, err := sm.clientset.StorageV1().StorageClasses().Get(
            context.TODO(), *pvc.Spec.StorageClassName, metav1.GetOptions{},
        )
        if err != nil {
            return err
        }
        
        // 检查存储类配置
        if provisioner := sc.Provisioner; provisioner == "ebs.csi.aws.com" {
            if volumeType, exists := sc.Parameters["type"]; exists {
                switch volumeType {
                case "gp2":
                    fmt.Printf("  Recommendation: Consider upgrading to gp3 for better performance\n")
                case "io1", "io2":
                    if iops, exists := sc.Parameters["iops"]; exists {
                        fmt.Printf("  IOPS: %s\n", iops)
                    }
                }
            }
        }
    }
    
    return nil
}

func (sm *StorageMonitor) OptimizeStorageClass() {
    // 推荐的存储类配置
    recommendations := map[string]string{
        "high-performance": `
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: high-performance-ssd
provisioner: ebs.csi.aws.com
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
parameters:
  type: gp3
  iops: "16000"
  throughput: "1000"
  encrypted: "true"
`,
        "cost-optimized": `
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: cost-optimized
provisioner: ebs.csi.aws.com
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
parameters:
  type: gp3
  iops: "3000"
  throughput: "125"
  encrypted: "true"
`,
    }
    
    for name, config := range recommendations {
        fmt.Printf("Recommended %s storage class:\n%s\n", name, config)
    }
}
```

---

## 8. Kubernetes使用中常见问题

### 8.1 Pod启动问题

#### 镜像拉取失败
```bash
# 诊断脚本
#!/bin/bash

# 检查Pod状态
echo "=== Pod状态检查 ==="
kubectl get pods -o wide

# 检查Pod详细信息
echo "\n=== Pod详细信息 ==="
kubectl describe pod $1

# 检查镜像拉取策略
echo "\n=== 镜像拉取策略 ==="
kubectl get pod $1 -o jsonpath='{.spec.containers[*].imagePullPolicy}'

# 检查镜像仓库密钥
echo "\n=== 镜像仓库密钥 ==="
kubectl get secrets --field-selector type=kubernetes.io/dockerconfigjson

# 检查节点镜像
echo "\n=== 节点镜像列表 ==="
kubectl get nodes -o jsonpath='{.items[*].status.images[*].names}'
```

#### 资源不足问题
```go
// 资源监控和诊断
package main

import (
    "context"
    "fmt"
    "sort"
    
    "k8s.io/api/core/v1"
    metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
    "k8s.io/client-go/kubernetes"
    "k8s.io/metrics/pkg/client/clientset/versioned"
)

type ResourceDiagnostic struct {
    clientset        *kubernetes.Clientset
    metricsClientset *versioned.Clientset
}

func (rd *ResourceDiagnostic) DiagnoseResourceIssues() error {
    // 检查节点资源
    nodes, err := rd.clientset.CoreV1().Nodes().List(context.TODO(), metav1.ListOptions{})
    if err != nil {
        return err
    }
    
    fmt.Println("=== 节点资源状态 ===")
    for _, node := range nodes.Items {
        fmt.Printf("节点: %s\n", node.Name)
        
        // 检查节点条件
        for _, condition := range node.Status.Conditions {
            if condition.Status == v1.ConditionTrue {
                switch condition.Type {
                case v1.NodeMemoryPressure:
                    fmt.Printf("  ⚠️  内存压力: %s\n", condition.Message)
                case v1.NodeDiskPressure:
                    fmt.Printf("  ⚠️  磁盘压力: %s\n", condition.Message)
                case v1.NodePIDPressure:
                    fmt.Printf("  ⚠️  PID压力: %s\n", condition.Message)
                }
            }
        }
        
        // 显示资源容量
        capacity := node.Status.Capacity
        allocatable := node.Status.Allocatable
        
        fmt.Printf("  CPU: %s (可分配: %s)\n", 
            capacity[v1.ResourceCPU], allocatable[v1.ResourceCPU])
        fmt.Printf("  内存: %s (可分配: %s)\n", 
            capacity[v1.ResourceMemory], allocatable[v1.ResourceMemory])
        fmt.Printf("  存储: %s (可分配: %s)\n", 
            capacity[v1.ResourceStorage], allocatable[v1.ResourceStorage])
        
        fmt.Println()
    }
    
    return nil
}

func (rd *ResourceDiagnostic) FindResourceHungryPods() error {
    pods, err := rd.clientset.CoreV1().Pods("").List(context.TODO(), metav1.ListOptions{})
    if err != nil {
        return err
    }
    
    type PodResource struct {
        Name      string
        Namespace string
        CPUReq    string
        MemReq    string
        CPULimit  string
        MemLimit  string
    }
    
    var podResources []PodResource
    
    for _, pod := range pods.Items {
        if pod.Status.Phase != v1.PodRunning {
            continue
        }
        
        var totalCPUReq, totalMemReq, totalCPULimit, totalMemLimit int64
        
        for _, container := range pod.Spec.Containers {
            if req := container.Resources.Requests; req != nil {
                if cpu := req[v1.ResourceCPU]; !cpu.IsZero() {
                    totalCPUReq += cpu.MilliValue()
                }
                if mem := req[v1.ResourceMemory]; !mem.IsZero() {
                    totalMemReq += mem.Value()
                }
            }
            
            if limit := container.Resources.Limits; limit != nil {
                if cpu := limit[v1.ResourceCPU]; !cpu.IsZero() {
                    totalCPULimit += cpu.MilliValue()
                }
                if mem := limit[v1.ResourceMemory]; !mem.IsZero() {
                    totalMemLimit += mem.Value()
                }
            }
        }
        
        podResources = append(podResources, PodResource{
            Name:      pod.Name,
            Namespace: pod.Namespace,
            CPUReq:    fmt.Sprintf("%dm", totalCPUReq),
            MemReq:    fmt.Sprintf("%dMi", totalMemReq/(1024*1024)),
            CPULimit:  fmt.Sprintf("%dm", totalCPULimit),
            MemLimit:  fmt.Sprintf("%dMi", totalMemLimit/(1024*1024)),
        })
    }
    
    // 按CPU请求排序
    sort.Slice(podResources, func(i, j int) bool {
        return podResources[i].CPUReq > podResources[j].CPUReq
    })
    
    fmt.Println("=== 资源消耗最大的Pod (按CPU请求排序) ===")
    fmt.Printf("%-30s %-15s %-10s %-10s %-10s %-10s\n", 
        "Pod名称", "命名空间", "CPU请求", "内存请求", "CPU限制", "内存限制")
    fmt.Println(strings.Repeat("-", 90))
    
    for i, pod := range podResources {
        if i >= 10 { // 只显示前10个
            break
        }
        fmt.Printf("%-30s %-15s %-10s %-10s %-10s %-10s\n", 
            pod.Name, pod.Namespace, pod.CPUReq, pod.MemReq, pod.CPULimit, pod.MemLimit)
    }
    
    return nil
}
```

### 8.2 网络连接问题

#### 服务发现问题诊断
```bash
#!/bin/bash

# 网络诊断脚本
function diagnose_network() {
    local pod_name=$1
    local namespace=${2:-default}
    
    echo "=== 网络诊断: $pod_name ==="
    
    # 检查Pod网络配置
    echo "1. Pod网络配置:"
    kubectl get pod $pod_name -n $namespace -o jsonpath='{.status.podIP}'
    echo
    
    # 检查DNS配置
    echo "2. DNS配置:"
    kubectl exec $pod_name -n $namespace -- cat /etc/resolv.conf
    
    # 测试DNS解析
    echo "3. DNS解析测试:"
    kubectl exec $pod_name -n $namespace -- nslookup kubernetes.default.svc.cluster.local
    
    # 检查服务端点
    echo "4. 服务端点:"
    kubectl get endpoints -n $namespace
    
    # 测试服务连接
    echo "5. 服务连接测试:"
    kubectl exec $pod_name -n $namespace -- wget -qO- --timeout=5 http://kubernetes.default.svc.cluster.local
    
    # 检查网络策略
    echo "6. 网络策略:"
    kubectl get networkpolicies -n $namespace
}

# 使用示例
# diagnose_network "my-pod" "default"
```

#### CNI问题排查
```yaml
# CNI诊断DaemonSet
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: network-diagnostic
  namespace: kube-system
spec:
  selector:
    matchLabels:
      app: network-diagnostic
  template:
    metadata:
      labels:
        app: network-diagnostic
    spec:
      hostNetwork: true
      hostPID: true
      containers:
      - name: diagnostic
        image: nicolaka/netshoot:latest
        command: ["/bin/bash"]
        args: ["-c", "while true; do sleep 3600; done"]
        securityContext:
          privileged: true
        volumeMounts:
        - name: host-root
          mountPath: /host
          readOnly: true
      volumes:
      - name: host-root
        hostPath:
          path: /
      tolerations:
      - operator: Exists
```

### 8.3 存储问题

#### PVC挂载失败
```go
// 存储问题诊断
package main

import (
    "context"
    "fmt"
    "strings"
    
    "k8s.io/api/core/v1"
    metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
    "k8s.io/client-go/kubernetes"
)

type StorageDiagnostic struct {
    clientset *kubernetes.Clientset
}

func (sd *StorageDiagnostic) DiagnosePVCIssues(namespace string) error {
    pvcs, err := sd.clientset.CoreV1().PersistentVolumeClaims(namespace).List(
        context.TODO(), metav1.ListOptions{},
    )
    if err != nil {
        return err
    }
    
    fmt.Println("=== PVC状态诊断 ===")
    for _, pvc := range pvcs.Items {
        fmt.Printf("PVC: %s\n", pvc.Name)
        fmt.Printf("  状态: %s\n", pvc.Status.Phase)
        
        switch pvc.Status.Phase {
        case v1.ClaimPending:
            fmt.Println("  ⚠️  PVC处于Pending状态，可能原因:")
            
            // 检查存储类
            if pvc.Spec.StorageClassName != nil {
                sc, err := sd.clientset.StorageV1().StorageClasses().Get(
                    context.TODO(), *pvc.Spec.StorageClassName, metav1.GetOptions{},
                )
                if err != nil {
                    fmt.Printf("    - 存储类 '%s' 不存在\n", *pvc.Spec.StorageClassName)
                } else {
                    fmt.Printf("    - 存储类: %s (Provisioner: %s)\n", 
                        sc.Name, sc.Provisioner)
                }
            } else {
                fmt.Println("    - 未指定存储类")
            }
            
            // 检查可用PV
            pvs, err := sd.clientset.CoreV1().PersistentVolumes().List(
                context.TODO(), metav1.ListOptions{},
            )
            if err == nil {
                availablePVs := 0
                for _, pv := range pvs.Items {
                    if pv.Status.Phase == v1.VolumeAvailable {
                        availablePVs++
                    }
                }
                fmt.Printf("    - 可用PV数量: %d\n", availablePVs)
            }
            
        case v1.ClaimBound:
            fmt.Printf("  ✅ PVC已绑定到PV: %s\n", pvc.Spec.VolumeName)
            
        case v1.ClaimLost:
            fmt.Println("  ❌ PVC丢失，需要重新创建")
        }
        
        // 检查事件
        events, err := sd.clientset.CoreV1().Events(namespace).List(
            context.TODO(), metav1.ListOptions{
                FieldSelector: fmt.Sprintf("involvedObject.name=%s", pvc.Name),
            },
        )
        if err == nil && len(events.Items) > 0 {
            fmt.Println("  最近事件:")
            for _, event := range events.Items {
                if strings.Contains(event.Message, "error") || 
                   strings.Contains(event.Message, "failed") {
                    fmt.Printf("    - %s: %s\n", event.Reason, event.Message)
                }
            }
        }
        
        fmt.Println()
    }
    
    return nil
}

func (sd *StorageDiagnostic) CheckStorageClasses() error {
    scs, err := sd.clientset.StorageV1().StorageClasses().List(
        context.TODO(), metav1.ListOptions{},
    )
    if err != nil {
        return err
    }
    
    fmt.Println("=== 存储类配置 ===")
    for _, sc := range scs.Items {
        fmt.Printf("存储类: %s\n", sc.Name)
        fmt.Printf("  Provisioner: %s\n", sc.Provisioner)
        fmt.Printf("  卷绑定模式: %s\n", *sc.VolumeBindingMode)
        fmt.Printf("  允许卷扩展: %t\n", *sc.AllowVolumeExpansion)
        
        if len(sc.Parameters) > 0 {
            fmt.Println("  参数:")
            for key, value := range sc.Parameters {
                fmt.Printf("    %s: %s\n", key, value)
            }
        }
        
        fmt.Println()
    }
    
    return nil
}
```

### 8.4 性能问题

#### 集群性能监控
```bash
#!/bin/bash

# 集群性能监控脚本
function monitor_cluster_performance() {
    echo "=== Kubernetes集群性能监控 ==="
    
    # 检查节点资源使用率
    echo "1. 节点资源使用率:"
    kubectl top nodes
    echo
    
    # 检查Pod资源使用率
    echo "2. Pod资源使用率 (Top 10):"
    kubectl top pods --all-namespaces --sort-by=cpu | head -11
    echo
    
    # 检查集群事件
    echo "3. 最近集群事件:"
    kubectl get events --sort-by='.lastTimestamp' | tail -10
    echo
    
    # 检查不健康的Pod
    echo "4. 不健康的Pod:"
    kubectl get pods --all-namespaces --field-selector=status.phase!=Running
    echo
    
    # 检查节点状态
    echo "5. 节点状态:"
    kubectl get nodes -o custom-columns=NAME:.metadata.name,STATUS:.status.conditions[-1].type,READY:.status.conditions[-1].status
    echo
    
    # 检查系统Pod状态
    echo "6. 系统Pod状态:"
    kubectl get pods -n kube-system --field-selector=status.phase!=Running
    echo
}

# 性能调优建议
function performance_recommendations() {
    echo "=== 性能调优建议 ==="
    
    # 检查资源请求和限制
    echo "1. 检查资源配置:"
    kubectl get pods --all-namespaces -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[*].resources}{"\n"}{end}' | \
    grep -v 'map\[\]' | head -10
    echo
    
    # 检查HPA配置
    echo "2. HPA配置:"
    kubectl get hpa --all-namespaces
    echo
    
    # 检查PDB配置
    echo "3. PodDisruptionBudget配置:"
    kubectl get pdb --all-namespaces
    echo
}

# 执行监控
monitor_cluster_performance
performance_recommendations
```

---

## 9. Kubernetes最佳实践

### 9.1 安全最佳实践

#### RBAC配置
```yaml
# 最小权限原则的RBAC配置
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: production
  name: pod-reader
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "watch", "list"]
- apiGroups: [""]
  resources: ["pods/log"]
  verbs: ["get"]

---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: read-pods
  namespace: production
subjects:
- kind: User
  name: developer
  apiGroup: rbac.authorization.k8s.io
- kind: ServiceAccount
  name: monitoring-sa
  namespace: production
roleRef:
  kind: Role
  name: pod-reader
  apiGroup: rbac.authorization.k8s.io

---
# 集群级别权限
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: node-reader
rules:
- apiGroups: [""]
  resources: ["nodes"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["metrics.k8s.io"]
  resources: ["nodes", "pods"]
  verbs: ["get", "list"]

---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: node-reader-binding
subjects:
- kind: ServiceAccount
  name: monitoring-sa
  namespace: monitoring
roleRef:
  kind: ClusterRole
  name: node-reader
  apiGroup: rbac.authorization.k8s.io
```

#### Pod安全策略
```yaml
# Pod安全标准
apiVersion: v1
kind: Pod
metadata:
  name: secure-pod
  namespace: production
spec:
  securityContext:
    # 运行为非root用户
    runAsNonRoot: true
    runAsUser: 1000
    runAsGroup: 1000
    # 设置文件系统组
    fsGroup: 1000
    # 禁用特权升级
    allowPrivilegeEscalation: false
    # 设置seccomp配置
    seccompProfile:
      type: RuntimeDefault
  containers:
  - name: app
    image: app:latest
    securityContext:
      # 容器级别安全配置
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      runAsNonRoot: true
      runAsUser: 1000
      capabilities:
        drop:
        - ALL
        add:
        - NET_BIND_SERVICE
    resources:
      requests:
        memory: "128Mi"
        cpu: "100m"
      limits:
        memory: "256Mi"
        cpu: "200m"
    volumeMounts:
    - name: tmp
      mountPath: /tmp
    - name: cache
      mountPath: /app/cache
  volumes:
  - name: tmp
    emptyDir: {}
  - name: cache
    emptyDir: {}
```

### 9.2 资源管理最佳实践

#### 资源配额和限制
```yaml
# 命名空间资源配额
apiVersion: v1
kind: ResourceQuota
metadata:
  name: production-quota
  namespace: production
spec:
  hard:
    # 计算资源
    requests.cpu: "10"
    requests.memory: 20Gi
    limits.cpu: "20"
    limits.memory: 40Gi
    
    # 存储资源
    requests.storage: 100Gi
    persistentvolumeclaims: "10"
    
    # 对象数量
    pods: "50"
    services: "10"
    secrets: "20"
    configmaps: "20"
    
    # 服务类型限制
    services.loadbalancers: "2"
    services.nodeports: "5"

---
# 限制范围
apiVersion: v1
kind: LimitRange
metadata:
  name: production-limits
  namespace: production
spec:
  limits:
  # Pod限制
  - type: Pod
    max:
      cpu: "4"
      memory: 8Gi
    min:
      cpu: 100m
      memory: 128Mi
  
  # 容器限制
  - type: Container
    default:
      cpu: 200m
      memory: 256Mi
    defaultRequest:
      cpu: 100m
      memory: 128Mi
    max:
      cpu: "2"
      memory: 4Gi
    min:
      cpu: 50m
      memory: 64Mi
  
  # PVC限制
  - type: PersistentVolumeClaim
    max:
      storage: 50Gi
    min:
      storage: 1Gi
```

### 9.3 监控和日志最佳实践

#### Prometheus监控配置
```yaml
# ServiceMonitor配置
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: app-metrics
  namespace: monitoring
  labels:
    app: prometheus
spec:
  selector:
    matchLabels:
      app: my-app
  endpoints:
  - port: metrics
    interval: 30s
    path: /metrics
    honorLabels: true
  namespaceSelector:
    matchNames:
    - production
    - staging

---
# PrometheusRule配置
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: app-alerts
  namespace: monitoring
  labels:
    app: prometheus
spec:
  groups:
  - name: app.rules
    rules:
    - alert: HighCPUUsage
      expr: rate(container_cpu_usage_seconds_total[5m]) > 0.8
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "High CPU usage detected"
        description: "Pod {{ $labels.pod }} in namespace {{ $labels.namespace }} has high CPU usage"
    
    - alert: HighMemoryUsage
      expr: container_memory_usage_bytes / container_spec_memory_limit_bytes > 0.9
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "High memory usage detected"
        description: "Pod {{ $labels.pod }} in namespace {{ $labels.namespace }} has high memory usage"
    
    - alert: PodCrashLooping
      expr: rate(kube_pod_container_status_restarts_total[15m]) > 0
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Pod is crash looping"
        description: "Pod {{ $labels.pod }} in namespace {{ $labels.namespace }} is crash looping"
```

### 9.4 部署最佳实践

#### 滚动更新策略
```yaml
# 优化的部署配置
apiVersion: apps/v1
kind: Deployment
metadata:
  name: production-app
  namespace: production
  labels:
    app: production-app
    version: v1.0.0
spec:
  replicas: 5
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 1
  selector:
    matchLabels:
      app: production-app
  template:
    metadata:
      labels:
        app: production-app
        version: v1.0.0
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8080"
        prometheus.io/path: "/metrics"
    spec:
      # 优雅关闭
      terminationGracePeriodSeconds: 30
      
      # 反亲和性确保Pod分布
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchExpressions:
                - key: app
                  operator: In
                  values:
                  - production-app
              topologyKey: kubernetes.io/hostname
      
      containers:
      - name: app
        image: production-app:v1.0.0
        ports:
        - containerPort: 8080
          name: http
        - containerPort: 8081
          name: metrics
        
        # 健康检查
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3
        
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 3
        
        # 启动探针
        startupProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 30
        
        # 资源配置
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        
        # 环境变量
        env:
        - name: POD_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: POD_NAMESPACE
          valueFrom:
            fieldRef:
              fieldPath: metadata.namespace
        - name: NODE_NAME
          valueFrom:
            fieldRef:
              fieldPath: spec.nodeName
        
        # 配置和密钥
        envFrom:
        - configMapRef:
            name: app-config
        - secretRef:
            name: app-secrets
        
        # 卷挂载
        volumeMounts:
        - name: config
          mountPath: /etc/config
          readOnly: true
        - name: logs
          mountPath: /var/log
      
      volumes:
      - name: config
        configMap:
          name: app-config
      - name: logs
        emptyDir: {}

---
# PodDisruptionBudget
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: production-app-pdb
  namespace: production
spec:
  minAvailable: 3
  selector:
    matchLabels:
      app: production-app
```

---

## 10. 总结

### 10.1 Kubernetes核心要点

1. **架构理解**
   - 掌握控制平面和工作节点的职责分工
   - 理解声明式API和控制器模式
   - 熟悉各核心组件的交互关系

2. **资源管理**
   - 合理设置资源请求和限制
   - 使用HPA/VPA实现自动扩缩容
   - 配置适当的调度策略和亲和性

3. **网络和存储**
   - 理解Service和Ingress的网络模型
   - 掌握PV/PVC的存储抽象
   - 配置合适的网络策略和存储类

4. **安全性**
   - 实施最小权限的RBAC策略
   - 配置Pod安全标准
   - 使用网络策略限制流量

5. **可观测性**
   - 部署完整的监控和日志系统
   - 配置合适的告警规则
   - 实现分布式链路追踪

### 10.2 生产环境建议

1. **高可用性**
   - 多主节点部署
   - 跨可用区分布
   - 定期备份etcd

2. **性能优化**
   - 节点资源规划
   - 网络性能调优
   - 存储性能优化

3. **运维自动化**
   - CI/CD流水线集成
   - 自动化部署和回滚
   - 基础设施即代码

### 10.3 发展趋势

1. **云原生生态**
   - Service Mesh集成
   - Serverless计算
   - 边缘计算支持

2. **AI/ML工作负载**
   - GPU资源调度
   - 机器学习流水线
   - 模型服务化

3. **安全增强**
   - 零信任网络
   - 运行时安全
   - 供应链安全

Kubernetes作为容器编排的事实标准，其生态系统仍在快速发展。掌握其核心概念和最佳实践，对于构建现代化的云原生应用至关重要。

---

## 11. 高级特性与扩展

### 11.1 自定义资源定义（CRD）

#### CRD定义
```yaml
# 自定义资源定义
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: webapps.example.com
spec:
  group: example.com
  versions:
  - name: v1
    served: true
    storage: true
    schema:
      openAPIV3Schema:
        type: object
        properties:
          spec:
            type: object
            properties:
              image:
                type: string
              replicas:
                type: integer
                minimum: 1
                maximum: 100
              port:
                type: integer
                minimum: 1
                maximum: 65535
              resources:
                type: object
                properties:
                  requests:
                    type: object
                    properties:
                      cpu:
                        type: string
                      memory:
                        type: string
                  limits:
                    type: object
                    properties:
                      cpu:
                        type: string
                      memory:
                        type: string
            required:
            - image
            - replicas
            - port
          status:
            type: object
            properties:
              phase:
                type: string
                enum: ["Pending", "Running", "Failed"]
              replicas:
                type: integer
              readyReplicas:
                type: integer
              conditions:
                type: array
                items:
                  type: object
                  properties:
                    type:
                      type: string
                    status:
                      type: string
                    lastTransitionTime:
                      type: string
                      format: date-time
                    reason:
                      type: string
                    message:
                      type: string
  scope: Namespaced
  names:
    plural: webapps
    singular: webapp
    kind: WebApp
    shortNames:
    - wa
```

#### Operator开发
```go
// Operator控制器实现
package main

import (
    "context"
    "fmt"
    "time"
    
    appsv1 "k8s.io/api/apps/v1"
    corev1 "k8s.io/api/core/v1"
    "k8s.io/apimachinery/pkg/api/errors"
    metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
    "k8s.io/apimachinery/pkg/runtime"
    "k8s.io/apimachinery/pkg/util/intstr"
    ctrl "sigs.k8s.io/controller-runtime"
    "sigs.k8s.io/controller-runtime/pkg/client"
    "sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
    "sigs.k8s.io/controller-runtime/pkg/log"
)

// WebAppReconciler reconciles a WebApp object
type WebAppReconciler struct {
    client.Client
    Scheme *runtime.Scheme
}

// WebApp represents the custom resource
type WebApp struct {
    metav1.TypeMeta   `json:",inline"`
    metav1.ObjectMeta `json:"metadata,omitempty"`
    Spec              WebAppSpec   `json:"spec,omitempty"`
    Status            WebAppStatus `json:"status,omitempty"`
}

type WebAppSpec struct {
    Image     string                      `json:"image"`
    Replicas  int32                       `json:"replicas"`
    Port      int32                       `json:"port"`
    Resources corev1.ResourceRequirements `json:"resources,omitempty"`
}

type WebAppStatus struct {
    Phase         string             `json:"phase,omitempty"`
    Replicas      int32              `json:"replicas,omitempty"`
    ReadyReplicas int32              `json:"readyReplicas,omitempty"`
    Conditions    []WebAppCondition  `json:"conditions,omitempty"`
}

type WebAppCondition struct {
    Type               string      `json:"type"`
    Status             string      `json:"status"`
    LastTransitionTime metav1.Time `json:"lastTransitionTime"`
    Reason             string      `json:"reason,omitempty"`
    Message            string      `json:"message,omitempty"`
}

// Reconcile implements the reconciliation logic
func (r *WebAppReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
    logger := log.FromContext(ctx)
    
    // Fetch the WebApp instance
    webapp := &WebApp{}
    err := r.Get(ctx, req.NamespacedName, webapp)
    if err != nil {
        if errors.IsNotFound(err) {
            logger.Info("WebApp resource not found. Ignoring since object must be deleted")
            return ctrl.Result{}, nil
        }
        logger.Error(err, "Failed to get WebApp")
        return ctrl.Result{}, err
    }
    
    // Create or update Deployment
    deployment := r.deploymentForWebApp(webapp)
    if err := controllerutil.SetControllerReference(webapp, deployment, r.Scheme); err != nil {
        return ctrl.Result{}, err
    }
    
    found := &appsv1.Deployment{}
    err = r.Get(ctx, client.ObjectKey{Name: deployment.Name, Namespace: deployment.Namespace}, found)
    if err != nil && errors.IsNotFound(err) {
        logger.Info("Creating a new Deployment", "Deployment.Namespace", deployment.Namespace, "Deployment.Name", deployment.Name)
        err = r.Create(ctx, deployment)
        if err != nil {
            logger.Error(err, "Failed to create new Deployment", "Deployment.Namespace", deployment.Namespace, "Deployment.Name", deployment.Name)
            return ctrl.Result{}, err
        }
        return ctrl.Result{Requeue: true}, nil
    } else if err != nil {
        logger.Error(err, "Failed to get Deployment")
        return ctrl.Result{}, err
    }
    
    // Update Deployment if needed
    if !r.deploymentEqual(found, deployment) {
        logger.Info("Updating Deployment", "Deployment.Namespace", deployment.Namespace, "Deployment.Name", deployment.Name)
        found.Spec = deployment.Spec
        err = r.Update(ctx, found)
        if err != nil {
            logger.Error(err, "Failed to update Deployment", "Deployment.Namespace", deployment.Namespace, "Deployment.Name", deployment.Name)
            return ctrl.Result{}, err
        }
        return ctrl.Result{Requeue: true}, nil
    }
    
    // Create or update Service
    service := r.serviceForWebApp(webapp)
    if err := controllerutil.SetControllerReference(webapp, service, r.Scheme); err != nil {
        return ctrl.Result{}, err
    }
    
    foundService := &corev1.Service{}
    err = r.Get(ctx, client.ObjectKey{Name: service.Name, Namespace: service.Namespace}, foundService)
    if err != nil && errors.IsNotFound(err) {
        logger.Info("Creating a new Service", "Service.Namespace", service.Namespace, "Service.Name", service.Name)
        err = r.Create(ctx, service)
        if err != nil {
            logger.Error(err, "Failed to create new Service", "Service.Namespace", service.Namespace, "Service.Name", service.Name)
            return ctrl.Result{}, err
        }
    } else if err != nil {
        logger.Error(err, "Failed to get Service")
        return ctrl.Result{}, err
    }
    
    // Update status
    webapp.Status.Replicas = found.Status.Replicas
    webapp.Status.ReadyReplicas = found.Status.ReadyReplicas
    
    if found.Status.ReadyReplicas == webapp.Spec.Replicas {
        webapp.Status.Phase = "Running"
    } else {
        webapp.Status.Phase = "Pending"
    }
    
    // Update conditions
    condition := WebAppCondition{
        Type:               "Ready",
        Status:             "False",
        LastTransitionTime: metav1.Now(),
        Reason:             "DeploymentNotReady",
        Message:            "Deployment is not ready",
    }
    
    if webapp.Status.Phase == "Running" {
        condition.Status = "True"
        condition.Reason = "DeploymentReady"
        condition.Message = "Deployment is ready"
    }
    
    webapp.Status.Conditions = []WebAppCondition{condition}
    
    err = r.Status().Update(ctx, webapp)
    if err != nil {
        logger.Error(err, "Failed to update WebApp status")
        return ctrl.Result{}, err
    }
    
    return ctrl.Result{RequeueAfter: time.Minute * 5}, nil
}

func (r *WebAppReconciler) deploymentForWebApp(webapp *WebApp) *appsv1.Deployment {
    labels := map[string]string{
        "app":        webapp.Name,
        "managed-by": "webapp-operator",
    }
    
    return &appsv1.Deployment{
        ObjectMeta: metav1.ObjectMeta{
            Name:      webapp.Name,
            Namespace: webapp.Namespace,
            Labels:    labels,
        },
        Spec: appsv1.DeploymentSpec{
            Replicas: &webapp.Spec.Replicas,
            Selector: &metav1.LabelSelector{
                MatchLabels: labels,
            },
            Template: corev1.PodTemplateSpec{
                ObjectMeta: metav1.ObjectMeta{
                    Labels: labels,
                },
                Spec: corev1.PodSpec{
                    Containers: []corev1.Container{
                        {
                            Name:  "webapp",
                            Image: webapp.Spec.Image,
                            Ports: []corev1.ContainerPort{
                                {
                                    ContainerPort: webapp.Spec.Port,
                                    Name:          "http",
                                },
                            },
                            Resources: webapp.Spec.Resources,
                            LivenessProbe: &corev1.Probe{
                                ProbeHandler: corev1.ProbeHandler{
                                    HTTPGet: &corev1.HTTPGetAction{
                                        Path: "/health",
                                        Port: intstr.FromInt(int(webapp.Spec.Port)),
                                    },
                                },
                                InitialDelaySeconds: 30,
                                PeriodSeconds:       10,
                            },
                            ReadinessProbe: &corev1.Probe{
                                ProbeHandler: corev1.ProbeHandler{
                                    HTTPGet: &corev1.HTTPGetAction{
                                        Path: "/ready",
                                        Port: intstr.FromInt(int(webapp.Spec.Port)),
                                    },
                                },
                                InitialDelaySeconds: 5,
                                PeriodSeconds:       5,
                            },
                        },
                    },
                },
            },
        },
    }
}

func (r *WebAppReconciler) serviceForWebApp(webapp *WebApp) *corev1.Service {
    labels := map[string]string{
        "app":        webapp.Name,
        "managed-by": "webapp-operator",
    }
    
    return &corev1.Service{
        ObjectMeta: metav1.ObjectMeta{
            Name:      webapp.Name + "-service",
            Namespace: webapp.Namespace,
            Labels:    labels,
        },
        Spec: corev1.ServiceSpec{
            Selector: labels,
            Ports: []corev1.ServicePort{
                {
                    Port:       80,
                    TargetPort: intstr.FromInt(int(webapp.Spec.Port)),
                    Protocol:   corev1.ProtocolTCP,
                },
            },
            Type: corev1.ServiceTypeClusterIP,
        },
    }
}

func (r *WebAppReconciler) deploymentEqual(found, desired *appsv1.Deployment) bool {
    return *found.Spec.Replicas == *desired.Spec.Replicas &&
           found.Spec.Template.Spec.Containers[0].Image == desired.Spec.Template.Spec.Containers[0].Image
}

// SetupWithManager sets up the controller with the Manager
func (r *WebAppReconciler) SetupWithManager(mgr ctrl.Manager) error {
    return ctrl.NewControllerManagedBy(mgr).
        For(&WebApp{}).
        Owns(&appsv1.Deployment{}).
        Owns(&corev1.Service{}).
        Complete(r)
}
```

### 11.2 准入控制器（Admission Controllers）

#### Validating Admission Webhook
```go
// 验证准入控制器
package main

import (
    "context"
    "encoding/json"
    "fmt"
    "net/http"
    "strings"
    
    admissionv1 "k8s.io/api/admission/v1"
    corev1 "k8s.io/api/core/v1"
    metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
    "k8s.io/apimachinery/pkg/runtime"
)

type WebhookServer struct {
    server *http.Server
}

type patchOperation struct {
    Op    string      `json:"op"`
    Path  string      `json:"path"`
    Value interface{} `json:"value,omitempty"`
}

func (ws *WebhookServer) validate(w http.ResponseWriter, r *http.Request) {
    var body []byte
    if r.Body != nil {
        if data, err := io.ReadAll(r.Body); err == nil {
            body = data
        }
    }
    
    var admissionResponse *admissionv1.AdmissionResponse
    ar := admissionv1.AdmissionReview{}
    if err := json.Unmarshal(body, &ar); err != nil {
        fmt.Printf("Could not unmarshal raw object: %v", err)
        admissionResponse = &admissionv1.AdmissionResponse{
            Result: &metav1.Status{
                Message: err.Error(),
            },
        }
    } else {
        admissionResponse = ws.validatePod(ar.Request)
    }
    
    admissionReview := admissionv1.AdmissionReview{}
    if admissionResponse != nil {
        admissionReview.Response = admissionResponse
        if ar.Request != nil {
            admissionReview.Response.UID = ar.Request.UID
        }
    }
    
    respBytes, _ := json.Marshal(admissionReview)
    w.Header().Set("Content-Type", "application/json")
    w.Write(respBytes)
}

func (ws *WebhookServer) validatePod(req *admissionv1.AdmissionRequest) *admissionv1.AdmissionResponse {
    var pod corev1.Pod
    if err := json.Unmarshal(req.Object.Raw, &pod); err != nil {
        return &admissionv1.AdmissionResponse{
            Result: &metav1.Status{
                Message: err.Error(),
            },
        }
    }
    
    allowed := true
    message := ""
    
    // 验证规则1: 禁止使用latest标签
    for _, container := range pod.Spec.Containers {
        if strings.HasSuffix(container.Image, ":latest") {
            allowed = false
            message = "Images with 'latest' tag are not allowed"
            break
        }
    }
    
    // 验证规则2: 必须设置资源限制
    if allowed {
        for _, container := range pod.Spec.Containers {
            if container.Resources.Limits == nil || 
               container.Resources.Limits.Cpu().IsZero() || 
               container.Resources.Limits.Memory().IsZero() {
                allowed = false
                message = "All containers must have CPU and memory limits"
                break
            }
        }
    }
    
    // 验证规则3: 生产环境必须设置非root用户
    if allowed && pod.Namespace == "production" {
        if pod.Spec.SecurityContext == nil || 
           pod.Spec.SecurityContext.RunAsNonRoot == nil || 
           !*pod.Spec.SecurityContext.RunAsNonRoot {
            allowed = false
            message = "Pods in production namespace must run as non-root user"
        }
    }
    
    return &admissionv1.AdmissionResponse{
        UID:     req.UID,
        Allowed: allowed,
        Result: &metav1.Status{
            Message: message,
        },
    }
}

func (ws *WebhookServer) mutate(w http.ResponseWriter, r *http.Request) {
    var body []byte
    if r.Body != nil {
        if data, err := io.ReadAll(r.Body); err == nil {
            body = data
        }
    }
    
    var admissionResponse *admissionv1.AdmissionResponse
    ar := admissionv1.AdmissionReview{}
    if err := json.Unmarshal(body, &ar); err != nil {
        admissionResponse = &admissionv1.AdmissionResponse{
            Result: &metav1.Status{
                Message: err.Error(),
            },
        }
    } else {
        admissionResponse = ws.mutatePod(ar.Request)
    }
    
    admissionReview := admissionv1.AdmissionReview{}
    if admissionResponse != nil {
        admissionReview.Response = admissionResponse
        if ar.Request != nil {
            admissionReview.Response.UID = ar.Request.UID
        }
    }
    
    respBytes, _ := json.Marshal(admissionReview)
    w.Header().Set("Content-Type", "application/json")
    w.Write(respBytes)
}

func (ws *WebhookServer) mutatePod(req *admissionv1.AdmissionRequest) *admissionv1.AdmissionResponse {
    var pod corev1.Pod
    if err := json.Unmarshal(req.Object.Raw, &pod); err != nil {
        return &admissionv1.AdmissionResponse{
            Result: &metav1.Status{
                Message: err.Error(),
            },
        }
    }
    
    var patches []patchOperation
    
    // 添加标签
    if pod.Labels == nil {
        patches = append(patches, patchOperation{
            Op:    "add",
            Path:  "/metadata/labels",
            Value: map[string]string{},
        })
    }
    
    patches = append(patches, patchOperation{
        Op:    "add",
        Path:  "/metadata/labels/injected-by",
        Value: "admission-webhook",
    })
    
    // 添加sidecar容器
    if pod.Namespace == "production" {
        sidecar := corev1.Container{
            Name:  "logging-sidecar",
            Image: "fluent/fluent-bit:latest",
            VolumeMounts: []corev1.VolumeMount{
                {
                    Name:      "varlog",
                    MountPath: "/var/log",
                },
            },
        }
        
        patches = append(patches, patchOperation{
            Op:    "add",
            Path:  "/spec/containers/-",
            Value: sidecar,
        })
        
        // 添加共享卷
        if len(pod.Spec.Volumes) == 0 {
            patches = append(patches, patchOperation{
                Op:    "add",
                Path:  "/spec/volumes",
                Value: []corev1.Volume{},
            })
        }
        
        volume := corev1.Volume{
            Name: "varlog",
            VolumeSource: corev1.VolumeSource{
                EmptyDir: &corev1.EmptyDirVolumeSource{},
            },
        }
        
        patches = append(patches, patchOperation{
            Op:    "add",
            Path:  "/spec/volumes/-",
            Value: volume,
        })
    }
    
    patchBytes, _ := json.Marshal(patches)
    
    return &admissionv1.AdmissionResponse{
        UID:     req.UID,
        Allowed: true,
        Patch:   patchBytes,
        PatchType: func() *admissionv1.PatchType {
            pt := admissionv1.PatchTypeJSONPatch
            return &pt
        }(),
    }
}
```

### 11.3 网络策略高级配置

#### 微分段网络策略
```yaml
# 默认拒绝所有流量
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress

---
# 允许DNS查询
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - to: []
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53

---
# Web层网络策略
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: web-tier-policy
  namespace: production
spec:
  podSelector:
    matchLabels:
      tier: web
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # 允许来自Ingress控制器的流量
  - from:
    - namespaceSelector:
        matchLabels:
          name: ingress-nginx
    ports:
    - protocol: TCP
      port: 8080
  # 允许来自监控系统的流量
  - from:
    - namespaceSelector:
        matchLabels:
          name: monitoring
    ports:
    - protocol: TCP
      port: 8080
  egress:
  # 允许访问应用层
  - to:
    - podSelector:
        matchLabels:
          tier: app
    ports:
    - protocol: TCP
      port: 8080
  # 允许访问外部API
  - to: []
    ports:
    - protocol: TCP
      port: 443

---
# 应用层网络策略
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: app-tier-policy
  namespace: production
spec:
  podSelector:
    matchLabels:
      tier: app
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # 只允许来自Web层的流量
  - from:
    - podSelector:
        matchLabels:
          tier: web
    ports:
    - protocol: TCP
      port: 8080
  egress:
  # 允许访问数据库层
  - to:
    - podSelector:
        matchLabels:
          tier: database
    ports:
    - protocol: TCP
      port: 3306
  # 允许访问缓存层
  - to:
    - podSelector:
        matchLabels:
          tier: cache
    ports:
    - protocol: TCP
      port: 6379

---
# 数据库层网络策略
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: database-tier-policy
  namespace: production
spec:
  podSelector:
    matchLabels:
      tier: database
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # 只允许来自应用层的流量
  - from:
    - podSelector:
        matchLabels:
          tier: app
    ports:
    - protocol: TCP
      port: 3306
  # 允许来自备份作业的流量
  - from:
    - podSelector:
        matchLabels:
          app: backup-job
    ports:
    - protocol: TCP
      port: 3306
  egress:
  # 数据库通常不需要出站连接，除了集群内通信
  - to:
    - podSelector:
        matchLabels:
          tier: database
    ports:
    - protocol: TCP
      port: 3306
```

### 11.4 高级调度策略

#### 多调度器配置
```yaml
# 自定义调度器配置
apiVersion: v1
kind: ConfigMap
metadata:
  name: custom-scheduler-config
  namespace: kube-system
data:
  config.yaml: |
    apiVersion: kubescheduler.config.k8s.io/v1beta3
    kind: KubeSchedulerConfiguration
    profiles:
    - schedulerName: custom-scheduler
      plugins:
        score:
          enabled:
          - name: NodeResourcesFit
          - name: NodeAffinity
          - name: PodTopologySpread
          - name: InterPodAffinity
          - name: NodeResourcesBalancedAllocation
        filter:
          enabled:
          - name: NodeUnschedulable
          - name: NodeName
          - name: TaintToleration
          - name: NodeAffinity
          - name: NodePorts
          - name: NodeResourcesFit
          - name: VolumeRestrictions
          - name: EBSLimits
          - name: GCEPDLimits
          - name: NodeVolumeLimits
          - name: AzureDiskLimits
          - name: VolumeBinding
          - name: VolumeZone
          - name: PodTopologySpread
          - name: InterPodAffinity
      pluginConfig:
      - name: NodeResourcesFit
        args:
          scoringStrategy:
            type: MostAllocated
            resources:
            - name: cpu
              weight: 1
            - name: memory
              weight: 1
            - name: nvidia.com/gpu
              weight: 5
      - name: PodTopologySpread
        args:
          defaultConstraints:
          - maxSkew: 1
            topologyKey: topology.kubernetes.io/zone
            whenUnsatisfiable: DoNotSchedule
          - maxSkew: 1
            topologyKey: kubernetes.io/hostname
            whenUnsatisfiable: ScheduleAnyway

---
# 自定义调度器部署
apiVersion: apps/v1
kind: Deployment
metadata:
  name: custom-scheduler
  namespace: kube-system
spec:
  replicas: 1
  selector:
    matchLabels:
      app: custom-scheduler
  template:
    metadata:
      labels:
        app: custom-scheduler
    spec:
      serviceAccountName: custom-scheduler
      containers:
      - name: kube-scheduler
        image: k8s.gcr.io/kube-scheduler:v1.28.0
        command:
        - kube-scheduler
        - --config=/etc/kubernetes/scheduler-config.yaml
        - --v=2
        volumeMounts:
        - name: config
          mountPath: /etc/kubernetes
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 200m
            memory: 256Mi
      volumes:
      - name: config
        configMap:
          name: custom-scheduler-config
```

#### GPU节点调度
```yaml
# GPU工作负载调度
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gpu-workload
  namespace: ml-training
spec:
  replicas: 2
  selector:
    matchLabels:
      app: gpu-workload
  template:
    metadata:
      labels:
        app: gpu-workload
    spec:
      schedulerName: custom-scheduler
      nodeSelector:
        accelerator: nvidia-tesla-v100
      tolerations:
      - key: nvidia.com/gpu
        operator: Exists
        effect: NoSchedule
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
            - matchExpressions:
              - key: node.kubernetes.io/instance-type
                operator: In
                values:
                - p3.2xlarge
                - p3.8xlarge
                - p3.16xlarge
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchExpressions:
                - key: app
                  operator: In
                  values:
                  - gpu-workload
              topologyKey: kubernetes.io/hostname
      containers:
      - name: training
        image: tensorflow/tensorflow:latest-gpu
        resources:
          requests:
            nvidia.com/gpu: 1
            cpu: "4"
            memory: 16Gi
          limits:
            nvidia.com/gpu: 1
            cpu: "8"
            memory: 32Gi
        env:
        - name: CUDA_VISIBLE_DEVICES
          value: "0"
        volumeMounts:
        - name: training-data
          mountPath: /data
        - name: model-output
          mountPath: /output
      volumes:
      - name: training-data
        persistentVolumeClaim:
          claimName: training-data-pvc
      - name: model-output
        persistentVolumeClaim:
          claimName: model-output-pvc
```

### 11.5 多集群管理

#### 集群联邦配置
```yaml
# 集群注册
apiVersion: cluster.x-k8s.io/v1beta1
kind: Cluster
metadata:
  name: production-us-west
  namespace: fleet-system
spec:
  clusterNetwork:
    pods:
      cidrBlocks:
      - 10.244.0.0/16
    services:
      cidrBlocks:
      - 10.96.0.0/12
  infrastructureRef:
    apiVersion: infrastructure.cluster.x-k8s.io/v1beta1
    kind: AWSCluster
    name: production-us-west
  controlPlaneRef:
    apiVersion: controlplane.cluster.x-k8s.io/v1beta1
    kind: KubeadmControlPlane
    name: production-us-west-control-plane

---
# 跨集群服务发现
apiVersion: networking.istio.io/v1beta1
kind: ServiceEntry
metadata:
  name: cross-cluster-service
  namespace: production
spec:
  hosts:
  - api.production-eu-west.local
  ports:
  - number: 80
    name: http
    protocol: HTTP
  - number: 443
    name: https
    protocol: HTTPS
  location: MESH_EXTERNAL
  resolution: DNS
  endpoints:
  - address: api-gateway.production.svc.cluster.local
    network: production-eu-west
    ports:
      http: 80
      https: 443
```

### 11.6 边缘计算支持

#### 边缘节点配置
```yaml
# 边缘节点标记
apiVersion: v1
kind: Node
metadata:
  name: edge-node-1
  labels:
    node-role.kubernetes.io/edge: ""
    topology.kubernetes.io/zone: edge-zone-1
    topology.kubernetes.io/region: edge-region
    node.kubernetes.io/instance-type: edge
spec:
  taints:
  - key: node-role.kubernetes.io/edge
    value: ""
    effect: NoSchedule

---
# 边缘工作负载
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: edge-agent
  namespace: edge-system
spec:
  selector:
    matchLabels:
      app: edge-agent
  template:
    metadata:
      labels:
        app: edge-agent
    spec:
      nodeSelector:
        node-role.kubernetes.io/edge: ""
      tolerations:
      - key: node-role.kubernetes.io/edge
        operator: Exists
        effect: NoSchedule
      hostNetwork: true
      hostPID: true
      containers:
      - name: edge-agent
        image: edge-agent:latest
        securityContext:
          privileged: true
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 500m
            memory: 512Mi
        volumeMounts:
        - name: host-root
          mountPath: /host
          readOnly: true
        - name: device
          mountPath: /dev
        env:
        - name: NODE_NAME
          valueFrom:
            fieldRef:
              fieldPath: spec.nodeName
      volumes:
      - name: host-root
        hostPath:
          path: /
      - name: device
        hostPath:
          path: /dev
```

通过这些高级特性和扩展，Kubernetes能够满足更复杂的企业级需求，包括自定义资源管理、准入控制、网络安全、高级调度、多集群管理和边缘计算等场景。这些功能使Kubernetes成为真正的企业级容器编排平台。

---

## 12. Kubernetes面试题精选

### 12.1 基础概念面试题

#### Q1: 请解释Kubernetes中Pod、Service、Deployment的关系和作用？

**答案：**
- **Pod**: Kubernetes中最小的部署单元，包含一个或多个容器，共享网络和存储
- **Deployment**: 管理Pod的副本数量，提供滚动更新、回滚等功能
- **Service**: 为Pod提供稳定的网络访问入口，实现负载均衡和服务发现

**关系图：**
```
Deployment → ReplicaSet → Pod(s) ← Service
```

#### Q2: Kubernetes的核心组件有哪些？各自的作用是什么？

**答案：**

**控制平面组件：**
- **kube-apiserver**: API网关，所有操作的入口
- **etcd**: 分布式键值存储，保存集群状态
- **kube-scheduler**: 调度器，决定Pod运行在哪个节点
- **kube-controller-manager**: 控制器管理器，维护集群期望状态
- **cloud-controller-manager**: 云控制器，与云平台集成

**节点组件：**
- **kubelet**: 节点代理，管理Pod生命周期
- **kube-proxy**: 网络代理，实现Service的负载均衡
- **容器运行时**: 如Docker、containerd等

#### Q3: 什么是Kubernetes的声明式API？与命令式API有什么区别？

**答案：**

**声明式API：**
- 描述期望的最终状态
- 系统自动计算如何达到该状态
- 幂等性，多次执行结果相同
- 例如：`kubectl apply -f deployment.yaml`

**命令式API：**
- 描述具体的操作步骤
- 需要明确指定每个动作
- 非幂等性，重复执行可能出错
- 例如：`kubectl create deployment nginx --image=nginx`

### 12.2 网络与存储面试题

#### Q4: Kubernetes中有哪些网络模型？请解释CNI的作用？

**答案：**

**网络模型要求：**
1. 所有Pod可以直接通信，无需NAT
2. 所有节点可以与所有Pod通信
3. Pod看到的自己的IP与其他Pod看到的相同

**CNI (Container Network Interface)：**
- 定义容器网络接口标准
- 插件化架构，支持多种网络方案
- 常见实现：Flannel、Calico、Weave、Cilium

**网络类型：**
```yaml
# ClusterIP - 集群内部访问
apiVersion: v1
kind: Service
metadata:
  name: internal-service
spec:
  type: ClusterIP
  selector:
    app: backend
  ports:
  - port: 80
    targetPort: 8080

---
# NodePort - 节点端口访问
apiVersion: v1
kind: Service
metadata:
  name: nodeport-service
spec:
  type: NodePort
  selector:
    app: web
  ports:
  - port: 80
    targetPort: 8080
    nodePort: 30080

---
# LoadBalancer - 云负载均衡器
apiVersion: v1
kind: Service
metadata:
  name: loadbalancer-service
spec:
  type: LoadBalancer
  selector:
    app: frontend
  ports:
  - port: 80
    targetPort: 8080
```

#### Q5: 请解释PV、PVC、StorageClass的关系和使用场景？

**答案：**

**关系图：**
```
StorageClass → PV ← PVC ← Pod
```

**详细说明：**
- **PV (PersistentVolume)**: 集群级别的存储资源
- **PVC (PersistentVolumeClaim)**: 用户对存储的请求
- **StorageClass**: 存储类，定义存储的类型和参数

**使用场景示例：**
```yaml
# StorageClass定义
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fast-ssd
provisioner: kubernetes.io/aws-ebs
parameters:
  type: gp3
  iops: "3000"
  throughput: "125"
allowVolumeExpansion: true
volumeBindingMode: WaitForFirstConsumer

---
# PVC请求
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: database-pvc
spec:
  accessModes:
  - ReadWriteOnce
  storageClassName: fast-ssd
  resources:
    requests:
      storage: 100Gi

---
# Pod使用PVC
apiVersion: v1
kind: Pod
metadata:
  name: database-pod
spec:
  containers:
  - name: mysql
    image: mysql:8.0
    volumeMounts:
    - name: data
      mountPath: /var/lib/mysql
  volumes:
  - name: data
    persistentVolumeClaim:
      claimName: database-pvc
```

### 12.3 调度与资源管理面试题

#### Q6: Kubernetes的调度过程是怎样的？如何影响Pod的调度？

**答案：**

**调度过程：**
1. **过滤阶段 (Filtering)**: 筛选出可调度的节点
2. **打分阶段 (Scoring)**: 对可调度节点进行评分
3. **绑定阶段 (Binding)**: 将Pod绑定到最高分节点

**影响调度的因素：**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: scheduled-pod
spec:
  # 节点选择器
  nodeSelector:
    disktype: ssd
  
  # 节点亲和性
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: kubernetes.io/arch
            operator: In
            values:
            - amd64
    
    # Pod亲和性
    podAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          labelSelector:
            matchExpressions:
            - key: app
              operator: In
              values:
              - cache
          topologyKey: kubernetes.io/hostname
  
  # 容忍度
  tolerations:
  - key: "node-role.kubernetes.io/master"
    operator: "Exists"
    effect: "NoSchedule"
  
  # 资源请求和限制
  containers:
  - name: app
    image: nginx
    resources:
      requests:
        cpu: 100m
        memory: 128Mi
      limits:
        cpu: 500m
        memory: 512Mi
```

#### Q7: 什么是QoS类别？Kubernetes如何根据QoS进行资源管理？

**答案：**

**QoS类别：**

1. **Guaranteed (保证级别)**
   - 所有容器都设置了CPU和内存的requests和limits
   - requests等于limits
   - 最高优先级，最后被驱逐

2. **Burstable (突发级别)**
   - 至少一个容器设置了CPU或内存的requests
   - 不满足Guaranteed条件
   - 中等优先级

3. **BestEffort (尽力而为级别)**
   - 没有设置任何requests和limits
   - 最低优先级，最先被驱逐

**示例配置：**
```yaml
# Guaranteed QoS
apiVersion: v1
kind: Pod
metadata:
  name: guaranteed-pod
spec:
  containers:
  - name: app
    image: nginx
    resources:
      requests:
        cpu: "1"
        memory: "1Gi"
      limits:
        cpu: "1"
        memory: "1Gi"

---
# Burstable QoS
apiVersion: v1
kind: Pod
metadata:
  name: burstable-pod
spec:
  containers:
  - name: app
    image: nginx
    resources:
      requests:
        cpu: "0.5"
        memory: "512Mi"
      limits:
        cpu: "2"
        memory: "2Gi"

---
# BestEffort QoS
apiVersion: v1
kind: Pod
metadata:
  name: besteffort-pod
spec:
  containers:
  - name: app
    image: nginx
    # 没有设置resources
```

### 12.4 高可用与故障处理面试题

#### Q8: 如何实现Kubernetes集群的高可用？

**答案：**

**控制平面高可用：**
1. **多Master节点**: 至少3个奇数个Master节点
2. **etcd集群**: 独立部署或与Master共存
3. **负载均衡器**: 为API Server提供统一入口

**架构示例：**
```yaml
# HAProxy配置示例
global
    log stdout local0
    chroot /var/lib/haproxy
    stats socket /run/haproxy/admin.sock mode 660
    stats timeout 30s
    user haproxy
    group haproxy
    daemon

defaults
    mode http
    log global
    option httplog
    option dontlognull
    option log-health-checks
    option forwardfor
    option httpchk GET /healthz
    timeout connect 10s
    timeout client 86400s
    timeout server 86400s
    timeout tunnel 86400s

frontend kubernetes-apiserver
    bind *:6443
    mode tcp
    option tcplog
    default_backend kubernetes-apiserver

backend kubernetes-apiserver
    mode tcp
    option tcplog
    option tcp-check
    balance roundrobin
    default-server inter 10s downinter 5s rise 2 fall 2 slowstart 60s maxconn 250 maxqueue 256 weight 100
    server apiserver1 10.0.1.10:6443 check
    server apiserver2 10.0.1.11:6443 check
    server apiserver3 10.0.1.12:6443 check
```

**应用高可用：**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ha-application
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1
      maxSurge: 1
  selector:
    matchLabels:
      app: ha-app
  template:
    metadata:
      labels:
        app: ha-app
    spec:
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchExpressions:
                - key: app
                  operator: In
                  values:
                  - ha-app
              topologyKey: kubernetes.io/hostname
      containers:
      - name: app
        image: myapp:v1.0
        ports:
        - containerPort: 8080
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 500m
            memory: 512Mi

---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: ha-app-pdb
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: ha-app
```

#### Q9: Pod一直处于Pending状态，如何排查？

**答案：**

**排查步骤：**

1. **查看Pod详细信息**
```bash
kubectl describe pod <pod-name> -n <namespace>
```

2. **检查常见原因**

**资源不足：**
```bash
# 查看节点资源使用情况
kubectl top nodes
kubectl describe nodes

# 查看资源配额
kubectl describe resourcequota -n <namespace>
```

**调度约束：**
```bash
# 检查节点标签
kubectl get nodes --show-labels

# 检查污点
kubectl describe node <node-name> | grep Taints
```

**存储问题：**
```bash
# 检查PVC状态
kubectl get pvc -n <namespace>
kubectl describe pvc <pvc-name> -n <namespace>

# 检查StorageClass
kubectl get storageclass
```

**网络问题：**
```bash
# 检查网络策略
kubectl get networkpolicy -n <namespace>

# 检查DNS
kubectl run test-pod --image=busybox --rm -it -- nslookup kubernetes.default
```

**诊断脚本：**
```bash
#!/bin/bash
# pod-debug.sh

POD_NAME=$1
NAMESPACE=${2:-default}

echo "=== Pod Information ==="
kubectl get pod $POD_NAME -n $NAMESPACE -o wide

echo "\n=== Pod Events ==="
kubectl describe pod $POD_NAME -n $NAMESPACE | grep -A 20 "Events:"

echo "\n=== Node Resources ==="
kubectl top nodes

echo "\n=== Namespace Resource Quota ==="
kubectl describe resourcequota -n $NAMESPACE

echo "\n=== PVC Status ==="
kubectl get pvc -n $NAMESPACE

echo "\n=== Scheduler Logs ==="
kubectl logs -n kube-system -l component=kube-scheduler --tail=50
```

### 12.5 安全与权限面试题

#### Q10: 请解释Kubernetes的RBAC机制？

**答案：**

**RBAC组件：**
- **Role/ClusterRole**: 定义权限集合
- **RoleBinding/ClusterRoleBinding**: 将权限绑定到用户/组/ServiceAccount
- **ServiceAccount**: 为Pod提供身份标识

**示例配置：**
```yaml
# 创建ServiceAccount
apiVersion: v1
kind: ServiceAccount
metadata:
  name: pod-reader
  namespace: default

---
# 创建Role
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: default
  name: pod-reader-role
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "watch", "list"]
- apiGroups: [""]
  resources: ["pods/log"]
  verbs: ["get"]

---
# 创建RoleBinding
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: read-pods
  namespace: default
subjects:
- kind: ServiceAccount
  name: pod-reader
  namespace: default
roleRef:
  kind: Role
  name: pod-reader-role
  apiGroup: rbac.authorization.k8s.io

---
# ClusterRole示例
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: node-reader
rules:
- apiGroups: [""]
  resources: ["nodes"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["metrics.k8s.io"]
  resources: ["nodes", "pods"]
  verbs: ["get", "list"]

---
# ClusterRoleBinding示例
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: node-reader-binding
subjects:
- kind: User
  name: monitoring-user
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: node-reader
  apiGroup: rbac.authorization.k8s.io
```

**权限验证：**
```bash
# 检查用户权限
kubectl auth can-i get pods --as=system:serviceaccount:default:pod-reader

# 检查所有权限
kubectl auth can-i --list --as=system:serviceaccount:default:pod-reader
```

### 12.6 性能优化面试题

#### Q11: 如何优化Kubernetes集群的性能？

**答案：**

**节点级优化：**
```yaml
# 节点配置优化
apiVersion: v1
kind: Node
metadata:
  name: optimized-node
  labels:
    node.kubernetes.io/instance-type: c5.4xlarge
    topology.kubernetes.io/zone: us-west-2a
spec:
  # 设置节点容量
  capacity:
    cpu: "16"
    memory: "32Gi"
    ephemeral-storage: "100Gi"
    pods: "110"
```

**kubelet优化配置：**
```yaml
# kubelet-config.yaml
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
# 提高并发数
maxPods: 110
podsPerCore: 10

# 资源预留
systemReserved:
  cpu: "1"
  memory: "2Gi"
  ephemeral-storage: "10Gi"
kubeReserved:
  cpu: "1"
  memory: "2Gi"
  ephemeral-storage: "10Gi"

# 垃圾回收
imageGCHighThresholdPercent: 85
imageGCLowThresholdPercent: 80
containerLogMaxSize: "10Mi"
containerLogMaxFiles: 5

# 网络优化
hairpinMode: "hairpin-veth"
networkPlugin: "cni"

# 性能调优
cpuManagerPolicy: "static"
topologyManagerPolicy: "single-numa-node"
memoryManagerPolicy: "Static"
```

**应用级优化：**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: optimized-app
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0
      maxSurge: 1
  selector:
    matchLabels:
      app: optimized-app
  template:
    metadata:
      labels:
        app: optimized-app
    spec:
      # 优化调度
      priorityClassName: high-priority
      nodeSelector:
        node-type: compute-optimized
      
      # 容器优化
      containers:
      - name: app
        image: myapp:optimized
        
        # 资源精确配置
        resources:
          requests:
            cpu: "2"
            memory: "4Gi"
          limits:
            cpu: "4"
            memory: "8Gi"
        
        # 健康检查优化
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 30
          timeoutSeconds: 5
          failureThreshold: 3
        
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 10
          timeoutSeconds: 3
          failureThreshold: 2
        
        # 环境变量优化
        env:
        - name: GOMAXPROCS
          valueFrom:
            resourceFieldRef:
              resource: limits.cpu
        - name: GOMEMLIMIT
          valueFrom:
            resourceFieldRef:
              resource: limits.memory
        
        # 安全上下文
        securityContext:
          runAsNonRoot: true
          runAsUser: 1000
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop:
            - ALL
      
      # DNS优化
      dnsPolicy: ClusterFirst
      dnsConfig:
        options:
        - name: ndots
          value: "2"
        - name: edns0

---
# 优先级类
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: high-priority
value: 1000
globalDefault: false
description: "High priority class for critical applications"
```

**监控和指标：**
```yaml
# 性能监控配置
apiVersion: v1
kind: ServiceMonitor
metadata:
  name: app-metrics
spec:
  selector:
    matchLabels:
      app: optimized-app
  endpoints:
  - port: metrics
    interval: 30s
    path: /metrics
```

### 12.7 故障排查面试题

#### Q12: 如何排查Kubernetes集群中的网络问题？

**答案：**

**网络排查工具包：**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: network-debug
spec:
  containers:
  - name: debug
    image: nicolaka/netshoot
    command: ["sleep", "3600"]
    securityContext:
      capabilities:
        add: ["NET_ADMIN"]
  hostNetwork: true
  dnsPolicy: ClusterFirstWithHostNet
```

**排查步骤脚本：**
```bash
#!/bin/bash
# network-debug.sh

echo "=== 1. 检查Pod网络连通性 ==="
kubectl exec -it network-debug -- ping -c 3 8.8.8.8

echo "\n=== 2. 检查DNS解析 ==="
kubectl exec -it network-debug -- nslookup kubernetes.default.svc.cluster.local
kubectl exec -it network-debug -- nslookup google.com

echo "\n=== 3. 检查Service连通性 ==="
kubectl get svc -A
kubectl exec -it network-debug -- curl -I kubernetes.default.svc.cluster.local

echo "\n=== 4. 检查网络策略 ==="
kubectl get networkpolicy -A

echo "\n=== 5. 检查CNI状态 ==="
kubectl get pods -n kube-system | grep -E "(calico|flannel|weave|cilium)"

echo "\n=== 6. 检查kube-proxy ==="
kubectl get pods -n kube-system | grep kube-proxy
kubectl logs -n kube-system -l k8s-app=kube-proxy --tail=20

echo "\n=== 7. 检查iptables规则 ==="
kubectl exec -it network-debug -- iptables -t nat -L | grep -A 5 KUBE-SERVICES

echo "\n=== 8. 检查路由表 ==="
kubectl exec -it network-debug -- ip route

echo "\n=== 9. 检查网络接口 ==="
kubectl exec -it network-debug -- ip addr show
```

**常见网络问题解决方案：**

1. **Pod无法访问外网**
```bash
# 检查NAT规则
iptables -t nat -L POSTROUTING

# 检查DNS配置
cat /etc/resolv.conf

# 检查网络策略
kubectl get networkpolicy -A
```

2. **Service无法访问**
```bash
# 检查Endpoints
kubectl get endpoints <service-name>

# 检查kube-proxy模式
kubectl logs -n kube-system -l k8s-app=kube-proxy | grep "Using"

# 检查iptables规则
iptables -t nat -L | grep <service-name>
```

3. **跨节点Pod通信失败**
```bash
# 检查CNI配置
cat /etc/cni/net.d/*

# 检查路由
ip route show

# 检查防火墙
systemctl status firewalld
ufw status
```

这些面试题涵盖了Kubernetes的核心概念、实际操作和故障排查，是面试中经常遇到的问题。通过这些题目的学习和实践，可以全面掌握Kubernetes的知识体系。
```