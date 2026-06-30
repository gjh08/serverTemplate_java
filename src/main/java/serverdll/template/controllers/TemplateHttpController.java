package serverdll.template.controllers;

import io.netty.handler.codec.http.FullHttpRequest;
import io.netty.handler.codec.http.FullHttpResponse;
import serverdll.serverfile.HttpRouteContext;
import serverdll.serverfile.UHttpController;
import serverdll.serverfile.UHttpRequestMapping;
import serverdll.serverfile.utils.HttpFileTransferHelper;

@UHttpController
public final class TemplateHttpController {

    @UHttpRequestMapping(uri = "/template/health", method = "GET")
    public String health() {
        return "{\"code\":0,\"message\":\"ok\",\"data\":{\"service\":\"server-template\",\"status\":\"ok\",\"ts\":"
                + System.currentTimeMillis() + "}}";
    }

    @UHttpRequestMapping(uri = "/template/echo")
    public String echo() {
        return "{\"code\":0,\"message\":\"ok\",\"data\":{\"echo\":\"pong\",\"channel\":\"http\",\"ts\":"
                + System.currentTimeMillis() + "}}";
    }

    /** 上传文件到 static/uploads（multipart 字段 file，或 raw body + ?name=xxx） */
    @UHttpRequestMapping(uri = "/template/files/upload", method = "POST")
    public String uploadFile(FullHttpRequest request) {
        return HttpFileTransferHelper.upload(request);
    }

    /** 下载 static/uploads 下的文件 */
    @UHttpRequestMapping(uri = "/template/files/download/{name}", method = "GET")
    public FullHttpResponse downloadFile() {
        String name = HttpRouteContext.pathVariable("name");
        return HttpFileTransferHelper.download(name);
    }

    /** 列出 static/uploads 目录 */
    @UHttpRequestMapping(uri = "/template/files/list", method = "GET")
    public String listFiles() {
        return HttpFileTransferHelper.listJson();
    }
}
