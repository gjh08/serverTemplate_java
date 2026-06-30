package serverdll.template.messages;

import serverdll.serverfile.UMessage;
import serverdll.serverfile.UMessageMeta;

@UMessageMeta(cmd = 9001)
public class EchoRequest extends UMessage {
    public long seq;
    public String payload = "";
}
