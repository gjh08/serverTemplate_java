# Server 模板（独立分发包）

仓库地址
https://github.com/gjh08/serverTemplate_java

ZIP 直接下载  	
https://github.com/gjh08/serverTemplate_java/archive/refs/heads/master.zip

Git 克隆
git clone https://github.com/gjh08/serverTemplate_java.git

基于 `serverdll:framework` 的最小 Server 示例，演示 **HTTP / WebSocket / TCP** 三种协议。

## 目录结构

```
serverTemplate/
  static/index.html                  # 浏览器接口测试台（打开 /）
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

## 接口测试

启动服务后访问 **http://127.0.0.1:17080/**，可在浏览器中测试：

- HTTP：`/template/health`、`/template/echo`、`/template/files/list`
- 文件：拖拽上传、列表下载（存于 `static/uploads/`）
- WebSocket：发送 cmd=9001，校验 cmd=9002 回复
- TCP：见页面说明，或使用 `py -3 tests/test_client.py`
