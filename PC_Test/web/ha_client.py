"""Home Assistant REST API 客户端（可选硬件通道）。

仪表盘设备控制默认走 MCP 直连 Arduino（web/hardware.py）；本客户端保留别组
HA 集成能力，供「硬件管理」页配置/探测 HA 设备使用。配置文件存 data/ha_config.json，
不含任何真实密钥的默认值，密钥只存在于本机不入库。
"""
import json
import logging
import threading

import requests

from .config import HA_CONFIG_PATH
from .utils import ConnectionHealth, retry_with_backoff

logger = logging.getLogger(__name__)

_DEFAULT_MAPPING = {
    'temperature_sensor': 'sensor.indoor_temperature',
    'humidity_sensor': 'sensor.indoor_humidity',
    'front_door': 'binary_sensor.front_door',
    'living_window': 'binary_sensor.living_room_window',
    'main_light': 'light.living_room',
    'fan': 'fan.smart_fan',
    'ac': 'climate.smart_ac',
    'door_lock': 'lock.front_door',
    'camera': 'camera.security_camera',
}


class HomeAssistantClient:
    def __init__(self, config_path=None):
        self.config_path = str(config_path or HA_CONFIG_PATH)
        self.config = self._load_config(self.config_path)
        self.base_url = self.config.get('ha_url', 'http://localhost:8123')
        self.token = self.config.get('ha_token', '')
        self.connected = False
        self.entities = {}
        self.health = ConnectionHealth("HomeAssistant")
        self._config_lock = threading.Lock()

    def _load_config(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            logger.warning("HA config not found at %s, using defaults", path)
            return {
                'ha_url': 'http://localhost:8123',
                'ha_token': '',
                'device_mapping': dict(_DEFAULT_MAPPING),
                'poll_interval': 10,
            }

    def _headers(self):
        return {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json',
        }

    # ==================== 连接管理 ====================

    @retry_with_backoff(max_retries=2, base_delay=0.5, max_delay=4.0,
                        exceptions=(requests.exceptions.ConnectionError,
                                    requests.exceptions.Timeout))
    def test_connection(self):
        try:
            resp = requests.get(f'{self.base_url}/api/', headers=self._headers(),
                                timeout=(3, 5))
            if resp.status_code == 200:
                self.connected = True
                self.health.record_success()
                return {'connected': True,
                        'message': resp.json().get('message', 'API running')}
            self.connected = False
            self.health.record_failure(f'HTTP {resp.status_code}')
            return {'connected': False, 'message': f'HTTP {resp.status_code}'}
        except requests.exceptions.ConnectionError:
            self.connected = False
            self.health.record_failure('connection error')
            return {'connected': False,
                    'message': '无法连接到 Home Assistant，请检查地址和端口'}
        except requests.exceptions.Timeout:
            self.connected = False
            self.health.record_failure('timeout')
            return {'connected': False, 'message': '连接超时，HA 响应过慢'}
        except Exception as e:
            self.connected = False
            self.health.record_failure(str(e))
            return {'connected': False, 'message': str(e)}

    @retry_with_backoff(max_retries=1, base_delay=0.5, max_delay=2.0,
                        exceptions=(requests.exceptions.ConnectionError,
                                    requests.exceptions.Timeout))
    def get_config(self):
        try:
            resp = requests.get(f'{self.base_url}/api/config',
                                headers=self._headers(), timeout=(3, 8))
            if resp.status_code == 200:
                self.health.record_success()
                data = resp.json()
                return {
                    'version': data.get('version'),
                    'location': data.get('location_name'),
                    'latitude': data.get('latitude'),
                    'longitude': data.get('longitude'),
                    'timezone': data.get('time_zone'),
                    'unit_system': data.get('unit_system'),
                }
        except Exception as e:
            logger.error('获取HA配置失败: %s', e)
            self.health.record_failure(str(e))
        return None

    def save_config(self, ha_url, ha_token, device_mapping=None):
        with self._config_lock:
            self.config['ha_url'] = ha_url
            self.config['ha_token'] = ha_token
            if device_mapping:
                self.config['device_mapping'] = device_mapping
            self.base_url = ha_url
            self.token = ha_token
            try:
                with open(self.config_path, 'w', encoding='utf-8') as f:
                    json.dump(self.config, f, indent=2, ensure_ascii=False)
                return True
            except Exception as e:
                logger.error("保存HA配置失败: %s", e)
                return False

    # ==================== 实体状态 ====================

    @retry_with_backoff(max_retries=2, base_delay=0.3, max_delay=3.0,
                        exceptions=(requests.exceptions.ConnectionError,
                                    requests.exceptions.Timeout))
    def get_all_states(self):
        try:
            resp = requests.get(f'{self.base_url}/api/states',
                                headers=self._headers(), timeout=(3, 15))
            if resp.status_code == 200:
                states = resp.json()
                self.entities = {s['entity_id']: s for s in states}
                self.health.record_success()
                return self.entities
        except Exception as e:
            logger.error('获取状态失败: %s', e)
            self.health.record_failure(str(e))
        return {}

    @retry_with_backoff(max_retries=1, base_delay=0.3, max_delay=2.0,
                        exceptions=(requests.exceptions.ConnectionError,
                                    requests.exceptions.Timeout))
    def get_entity(self, entity_id):
        try:
            resp = requests.get(f'{self.base_url}/api/states/{entity_id}',
                                headers=self._headers(), timeout=(3, 5))
            if resp.status_code == 200:
                self.health.record_success()
                return resp.json()
        except Exception as e:
            logger.error('获取实体 %s 失败: %s', entity_id, e)
            self.health.record_failure(str(e))
        return None

    # ==================== 服务调用 ====================

    @retry_with_backoff(max_retries=2, base_delay=0.5, max_delay=4.0,
                        exceptions=(requests.exceptions.ConnectionError,
                                    requests.exceptions.Timeout))
    def call_service(self, domain, service, entity_id, service_data=None):
        try:
            data = {'entity_id': entity_id}
            if service_data:
                data.update(service_data)
            resp = requests.post(
                f'{self.base_url}/api/services/{domain}/{service}',
                headers=self._headers(), json=data, timeout=(3, 12))
            if resp.status_code == 200:
                self.health.record_success()
                return {'success': True, 'changed_states': resp.json()}
            return {'success': False, 'status': resp.status_code}
        except Exception as e:
            logger.error('调用服务 %s.%s 失败: %s', domain, service, e)
            self.health.record_failure(str(e))
            return {'success': False, 'message': str(e)}

    # ==================== 便捷设备方法 ====================

    def get_temperature(self):
        state = self.get_entity(self.config['device_mapping'].get('temperature_sensor'))
        if state:
            try:
                return float(state.get('state', 0))
            except (ValueError, TypeError):
                return None
        return None

    def get_humidity(self):
        state = self.get_entity(self.config['device_mapping'].get('humidity_sensor'))
        if state:
            try:
                return float(state.get('state', 0))
            except (ValueError, TypeError):
                return None
        return None

    def control_light(self, action, brightness=None):
        eid = self.config['device_mapping'].get('main_light')
        service_data = {}
        if action == 'on' and brightness is not None:
            service_data['brightness_pct'] = brightness
        return self.call_service('light', action, eid,
                                 service_data if service_data else None)

    def control_fan(self, speed_pct=None):
        eid = self.config['device_mapping'].get('fan')
        if speed_pct is not None and speed_pct > 0:
            return self.call_service('fan', 'turn_on', eid, {'percentage': speed_pct})
        return self.call_service('fan', 'turn_off', eid)

    def control_ac(self, mode='off', temperature=None):
        eid = self.config['device_mapping'].get('ac')
        if mode == 'off':
            return self.call_service('climate', 'turn_off', eid)
        service_data = {'hvac_mode': mode}
        if temperature:
            service_data['temperature'] = temperature
        return self.call_service('climate', 'set_temperature', eid, service_data)

    def control_door(self, action='unlock'):
        eid = self.config['device_mapping'].get('door_lock')
        return self.call_service('lock', action, eid)

    def get_door_status(self):
        state = self.get_entity(self.config['device_mapping'].get('front_door'))
        return state.get('state') if state else None

    def get_window_status(self):
        state = self.get_entity(self.config['device_mapping'].get('living_window'))
        return state.get('state') if state else None

    def get_camera_image(self):
        eid = self.config['device_mapping'].get('camera')
        if not eid:
            return None
        try:
            resp = requests.get(
                f'{self.base_url}/api/camera_proxy/{eid}',
                headers=self._headers(), timeout=(3, 10))
            if resp.status_code == 200 and 'image' in resp.headers.get('content-type', ''):
                return resp.content
        except Exception as e:
            logger.error('获取摄像头图像失败: %s', e)
        return None

    # ==================== 设备映射/发现/历史 ====================

    def get_device_mapping(self):
        return self.config.get('device_mapping', {})

    def update_device_mapping(self, device_type, entity_id):
        self.config['device_mapping'][device_type] = entity_id
        return self.save_config(self.config['ha_url'], self.config['ha_token'],
                                self.config['device_mapping'])

    def get_discovered_devices(self):
        try:
            devices = []
            for eid, state in self.get_all_states().items():
                attrs = state.get('attributes', {})
                devices.append({
                    'entity_id': eid,
                    'state': state.get('state'),
                    'friendly_name': attrs.get('friendly_name', eid),
                    'domain': eid.split('.')[0],
                    'last_changed': state.get('last_changed'),
                })
            return sorted(devices, key=lambda x: x['friendly_name'])
        except Exception as e:
            logger.error('获取设备列表失败: %s', e)
            return []

    def get_history(self, entity_ids, start_time=None):
        try:
            params = {'filter_entity_id': ','.join(entity_ids), 'minimal_response': ''}
            if start_time:
                params['start'] = start_time
            resp = requests.get(f'{self.base_url}/api/history/period',
                                headers=self._headers(), params=params,
                                timeout=(3, 20))
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error('获取HA历史数据失败: %s', e)
        return []
