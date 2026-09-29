// ==================== i18n 国际化模块 ====================
const I18N = {
    currentLang: localStorage.getItem('smart_home_lang') || 'zh',

    dict: {
        zh: {
            // 通用
            'nav.dashboard': '仪表盘',
            'nav.history': '历史数据',
            'nav.access': '门禁管理',
            'nav.lang': 'EN',
            'system.title': '智能家居控制系统',
            'system.online': '系统在线',
            'system.offline': '系统离线',

            // 温湿度
            'temp.title': '温湿度监控',
            'temp.humidity': '湿度',
            'temp.high': '最高',
            'temp.low': '最低',
            'temp.avg': '平均',
            'temp.normal': '正常',
            'temp.high_warn': '偏高',
            'temp.too_high': '过高',
            'temp.auto_fan': '温度过高将自动启动风扇',
            'temp.trend': '温度趋势',
            'temp.trend_24h': '温度趋势 (24小时)',
            'temp.label': '温度 (°C)',
            'humidity.label': '湿度 (%)',

            // 风扇
            'fan.title': '风扇 / 伺服电机',
            'fan.speed': '风扇速度',
            'fan.off': '关闭',
            'fan.low': '低速',
            'fan.medium': '中速',
            'fan.high': '高速',

            // 门窗
            'door.title': '门窗状态',
            'door.front': '前门',
            'door.window': '客厅窗户',
            'door.opened': '已打开',
            'door.closed': '已关闭',
            'door.toggle': '切换',

            // 灯光
            'light.title': '灯光控制',
            'light.brightness': '灯光亮度',
            'light.full': '全亮',
            'light.half': '半亮',
            'light.night': '夜灯',
            'light.off': '关闭',

            // 空调
            'ac.title': '空调控制',
            'ac.set_temp': '设定温度',
            'ac.off': '关闭',
            'ac.running': '运行中',

            // 远程控制
            'remote.title': '远程控制面板',
            'remote.subtitle': '一键控制所有设备',
            'remote.light_on': '全部开灯',
            'remote.light_off': '全部关灯',
            'remote.ac_on': '开启空调',
            'remote.ac_off': '关闭空调',
            'remote.fan_on': '开启风扇',
            'remote.fan_off': '关闭风扇',
            'remote.door_open': '开门',
            'remote.door_close': '关门',

            // 历史数据
            'history.title': '历史数据 - 智能家居',
            'history.data_type': '数据类型',
            'history.time_range': '时间范围',
            'history.refresh': '刷新数据',
            'history.type_temp': '温度',
            'history.type_humidity': '湿度',
            'history.type_door': '门窗状态',
            'history.type_light': '灯光状态',
            'history.range_1h': '最近1小时',
            'history.range_6h': '最近6小时',
            'history.range_12h': '最近12小时',
            'history.range_24h': '最近24小时',
            'history.range_3d': '最近3天',
            'history.range_7d': '最近7天',
            'history.stat_max': '最高温度',
            'history.stat_min': '最低温度',
            'history.stat_avg': '平均温度',
            'history.stat_count': '数据点数',
            'history.chart_title': '温度历史趋势',
            'history.chart_humidity': '湿度历史趋势',
            'history.chart_door': '门窗状态历史',
            'history.chart_light': '灯光亮度历史',
            'history.records': '详细记录',
            'history.records_count': '共 {0} 条记录',
            'history.time': '时间',
            'history.value': '数值',
            'history.device_type': '设备类型',
            'history.device_name': '设备名称',
            'history.status': '状态',
            'history.light_name': '灯光名称',
            'history.brightness': '亮度 (%)',
            'history.no_data': '暂无数据',
            'history.loading': '加载中...',

            // 门禁
            'access.title': '门禁管理 - 智能家居',
            'access.verify': '门禁验证 (人脸识别)',
            'access.scan': '模拟RFID刷卡',
            'access.verifying': '验证中...',
            'access.face_admin': '人脸识别 - 管理员',
            'access.face_family': '人脸识别 - 家庭成员A',
            'access.face_unknown': '人脸识别 - 未授权',
            'access.face_wait': '等待人脸识别...',
            'access.face_scanning': '正在识别人脸...',
            'access.camera_start': '启动摄像头',
            'access.camera_stop': '关闭摄像头',
            'access.face_id': '人脸ID',
            'access.btn_admin': '刷卡 - 管理员',
            'access.btn_family': '刷卡 - 家庭成员A',
            'access.btn_unauth': '刷卡 - 未授权',
            'access.persons': '授权人员',
            'access.add_person': '添加授权人员',
            'access.name': '姓名',
            'access.rfid': 'RFID标签',
            'access.add': '添加',
            'access.no_persons': '暂无授权人员',
            'access.unset': '未设置',
            'access.logs': '门禁访问日志',
            'access.log_time': '时间',
            'access.log_person': '人员',
            'access.log_method': '验证方式',
            'access.log_status': '状态',
            'access.log_granted': '通过',
            'access.log_denied': '拒绝',
            'access.refresh': '刷新',
            'access.no_records': '暂无记录',
            // 人脸识别展示面板
            'access.live_face': '实时人脸识别',
            'access.listening': '监听中',
            'access.waiting_push': '等待香橙派推送识别结果...',
            'access.waiting_sub': '人脸识别在香橙派上独立运行',
            'access.confidence': '置信度',
            'access.time': '识别时间',
            'access.source': '识别来源',
            'access.sim_admin': '模拟推送 - 管理员',
            'access.sim_family': '模拟推送 - 家庭成员A',
            'access.sim_unknown': '模拟推送 - 未知人员',
            'access.pushing': '推送中...',
            'access.unknown': '未知',
            'access.face_events': '人脸识别事件',
            'access.event_time': '时间',
            'access.event_person': '人员',
            'access.event_face_id': '人脸ID',
            'access.event_confidence': '置信度',
            'access.event_status': '验证状态',
            'access.event_source': '来源',
            'access.no_events': '暂无识别事件',

            // 通知
            'notify.ac_on': '空调已开启',
            'notify.ac_off': '空调已关闭',
            'notify.enter_name': '请输入姓名',
            'notify.access_granted': '门禁验证通过: {0}',
            'notify.access_denied': '门禁验证失败: 未授权人员',

            // 硬件管理
            'nav.hardware': '硬件管理',
            'ha.config_title': 'Home Assistant 连接配置',
            'ha.url': 'HA 地址',
            'ha.fixed': '已固定',
            'ha.url_placeholder': 'http://192.168.1.100:8123',
            'ha.test': '测试连接',
            'ha.save': '保存配置',
            'ha.discover': '发现设备',
            'ha.mapping_title': '设备映射配置',
            'ha.mapping_subtitle': '将HA实体映射到系统功能',
            'ha.device_type': '设备类型',
            'ha.entity_id': 'HA 实体 ID',
            'ha.current_state': '当前状态',
            'ha.action': '操作',
            'ha.devices_title': '已发现设备',
            'ha.device_count': '0 个设备',
            'ha.friendly_name': '名称',
            'ha.state': '状态',
            'ha.domain': '域',
            'ha.click_discover': '点击"发现设备"加载',
            'ha.quick_control': '快捷硬件控制',
            'ha.quick_subtitle': '通过 HA 直接控制硬件设备',
            'ha.light_on': '开灯',
            'ha.light_off': '关灯',
            'ha.ac_on': '开空调',
            'ha.ac_off': '关空调',
            'ha.fan_on': '开风扇',
            'ha.fan_off': '关风扇',
            'ha.unlock': '开锁',
            'ha.lock': '上锁',

            // 图表标签
            'chart.temp': '温度 (°C)',
            'chart.humidity': '湿度 (%)',
            'chart.door_status': '状态 (1=开/0=关)',
            'chart.light_brightness': '亮度 (%)',
            'chart.temp_history': '温度历史趋势',
            'chart.humidity_history': '湿度历史趋势',
            'chart.door_history': '门窗状态历史',
            'chart.light_history': '灯光亮度历史',
        },
        en: {
            // Common
            'nav.dashboard': 'Dashboard',
            'nav.history': 'History',
            'nav.access': 'Access Control',
            'nav.lang': '中',
            'system.title': 'Smart Home Control System',
            'system.online': 'System Online',
            'system.offline': 'System Offline',

            // Temperature & Humidity
            'temp.title': 'Temperature & Humidity',
            'temp.humidity': 'Humidity',
            'temp.high': 'Max',
            'temp.low': 'Min',
            'temp.avg': 'Avg',
            'temp.normal': 'Normal',
            'temp.high_warn': 'High',
            'temp.too_high': 'Too High',
            'temp.auto_fan': 'Fan auto-starts when temp is high',
            'temp.trend': 'Temperature Trend',
            'temp.trend_24h': 'Temperature Trend (24H)',
            'temp.label': 'Temperature (°C)',
            'humidity.label': 'Humidity (%)',

            // Fan
            'fan.title': 'Fan / Servo Motor',
            'fan.speed': 'Fan Speed',
            'fan.off': 'Off',
            'fan.low': 'Low',
            'fan.medium': 'Medium',
            'fan.high': 'High',

            // Door & Window
            'door.title': 'Door & Window Status',
            'door.front': 'Front Door',
            'door.window': 'Living Room Window',
            'door.opened': 'Opened',
            'door.closed': 'Closed',
            'door.toggle': 'Toggle',

            // Light
            'light.title': 'Light Control',
            'light.brightness': 'Brightness',
            'light.full': 'Full',
            'light.half': 'Half',
            'light.night': 'Night',
            'light.off': 'Off',

            // AC
            'ac.title': 'AC Control',
            'ac.set_temp': 'Set Temperature',
            'ac.off': 'Off',
            'ac.running': 'Running',

            // Remote Control
            'remote.title': 'Remote Control Panel',
            'remote.subtitle': 'One-touch control for all devices',
            'remote.light_on': 'All Lights On',
            'remote.light_off': 'All Lights Off',
            'remote.ac_on': 'Turn On AC',
            'remote.ac_off': 'Turn Off AC',
            'remote.fan_on': 'Turn On Fan',
            'remote.fan_off': 'Turn Off Fan',
            'remote.door_open': 'Open Door',
            'remote.door_close': 'Close Door',

            // History
            'history.title': 'History - Smart Home',
            'history.data_type': 'Data Type',
            'history.time_range': 'Time Range',
            'history.refresh': 'Refresh Data',
            'history.type_temp': 'Temperature',
            'history.type_humidity': 'Humidity',
            'history.type_door': 'Door/Window Status',
            'history.type_light': 'Light Status',
            'history.range_1h': 'Last 1 Hour',
            'history.range_6h': 'Last 6 Hours',
            'history.range_12h': 'Last 12 Hours',
            'history.range_24h': 'Last 24 Hours',
            'history.range_3d': 'Last 3 Days',
            'history.range_7d': 'Last 7 Days',
            'history.stat_max': 'Max Temp',
            'history.stat_min': 'Min Temp',
            'history.stat_avg': 'Avg Temp',
            'history.stat_count': 'Data Points',
            'history.chart_title': 'Temperature History',
            'history.chart_humidity': 'Humidity History',
            'history.chart_door': 'Door/Window History',
            'history.chart_light': 'Light Brightness History',
            'history.records': 'Detailed Records',
            'history.records_count': '{0} records total',
            'history.time': 'Time',
            'history.value': 'Value',
            'history.device_type': 'Device Type',
            'history.device_name': 'Device Name',
            'history.status': 'Status',
            'history.light_name': 'Light Name',
            'history.brightness': 'Brightness (%)',
            'history.no_data': 'No data',
            'history.loading': 'Loading...',

            // Access Control
            'access.title': 'Access Control - Smart Home',
            'access.verify': 'Access Verification (Face Recognition)',
            'access.scan': 'Simulate RFID Tap',
            'access.verifying': 'Verifying...',
            'access.face_admin': 'Face Recognition - Admin',
            'access.face_family': 'Face Recognition - Family A',
            'access.face_unknown': 'Face Recognition - Unauthorized',
            'access.face_wait': 'Waiting for face recognition...',
            'access.face_scanning': 'Scanning face...',
            'access.camera_start': 'Start Camera',
            'access.camera_stop': 'Stop Camera',
            'access.face_id': 'Face ID',
            'access.btn_admin': 'Tap - Admin',
            'access.btn_family': 'Tap - Family A',
            'access.btn_unauth': 'Tap - Unauthorized',
            'access.persons': 'Authorized Persons',
            'access.add_person': 'Add Authorized Person',
            'access.name': 'Name',
            'access.rfid': 'RFID Tag',
            'access.add': 'Add',
            'access.no_persons': 'No authorized persons',
            'access.unset': 'Not set',
            'access.logs': 'Access Logs',
            'access.log_time': 'Time',
            'access.log_person': 'Person',
            'access.log_method': 'Method',
            'access.log_status': 'Status',
            'access.log_granted': 'Granted',
            'access.log_denied': 'Denied',
            'access.refresh': 'Refresh',
            'access.no_records': 'No records',
            // Face Recognition Display Panel
            'access.live_face': 'Live Face Recognition',
            'access.listening': 'Listening',
            'access.waiting_push': 'Waiting for Orange Pi to push recognition result...',
            'access.waiting_sub': 'Face recognition runs independently on Orange Pi',
            'access.confidence': 'Confidence',
            'access.time': 'Recognition Time',
            'access.source': 'Source',
            'access.sim_admin': 'Sim Push - Admin',
            'access.sim_family': 'Sim Push - Family A',
            'access.sim_unknown': 'Sim Push - Unknown',
            'access.pushing': 'Pushing...',
            'access.unknown': 'Unknown',
            'access.face_events': 'Face Recognition Events',
            'access.event_time': 'Time',
            'access.event_person': 'Person',
            'access.event_face_id': 'Face ID',
            'access.event_confidence': 'Confidence',
            'access.event_status': 'Status',
            'access.event_source': 'Source',
            'access.no_events': 'No face events yet',

            // Notifications
            'notify.ac_on': 'AC turned on',
            'notify.ac_off': 'AC turned off',
            'notify.enter_name': 'Please enter a name',
            'notify.access_granted': 'Access granted: {0}',
            'notify.access_denied': 'Access denied: Unauthorized person',

            // Hardware Management
            'nav.hardware': 'Hardware',
            'ha.config_title': 'Home Assistant Connection Config',
            'ha.url': 'HA URL',
            'ha.fixed': 'Fixed',
            'ha.url_placeholder': 'http://192.168.1.100:8123',
            'ha.test': 'Test Connection',
            'ha.save': 'Save Config',
            'ha.discover': 'Discover Devices',
            'ha.mapping_title': 'Device Mapping Config',
            'ha.mapping_subtitle': 'Map HA entities to system functions',
            'ha.device_type': 'Device Type',
            'ha.entity_id': 'HA Entity ID',
            'ha.current_state': 'Current State',
            'ha.action': 'Action',
            'ha.devices_title': 'Discovered Devices',
            'ha.device_count': '0 devices',
            'ha.friendly_name': 'Name',
            'ha.state': 'State',
            'ha.domain': 'Domain',
            'ha.click_discover': 'Click "Discover Devices" to load',
            'ha.quick_control': 'Quick Hardware Control',
            'ha.quick_subtitle': 'Control hardware devices via HA',
            'ha.light_on': 'Light On',
            'ha.light_off': 'Light Off',
            'ha.ac_on': 'AC On',
            'ha.ac_off': 'AC Off',
            'ha.fan_on': 'Fan On',
            'ha.fan_off': 'Fan Off',
            'ha.unlock': 'Unlock',
            'ha.lock': 'Lock',

            // Chart labels
            'chart.temp': 'Temperature (°C)',
            'chart.humidity': 'Humidity (%)',
            'chart.door_status': 'Status (1=Open/0=Closed)',
            'chart.light_brightness': 'Brightness (%)',
            'chart.temp_history': 'Temperature History',
            'chart.humidity_history': 'Humidity History',
            'chart.door_history': 'Door/Window History',
            'chart.light_history': 'Light Brightness History',
        }
    },

    t(key, ...args) {
        const text = this.dict[this.currentLang]?.[key] || this.dict['zh']?.[key] || key;
        return args.reduce((str, arg, i) => str.replace(`{${i}}`, arg), text);
    },

    setLang(lang) {
        if (!this.dict[lang]) return;
        this.currentLang = lang;
        localStorage.setItem('smart_home_lang', lang);
        this.applyI18n();
        document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
    },

    applyI18n() {
        // 翻译 data-i18n 元素
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            if (key) el.textContent = this.t(key);
        });
        // 翻译 placeholder
        document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            const key = el.getAttribute('data-i18n-placeholder');
            if (key) el.placeholder = this.t(key);
        });
        // 翻译 title
        document.querySelectorAll('[data-i18n-title]').forEach(el => {
            const key = el.getAttribute('data-i18n-title');
            if (key) el.title = this.t(key);
        });
        // 翻译 select options
        document.querySelectorAll('select[data-i18n-options]').forEach(select => {
            const mapping = select.getAttribute('data-i18n-options');
            select.querySelectorAll('option').forEach(opt => {
                const key = `${mapping}.${opt.value}`;
                const translated = this.t(key);
                if (translated !== key) opt.textContent = translated;
            });
        });
        // 更新页面标题
        const titleEl = document.querySelector('title[data-i18n]');
        if (titleEl) document.title = this.t(titleEl.getAttribute('data-i18n'));
    },

    init() {
        // 监听自定义事件
        document.addEventListener('i18n:ready', () => this.applyI18n());
        // 页面加载时立即应用
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.applyI18n());
        } else {
            this.applyI18n();
        }
    }
};

// 简写函数
function t(key, ...args) { return I18N.t(key, ...args); }
function setLang(lang) { I18N.setLang(lang); }

// 初始化
I18N.init();
