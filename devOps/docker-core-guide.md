# Docker容器技术核心指南

## 目录
1. [Docker核心概念](#docker核心概念)
2. [Docker架构设计](#docker架构设计)
3. [Docker核心原理](#docker核心原理)
4. [Docker核心组件](#docker核心组件)
5. [Docker核心能力](#docker核心能力)
6. [Docker使用场景](#docker使用场景)
7. [Docker优化方案](#docker优化方案)
8. [Docker常见问题](#docker常见问题)
9. [Docker最佳实践](#docker最佳实践)
10. [Docker生产环境部署](#docker生产环境部署)

---

## Docker核心概念

### 1.1 容器化技术基础

#### 什么是容器
容器是一种轻量级、可移植的封装技术，它将应用程序及其依赖项打包在一起，确保应用在任何环境中都能一致运行。

```bash
# 容器与虚拟机的对比
# 虚拟机：硬件 -> 宿主机OS -> Hypervisor -> 客户机OS -> 应用
# 容器：硬件 -> 宿主机OS -> Docker Engine -> 容器 -> 应用
```

#### 容器化的优势
- **轻量级**：共享宿主机内核，资源占用少
- **快速启动**：秒级启动时间
- **一致性**：开发、测试、生产环境一致
- **可移植性**：跨平台运行
- **可扩展性**：易于水平扩展

### 1.2 Docker基本概念

#### 镜像（Image）
```dockerfile
# Dockerfile示例
FROM golang:1.19-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o main .

FROM alpine:latest
RUN apk --no-cache add ca-certificates
WORKDIR /root/
COPY --from=builder /app/main .
EXPOSE 8080
CMD ["./main"]
```

#### 容器（Container）
```bash
# 创建并运行容器
docker run -d --name myapp -p 8080:8080 myapp:latest

# 查看运行中的容器
docker ps

# 进入容器
docker exec -it myapp /bin/sh

# 查看容器日志
docker logs -f myapp
```

#### 仓库（Repository）
```bash
# 推送镜像到仓库
docker tag myapp:latest registry.company.com/myapp:v1.0.0
docker push registry.company.com/myapp:v1.0.0

# 从仓库拉取镜像
docker pull registry.company.com/myapp:v1.0.0
```

---

## Docker架构设计

### 2.1 Docker整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Client                           │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐          │
│  │ docker build│ │ docker pull │ │ docker run  │          │
│  └─────────────┘ └─────────────┘ └─────────────┘          │
└─────────────────────┬───────────────────────────────────────┘
                      │ REST API
┌─────────────────────▼───────────────────────────────────────┐
│                 Docker Daemon                              │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐          │
│  │   Images    │ │ Containers  │ │  Networks   │          │
│  └─────────────┘ └─────────────┘ └─────────────┘          │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐          │
│  │   Volumes   │ │   Plugins   │ │   Registry  │          │
│  └─────────────┘ └─────────────┘ └─────────────┘          │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                 Container Runtime                          │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐          │
│  │   runC      │ │ containerd  │ │    OCI      │          │
│  └─────────────┘ └─────────────┘ └─────────────┘          │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 核心组件关系

#### Docker Client
```bash
# Docker客户端命令示例
docker version          # 查看版本信息
docker info            # 查看系统信息
docker system df       # 查看磁盘使用情况
docker system prune    # 清理未使用的资源
```

#### Docker Daemon
```json
{
  "hosts": ["unix:///var/run/docker.sock", "tcp://0.0.0.0:2376"],
  "tls": true,
  "tlscert": "/etc/docker/server-cert.pem",
  "tlskey": "/etc/docker/server-key.pem",
  "tlsverify": true,
  "tlscacert": "/etc/docker/ca.pem",
  "storage-driver": "overlay2",
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "registry-mirrors": [
    "https://mirror.ccs.tencentyun.com"
  ]
}
```

---

## Docker核心原理

### 3.1 Linux内核技术

#### Namespace（命名空间）
```go
// Go语言演示Namespace概念
package main

import (
    "fmt"
    "os"
    "syscall"
)

// PID Namespace示例
func demonstratePIDNamespace() {
    fmt.Printf("当前进程PID: %d\n", os.Getpid())
    fmt.Printf("父进程PID: %d\n", os.Getppid())
    
    // 在容器中，PID通常从1开始
    // 宿主机看到的是真实PID，容器内看到的是虚拟PID
}

// Network Namespace示例
func demonstrateNetworkNamespace() {
    // 每个容器都有独立的网络栈
    // 包括网络接口、路由表、防火墙规则等
    fmt.Println("容器拥有独立的网络命名空间")
}

// Mount Namespace示例
func demonstrateMountNamespace() {
    // 每个容器都有独立的文件系统视图
    fmt.Println("容器拥有独立的挂载命名空间")
}
```

#### CGroups（控制组）
```bash
# 查看容器的CGroups限制
docker run -d --name test-cgroup \
  --memory=512m \
  --cpus=1.5 \
  --memory-swap=1g \
  nginx:alpine

# 查看CGroups信息
cat /sys/fs/cgroup/memory/docker/$(docker inspect test-cgroup --format '{{.Id}}')/memory.limit_in_bytes
cat /sys/fs/cgroup/cpu/docker/$(docker inspect test-cgroup --format '{{.Id}}')/cpu.cfs_quota_us
```

#### Union File System
```bash
# 查看镜像层信息
docker history nginx:alpine

# 查看容器文件系统层
docker inspect nginx:alpine | jq '.[0].RootFS'

# OverlayFS示例
# /var/lib/docker/overlay2/
# ├── l/          # 短链接
# ├── <layer-id>/
# │   ├── diff/   # 该层的文件变更
# │   ├── link    # 指向l/目录的短链接
# │   ├── lower   # 下层引用
# │   └── work/   # OverlayFS工作目录
```

### 3.2 容器运行时

#### OCI规范
```json
{
  "ociVersion": "1.0.0",
  "process": {
    "terminal": false,
    "user": {
      "uid": 0,
      "gid": 0
    },
    "args": [
      "/bin/sh",
      "-c",
      "echo hello world"
    ],
    "env": [
      "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
      "TERM=xterm"
    ],
    "cwd": "/",
    "capabilities": {
      "bounding": [
        "CAP_AUDIT_WRITE",
        "CAP_KILL",
        "CAP_NET_BIND_SERVICE"
      ],
      "effective": [
        "CAP_AUDIT_WRITE",
        "CAP_KILL",
        "CAP_NET_BIND_SERVICE"
      ],
      "inheritable": [
        "CAP_AUDIT_WRITE",
        "CAP_KILL",
        "CAP_NET_BIND_SERVICE"
      ],
      "permitted": [
        "CAP_AUDIT_WRITE",
        "CAP_KILL",
        "CAP_NET_BIND_SERVICE"
      ]
    },
    "rlimits": [
      {
        "type": "RLIMIT_NOFILE",
        "hard": 1024,
        "soft": 1024
      }
    ]
  },
  "root": {
    "path": "rootfs",
    "readonly": true
  },
  "hostname": "container",
  "mounts": [
    {
      "destination": "/proc",
      "type": "proc",
      "source": "proc"
    },
    {
      "destination": "/dev",
      "type": "tmpfs",
      "source": "tmpfs",
      "options": [
        "nosuid",
        "strictatime",
        "mode=755",
        "size=65536k"
      ]
    }
  ],
  "linux": {
    "namespaces": [
      {
        "type": "pid"
      },
      {
        "type": "network"
      },
      {
        "type": "ipc"
      },
      {
        "type": "uts"
      },
      {
        "type": "mount"
      }
    ],
    "resources": {
      "memory": {
        "limit": 536870912
      },
      "cpu": {
        "quota": 150000,
        "period": 100000
      }
    }
  }
}
```

---

## Docker核心组件

### 4.1 Docker Engine

#### containerd
```bash
# containerd命令行工具
ctr --namespace=moby containers list
ctr --namespace=moby images list
ctr --namespace=moby snapshots list

# containerd配置
# /etc/containerd/config.toml
[plugins."io.containerd.grpc.v1.cri"]
  sandbox_image = "k8s.gcr.io/pause:3.7"
  
[plugins."io.containerd.grpc.v1.cri".containerd]
  snapshotter = "overlayfs"
  default_runtime_name = "runc"
  
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc]
  runtime_type = "io.containerd.runc.v2"
  
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
  SystemdCgroup = true
```

#### runC
```bash
# 使用runC直接运行容器
# 1. 创建bundle目录
mkdir /tmp/mycontainer
cd /tmp/mycontainer

# 2. 创建rootfs
mkdir rootfs
docker export $(docker create busybox) | tar -C rootfs -xvf -

# 3. 生成config.json
runc spec

# 4. 运行容器
runc run mycontainer
```

### 4.2 网络组件

#### Docker网络驱动
```bash
# 查看网络驱动
docker network ls

# 创建自定义网络
docker network create --driver bridge \
  --subnet=172.20.0.0/16 \
  --ip-range=172.20.240.0/20 \
  --gateway=172.20.0.1 \
  mynetwork

# 创建overlay网络（Swarm模式）
docker network create --driver overlay \
  --subnet=10.0.9.0/24 \
  --attachable \
  my-overlay-network
```

#### 网络配置示例
```yaml
# docker-compose.yml网络配置
version: '3.8'
services:
  web:
    image: nginx:alpine
    networks:
      - frontend
      - backend
    ports:
      - "80:80"
  
  api:
    image: myapi:latest
    networks:
      - backend
      - database
    environment:
      - DB_HOST=db
  
  db:
    image: postgres:13
    networks:
      - database
    environment:
      - POSTGRES_DB=myapp
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=password

networks:
  frontend:
    driver: bridge
  backend:
    driver: bridge
  database:
    driver: bridge
    internal: true  # 内部网络，不能访问外网
```

### 4.3 存储组件

#### 存储驱动
```bash
# 查看存储驱动信息
docker info | grep "Storage Driver"

# OverlayFS配置
# /etc/docker/daemon.json
{
  "storage-driver": "overlay2",
  "storage-opts": [
    "overlay2.override_kernel_check=true"
  ]
}
```

#### 数据卷管理
```bash
# 创建命名卷
docker volume create --driver local \
  --opt type=nfs \
  --opt o=addr=192.168.1.100,rw \
  --opt device=:/path/to/dir \
  nfs-volume

# 使用数据卷
docker run -d --name myapp \
  -v nfs-volume:/app/data \
  -v /host/config:/app/config:ro \
  myapp:latest

# 备份数据卷
docker run --rm \
  -v myapp-data:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/backup.tar.gz -C /data .

# 恢复数据卷
docker run --rm \
  -v myapp-data:/data \
  -v $(pwd):/backup \
  alpine tar xzf /backup/backup.tar.gz -C /data
```

---

## Docker核心能力

### 5.1 镜像管理能力

#### 多阶段构建
```dockerfile
# 多阶段构建优化镜像大小
FROM node:16-alpine AS frontend-builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
COPY . .
RUN npm run build

FROM golang:1.19-alpine AS backend-builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o main .

FROM alpine:latest
RUN apk --no-cache add ca-certificates tzdata
WORKDIR /root/

# 复制前端构建产物
COPY --from=frontend-builder /app/dist ./static

# 复制后端二进制文件
COPY --from=backend-builder /app/main .

# 设置时区
ENV TZ=Asia/Shanghai

EXPOSE 8080
CMD ["./main"]
```

#### 镜像优化技术
```dockerfile
# 镜像优化最佳实践
FROM alpine:3.16

# 使用非root用户
RUN addgroup -g 1001 -S appgroup && \
    adduser -u 1001 -S appuser -G appgroup

# 合并RUN指令减少层数
RUN apk add --no-cache \
    ca-certificates \
    tzdata \
    curl \
    && rm -rf /var/cache/apk/*

# 使用.dockerignore
# .dockerignore内容：
# .git
# .gitignore
# README.md
# Dockerfile
# .dockerignore
# node_modules
# npm-debug.log

WORKDIR /app

# 先复制依赖文件，利用Docker缓存
COPY go.mod go.sum ./
RUN go mod download

# 再复制源代码
COPY . .
RUN go build -o main .

# 切换到非root用户
USER appuser

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1

CMD ["./main"]
```

### 5.2 容器编排能力

#### Docker Compose
```yaml
# docker-compose.yml - 完整的微服务编排
version: '3.8'

services:
  # 反向代理
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
    depends_on:
      - api
      - web
    networks:
      - frontend
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  # 前端应用
  web:
    build:
      context: ./frontend
      dockerfile: Dockerfile
      args:
        - NODE_ENV=production
    environment:
      - API_URL=http://api:8080
    networks:
      - frontend
    restart: unless-stopped
    deploy:
      replicas: 2
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
        reservations:
          cpus: '0.25'
          memory: 256M

  # API服务
  api:
    build:
      context: ./backend
      dockerfile: Dockerfile
    environment:
      - DB_HOST=postgres
      - DB_PORT=5432
      - DB_NAME=myapp
      - DB_USER=postgres
      - DB_PASSWORD_FILE=/run/secrets/db_password
      - REDIS_URL=redis://redis:6379
      - JWT_SECRET_FILE=/run/secrets/jwt_secret
    secrets:
      - db_password
      - jwt_secret
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - frontend
      - backend
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  # 数据库
  postgres:
    image: postgres:13-alpine
    environment:
      - POSTGRES_DB=myapp
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD_FILE=/run/secrets/db_password
    secrets:
      - db_password
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    networks:
      - backend
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5

  # 缓存
  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes --requirepass "$${REDIS_PASSWORD}"
    environment:
      - REDIS_PASSWORD_FILE=/run/secrets/redis_password
    secrets:
      - redis_password
    volumes:
      - redis_data:/data
    networks:
      - backend
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 3

  # 监控
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/etc/prometheus/console_libraries'
      - '--web.console.templates=/etc/prometheus/consoles'
      - '--storage.tsdb.retention.time=200h'
      - '--web.enable-lifecycle'
    networks:
      - monitoring
    restart: unless-stopped

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD_FILE=/run/secrets/grafana_password
    secrets:
      - grafana_password
    volumes:
      - grafana_data:/var/lib/grafana
    networks:
      - monitoring
    restart: unless-stopped

volumes:
  postgres_data:
    driver: local
  redis_data:
    driver: local
  prometheus_data:
    driver: local
  grafana_data:
    driver: local

networks:
  frontend:
    driver: bridge
  backend:
    driver: bridge
    internal: true
  monitoring:
    driver: bridge

secrets:
  db_password:
    file: ./secrets/db_password.txt
  redis_password:
    file: ./secrets/redis_password.txt
  jwt_secret:
    file: ./secrets/jwt_secret.txt
  grafana_password:
    file: ./secrets/grafana_password.txt
```

### 5.3 安全能力

#### 容器安全配置
```bash
# 安全运行容器
docker run -d \
  --name secure-app \
  --user 1001:1001 \
  --read-only \
  --tmpfs /tmp \
  --tmpfs /var/run \
  --cap-drop ALL \
  --cap-add NET_BIND_SERVICE \
  --security-opt no-new-privileges:true \
  --security-opt seccomp=seccomp-profile.json \
  --memory 512m \
  --cpus 1.0 \
  --pids-limit 100 \
  --ulimit nofile=1024:1024 \
  myapp:latest
```

#### Seccomp安全配置
```json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "architectures": [
    "SCMP_ARCH_X86_64",
    "SCMP_ARCH_X86",
    "SCMP_ARCH_X32"
  ],
  "syscalls": [
    {
      "names": [
        "accept",
        "accept4",
        "access",
        "adjtimex",
        "alarm",
        "bind",
        "brk",
        "capget",
        "capset",
        "chdir",
        "chmod",
        "chown",
        "chown32",
        "clock_getres",
        "clock_gettime",
        "clock_nanosleep",
        "close",
        "connect",
        "copy_file_range",
        "creat",
        "dup",
        "dup2",
        "dup3",
        "epoll_create",
        "epoll_create1",
        "epoll_ctl",
        "epoll_pwait",
        "epoll_wait",
        "eventfd",
        "eventfd2",
        "execve",
        "execveat",
        "exit",
        "exit_group",
        "faccessat",
        "fadvise64",
        "fadvise64_64",
        "fallocate",
        "fanotify_mark",
        "fchdir",
        "fchmod",
        "fchmodat",
        "fchown",
        "fchown32",
        "fchownat",
        "fcntl",
        "fcntl64",
        "fdatasync",
        "fgetxattr",
        "flistxattr",
        "flock",
        "fork",
        "fremovexattr",
        "fsetxattr",
        "fstat",
        "fstat64",
        "fstatat64",
        "fstatfs",
        "fstatfs64",
        "fsync",
        "ftruncate",
        "ftruncate64",
        "futex",
        "getcwd",
        "getdents",
        "getdents64",
        "getegid",
        "getegid32",
        "geteuid",
        "geteuid32",
        "getgid",
        "getgid32",
        "getgroups",
        "getgroups32",
        "getitimer",
        "getpeername",
        "getpgid",
        "getpgrp",
        "getpid",
        "getppid",
        "getpriority",
        "getrandom",
        "getresgid",
        "getresgid32",
        "getresuid",
        "getresuid32",
        "getrlimit",
        "get_robust_list",
        "getrusage",
        "getsid",
        "getsockname",
        "getsockopt",
        "get_thread_area",
        "gettid",
        "gettimeofday",
        "getuid",
        "getuid32",
        "getxattr",
        "inotify_add_watch",
        "inotify_init",
        "inotify_init1",
        "inotify_rm_watch",
        "io_cancel",
        "ioctl",
        "io_destroy",
        "io_getevents",
        "ioprio_get",
        "ioprio_set",
        "io_setup",
        "io_submit",
        "ipc",
        "kill",
        "lchown",
        "lchown32",
        "lgetxattr",
        "link",
        "linkat",
        "listen",
        "listxattr",
        "llistxattr",
        "_llseek",
        "lremovexattr",
        "lseek",
        "lsetxattr",
        "lstat",
        "lstat64",
        "madvise",
        "memfd_create",
        "mincore",
        "mkdir",
        "mkdirat",
        "mknod",
        "mknodat",
        "mlock",
        "mlock2",
        "mlockall",
        "mmap",
        "mmap2",
        "mprotect",
        "mq_getsetattr",
        "mq_notify",
        "mq_open",
        "mq_timedreceive",
        "mq_timedsend",
        "mq_unlink",
        "mremap",
        "msgctl",
        "msgget",
        "msgrcv",
        "msgsnd",
        "msync",
        "munlock",
        "munlockall",
        "munmap",
        "nanosleep",
        "newfstatat",
        "_newselect",
        "open",
        "openat",
        "pause",
        "pipe",
        "pipe2",
        "poll",
        "ppoll",
        "prctl",
        "pread64",
        "preadv",
        "prlimit64",
        "pselect6",
        "ptrace",
        "pwrite64",
        "pwritev",
        "read",
        "readahead",
        "readlink",
        "readlinkat",
        "readv",
        "recv",
        "recvfrom",
        "recvmmsg",
        "recvmsg",
        "remap_file_pages",
        "removexattr",
        "rename",
        "renameat",
        "renameat2",
        "restart_syscall",
        "rmdir",
        "rt_sigaction",
        "rt_sigpending",
        "rt_sigprocmask",
        "rt_sigqueueinfo",
        "rt_sigreturn",
        "rt_sigsuspend",
        "rt_sigtimedwait",
        "rt_tgsigqueueinfo",
        "sched_getaffinity",
        "sched_getattr",
        "sched_getparam",
        "sched_get_priority_max",
        "sched_get_priority_min",
        "sched_getscheduler",
        "sched_rr_get_interval",
        "sched_setaffinity",
        "sched_setattr",
        "sched_setparam",
        "sched_setscheduler",
        "sched_yield",
        "seccomp",
        "select",
        "semctl",
        "semget",
        "semop",
        "semtimedop",
        "send",
        "sendfile",
        "sendfile64",
        "sendmmsg",
        "sendmsg",
        "sendto",
        "setfsgid",
        "setfsgid32",
        "setfsuid",
        "setfsuid32",
        "setgid",
        "setgid32",
        "setgroups",
        "setgroups32",
        "setitimer",
        "setpgid",
        "setpriority",
        "setregid",
        "setregid32",
        "setresgid",
        "setresgid32",
        "setresuid",
        "setresuid32",
        "setreuid",
        "setreuid32",
        "setrlimit",
        "set_robust_list",
        "setsid",
        "setsockopt",
        "set_thread_area",
        "set_tid_address",
        "setuid",
        "setuid32",
        "setxattr",
        "shmat",
        "shmctl",
        "shmdt",
        "shmget",
        "shutdown",
        "sigaltstack",
        "signalfd",
        "signalfd4",
        "sigreturn",
        "socket",
        "socketcall",
        "socketpair",
        "splice",
        "stat",
        "stat64",
        "statfs",
        "statfs64",
        "statx",
        "symlink",
        "symlinkat",
        "sync",
        "sync_file_range",
        "syncfs",
        "sysinfo",
        "tee",
        "tgkill",
        "time",
        "timer_create",
        "timer_delete",
        "timerfd_create",
        "timerfd_gettime",
        "timerfd_settime",
        "timer_getoverrun",
        "timer_gettime",
        "timer_settime",
        "times",
        "tkill",
        "truncate",
        "truncate64",
        "ugetrlimit",
        "umask",
        "uname",
        "unlink",
        "unlinkat",
        "utime",
        "utimensat",
        "utimes",
        "vfork",
        "vmsplice",
        "wait4",
        "waitid",
        "waitpid",
        "write",
        "writev"
      ],
      "action": "SCMP_ACT_ALLOW"
    }
  ]
}
```

---

## Docker使用场景

### 6.1 开发环境标准化

#### 开发环境一致性
```yaml
# docker-compose.dev.yml
version: '3.8'
services:
  app:
    build:
      context: .
      dockerfile: Dockerfile.dev
    volumes:
      - .:/app
      - /app/node_modules
    ports:
      - "3000:3000"
    environment:
      - NODE_ENV=development
      - CHOKIDAR_USEPOLLING=true
    command: npm run dev

  db:
    image: postgres:13
    environment:
      - POSTGRES_DB=myapp_dev
      - POSTGRES_USER=dev
      - POSTGRES_PASSWORD=dev123
    ports:
      - "5432:5432"
    volumes:
      - postgres_dev:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  postgres_dev:
```

#### 多版本环境管理
```bash
#!/bin/bash
# env-manager.sh - 环境管理脚本

set -e

ENV_NAME=${1:-dev}
ACTION=${2:-up}

case $ENV_NAME in
  "dev")
    COMPOSE_FILE="docker-compose.dev.yml"
    ;;
  "test")
    COMPOSE_FILE="docker-compose.test.yml"
    ;;
  "staging")
    COMPOSE_FILE="docker-compose.staging.yml"
    ;;
  "prod")
    COMPOSE_FILE="docker-compose.prod.yml"
    ;;
  *)
    echo "Unknown environment: $ENV_NAME"
    exit 1
    ;;
esac

case $ACTION in
  "up")
    echo "Starting $ENV_NAME environment..."
    docker-compose -f $COMPOSE_FILE up -d
    ;;
  "down")
    echo "Stopping $ENV_NAME environment..."
    docker-compose -f $COMPOSE_FILE down
    ;;
  "logs")
    docker-compose -f $COMPOSE_FILE logs -f
    ;;
  "ps")
    docker-compose -f $COMPOSE_FILE ps
    ;;
  *)
    echo "Unknown action: $ACTION"
    echo "Usage: $0 <env> <action>"
    echo "Environments: dev, test, staging, prod"
    echo "Actions: up, down, logs, ps"
    exit 1
    ;;
esac
```

### 6.2 微服务架构

#### 服务拆分与部署
```yaml
# 微服务架构示例
version: '3.8'
services:
  # API网关
  api-gateway:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./gateway/nginx.conf:/etc/nginx/nginx.conf
    depends_on:
      - user-service
      - order-service
      - product-service
    networks:
      - microservices

  # 用户服务
  user-service:
    build: ./services/user
    environment:
      - DB_HOST=user-db
      - REDIS_HOST=redis
      - SERVICE_PORT=8001
    depends_on:
      - user-db
      - redis
    networks:
      - microservices
      - user-network
    deploy:
      replicas: 2

  user-db:
    image: postgres:13
    environment:
      - POSTGRES_DB=users
      - POSTGRES_USER=user_service
      - POSTGRES_PASSWORD=password123
    volumes:
      - user_db_data:/var/lib/postgresql/data
    networks:
      - user-network

  # 订单服务
  order-service:
    build: ./services/order
    environment:
      - DB_HOST=order-db
      - REDIS_HOST=redis
      - SERVICE_PORT=8002
      - USER_SERVICE_URL=http://user-service:8001
      - PRODUCT_SERVICE_URL=http://product-service:8003
    depends_on:
      - order-db
      - redis
    networks:
      - microservices
      - order-network
    deploy:
      replicas: 3

  order-db:
    image: postgres:13
    environment:
      - POSTGRES_DB=orders
      - POSTGRES_USER=order_service
      - POSTGRES_PASSWORD=password123
    volumes:
      - order_db_data:/var/lib/postgresql/data
    networks:
      - order-network

  # 产品服务
  product-service:
    build: ./services/product
    environment:
      - DB_HOST=product-db
      - REDIS_HOST=redis
      - SERVICE_PORT=8003
    depends_on:
      - product-db
      - redis
    networks:
      - microservices
      - product-network
    deploy:
      replicas: 2

  product-db:
    image: postgres:13
    environment:
      - POSTGRES_DB=products
      - POSTGRES_USER=product_service
      - POSTGRES_PASSWORD=password123
    volumes:
      - product_db_data:/var/lib/postgresql/data
    networks:
      - product-network

  # 共享缓存
  redis:
    image: redis:7-alpine
    networks:
      - microservices
    volumes:
      - redis_data:/data

  # 消息队列
  rabbitmq:
    image: rabbitmq:3-management
    environment:
      - RABBITMQ_DEFAULT_USER=admin
      - RABBITMQ_DEFAULT_PASS=admin123
    ports:
      - "15672:15672"
    networks:
      - microservices
    volumes:
      - rabbitmq_data:/var/lib/rabbitmq

  # 服务发现
  consul:
    image: consul:latest
    ports:
      - "8500:8500"
    networks:
      - microservices
    volumes:
      - consul_data:/consul/data

volumes:
  user_db_data:
  order_db_data:
  product_db_data:
  redis_data:
  rabbitmq_data:
  consul_data:

networks:
  microservices:
    driver: bridge
  user-network:
    driver: bridge
    internal: true
  order-network:
    driver: bridge
    internal: true
  product-network:
    driver: bridge
    internal: true
```

### 6.3 CI/CD流水线

#### GitLab CI集成
```yaml
# .gitlab-ci.yml
stages:
  - test
  - build
  - security
  - deploy

variables:
  DOCKER_DRIVER: overlay2
  DOCKER_TLS_CERTDIR: "/certs"
  IMAGE_TAG: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
  LATEST_TAG: $CI_REGISTRY_IMAGE:latest

services:
  - docker:20.10.16-dind

before_script:
  - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY

# 单元测试
unit-test:
  stage: test
  image: golang:1.19
  script:
    - go mod download
    - go test -v -race -coverprofile=coverage.out ./...
    - go tool cover -html=coverage.out -o coverage.html
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
    paths:
      - coverage.html
    expire_in: 1 week
  coverage: '/coverage: \d+\.\d+% of statements/'

# 集成测试
integration-test:
  stage: test
  image: docker:20.10.16
  script:
    - docker-compose -f docker-compose.test.yml up -d
    - docker-compose -f docker-compose.test.yml exec -T app go test -tags=integration ./tests/...
  after_script:
    - docker-compose -f docker-compose.test.yml down -v

# 构建镜像
build-image:
  stage: build
  image: docker:20.10.16
  script:
    - docker build -t $IMAGE_TAG .
    - docker tag $IMAGE_TAG $LATEST_TAG
    - docker push $IMAGE_TAG
    - docker push $LATEST_TAG
  only:
    - main
    - develop
    - /^release\/.*$/

# 安全扫描
security-scan:
  stage: security
  image: aquasec/trivy:latest
  script:
    - trivy image --exit-code 0 --severity HIGH,CRITICAL --format template --template "@contrib/gitlab.tpl" -o gl-container-scanning-report.json $IMAGE_TAG
    - trivy image --exit-code 1 --severity CRITICAL $IMAGE_TAG
  artifacts:
    reports:
      container_scanning: gl-container-scanning-report.json
  only:
    - main
    - develop

# 部署到开发环境
deploy-dev:
  stage: deploy
  image: alpine:latest
  before_script:
    - apk add --no-cache curl
    - curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
    - chmod +x kubectl
    - mv kubectl /usr/local/bin/
  script:
    - kubectl config use-context dev-cluster
    - kubectl set image deployment/myapp myapp=$IMAGE_TAG -n development
    - kubectl rollout status deployment/myapp -n development
  environment:
    name: development
    url: https://dev.myapp.com
  only:
    - develop

# 部署到生产环境
deploy-prod:
  stage: deploy
  image: alpine:latest
  before_script:
    - apk add --no-cache curl
    - curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
    - chmod +x kubectl
    - mv kubectl /usr/local/bin/
  script:
    - kubectl config use-context prod-cluster
    - kubectl set image deployment/myapp myapp=$IMAGE_TAG -n production
    - kubectl rollout status deployment/myapp -n production
  environment:
    name: production
    url: https://myapp.com
  when: manual
  only:
    - main
```

### 6.4 云原生应用

#### 12-Factor应用实践
```dockerfile
# 12-Factor应用Dockerfile
FROM golang:1.19-alpine AS builder

# 1. 代码库：一个代码库，多个部署
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .

# 2. 依赖：显式声明和隔离依赖
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o main .

FROM alpine:latest
RUN apk --no-cache add ca-certificates
WORKDIR /root/

# 3. 配置：在环境中存储配置
# 4. 后端服务：把后端服务当作附加资源
# 5. 构建、发布、运行：严格分离构建和运行
COPY --from=builder /app/main .

# 6. 进程：以一个或多个无状态进程运行应用
# 7. 端口绑定：通过端口绑定提供服务
EXPOSE 8080

# 8. 并发：通过进程模型进行扩展
# 9. 易处理：快速启动和优雅终止
# 10. 开发环境与线上环境等价
# 11. 日志：把日志当作事件流
# 12. 管理进程：后台管理任务当作一次性进程运行

USER 1001
CMD ["./main"]
```

---

## Docker优化方案

### 7.1 镜像优化

#### 镜像大小优化
```dockerfile
# 优化前：大镜像
FROM ubuntu:20.04
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    git \
    curl \
    wget
COPY requirements.txt .
RUN pip3 install -r requirements.txt
COPY . .
CMD ["python3", "app.py"]

# 优化后：小镜像
FROM python:3.9-alpine AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.9-alpine
WORKDIR /app
# 只复制必要的文件
COPY --from=builder /root/.local /root/.local
COPY app.py .
# 确保脚本在PATH中
ENV PATH=/root/.local/bin:$PATH
USER 1001
CMD ["python", "app.py"]
```

#### 构建缓存优化
```dockerfile
# 优化构建缓存
FROM node:16-alpine

WORKDIR /app

# 先复制package文件，利用Docker层缓存
COPY package*.json ./
RUN npm ci --only=production && npm cache clean --force

# 再复制源代码
COPY . .

# 构建应用
RUN npm run build

# 多阶段构建，只保留必要文件
FROM nginx:alpine
COPY --from=0 /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

### 7.2 性能优化

#### 资源限制优化
```yaml
# docker-compose.yml资源优化
version: '3.8'
services:
  web:
    image: myapp:latest
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 1G
        reservations:
          cpus: '1.0'
          memory: 512M
      restart_policy:
        condition: on-failure
        delay: 5s
        max_attempts: 3
        window: 120s
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
```

#### 网络性能优化
```bash
# 网络性能调优
# 1. 使用host网络模式（适用于高性能场景）
docker run --network host myapp:latest

# 2. 优化bridge网络
docker network create --driver bridge \
  --opt com.docker.network.bridge.name=docker1 \
  --opt com.docker.network.driver.mtu=1500 \
  --opt com.docker.network.bridge.enable_ip_masquerade=true \
  optimized-bridge

# 3. 使用macvlan网络（直接访问物理网络）
docker network create -d macvlan \
  --subnet=192.168.1.0/24 \
  --gateway=192.168.1.1 \
  -o parent=eth0 \
  macvlan-net
```

#### 存储性能优化
```bash
# 存储性能优化
# 1. 使用tmpfs挂载临时数据
docker run -d --tmpfs /tmp:rw,noexec,nosuid,size=100m myapp:latest

# 2. 优化数据卷性能
docker volume create --driver local \
  --opt type=none \
  --opt o=bind \
  --opt device=/fast/ssd/path \
  fast-volume

# 3. 使用bind mount优化开发环境
docker run -d \
  -v /host/app:/app:cached \
  -v /host/node_modules:/app/node_modules:delegated \
  myapp:latest
```

### 7.3 监控与日志优化

#### 日志管理优化
```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3",
    "compress": "true"
  }
}
```

#### 监控集成
```yaml
# 监控配置
version: '3.8'
services:
  app:
    image: myapp:latest
    labels:
      - "prometheus.io/scrape=true"
      - "prometheus.io/port=8080"
      - "prometheus.io/path=/metrics"
    logging:
      driver: "fluentd"
      options:
        fluentd-address: "localhost:24224"
        tag: "myapp"

  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/etc/prometheus/console_libraries'
      - '--web.console.templates=/etc/prometheus/consoles'
      - '--storage.tsdb.retention.time=200h'
      - '--web.enable-lifecycle'

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin123
    volumes:
      - grafana-data:/var/lib/grafana

  fluentd:
    image: fluent/fluentd:latest
    ports:
      - "24224:24224"
    volumes:
      - ./fluentd.conf:/fluentd/etc/fluent.conf
      - /var/log:/var/log

volumes:
  grafana-data:
```

---

## Docker常见问题

### 8.1 镜像相关问题

#### 镜像构建失败
```bash
# 问题1：网络超时
# 解决方案：使用镜像加速器
# /etc/docker/daemon.json
{
  "registry-mirrors": [
    "https://mirror.ccs.tencentyun.com",
    "https://docker.mirrors.ustc.edu.cn",
    "https://hub-mirror.c.163.com"
  ]
}

# 问题2：磁盘空间不足
# 解决方案：清理无用镜像和容器
docker system prune -a --volumes
docker image prune -a
docker container prune
docker volume prune

# 问题3：构建上下文过大
# 解决方案：优化.dockerignore
echo "node_modules
.git
*.log
.DS_Store
README.md" > .dockerignore
```

#### 镜像拉取问题
```bash
# 问题：镜像拉取失败
# 解决方案1：重试机制
#!/bin/bash
retry_pull() {
    local image=$1
    local max_attempts=3
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        echo "Attempt $attempt to pull $image"
        if docker pull $image; then
            echo "Successfully pulled $image"
            return 0
        else
            echo "Failed to pull $image (attempt $attempt)"
            attempt=$((attempt + 1))
            sleep 5
        fi
    done
    
    echo "Failed to pull $image after $max_attempts attempts"
    return 1
}

# 解决方案2：使用代理
docker pull --proxy http://proxy.company.com:8080 nginx:alpine
```

### 8.2 容器运行问题

#### 容器启动失败
```bash
# 问题1：端口冲突
# 解决方案：检查端口占用
netstat -tulpn | grep :8080
lsof -i :8080

# 动态分配端口
docker run -d -P myapp:latest

# 问题2：权限问题
# 解决方案：调整用户权限
docker run -d --user $(id -u):$(id -g) \
  -v /host/data:/app/data \
  myapp:latest

# 问题3：资源不足
# 解决方案：检查系统资源
docker system df
docker stats
free -h
df -h
```

#### 容器网络问题
```bash
# 网络连接问题诊断
# 1. 检查容器网络配置
docker network ls
docker network inspect bridge

# 2. 容器间通信测试
docker exec container1 ping container2
docker exec container1 nslookup container2

# 3. 端口映射检查
docker port myapp
iptables -t nat -L -n | grep 8080

# 4. DNS解析问题
docker exec myapp nslookup google.com
docker exec myapp cat /etc/resolv.conf
```

### 8.3 性能问题

#### 容器性能调优
```bash
# 性能监控
docker stats --no-stream
docker exec myapp top
docker exec myapp iostat -x 1

# CPU性能优化
docker run -d --cpus="1.5" --cpu-shares=1024 myapp:latest

# 内存性能优化
docker run -d --memory="1g" --memory-swap="2g" \
  --oom-kill-disable=false myapp:latest

# I/O性能优化
docker run -d --device-read-bps /dev/sda:1mb \
  --device-write-bps /dev/sda:1mb myapp:latest
```

### 8.4 数据持久化问题

#### 数据丢失问题
```bash
# 问题：容器删除导致数据丢失
# 解决方案：使用数据卷
docker volume create myapp-data
docker run -d -v myapp-data:/app/data myapp:latest

# 数据备份
docker run --rm -v myapp-data:/data -v $(pwd):/backup \
  alpine tar czf /backup/backup.tar.gz -C /data .

# 数据恢复
docker run --rm -v myapp-data:/data -v $(pwd):/backup \
  alpine tar xzf /backup/backup.tar.gz -C /data
```

---

## Docker最佳实践

### 9.1 安全最佳实践

#### 镜像安全
```dockerfile
# 安全的Dockerfile
FROM alpine:3.16

# 创建非root用户
RUN addgroup -g 1001 -S appgroup && \
    adduser -u 1001 -S appuser -G appgroup

# 安装必要软件并清理
RUN apk add --no-cache ca-certificates tzdata && \
    rm -rf /var/cache/apk/*

# 设置工作目录
WORKDIR /app

# 复制应用文件
COPY --chown=appuser:appgroup . .

# 切换到非root用户
USER appuser

# 健康检查
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1

EXPOSE 8080
CMD ["./app"]
```

#### 运行时安全
```bash
# 安全运行容器
docker run -d \
  --name secure-app \
  --user 1001:1001 \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=100m \
  --cap-drop ALL \
  --cap-add NET_BIND_SERVICE \
  --security-opt no-new-privileges:true \
  --security-opt apparmor:docker-default \
  --memory 512m \
  --cpus 1.0 \
  --pids-limit 100 \
  --restart unless-stopped \
  myapp:latest
```

### 9.2 生产环境最佳实践

#### 健康检查
```dockerfile
# 应用级健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1
```

```go
// Go应用健康检查端点
package main

import (
    "encoding/json"
    "net/http"
    "time"
)

type HealthStatus struct {
    Status    string            `json:"status"`
    Timestamp time.Time         `json:"timestamp"`
    Checks    map[string]string `json:"checks"`
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
    health := HealthStatus{
        Status:    "healthy",
        Timestamp: time.Now(),
        Checks:    make(map[string]string),
    }
    
    // 检查数据库连接
    if err := checkDatabase(); err != nil {
        health.Status = "unhealthy"
        health.Checks["database"] = "failed: " + err.Error()
        w.WriteHeader(http.StatusServiceUnavailable)
    } else {
        health.Checks["database"] = "ok"
    }
    
    // 检查Redis连接
    if err := checkRedis(); err != nil {
        health.Status = "unhealthy"
        health.Checks["redis"] = "failed: " + err.Error()
        w.WriteHeader(http.StatusServiceUnavailable)
    } else {
        health.Checks["redis"] = "ok"
    }
    
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(health)
}

func checkDatabase() error {
    // 实现数据库健康检查
    return nil
}

func checkRedis() error {
    // 实现Redis健康检查
    return nil
}
```

#### 优雅关闭
```go
// 优雅关闭示例
package main

import (
    "context"
    "log"
    "net/http"
    "os"
    "os/signal"
    "syscall"
    "time"
)

func main() {
    server := &http.Server{
        Addr:    ":8080",
        Handler: setupRoutes(),
    }
    
    // 启动服务器
    go func() {
        if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
            log.Fatalf("Server failed to start: %v", err)
        }
    }()
    
    log.Println("Server started on :8080")
    
    // 等待中断信号
    quit := make(chan os.Signal, 1)
    signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
    <-quit
    
    log.Println("Shutting down server...")
    
    // 优雅关闭，最多等待30秒
    ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
    defer cancel()
    
    if err := server.Shutdown(ctx); err != nil {
        log.Fatalf("Server forced to shutdown: %v", err)
    }
    
    log.Println("Server exited")
}
```

---

## Docker生产环境部署

### 10.1 生产环境配置

#### Docker Daemon配置
```json
{
  "hosts": ["unix:///var/run/docker.sock"],
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3",
    "compress": "true"
  },
  "storage-driver": "overlay2",
  "storage-opts": [
    "overlay2.override_kernel_check=true"
  ],
  "registry-mirrors": [
    "https://mirror.ccs.tencentyun.com"
  ],
  "insecure-registries": [
    "registry.company.com:5000"
  ],
  "default-ulimits": {
    "nofile": {
      "Name": "nofile",
      "Hard": 64000,
      "Soft": 64000
    }
  },
  "live-restore": true,
  "userland-proxy": false,
  "experimental": false,
  "metrics-addr": "127.0.0.1:9323",
  "iptables": true,
  "ip-forward": true,
  "ip-masq": true,
  "ipv6": false
}
```

#### 系统优化
```bash
#!/bin/bash
# docker-system-optimization.sh

# 内核参数优化
cat >> /etc/sysctl.conf << EOF
# Docker优化参数
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward = 1
vm.max_map_count = 262144
fs.file-max = 65536
net.core.somaxconn = 32768
net.ipv4.tcp_max_syn_backlog = 16384
net.core.netdev_max_backlog = 16384
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_tw_reuse = 1
EOF

# 应用内核参数
sysctl -p

# 设置ulimit
cat >> /etc/security/limits.conf << EOF
* soft nofile 65536
* hard nofile 65536
* soft nproc 32768
* hard nproc 32768
EOF

# Docker服务优化
systemctl enable docker
systemctl daemon-reload
systemctl restart docker

echo "Docker system optimization completed"
```

### 10.2 监控与告警

#### Prometheus监控配置
```yaml
# prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - "docker_rules.yml"

alerting:
  alertmanagers:
    - static_configs:
        - targets:
          - alertmanager:9093

scrape_configs:
  - job_name: 'docker'
    static_configs:
      - targets: ['localhost:9323']
    metrics_path: /metrics
    scrape_interval: 5s

  - job_name: 'cadvisor'
    static_configs:
      - targets: ['cadvisor:8080']
    scrape_interval: 5s

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']
    scrape_interval: 5s
```

#### 告警规则
```yaml
# docker_rules.yml
groups:
- name: docker.rules
  rules:
  - alert: ContainerDown
    expr: up{job="docker"} == 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Container {{ $labels.instance }} is down"
      description: "Container {{ $labels.instance }} has been down for more than 1 minute."

  - alert: HighCPUUsage
    expr: rate(container_cpu_usage_seconds_total[5m]) * 100 > 80
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: "High CPU usage on {{ $labels.name }}"
      description: "Container {{ $labels.name }} CPU usage is above 80% for more than 2 minutes."

  - alert: HighMemoryUsage
    expr: (container_memory_usage_bytes / container_spec_memory_limit_bytes) * 100 > 90
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "High memory usage on {{ $labels.name }}"
      description: "Container {{ $labels.name }} memory usage is above 90% for more than 2 minutes."

  - alert: ContainerRestarting
    expr: increase(container_start_time_seconds[1h]) > 3
    for: 0m
    labels:
      severity: warning
    annotations:
      summary: "Container {{ $labels.name }} is restarting frequently"
      description: "Container {{ $labels.name }} has restarted more than 3 times in the last hour."
```

---

## 总结

Docker作为容器化技术的代表，已经成为现代应用部署和运维的重要工具。通过本指南，我们深入了解了Docker的核心概念、架构设计、核心原理、使用场景、优化方案和最佳实践。

### 关键要点

1. **容器化优势**：轻量级、快速启动、环境一致性、可移植性
2. **核心技术**：Namespace、CGroups、Union File System
3. **架构组件**：Docker Client、Docker Daemon、Container Runtime
4. **使用场景**：开发环境标准化、微服务架构、CI/CD流水线、云原生应用
5. **优化策略**：镜像优化、性能调优、安全加固、监控告警
6. **生产实践**：健康检查、优雅关闭、资源限制、日志管理

### 发展趋势

- **云原生集成**：与Kubernetes深度集成
- **安全增强**：更强的安全隔离和扫描能力
- **性能优化**：更高效的存储和网络驱动
- **开发体验**：更好的开发工具和调试能力

Docker技术栈在不断演进，建议持续关注最新发展动态，结合实际业务需求选择合适的容器化方案。