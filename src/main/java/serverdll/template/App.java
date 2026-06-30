package serverdll.template;

import serverdll.serverfile.SockServer;
import serverdll.serverfile.Tasks.UTaskWorkerPool;
import serverdll.serverfile.UEventDispatcher;
import serverdll.serverfile.UHttpRouteDispatcher;
import serverdll.serverfile.UMessageFactory;
import serverdll.serverfile.utils.GameUtility;

/**
 * 独立 Server 模板入口。
 * 默认端口：HTTP 17080 / WS 17081 / TCP 17082
 * 启动参数：tcpPort wsPort httpPort
 * 静态文档：static/ 目录，浏览器访问 http://127.0.0.1:17080/
 */
public final class App {
    public static final int DEFAULT_HTTP = 17080;
    public static final int DEFAULT_WS = 17081;
    public static final int DEFAULT_TCP = 17082;

    public static void main(String[] args) throws Exception {
        System.out.println("Server Template Starting...");
        UMessageFactory.Instance.Awake("serverdll.template.messages");  /* 启动扫描 */
        UEventDispatcher.Instance.Awake();
        UHttpRouteDispatcher.Instance.Awake();  /* 建立静态文件夹 */
        GameUtility.initStaticFolder("static");
        UTaskWorkerPool.Instance.Start();  /* 开启多线程workpool */

        int tcpPort = args.length > 0 ? Integer.parseInt(args[0]) : DEFAULT_TCP;
        int wsPort = args.length > 1 ? Integer.parseInt(args[1]) : DEFAULT_WS;
        int httpPort = args.length > 2 ? Integer.parseInt(args[2]) : DEFAULT_HTTP;

        SockServer server = new SockServer();
        server.StartNetty(tcpPort, wsPort, false);
        server.StartHttpServer(httpPort, false);
        System.out.println("Server Template Ready.");
        System.out.println("  Docs  http://127.0.0.1:" + httpPort + "/");
        System.out.println("  HTTP  http://127.0.0.1:" + httpPort + "/template/health");
        System.out.println("  Files upload POST /template/files/upload  -> static/uploads/");
        System.out.println("  Files download GET  /template/files/download/{name}");
        System.out.println("  Files list   GET  /template/files/list");
        System.out.println("  WS    ws://127.0.0.1:" + wsPort + "/websocket");
        System.out.println("  TCP   127.0.0.1:" + tcpPort);
        System.out.println("  Test  py -3 tests/test_client.py");
        Thread.currentThread().join();
    }
}
