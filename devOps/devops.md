# DevOps 云重建实践指南

## 目录
1. [Docker容器化实践与最佳实践](#docker容器化实践与最佳实践)
2. [Kubernetes集群管理与服务编排](#kubernetes集群管理与服务编排)
3. [DevOps流水线搭建](#devops流水线搭建)
4. [云原生架构设计](#云原生架构设计)
5. [监控与日志管理](#监控与日志管理)
6. [安全与合规](#安全与合规)

## Docker容器化实践与最佳实践

### 1.1 Docker基础架构

#### Docker核心组件
```yaml
# Docker架构组件
Docker Engine:
  - Docker Daemon (dockerd)
  - Docker CLI (docker)
  - REST API
  
Docker Objects:
  - Images (镜像)
  - Containers (容器)
  - Networks (网络)
  - Volumes (数据卷)
  - Plugins (插件)
```

#### Dockerfile最佳实践
```dockerfile
# 多阶段构建示例 - Go应用
FROM golang:1.21-alpine AS builder

# 设置工作目录
WORKDIR /app

# 复制依赖文件
COPY go.mod go.sum ./
RUN go mod download

# 复制源代码
COPY . .

# 构建应用
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o main .

# 运行阶段
FROM alpine:latest

# 安装ca-certificates用于HTTPS请求
RUN apk --no-cache add ca-certificates

# 创建非root用户
RUN addgroup -g 1001 -S appgroup && \
    adduser -u 1001 -S appuser -G appgroup

WORKDIR /root/

# 从构建阶段复制二进制文件
COPY --from=builder /app/main .

# 切换到非root用户
USER appuser

# 暴露端口
EXPOSE 8080

# 健康检查
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1

# 启动应用
CMD ["./main"]
```

#### Docker Compose生产配置
```yaml
# docker-compose.prod.yml
version: '3.8'

services:
  app:
    build:
      context: .
      dockerfile: Dockerfile
      target: production
    image: myapp:${VERSION:-latest}
    container_name: myapp-prod
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      - ENV=production
      - DB_HOST=db
      - REDIS_HOST=redis
    volumes:
      - app-logs:/var/log/app
    networks:
      - app-network
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 1G
        reservations:
          cpus: '1.0'
          memory: 512M
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  db:
    image: postgres:15-alpine
    container_name: postgres-prod
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${DB_NAME}
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres-data:/var/lib/postgresql/data
      - ./init.sql:/docker-entrypoint-initdb.d/init.sql
    networks:
      - app-network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER} -d ${DB_NAME}"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: redis-prod
    restart: unless-stopped
    command: redis-server --appendonly yes --requirepass ${REDIS_PASSWORD}
    volumes:
      - redis-data:/data
    networks:
      - app-network

  nginx:
    image: nginx:alpine
    container_name: nginx-prod
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./ssl:/etc/nginx/ssl
      - nginx-logs:/var/log/nginx
    networks:
      - app-network
    depends_on:
      - app

volumes:
  postgres-data:
    driver: local
  redis-data:
    driver: local
  app-logs:
    driver: local
  nginx-logs:
    driver: local

networks:
  app-network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
```

### 1.2 容器安全最佳实践

#### 安全扫描与镜像管理
```bash
#!/bin/bash
# 容器安全扫描脚本

# 使用Trivy扫描镜像漏洞
trivy image --severity HIGH,CRITICAL myapp:latest

# 使用Docker Bench进行安全基准测试
docker run --rm --net host --pid host --userns host --cap-add audit_control \
    -e DOCKER_CONTENT_TRUST=$DOCKER_CONTENT_TRUST \
    -v /etc:/etc:ro \
    -v /usr/bin/containerd:/usr/bin/containerd:ro \
    -v /usr/bin/runc:/usr/bin/runc:ro \
    -v /usr/lib/systemd:/usr/lib/systemd:ro \
    -v /var/lib:/var/lib:ro \
    -v /var/run/docker.sock:/var/run/docker.sock:ro \
    --label docker_bench_security \
    docker/docker-bench-security

# 镜像签名验证
export DOCKER_CONTENT_TRUST=1
docker pull myregistry.com/myapp:latest
```

#### 运行时安全配置
```yaml
# 安全的容器运行配置
version: '3.8'
services:
  secure-app:
    image: myapp:latest
    # 只读根文件系统
    read_only: true
    # 临时文件系统
    tmpfs:
      - /tmp:noexec,nosuid,size=100m
      - /var/run:noexec,nosuid,size=50m
    # 安全选项
    security_opt:
      - no-new-privileges:true
      - apparmor:docker-default
    # 资源限制
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 512M
          pids: 100
    # 网络安全
    networks:
      - secure-network
    # 用户权限
    user: "1001:1001"
    # 禁用特权模式
    privileged: false
    # 移除危险能力
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE

networks:
  secure-network:
    driver: bridge
    driver_opts:
      com.docker.network.bridge.enable_icc: "false"
```

## Kubernetes集群管理与服务编排

### 2.1 Kubernetes架构与组件

#### 集群架构图
```yaml
# Kubernetes集群架构
Master Node (Control Plane):
  - kube-apiserver      # API服务器
  - etcd               # 分布式键值存储
  - kube-scheduler     # 调度器
  - kube-controller-manager # 控制器管理器
  - cloud-controller-manager # 云控制器管理器

Worker Node:
  - kubelet            # 节点代理
  - kube-proxy         # 网络代理
  - container-runtime  # 容器运行时

Add-ons:
  - DNS (CoreDNS)
  - Dashboard
  - Ingress Controller
  - CNI Plugin
```

#### 生产级集群部署
```yaml
# kubeadm-config.yaml
apiVersion: kubeadm.k8s.io/v1beta3
kind: InitConfiguration
localAPIEndpoint:
  advertiseAddress: 192.168.1.100
  bindPort: 6443
nodeRegistration:
  criSocket: unix:///var/run/containerd/containerd.sock
  kubeletExtraArgs:
    cloud-provider: external
---
apiVersion: kubeadm.k8s.io/v1beta3
kind: ClusterConfiguration
kubernetesVersion: v1.28.0
controlPlaneEndpoint: "k8s-api.example.com:6443"
networking:
  serviceSubnet: "10.96.0.0/16"
  podSubnet: "10.244.0.0/16"
  dnsDomain: "cluster.local"
etcd:
  external:
    endpoints:
    - https://etcd1.example.com:2379
    - https://etcd2.example.com:2379
    - https://etcd3.example.com:2379
    caFile: /etc/kubernetes/pki/etcd/ca.crt
    certFile: /etc/kubernetes/pki/apiserver-etcd-client.crt
    keyFile: /etc/kubernetes/pki/apiserver-etcd-client.key
apiServer:
  extraArgs:
    audit-log-maxage: "30"
    audit-log-maxbackup: "10"
    audit-log-maxsize: "100"
    audit-log-path: /var/log/audit.log
    enable-admission-plugins: NodeRestriction,ResourceQuota,PodSecurityPolicy
  certSANs:
  - "k8s-api.example.com"
  - "192.168.1.100"
  - "127.0.0.1"
controllerManager:
  extraArgs:
    bind-address: 0.0.0.0
scheduler:
  extraArgs:
    bind-address: 0.0.0.0
---
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
serverTLSBootstrap: true
rotateCertificates: true
```

### 2.2 应用部署与管理

#### 完整的微服务部署示例
```yaml
# namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: microservices
  labels:
    name: microservices
    environment: production
---
# configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
  namespace: microservices
data:
  database.properties: |
    db.host=postgres-service
    db.port=5432
    db.name=myapp
  redis.properties: |
    redis.host=redis-service
    redis.port=6379
  application.yaml: |
    server:
      port: 8080
    logging:
      level:
        root: INFO
        com.myapp: DEBUG
---
# secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: app-secrets
  namespace: microservices
type: Opaque
data:
  db-password: cGFzc3dvcmQxMjM=  # password123
  redis-password: cmVkaXNwYXNz      # redispass
  jwt-secret: bXlqd3RzZWNyZXQ=     # myjwtsecret
---
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: user-service
  namespace: microservices
  labels:
    app: user-service
    version: v1.0.0
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 1
  selector:
    matchLabels:
      app: user-service
  template:
    metadata:
      labels:
        app: user-service
        version: v1.0.0
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8080"
        prometheus.io/path: "/metrics"
    spec:
      serviceAccountName: user-service-sa
      securityContext:
        runAsNonRoot: true
        runAsUser: 1001
        fsGroup: 1001
      containers:
      - name: user-service
        image: myregistry.com/user-service:v1.0.0
        imagePullPolicy: Always
        ports:
        - containerPort: 8080
          name: http
          protocol: TCP
        env:
        - name: DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: app-secrets
              key: db-password
        - name: REDIS_PASSWORD
          valueFrom:
            secretKeyRef:
              name: app-secrets
              key: redis-password
        - name: JWT_SECRET
          valueFrom:
            secretKeyRef:
              name: app-secrets
              key: jwt-secret
        volumeMounts:
        - name: config-volume
          mountPath: /etc/config
        - name: logs-volume
          mountPath: /var/log/app
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
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop:
            - ALL
      volumes:
      - name: config-volume
        configMap:
          name: app-config
      - name: logs-volume
        emptyDir: {}
      imagePullSecrets:
      - name: registry-secret
      nodeSelector:
        kubernetes.io/arch: amd64
      tolerations:
      - key: "app"
        operator: "Equal"
        value: "user-service"
        effect: "NoSchedule"
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
                  - user-service
              topologyKey: kubernetes.io/hostname
---
# service.yaml
apiVersion: v1
kind: Service
metadata:
  name: user-service
  namespace: microservices
  labels:
    app: user-service
spec:
  type: ClusterIP
  ports:
  - port: 80
    targetPort: 8080
    protocol: TCP
    name: http
  selector:
    app: user-service
---
# hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: user-service-hpa
  namespace: microservices
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: user-service
  minReplicas: 3
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
```

#### Ingress配置与负载均衡
```yaml
# ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: microservices-ingress
  namespace: microservices
  annotations:
    kubernetes.io/ingress.class: nginx
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/use-regex: "true"
    nginx.ingress.kubernetes.io/rewrite-target: /$2
    nginx.ingress.kubernetes.io/rate-limit: "100"
    nginx.ingress.kubernetes.io/rate-limit-window: "1m"
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/cors-allow-origin: "https://myapp.com"
    nginx.ingress.kubernetes.io/cors-allow-methods: "GET, POST, PUT, DELETE, OPTIONS"
    nginx.ingress.kubernetes.io/cors-allow-headers: "DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range,Authorization"
spec:
  tls:
  - hosts:
    - api.myapp.com
    secretName: api-tls-secret
  rules:
  - host: api.myapp.com
    http:
      paths:
      - path: /api/users(/|$)(.*)
        pathType: Prefix
        backend:
          service:
            name: user-service
            port:
              number: 80
      - path: /api/orders(/|$)(.*)
        pathType: Prefix
        backend:
          service:
            name: order-service
            port:
              number: 80
      - path: /api/payments(/|$)(.*)
        pathType: Prefix
        backend:
          service:
            name: payment-service
            port:
              number: 80
```

### 2.3 存储与数据管理

#### StatefulSet数据库部署
```yaml
# postgres-statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: microservices
spec:
  serviceName: postgres-headless
  replicas: 3
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgres
        image: postgres:15
        env:
        - name: POSTGRES_DB
          value: myapp
        - name: POSTGRES_USER
          value: postgres
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: postgres-secret
              key: password
        - name: POSTGRES_REPLICATION_USER
          value: replicator
        - name: POSTGRES_REPLICATION_PASSWORD
          valueFrom:
            secretKeyRef:
              name: postgres-secret
              key: replication-password
        ports:
        - containerPort: 5432
          name: postgres
        volumeMounts:
        - name: postgres-storage
          mountPath: /var/lib/postgresql/data
        - name: postgres-config
          mountPath: /etc/postgresql/postgresql.conf
          subPath: postgresql.conf
        resources:
          requests:
            memory: "1Gi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
        livenessProbe:
          exec:
            command:
            - /bin/sh
            - -c
            - pg_isready -U postgres -d myapp
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          exec:
            command:
            - /bin/sh
            - -c
            - pg_isready -U postgres -d myapp
          initialDelaySeconds: 5
          periodSeconds: 5
      volumes:
      - name: postgres-config
        configMap:
          name: postgres-config
  volumeClaimTemplates:
  - metadata:
      name: postgres-storage
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: fast-ssd
      resources:
        requests:
          storage: 100Gi
---
apiVersion: v1
kind: Service
metadata:
  name: postgres-headless
  namespace: microservices
spec:
  clusterIP: None
  ports:
  - port: 5432
    targetPort: 5432
  selector:
    app: postgres
---
apiVersion: v1
kind: Service
metadata:
  name: postgres-service
  namespace: microservices
spec:
  ports:
  - port: 5432
    targetPort: 5432
  selector:
    app: postgres
```

## DevOps流水线搭建

### 3.1 CI/CD流水线设计

#### GitLab CI/CD配置
```yaml
# .gitlab-ci.yml
stages:
  - test
  - build
  - security-scan
  - deploy-staging
  - integration-test
  - deploy-production

variables:
  DOCKER_DRIVER: overlay2
  DOCKER_TLS_CERTDIR: "/certs"
  REGISTRY: registry.gitlab.com
  IMAGE_NAME: $REGISTRY/$CI_PROJECT_PATH
  KUBECONFIG_FILE: $KUBECONFIG

before_script:
  - echo $CI_REGISTRY_PASSWORD | docker login -u $CI_REGISTRY_USER --password-stdin $CI_REGISTRY

# 单元测试阶段
unit-test:
  stage: test
  image: golang:1.21
  services:
    - postgres:15
    - redis:7
  variables:
    POSTGRES_DB: test_db
    POSTGRES_USER: test_user
    POSTGRES_PASSWORD: test_pass
    DATABASE_URL: postgres://test_user:test_pass@postgres:5432/test_db
    REDIS_URL: redis://redis:6379
  script:
    - go mod download
    - go test -v -race -coverprofile=coverage.out ./...
    - go tool cover -html=coverage.out -o coverage.html
  coverage: '/coverage: \d+\.\d+% of statements/'
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
    paths:
      - coverage.html
    expire_in: 1 week
  only:
    - merge_requests
    - main
    - develop

# 代码质量检查
code-quality:
  stage: test
  image: golangci/golangci-lint:latest
  script:
    - golangci-lint run -v
  artifacts:
    reports:
      codequality: gl-code-quality-report.json
  only:
    - merge_requests
    - main
    - develop

# 构建Docker镜像
build-image:
  stage: build
  image: docker:latest
  services:
    - docker:dind
  script:
    - docker build -t $IMAGE_NAME:$CI_COMMIT_SHA .
    - docker tag $IMAGE_NAME:$CI_COMMIT_SHA $IMAGE_NAME:latest
    - docker push $IMAGE_NAME:$CI_COMMIT_SHA
    - docker push $IMAGE_NAME:latest
  only:
    - main
    - develop

# 安全扫描
security-scan:
  stage: security-scan
  image: aquasec/trivy:latest
  script:
    - trivy image --exit-code 0 --severity HIGH,CRITICAL --format template --template "@contrib/gitlab.tpl" -o gl-container-scanning-report.json $IMAGE_NAME:$CI_COMMIT_SHA
    - trivy image --exit-code 1 --severity CRITICAL $IMAGE_NAME:$CI_COMMIT_SHA
  artifacts:
    reports:
      container_scanning: gl-container-scanning-report.json
  dependencies:
    - build-image
  only:
    - main
    - develop

# 部署到Staging环境
deploy-staging:
  stage: deploy-staging
  image: bitnami/kubectl:latest
  environment:
    name: staging
    url: https://staging-api.myapp.com
  script:
    - echo $KUBECONFIG_STAGING | base64 -d > kubeconfig
    - export KUBECONFIG=kubeconfig
    - kubectl set image deployment/user-service user-service=$IMAGE_NAME:$CI_COMMIT_SHA -n staging
    - kubectl rollout status deployment/user-service -n staging --timeout=300s
  dependencies:
    - build-image
    - security-scan
  only:
    - develop

# 集成测试
integration-test:
  stage: integration-test
  image: postman/newman:latest
  script:
    - newman run tests/integration/api-tests.json --environment tests/integration/staging-env.json --reporters cli,junit --reporter-junit-export newman-report.xml
  artifacts:
    reports:
      junit: newman-report.xml
  dependencies:
    - deploy-staging
  only:
    - develop

# 部署到生产环境
deploy-production:
  stage: deploy-production
  image: bitnami/kubectl:latest
  environment:
    name: production
    url: https://api.myapp.com
  script:
    - echo $KUBECONFIG_PRODUCTION | base64 -d > kubeconfig
    - export KUBECONFIG=kubeconfig
    - kubectl set image deployment/user-service user-service=$IMAGE_NAME:$CI_COMMIT_SHA -n production
    - kubectl rollout status deployment/user-service -n production --timeout=600s
  dependencies:
    - integration-test
  when: manual
  only:
    - main
```

#### Jenkins Pipeline配置
```groovy
// Jenkinsfile
pipeline {
    agent any
    
    environment {
        REGISTRY = 'registry.company.com'
        IMAGE_NAME = "${REGISTRY}/myapp"
        KUBECONFIG = credentials('kubeconfig')
        DOCKER_REGISTRY_CREDS = credentials('docker-registry')
    }
    
    stages {
        stage('Checkout') {
            steps {
                checkout scm
                script {
                    env.GIT_COMMIT_SHORT = sh(
                        script: "git rev-parse --short HEAD",
                        returnStdout: true
                    ).trim()
                }
            }
        }
        
        stage('Test') {
            parallel {
                stage('Unit Tests') {
                    steps {
                        sh '''
                            go mod download
                            go test -v -race -coverprofile=coverage.out ./...
                            go tool cover -html=coverage.out -o coverage.html
                        '''
                    }
                    post {
                        always {
                            publishHTML([
                                allowMissing: false,
                                alwaysLinkToLastBuild: true,
                                keepAll: true,
                                reportDir: '.',
                                reportFiles: 'coverage.html',
                                reportName: 'Coverage Report'
                            ])
                        }
                    }
                }
                
                stage('Code Quality') {
                    steps {
                        sh 'golangci-lint run -v'
                    }
                }
                
                stage('Security Scan') {
                    steps {
                        sh '''
                            # SAST扫描
                            gosec -fmt json -out gosec-report.json ./...
                            
                            # 依赖漏洞扫描
                            nancy sleuth
                        '''
                    }
                }
            }
        }
        
        stage('Build') {
            steps {
                script {
                    def image = docker.build("${IMAGE_NAME}:${env.GIT_COMMIT_SHORT}")
                    
                    docker.withRegistry("https://${REGISTRY}", env.DOCKER_REGISTRY_CREDS) {
                        image.push()
                        image.push('latest')
                    }
                }
            }
        }
        
        stage('Container Security Scan') {
            steps {
                sh '''
                    trivy image --exit-code 0 --severity HIGH,CRITICAL \
                        --format template --template "@contrib/junit.tpl" \
                        -o trivy-report.xml ${IMAGE_NAME}:${GIT_COMMIT_SHORT}
                '''
            }
            post {
                always {
                    publishTestResults testResultsPattern: 'trivy-report.xml'
                }
            }
        }
        
        stage('Deploy to Staging') {
            when {
                branch 'develop'
            }
            steps {
                sh '''
                    helm upgrade --install myapp-staging ./helm/myapp \
                        --namespace staging \
                        --set image.tag=${GIT_COMMIT_SHORT} \
                        --set environment=staging \
                        --wait --timeout=300s
                '''
            }
        }
        
        stage('Integration Tests') {
            when {
                branch 'develop'
            }
            steps {
                sh '''
                    # 等待服务就绪
                    kubectl wait --for=condition=ready pod -l app=myapp -n staging --timeout=300s
                    
                    # 运行集成测试
                    newman run tests/integration/api-tests.json \
                        --environment tests/integration/staging-env.json \
                        --reporters cli,junit \
                        --reporter-junit-export newman-report.xml
                '''
            }
            post {
                always {
                    publishTestResults testResultsPattern: 'newman-report.xml'
                }
            }
        }
        
        stage('Deploy to Production') {
            when {
                branch 'main'
            }
            steps {
                input message: 'Deploy to production?', ok: 'Deploy'
                
                sh '''
                    helm upgrade --install myapp-production ./helm/myapp \
                        --namespace production \
                        --set image.tag=${GIT_COMMIT_SHORT} \
                        --set environment=production \
                        --set replicaCount=5 \
                        --wait --timeout=600s
                '''
            }
        }
    }
    
    post {
        always {
            cleanWs()
        }
        failure {
            emailext (
                subject: "Build Failed: ${env.JOB_NAME} - ${env.BUILD_NUMBER}",
                body: "Build failed. Check console output at ${env.BUILD_URL}",
                to: "${env.CHANGE_AUTHOR_EMAIL}"
            )
        }
        success {
            script {
                if (env.BRANCH_NAME == 'main') {
                    slackSend (
                        channel: '#deployments',
                        color: 'good',
                        message: "✅ Successfully deployed ${env.JOB_NAME} ${env.GIT_COMMIT_SHORT} to production"
                    )
                }
            }
        }
    }
}
```

### 3.2 Helm包管理

#### Helm Chart结构
```yaml
# helm/myapp/Chart.yaml
apiVersion: v2
name: myapp
description: A Helm chart for MyApp microservice
type: application
version: 0.1.0
appVersion: "1.0.0"

dependencies:
  - name: postgresql
    version: 12.1.2
    repository: https://charts.bitnami.com/bitnami
    condition: postgresql.enabled
  - name: redis
    version: 17.3.7
    repository: https://charts.bitnami.com/bitnami
    condition: redis.enabled

---
# helm/myapp/values.yaml
replicaCount: 3

image:
  repository: registry.company.com/myapp
  pullPolicy: IfNotPresent
  tag: "latest"

imagePullSecrets:
  - name: registry-secret

nameOverride: ""
fullnameOverride: ""

serviceAccount:
  create: true
  annotations: {}
  name: ""

podAnnotations:
  prometheus.io/scrape: "true"
  prometheus.io/port: "8080"
  prometheus.io/path: "/metrics"

podSecurityContext:
  fsGroup: 1001
  runAsNonRoot: true
  runAsUser: 1001

securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop:
    - ALL

service:
  type: ClusterIP
  port: 80
  targetPort: 8080

ingress:
  enabled: true
  className: "nginx"
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/rate-limit: "100"
  hosts:
    - host: api.myapp.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: api-tls-secret
      hosts:
        - api.myapp.com

resources:
  limits:
    cpu: 500m
    memory: 512Mi
  requests:
    cpu: 250m
    memory: 256Mi

autoscaling:
  enabled: true
  minReplicas: 3
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
  targetMemoryUtilizationPercentage: 80

nodeSelector: {}

tolerations: []

affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
    - weight: 100
      podAffinityTerm:
        labelSelector:
          matchExpressions:
          - key: app.kubernetes.io/name
            operator: In
            values:
            - myapp
        topologyKey: kubernetes.io/hostname

# 数据库配置
postgresql:
  enabled: true
  auth:
    postgresPassword: "changeme"
    database: "myapp"
  primary:
    persistence:
      enabled: true
      size: 100Gi
      storageClass: "fast-ssd"

# Redis配置
redis:
  enabled: true
  auth:
    enabled: true
    password: "changeme"
  master:
    persistence:
      enabled: true
      size: 10Gi
      storageClass: "fast-ssd"

# 环境变量
env:
  - name: ENV
    value: "production"
  - name: LOG_LEVEL
    value: "info"

# 配置文件
config:
  application.yaml: |
    server:
      port: 8080
    database:
      host: myapp-postgresql
      port: 5432
      name: myapp
    redis:
      host: myapp-redis-master
      port: 6379
    logging:
      level: info

# 密钥
secrets:
  db-password: "changeme"
  redis-password: "changeme"
  jwt-secret: "myjwtsecret"
```

## 云原生架构设计

### 4.1 微服务架构模式

#### 服务网格 (Istio) 配置
```yaml
# istio-gateway.yaml
apiVersion: networking.istio.io/v1beta1
kind: Gateway
metadata:
  name: myapp-gateway
  namespace: microservices
spec:
  selector:
    istio: ingressgateway
  servers:
  - port:
      number: 443
      name: https
      protocol: HTTPS
    tls:
      mode: SIMPLE
      credentialName: api-tls-secret
    hosts:
    - api.myapp.com
  - port:
      number: 80
      name: http
      protocol: HTTP
    hosts:
    - api.myapp.com
    redirect:
      httpsRedirect: true
---
# virtual-service.yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: myapp-vs
  namespace: microservices
spec:
  hosts:
  - api.myapp.com
  gateways:
  - myapp-gateway
  http:
  - match:
    - uri:
        prefix: /api/users
    route:
    - destination:
        host: user-service
        port:
          number: 80
    fault:
      delay:
        percentage:
          value: 0.1
        fixedDelay: 5s
    retries:
      attempts: 3
      perTryTimeout: 2s
    timeout: 10s
  - match:
    - uri:
        prefix: /api/orders
    route:
    - destination:
        host: order-service
        port:
          number: 80
        subset: v1
      weight: 90
    - destination:
        host: order-service
        port:
          number: 80
        subset: v2
      weight: 10
---
# destination-rule.yaml
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: order-service-dr
  namespace: microservices
spec:
  host: order-service
  trafficPolicy:
    connectionPool:
      tcp:
        maxConnections: 100
      http:
        http1MaxPendingRequests: 50
        maxRequestsPerConnection: 10
    circuitBreaker:
      consecutiveErrors: 3
      interval: 30s
      baseEjectionTime: 30s
      maxEjectionPercent: 50
    outlierDetection:
      consecutive5xxErrors: 3
      interval: 30s
      baseEjectionTime: 30s
      maxEjectionPercent: 50
  subsets:
  - name: v1
    labels:
      version: v1
  - name: v2
    labels:
      version: v2
```

#### 服务安全策略
```yaml
# security-policy.yaml
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: microservices
spec:
  mtls:
    mode: STRICT
---
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: user-service-authz
  namespace: microservices
spec:
  selector:
    matchLabels:
      app: user-service
  rules:
  - from:
    - source:
        principals: ["cluster.local/ns/microservices/sa/api-gateway"]
  - to:
    - operation:
        methods: ["GET", "POST"]
        paths: ["/api/users/*"]
  - when:
    - key: request.headers[authorization]
      values: ["Bearer *"]
```

### 4.2 可观测性实现

#### Prometheus监控配置
```yaml
# prometheus-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-config
  namespace: monitoring
data:
  prometheus.yml: |
    global:
      scrape_interval: 15s
      evaluation_interval: 15s
    
    rule_files:
      - "/etc/prometheus/rules/*.yml"
    
    alerting:
      alertmanagers:
        - static_configs:
            - targets:
              - alertmanager:9093
    
    scrape_configs:
      - job_name: 'kubernetes-apiservers'
        kubernetes_sd_configs:
        - role: endpoints
        scheme: https
        tls_config:
          ca_file: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
        bearer_token_file: /var/run/secrets/kubernetes.io/serviceaccount/token
        relabel_configs:
        - source_labels: [__meta_kubernetes_namespace, __meta_kubernetes_service_name, __meta_kubernetes_endpoint_port_name]
          action: keep
          regex: default;kubernetes;https
      
      - job_name: 'kubernetes-nodes'
        kubernetes_sd_configs:
        - role: node
        scheme: https
        tls_config:
          ca_file: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
        bearer_token_file: /var/run/secrets/kubernetes.io/serviceaccount/token
        relabel_configs:
        - action: labelmap
          regex: __meta_kubernetes_node_label_(.+)
        - target_label: __address__
          replacement: kubernetes.default.svc:443
        - source_labels: [__meta_kubernetes_node_name]
          regex: (.+)
          target_label: __metrics_path__
          replacement: /api/v1/nodes/${1}/proxy/metrics
      
      - job_name: 'kubernetes-pods'
        kubernetes_sd_configs:
        - role: pod
        relabel_configs:
        - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
          action: keep
          regex: true
        - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
          action: replace
          target_label: __metrics_path__
          regex: (.+)
        - source_labels: [__address__, __meta_kubernetes_pod_annotation_prometheus_io_port]
          action: replace
          regex: ([^:]+)(?::\d+)?;(\d+)
          replacement: $1:$2
          target_label: __address__
        - action: labelmap
          regex: __meta_kubernetes_pod_label_(.+)
        - source_labels: [__meta_kubernetes_namespace]
          action: replace
          target_label: kubernetes_namespace
        - source_labels: [__meta_kubernetes_pod_name]
          action: replace
          target_label: kubernetes_pod_name
  
  alerts.yml: |
    groups:
    - name: kubernetes
      rules:
      - alert: PodCrashLooping
        expr: rate(kube_pod_container_status_restarts_total[15m]) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Pod {{ $labels.pod }} is crash looping"
          description: "Pod {{ $labels.pod }} in namespace {{ $labels.namespace }} is restarting frequently"
      
      - alert: HighMemoryUsage
        expr: (container_memory_usage_bytes / container_spec_memory_limit_bytes) > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High memory usage detected"
          description: "Container {{ $labels.container }} in pod {{ $labels.pod }} is using {{ $value | humanizePercentage }} of memory"
      
      - alert: HighCPUUsage
        expr: rate(container_cpu_usage_seconds_total[5m]) > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High CPU usage detected"
          description: "Container {{ $labels.container }} in pod {{ $labels.pod }} is using {{ $value | humanizePercentage }} of CPU"
```

#### Grafana仪表板配置
```json
{
  "dashboard": {
    "id": null,
    "title": "Microservices Overview",
    "tags": ["kubernetes", "microservices"],
    "timezone": "browser",
    "panels": [
      {
        "id": 1,
        "title": "Request Rate",
        "type": "graph",
        "targets": [
          {
            "expr": "sum(rate(http_requests_total[5m])) by (service)",
            "legendFormat": "{{service}}"
          }
        ],
        "yAxes": [
          {
            "label": "Requests/sec"
          }
        ]
      },
      {
        "id": 2,
        "title": "Error Rate",
        "type": "graph",
        "targets": [
          {
            "expr": "sum(rate(http_requests_total{status=~\"5..\"}[5m])) by (service) / sum(rate(http_requests_total[5m])) by (service)",
            "legendFormat": "{{service}}"
          }
        ],
        "yAxes": [
          {
            "label": "Error Rate",
            "max": 1,
            "min": 0
          }
        ]
      },
      {
        "id": 3,
        "title": "Response Time",
        "type": "graph",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (service, le))",
            "legendFormat": "{{service}} 95th percentile"
          },
          {
            "expr": "histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket[5m])) by (service, le))",
            "legendFormat": "{{service}} 50th percentile"
          }
        ],
        "yAxes": [
          {
            "label": "Response Time (s)"
          }
        ]
      }
    ],
    "time": {
      "from": "now-1h",
      "to": "now"
    },
    "refresh": "5s"
  }
}
```

## 监控与日志管理

### 5.1 ELK Stack部署

#### Elasticsearch集群配置
```yaml
# elasticsearch.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: elasticsearch
  namespace: logging
spec:
  serviceName: elasticsearch-headless
  replicas: 3
  selector:
    matchLabels:
      app: elasticsearch
  template:
    metadata:
      labels:
        app: elasticsearch
    spec:
      initContainers:
      - name: increase-vm-max-map
        image: busybox
        command: ["sysctl", "-w", "vm.max_map_count=262144"]
        securityContext:
          privileged: true
      containers:
      - name: elasticsearch
        image: docker.elastic.co/elasticsearch/elasticsearch:8.5.0
        env:
        - name: cluster.name
          value: "docker-cluster"
        - name: node.name
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: discovery.seed_hosts
          value: "elasticsearch-0.elasticsearch-headless,elasticsearch-1.elasticsearch-headless,elasticsearch-2.elasticsearch-headless"
        - name: cluster.initial_master_nodes
          value: "elasticsearch-0,elasticsearch-1,elasticsearch-2"
        - name: ES_JAVA_OPTS
          value: "-Xms2g -Xmx2g"
        - name: xpack.security.enabled
          value: "false"
        ports:
        - containerPort: 9200
          name: http
        - containerPort: 9300
          name: transport
        volumeMounts:
        - name: elasticsearch-data
          mountPath: /usr/share/elasticsearch/data
        resources:
          requests:
            memory: "2Gi"
            cpu: "1000m"
          limits:
            memory: "4Gi"
            cpu: "2000m"
  volumeClaimTemplates:
  - metadata:
      name: elasticsearch-data
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: fast-ssd
      resources:
        requests:
          storage: 100Gi
```

#### Logstash配置
```yaml
# logstash-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: logstash-config
  namespace: logging
data:
  logstash.yml: |
    http.host: "0.0.0.0"
    path.config: /usr/share/logstash/pipeline
    xpack.monitoring.elasticsearch.hosts: ["http://elasticsearch:9200"]
  
  pipeline.conf: |
    input {
      beats {
        port => 5044
      }
      
      http {
        port => 8080
        codec => json
      }
    }
    
    filter {
      if [kubernetes] {
        mutate {
          add_field => { "cluster" => "production" }
        }
        
        # 解析JSON日志
        if [message] =~ /^\{.*\}$/ {
          json {
            source => "message"
          }
        }
        
        # 添加时间戳
        date {
          match => [ "timestamp", "ISO8601" ]
        }
        
        # 提取错误信息
        if [level] == "ERROR" {
          grok {
            match => { "message" => "%{GREEDYDATA:error_message}" }
          }
        }
      }
    }
    
    output {
      elasticsearch {
        hosts => ["http://elasticsearch:9200"]
        index => "logstash-%{[kubernetes][namespace]}-%{+YYYY.MM.dd}"
      }
      
      # 输出到控制台用于调试
      stdout {
        codec => rubydebug
      }
    }
```

#### Filebeat DaemonSet
```yaml
# filebeat.yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: filebeat
  namespace: logging
spec:
  selector:
    matchLabels:
      app: filebeat
  template:
    metadata:
      labels:
        app: filebeat
    spec:
      serviceAccountName: filebeat
      terminationGracePeriodSeconds: 30
      containers:
      - name: filebeat
        image: docker.elastic.co/beats/filebeat:8.5.0
        args: [
          "-c", "/etc/filebeat.yml",
          "-e",
        ]
        env:
        - name: ELASTICSEARCH_HOST
          value: elasticsearch
        - name: ELASTICSEARCH_PORT
          value: "9200"
        - name: NODE_NAME
          valueFrom:
            fieldRef:
              fieldPath: spec.nodeName
        securityContext:
          runAsUser: 0
        resources:
          limits:
            memory: 200Mi
            cpu: 100m
          requests:
            memory: 100Mi
            cpu: 50m
        volumeMounts:
        - name: config
          mountPath: /etc/filebeat.yml
          readOnly: true
          subPath: filebeat.yml
        - name: data
          mountPath: /usr/share/filebeat/data
        - name: varlibdockercontainers
          mountPath: /var/lib/docker/containers
          readOnly: true
        - name: varlog
          mountPath: /var/log
          readOnly: true
      volumes:
      - name: config
        configMap:
          defaultMode: 0600
          name: filebeat-config
      - name: varlibdockercontainers
        hostPath:
          path: /var/lib/docker/containers
      - name: varlog
        hostPath:
          path: /var/log
      - name: data
        hostPath:
          path: /var/lib/filebeat-data
          type: DirectoryOrCreate
```

### 5.2 分布式链路追踪

#### Jaeger部署配置
```yaml
# jaeger.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jaeger
  namespace: tracing
spec:
  replicas: 1
  selector:
    matchLabels:
      app: jaeger
  template:
    metadata:
      labels:
        app: jaeger
    spec:
      containers:
      - name: jaeger
        image: jaegertracing/all-in-one:latest
        env:
        - name: COLLECTOR_ZIPKIN_HTTP_PORT
          value: "9411"
        - name: SPAN_STORAGE_TYPE
          value: "elasticsearch"
        - name: ES_SERVER_URLS
          value: "http://elasticsearch.logging:9200"
        - name: ES_INDEX_PREFIX
          value: "jaeger"
        ports:
        - containerPort: 16686
          name: ui
        - containerPort: 14268
          name: collector
        - containerPort: 14250
          name: grpc
        - containerPort: 9411
          name: zipkin
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "1Gi"
            cpu: "500m"
---
apiVersion: v1
kind: Service
metadata:
  name: jaeger
  namespace: tracing
spec:
  ports:
  - port: 16686
    targetPort: 16686
    name: ui
  - port: 14268
    targetPort: 14268
    name: collector
  - port: 14250
    targetPort: 14250
    name: grpc
  - port: 9411
    targetPort: 9411
    name: zipkin
  selector:
    app: jaeger
```

## 安全与合规

### 6.1 Pod安全策略

#### Pod Security Standards
```yaml
# pod-security-policy.yaml
apiVersion: policy/v1beta1
kind: PodSecurityPolicy
metadata:
  name: restricted
spec:
  privileged: false
  allowPrivilegeEscalation: false
  requiredDropCapabilities:
    - ALL
  volumes:
    - 'configMap'
    - 'emptyDir'
    - 'projected'
    - 'secret'
    - 'downwardAPI'
    - 'persistentVolumeClaim'
  runAsUser:
    rule: 'MustRunAsNonRoot'
  seLinux:
    rule: 'RunAsAny'
  fsGroup:
    rule: 'RunAsAny'
  readOnlyRootFilesystem: true
---
apiVersion: v1
kind: Namespace
metadata:
  name: secure-namespace
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
```

#### Network Policies
```yaml
# network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: microservices-netpol
  namespace: microservices
spec:
  podSelector:
    matchLabels:
      app: user-service
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: api-gateway
    - podSelector:
        matchLabels:
          app: api-gateway
    ports:
    - protocol: TCP
      port: 8080
  egress:
   - to:
     - namespaceSelector:
         matchLabels:
           name: microservices
     - podSelector:
         matchLabels:
           app: postgres
     ports:
     - protocol: TCP
       port: 5432
   - to:
     - namespaceSelector:
         matchLabels:
           name: microservices
     - podSelector:
         matchLabels:
           app: redis
     ports:
     - protocol: TCP
       port: 6379
   # 允许DNS查询
   - to: []
     ports:
     - protocol: UDP
       port: 53
```

### 6.2 RBAC权限控制

#### 服务账户与角色绑定
```yaml
# rbac.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: user-service-sa
  namespace: microservices
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: microservices
  name: user-service-role
rules:
- apiGroups: [""]
  resources: ["configmaps", "secrets"]
  verbs: ["get", "list"]
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: user-service-binding
  namespace: microservices
subjects:
- kind: ServiceAccount
  name: user-service-sa
  namespace: microservices
roleRef:
  kind: Role
  name: user-service-role
  apiGroup: rbac.authorization.k8s.io
```

### 6.3 密钥管理

#### External Secrets Operator
```yaml
# external-secrets.yaml
apiVersion: external-secrets.io/v1beta1
kind: SecretStore
metadata:
  name: vault-backend
  namespace: microservices
spec:
  provider:
    vault:
      server: "https://vault.company.com"
      path: "secret"
      version: "v2"
      auth:
        kubernetes:
          mountPath: "kubernetes"
          role: "microservices"
          serviceAccountRef:
            name: "external-secrets-sa"
---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: app-secrets
  namespace: microservices
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: app-secrets
    creationPolicy: Owner
  data:
  - secretKey: db-password
    remoteRef:
      key: database
      property: password
  - secretKey: redis-password
    remoteRef:
      key: redis
      property: password
  - secretKey: jwt-secret
    remoteRef:
      key: jwt
      property: secret
```

## 备份与恢复

### 7.1 数据备份策略

#### Velero备份配置
```yaml
# velero-backup.yaml
apiVersion: velero.io/v1
kind: Schedule
metadata:
  name: daily-backup
  namespace: velero
spec:
  schedule: "0 2 * * *"  # 每天凌晨2点
  template:
    includedNamespaces:
    - microservices
    - monitoring
    - logging
    excludedResources:
    - events
    - events.events.k8s.io
    storageLocation: default
    volumeSnapshotLocations:
    - default
    ttl: 720h0m0s  # 30天保留期
    hooks:
      resources:
      - name: postgres-backup-hook
        includedNamespaces:
        - microservices
        labelSelector:
          matchLabels:
            app: postgres
        pre:
        - exec:
            container: postgres
            command:
            - /bin/bash
            - -c
            - "pg_dump -U postgres myapp > /tmp/backup.sql"
        post:
        - exec:
            container: postgres
            command:
            - /bin/bash
            - -c
            - "rm -f /tmp/backup.sql"
---
apiVersion: velero.io/v1
kind: BackupStorageLocation
metadata:
  name: default
  namespace: velero
spec:
  provider: aws
  objectStorage:
    bucket: company-k8s-backups
    prefix: production
  config:
    region: us-west-2
    s3ForcePathStyle: "false"
```

#### 数据库备份脚本
```bash
#!/bin/bash
# postgres-backup.sh

set -e

# 配置变量
NAMESPACE="microservices"
POD_NAME="postgres-0"
DB_NAME="myapp"
DB_USER="postgres"
BACKUP_DIR="/backups"
S3_BUCKET="company-db-backups"
RETENTION_DAYS=30

# 创建备份目录
mkdir -p $BACKUP_DIR

# 生成备份文件名
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${DB_NAME}_${TIMESTAMP}.sql"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_FILE}"

echo "Starting backup of database ${DB_NAME}..."

# 执行数据库备份
kubectl exec -n $NAMESPACE $POD_NAME -- pg_dump -U $DB_USER -d $DB_NAME > $BACKUP_PATH

if [ $? -eq 0 ]; then
    echo "Database backup completed: $BACKUP_PATH"
    
    # 压缩备份文件
    gzip $BACKUP_PATH
    BACKUP_PATH="${BACKUP_PATH}.gz"
    
    # 上传到S3
    aws s3 cp $BACKUP_PATH s3://$S3_BUCKET/postgres/
    
    if [ $? -eq 0 ]; then
        echo "Backup uploaded to S3 successfully"
        rm $BACKUP_PATH
    else
        echo "Failed to upload backup to S3"
        exit 1
    fi
    
    # 清理旧备份
    aws s3 ls s3://$S3_BUCKET/postgres/ | while read -r line; do
        createDate=$(echo $line | awk '{print $1" "$2}')
        createDate=$(date -d "$createDate" +%s)
        olderThan=$(date -d "$RETENTION_DAYS days ago" +%s)
        if [[ $createDate -lt $olderThan ]]; then
            fileName=$(echo $line | awk '{print $4}')
            if [[ $fileName != "" ]]; then
                aws s3 rm s3://$S3_BUCKET/postgres/$fileName
                echo "Deleted old backup: $fileName"
            fi
        fi
    done
else
    echo "Database backup failed"
    exit 1
fi

echo "Backup process completed"
```

### 7.2 灾难恢复

#### 集群恢复流程
```yaml
# disaster-recovery.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: disaster-recovery-runbook
  namespace: kube-system
data:
  recovery-steps.md: |
    # 灾难恢复流程
    
    ## 1. 评估损坏程度
    ```bash
    # 检查节点状态
    kubectl get nodes
    
    # 检查关键组件
    kubectl get pods -n kube-system
    
    # 检查存储状态
    kubectl get pv,pvc --all-namespaces
    ```
    
    ## 2. 恢复etcd集群
    ```bash
    # 停止所有API服务器
    sudo systemctl stop kubelet
    
    # 从备份恢复etcd
    sudo etcdctl snapshot restore /backup/etcd-snapshot.db \
      --data-dir=/var/lib/etcd-restore \
      --name=master-1 \
      --initial-cluster=master-1=https://192.168.1.10:2380 \
      --initial-advertise-peer-urls=https://192.168.1.10:2380
    
    # 更新etcd配置
    sudo mv /var/lib/etcd /var/lib/etcd.old
    sudo mv /var/lib/etcd-restore /var/lib/etcd
    
    # 重启服务
    sudo systemctl start kubelet
    ```
    
    ## 3. 恢复应用数据
    ```bash
    # 使用Velero恢复
    velero restore create --from-backup daily-backup-20231201020000
    
    # 监控恢复进度
    velero restore get
    velero restore describe <restore-name>
    ```
    
    ## 4. 验证恢复结果
    ```bash
    # 检查所有Pod状态
    kubectl get pods --all-namespaces
    
    # 验证服务可用性
    kubectl get svc --all-namespaces
    
    # 运行健康检查
    kubectl run test-pod --image=curlimages/curl --rm -it -- \
      curl -f http://user-service.microservices/health
    ```
```

## 性能优化

### 8.1 资源优化

#### 垂直Pod自动扩缩容
```yaml
# vpa.yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: user-service-vpa
  namespace: microservices
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: user-service
  updatePolicy:
    updateMode: "Auto"
  resourcePolicy:
    containerPolicies:
    - containerName: user-service
      minAllowed:
        cpu: 100m
        memory: 128Mi
      maxAllowed:
        cpu: 2
        memory: 2Gi
      controlledResources: ["cpu", "memory"]
      controlledValues: RequestsAndLimits
```

#### 集群自动扩缩容
```yaml
# cluster-autoscaler.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cluster-autoscaler
  namespace: kube-system
spec:
  replicas: 1
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
        - --node-group-auto-discovery=asg:tag=k8s.io/cluster-autoscaler/enabled,k8s.io/cluster-autoscaler/production
        - --balance-similar-node-groups
        - --skip-nodes-with-system-pods=false
        - --scale-down-delay-after-add=10m
        - --scale-down-unneeded-time=10m
        - --scale-down-delay-after-delete=10s
        - --scale-down-delay-after-failure=3m
        - --scale-down-utilization-threshold=0.5
        env:
        - name: AWS_REGION
          value: us-west-2
```

### 8.2 网络优化

#### CNI性能调优
```yaml
# calico-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: calico-config
  namespace: kube-system
data:
  # 启用eBPF数据平面
  felix_bpf_enabled: "true"
  felix_bpf_kube_proxy_iptables_cleanup_enabled: "true"
  felix_bpf_external_service_mode: "Tunnel"
  
  # 优化性能参数
  felix_reporting_interval: "30s"
  felix_log_severity_screen: "Info"
  felix_health_enabled: "true"
  felix_prometheus_metrics_enabled: "true"
  
  # 网络策略优化
  felix_policy_sync_path_prefix: "/var/run/nodeagent"
  felix_default_endpoint_to_host_action: "ACCEPT"
  
  # IPIP隧道优化
  calico_backend: "bird"
  cluster_type: "k8s,bgp"
  ipip_enabled: "true"
  ipip_mode: "CrossSubnet"
```

## 故障排除

### 9.1 常见问题诊断

#### 诊断脚本
```bash
#!/bin/bash
# k8s-troubleshoot.sh

echo "=== Kubernetes集群诊断工具 ==="
echo

# 检查集群基本状态
echo "1. 集群节点状态:"
kubectl get nodes -o wide
echo

# 检查系统Pod
echo "2. 系统组件状态:"
kubectl get pods -n kube-system
echo

# 检查资源使用情况
echo "3. 节点资源使用:"
kubectl top nodes
echo

# 检查存储状态
echo "4. 存储卷状态:"
kubectl get pv,pvc --all-namespaces
echo

# 检查网络组件
echo "5. 网络组件状态:"
kubectl get pods -n kube-system | grep -E "(calico|flannel|weave|cilium)"
echo

# 检查DNS
echo "6. DNS解析测试:"
kubectl run dns-test --image=busybox --rm -it --restart=Never -- nslookup kubernetes.default
echo

# 检查证书有效期
echo "7. 证书有效期检查:"
for cert in /etc/kubernetes/pki/*.crt; do
    echo "$cert:"
    openssl x509 -in "$cert" -noout -enddate
done
echo

# 检查事件
echo "8. 最近的集群事件:"
kubectl get events --sort-by=.metadata.creationTimestamp --all-namespaces | tail -20
echo

# 检查资源配额
echo "9. 资源配额使用:"
kubectl describe quota --all-namespaces
echo

# 检查服务端点
echo "10. 服务端点状态:"
kubectl get endpoints --all-namespaces
echo

echo "=== 诊断完成 ==="
```

#### 性能分析工具
```yaml
# performance-analysis.yaml
apiVersion: v1
kind: Pod
metadata:
  name: perf-analyzer
  namespace: default
spec:
  containers:
  - name: analyzer
    image: nicolaka/netshoot
    command: ["/bin/bash"]
    args: ["-c", "while true; do sleep 3600; done"]
    securityContext:
      privileged: true
    volumeMounts:
    - name: proc
      mountPath: /host/proc
      readOnly: true
    - name: sys
      mountPath: /host/sys
      readOnly: true
  volumes:
  - name: proc
    hostPath:
      path: /proc
  - name: sys
    hostPath:
      path: /sys
  hostNetwork: true
  hostPID: true
```

### 9.2 日志分析

#### 日志聚合查询
```bash
#!/bin/bash
# log-analysis.sh

# 查询错误日志
echo "=== 错误日志分析 ==="
kubectl logs -l app=user-service --tail=1000 | grep -i error

# 查询性能相关日志
echo "=== 性能日志分析 ==="
kubectl logs -l app=user-service --tail=1000 | grep -E "(slow|timeout|latency)"

# 查询资源相关日志
echo "=== 资源日志分析 ==="
kubectl describe nodes | grep -A 5 -B 5 "OutOfMemory\|DiskPressure\|PIDPressure"

# 分析Pod重启原因
echo "=== Pod重启分析 ==="
kubectl get pods --all-namespaces -o json | jq -r '.items[] | select(.status.restartCount > 0) | "\(.metadata.namespace)/\(.metadata.name): \(.status.restartCount) restarts"'

# 网络连接分析
echo "=== 网络连接分析 ==="
kubectl exec -it perf-analyzer -- netstat -tulpn | grep LISTEN
```

## 最佳实践总结

### 10.1 开发最佳实践

1. **容器化原则**
   - 使用多阶段构建减小镜像大小
   - 运行非root用户提高安全性
   - 实现健康检查和优雅关闭
   - 使用.dockerignore减少构建上下文

2. **Kubernetes部署原则**
   - 设置合适的资源请求和限制
   - 使用命名空间隔离环境
   - 实现Pod反亲和性提高可用性
   - 配置存活性和就绪性探针

3. **安全最佳实践**
   - 启用RBAC权限控制
   - 使用网络策略限制流量
   - 定期扫描镜像漏洞
   - 实施Pod安全策略

### 10.2 运维最佳实践

1. **监控告警**
   - 建立完整的监控体系
   - 设置合理的告警阈值
   - 实现分布式链路追踪
   - 定期进行性能调优

2. **备份恢复**
   - 制定完整的备份策略
   - 定期测试恢复流程
   - 建立灾难恢复预案
   - 实现自动化备份

3. **CI/CD流水线**
   - 实现自动化测试
   - 建立多环境部署
   - 实施蓝绿部署或金丝雀发布
   - 集成安全扫描

### 10.3 架构演进路径

1. **单体应用 → 微服务**
   - 识别服务边界
   - 数据库拆分
   - 服务间通信
   - 分布式事务处理

2. **传统部署 → 容器化**
   - 应用容器化改造
   - 配置外部化
   - 状态分离
   - 服务发现

3. **容器化 → 云原生**
   - 服务网格引入
   - 可观测性建设
   - 自动化运维
   - 多云部署

---

## 结语

本文档涵盖了DevOps云重建的核心技术栈，从Docker容器化到Kubernetes集群管理，从CI/CD流水线到云原生架构设计，提供了完整的实践指南。通过这些最佳实践，可以构建高可用、可扩展、安全的云原生应用平台。

在实际应用中，需要根据具体业务需求和技术栈选择合适的方案，并持续优化和改进。云原生技术栈在不断演进，建议保持学习和跟进最新的技术发展趋势。