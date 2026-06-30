package serverdll.template.support;

import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.LinkedHashMap;
import java.util.Map;

public final class JsonHelper {
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private JsonHelper() {}

    public static String ok(Object data) {
        Map<String, Object> wrap = new LinkedHashMap<>();
        wrap.put("code", 0);
        wrap.put("message", "ok");
        wrap.put("data", data);
        return toJson(wrap);
    }

    public static String toJson(Object value) {
        try {
            return MAPPER.writeValueAsString(value);
        } catch (Exception e) {
            return "{\"code\":500,\"message\":\"json error\"}";
        }
    }
}
