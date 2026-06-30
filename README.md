# Server 模板（独立分发包）

基于 `serverdll:framework` 的最小 Server 示例，演示 **HTTP / WebSocket / TCP** 三种协议。

## 目录结构

```
serverTemplate/
  static/index.html                  # HTTP 说明文档（浏览器打开 /）
  lib/framework-1.0.0-SNAPSHOT.jar   # framework 依赖（须随包分发）
  src/main/java/serverdll/template/  # 业务代码（从此扩展）
  tests/test_client.py               # Python 联调脚本
  scripts/prepare-lib.ps1            # 从主工程复制 framework JAR
  scripts/run.bat                    # 构建并启动
  pom.xml
```

## 环境要求

- JDK 17+
- Maven 3.8+
- Python 3.8+（联调脚本，WS 需 `pip install websocket-client`）

## 快速开始

### 1. 准备 framework JAR

在 **Agent_java 主工程** 根目录：

```powershell
mvn -pl framework clean package
cd serverTemplate
.\scripts\prepare-lib.ps1
```

若只拿到分发 zip（已含 `lib/framework-*.jar`），在 `serverTemplate` 目录执行一次：

```powershell
.\scripts\prepare-lib.ps1
```

（从 lib 安装到本地 Maven 仓库，再 `mvn package`）

### 2. 构建并运行

```powershell
mvn clean package
java -jar target/server-template-1.0.0.jar
```

或：`scripts\run.bat`

默认端口：

| 协议 | 端口 | 测试地址 |
|------|------|----------|
| HTTP | 17080 | `http://127.0.0.1:17080/`（说明文档）· `/template/health` |
| WS   | 17081 | `ws://127.0.0.1:17081/websocket` |
| TCP  | 17082 | `127.0.0.1:17082` |

自定义端口：`java -jar target/server-template-1.0.0.jar <tcp> <ws> <http>`

### 3. Python 联调

```powershell
pip install websocket-client
py -3 tests/test_client.py
```

## 开发指引

1. **HTTP**：在 `controllers/` 下加 `@UHttpController` + `@UHttpRequestMapping`
2. **TCP/WS**：在 `messages/` 定义 `@UMessageMeta(cmd=N)` 消息类，在 `handlers/` 加 `@UController` + `@AIMapping`
3. `App.java` 中 `UMessageFactory.Instance.Awake("serverdll.template.messages")` 注册消息包
4. 包名须以 `serverdll` 开头（框架 Reflections 扫描范围）

---

## 压力测试（vs ASprintBootServer · 隔离并发）

对比对象：`D:\ASprintBootServer`（Spring Boot 3 参考实现）。

**方法**：同机**隔离压测**（一次只运行一个服务），并发档位 100 / 400 / 1000 / 2000，每协议每档 **10000** 请求。HTTP 均使用 keep-alive；WS 客户端均为 async `websockets`。

### 复现命令

```powershell
pip install websockets
cd d:\serverTemplate_java
.\scripts\run_isolated_bench.ps1 -Concurrency "100,400,1000,2000" -Count 10000
```

原始数据：[`bench_data/template.json`](bench_data/template.json) · [`bench_data/spring.json`](bench_data/spring.json)  
完整报告：[`bench_readme_latest.md`](bench_readme_latest.md)

### 测试环境（2026-06-30 08:54 · 最后一轮）

| 项目 | 值 |
|------|-----|
| 主机 | 127.0.0.1 |
| 并发 | 100, 400, 1000, 2000 |
| 每档请求数 | 10000 / 协议 |
| serverTemplate | HTTP :17080 · WS :17081 · TCP :17082 |
| ASprintBoot | HTTP/WS :8180 · TCP :9011 |

### 吞吐量对比 (req/s)

| 并发 | 协议 | serverTemplate | ASprintBoot | 领先 |
|------|------|----------------|-------------|------|
| 100 | HTTP | 5514 | 5030 | **serverTemplate** (+10%) |
| 100 | WS | 12495 | 12628 | ASprintBoot |
| 100 | TCP | 20467 | 19527 | **serverTemplate** (+5%) |
| 400 | HTTP | 7399 | 5723 | **serverTemplate** (+29%) |
| 400 | WS | 8951 | 9040 | ASprintBoot |
| 400 | TCP | 15614 | 20278 | ASprintBoot |
| 1000 | HTTP | 5612 | 5318 | **serverTemplate** (+6%) |
| 1000 | WS | 5897 | 5084 | **serverTemplate** (+16%) |
| 1000 | TCP | 11951 | 12906 | ASprintBoot |
| 2000 | HTTP | 4820 | 4374 | **serverTemplate** (+10%) |
| 2000 | WS | 4073 | 2931 | **serverTemplate** (+39%) |
| 2000 | TCP | 9909 | 10216 | ASprintBoot |

### 综合结论

| 指标 | serverTemplate | ASprintBoot |
|------|----------------|-------------|
| 吞吐领先场次（12 场） | **7** | 5 |
| 总错误数 | **0** | **0** |
| 进程崩溃 | 无 | 无 |
| **判定** | **serverTemplate 综合能力更优** | |

**解读**：

- **HTTP**：四个并发档位 **全部领先**（+6%～+29%）。
- **WS**：1000 / 2000 并发 **明显领先**（2000 并发 +39%）；100 / 400 略逊几个百分点。
- **TCP**：100 并发领先；400 / 1000 / 2000 Spring Netty 直 echo 路径更快（template 走完整 Controller 路径）。
- **稳定性**：两栈 **零错误**，压测后服务正常退出。

> WS/TCP 协议栈不同，对比的是同机各协议 echo/health 路径的吞吐与延迟，非字节级等价负载。

### 延迟快照（p50 ms · 并发 2000）

| 协议 | serverTemplate | ASprintBoot |
|------|----------------|-------------|
| HTTP | 17.0 | 19.5 |
| WS | 156.9 | 197.2 |
| TCP | 5.9 | 8.3 |
