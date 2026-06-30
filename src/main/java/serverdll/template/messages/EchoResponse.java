package serverdll.template.messages;

import serverdll.serverfile.UMessage;
import serverdll.serverfile.UMessageMeta;

@UMessageMeta(cmd = 9002)
public class EchoResponse extends UMessage {
    public long seq;
    public String payload = "";
    public String channel = "";
    public long ts;
}
