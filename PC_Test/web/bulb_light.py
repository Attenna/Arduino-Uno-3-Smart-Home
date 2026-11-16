"""摄像头灯泡检测触发开灯，通过现有设备命令收口器执行。"""
import threading
import time


class BulbLightLink:
    def __init__(self):
        self.lock = threading.Lock()
        self.last_attempt = None

    def process(self, detections, enabled, camera_source, activate):
        if not enabled:
            return {"state": "disabled", "message": "灯泡开灯联动已关闭"}
        if not camera_source:
            return {"state": "preview", "message": "上传图片仅用于识别预览"}
        if not any(d.get("label") == "light bulb" for d in detections):
            return {"state": "waiting", "message": "等待摄像头检测到灯泡"}
        with self.lock:
            now = time.monotonic()
            if self.last_attempt is not None and now - self.last_attempt < 30:
                return {"state": "cooldown", "message": "联动冷却中，30秒内最多尝试一次"}
            self.last_attempt = now
            ok, message = activate()
            return {"state": "success" if ok else "failed", "message": message}


def activate_light():
    from . import extensions, light_state
    from .api.devices import gate
    bridge = extensions.bridge
    if bridge is None:
        return False, "硬件服务未启动"
    current = extensions.db.get_current_status()
    brightness = int(current.get("light_brightness") or 100)
    style = light_state.from_status(current)
    count = current.get("light_count")
    target = ("on", brightness, style, count)

    def execute(value):
        status, level, selected_style, selected_count = value
        method, args, kwargs = light_state.hardware_plan(status, level, selected_style, selected_count)
        ok, message = getattr(bridge, method)(*args, **kwargs)
        if ok:
            values = light_state.status_values(status, level, selected_style, selected_count)
            extensions.db.update_status(**values)
            extensions.db.add_light_event("客厅主灯(灯泡检测联动)", values["light_status"], values["light_brightness"])
        return ok, message

    outcome, applied, ok, message = gate.submit("light", target, None, None, execute)
    if outcome == "stale" or applied != target:
        return False, "联动已被更新的灯光操作覆盖"
    return ok, "灯泡检测已触发开灯，硬件已确认" if ok else message
