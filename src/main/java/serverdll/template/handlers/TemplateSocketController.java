package serverdll.template.handlers;

import serverdll.serverfile.MagicAI.AIMapping;
import serverdll.serverfile.SessionManager.USession;
import serverdll.serverfile.UController;
import serverdll.template.messages.EchoRequest;
import serverdll.template.messages.EchoResponse;

@UController
public final class TemplateSocketController {

    @AIMapping
    public EchoResponse echo(USession session, EchoRequest req) {
        EchoResponse resp = new EchoResponse();
        if (req != null) {
            resp.seq = req.seq;
            resp.payload = req.payload != null ? req.payload : "";
        }
        resp.channel = session != null && session.isWebSocket ? "ws" : "tcp";
        resp.ts = req != null ? req.seq : 0L;
        return resp;
    }
}
