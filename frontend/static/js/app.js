const { createApp } = Vue;
const { ElMessage, ElMessageBox } = ElementPlus;

// API 基础 URL
const API_BASE = '/api';

const app = createApp({
    data() {
        return {
            activeMenu: 'dashboard',
            tasks: [],
            logs: [],
            recentLogs: [],
            logStats: {},
            globalConfig: {
                log_level: 'INFO',
                web_port: 8888,
                ssh_host_key_policy: 'reject',
                ssh_known_hosts_path: './data/known_hosts'
            },
            authToken: '',
            authTokenInput: '',
            authPrompting: false,
            taskDialogVisible: false,
            isEditMode: false,
            taskDetailVisible: false,
            taskDetail: null,
            taskFilters: {
                query: '',
                targetType: '',
                running: null,
                enabled: null
            },
            tasksPage: 1,
            tasksPageSize: 20,
            selectedLogTaskId: null,
            logFilters: {
                status: ''
            },
            logsLimit: 200,
            wsConnected: {
                logs: false,
                status: false
            },
            wsLogs: null,
            wsStatus: null,
            wsHeartbeat: null,
            wsLogTaskId: null,
            wsLogManualClose: false,
            wsStatusManualClose: false,
            wsReconnectTimers: {
                logs: null,
                status: null
            },
            wsRetryCount: {
                logs: 0,
                status: 0
            },
            wsLastClose: {
                logs: null,
                status: null
            },
            wsAuthFailed: {
                logs: false,
                status: false
            },
            wsLastMessageAt: {
                logs: null,
                status: null
            },
            wsLastHeartbeatAt: {
                logs: null,
                status: null
            },
            taskForm: {
                id: null,
                name: '',
                mode: 'one_way',
                source_path: '',
                target_type: 'local',
                target_host: '',
                target_port: 22,
                target_username: '',
                target_password: '',
                target_ssh_key_path: '',
                target_path: '',
                endpoint_a: {
                    type: 'local',
                    path: '',
                    host: '',
                    port: 22,
                    username: '',
                    password: '',
                    ssh_key_path: ''
                },
                endpoint_b: {
                    type: 'local',
                    path: '',
                    host: '',
                    port: 22,
                    username: '',
                    password: '',
                    ssh_key_path: ''
                },
                enabled: true,
                auto_start: true,
                eol_normalize: 'lf',
                exclude_patterns: [],
                file_extensions: [],
                poll_interval_seconds: 5,
                trash_retention_days: 7,
                backup_retention_days: 7
            },
            excludePatternsText: '',
            refreshTimer: null,
            resizeHandler: null
        };
    },
    computed: {
        runningCount() {
            return this.tasks.filter(t => t.is_running).length;
        },
        wsStatusText() {
            const logs = this.wsConnected.logs ? '日志✓' : '日志✗';
            const status = this.wsConnected.status ? '状态✓' : '状态✗';
            return `WS: ${logs} ${status}`;
        },
        wsStatusType() {
            if (this.wsConnected.logs && this.wsConnected.status) return 'success';
            if (this.wsConnected.logs || this.wsConnected.status) return 'warning';
            return 'danger';
        },
        wsHeartbeatText() {
            const format = (value) => {
                if (!value) return '-';
                const diff = Math.floor((Date.now() - value) / 1000);
                if (diff < 60) return `${diff}s`;
                const mins = Math.floor(diff / 60);
                return `${mins}m`;
            };
            return `心跳: 日志 ${format(this.wsLastHeartbeatAt.logs)} / 状态 ${format(this.wsLastHeartbeatAt.status)}`;
        },
        wsReconnectHint() {
            if (this.wsConnected.logs && this.wsConnected.status) return '';
            const parts = [];
            const fmt = (kind, label) => {
                const info = this.wsLastClose?.[kind];
                if (!info) return null;
                const code = typeof info.code === 'number' ? info.code : '-';
                const reason = info.reason ? `/${info.reason}` : '';
                return `${label}:${code}${reason}`;
            };
            const logs = fmt('logs', '日志');
            const status = fmt('status', '状态');
            if (logs) parts.push(logs);
            if (status) parts.push(status);
            const suffix = parts.length ? `（上次断开 ${parts.join('，')}）` : '';
            return `WS 断开，正在重连…${suffix}`;
        },
        filteredTasks() {
            const query = (this.taskFilters.query || '').trim().toLowerCase();
            const targetType = (this.taskFilters.targetType === 'local' || this.taskFilters.targetType === 'ssh')
                ? this.taskFilters.targetType
                : '';
            const runningFilter = (this.taskFilters.running === true || this.taskFilters.running === false)
                ? this.taskFilters.running
                : null;
            const enabledFilter = (this.taskFilters.enabled === true || this.taskFilters.enabled === false)
                ? this.taskFilters.enabled
                : null;
            return this.tasks.filter(task => {
                if (targetType && task.target_type !== targetType) return false;
                if (runningFilter !== null && task.is_running !== runningFilter) return false;
                if (enabledFilter !== null && task.enabled !== enabledFilter) return false;

                if (!query) return true;
                const haystack = [
                    task.name,
                    task.source_path,
                    task.target_path,
                    task.target_host,
                    task.target_username
                ]
                    .filter(Boolean)
                    .join(' ')
                    .toLowerCase();
                return haystack.includes(query);
            });
        },
        pagedTasks() {
            const start = (this.tasksPage - 1) * this.tasksPageSize;
            return this.filteredTasks.slice(start, start + this.tasksPageSize);
        },
        selectedLogTask() {
            return this.tasks.find(t => t.id === this.selectedLogTaskId) || null;
        },
        filteredLogs() {
            const status = (this.logFilters.status === 'success' || this.logFilters.status === 'failed' || this.logFilters.status === 'skipped')
                ? this.logFilters.status
                : '';
            if (!status) return this.logs;
            return this.logs.filter(l => l.status === status);
        }
    },
    mounted() {
        this.loadAuthToken();
        this.loadTasks();
        this.loadLogs();
        this.loadLogStats();
        this.loadGlobalConfig();
        this.connectWebSockets();

        // 窗口尺寸变化时，重新计算表格布局（避免出现宽度不铺满的情况）
        this.resizeHandler = () => this.relayoutTables();
        window.addEventListener('resize', this.resizeHandler);

        // 自动刷新（每 5 秒，WebSocket 断开时兜底）
        this.refreshTimer = setInterval(() => {
            if (this.activeMenu === 'tasks' && !this.wsConnected.status) {
                this.loadTasks();
            }
            if (this.activeMenu === 'logs' && !this.wsConnected.logs) {
                this.loadLogs();
            }
            if (this.activeMenu === 'dashboard' && !this.wsConnected.logs) {
                this.loadLogStats();
                this.loadRecentLogs();
            }
        }, 5000);

        // [New] 移除 Loading 遮罩
        this.$nextTick(() => {
            const loader = document.getElementById('app-loader');
            if (loader) {
                // 延迟 800ms 以平滑过渡，并确保数据已填充
                setTimeout(() => {
                    loader.classList.add('fade-out');
                    setTimeout(() => loader.remove(), 600);
                }, 800);
            }
        });
    },
    beforeUnmount() {
        if (this.refreshTimer) {
            clearInterval(this.refreshTimer);
        }
        if (this.resizeHandler) {
            window.removeEventListener('resize', this.resizeHandler);
        }
        this.disconnectWebSockets();
    },
    methods: {
        loadAuthToken() {
            const stored = localStorage.getItem('api_token') || '';
            this.authToken = stored;
            this.authTokenInput = stored;
        },
        saveAuthToken() {
            this.authToken = (this.authTokenInput || '').trim();
            if (this.authToken) {
                localStorage.setItem('api_token', this.authToken);
            } else {
                localStorage.removeItem('api_token');
            }
            this.connectWebSockets(true);
            ElMessage.success('认证令牌已更新');
        },
        getAuthHeaders() {
            const headers = {};
            if (this.authToken) {
                headers['Authorization'] = `Bearer ${this.authToken}`;
            }
            return headers;
        },
        async promptAuth() {
            if (this.authPrompting) return false;
            this.authPrompting = true;
            try {
                const { value } = await ElMessageBox.prompt('请输入 API 访问令牌', '需要认证', {
                    confirmButtonText: '保存',
                    cancelButtonText: '取消',
                    inputType: 'password',
                    inputPlaceholder: 'API Token'
                });
                this.authToken = (value || '').trim();
                if (this.authToken) {
                    localStorage.setItem('api_token', this.authToken);
                }
                this.connectWebSockets(true);
                return true;
            } catch (error) {
                return false;
            } finally {
                this.authPrompting = false;
            }
        },
        async apiFetch(path, options = {}, retry = true) {
            const headers = { ...(options.headers || {}), ...this.getAuthHeaders() };
            const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
            if ((response.status === 401 || response.status === 403) && retry) {
                const ok = await this.promptAuth();
                if (ok) {
                    return this.apiFetch(path, options, false);
                }
            }
            return response;
        },
        buildWsUrl(path) {
            const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
            const token = this.authToken ? `token=${encodeURIComponent(this.authToken)}` : '';
            const joiner = path.includes('?') ? '&' : '?';
            const query = token ? `${joiner}${token}` : '';
            return `${protocol}://${window.location.host}${path}${query}`;
        },
        connectWebSockets(force = false) {
            if (force) {
                this.disconnectWebSockets();
            }
            if (!this.wsLogs) {
                this.connectLogSocket(this.getLogWsTaskId());
            }
            if (!this.wsStatus) {
                this.connectStatusSocket();
            }
            this.startWsHeartbeat();
        },
        disconnectWebSockets() {
            this.clearWsReconnect('logs');
            this.clearWsReconnect('status');
            if (this.wsLogs) {
                this.wsLogManualClose = true;
                this.wsLogs.close();
                this.wsLogs = null;
            }
            if (this.wsStatus) {
                this.wsStatusManualClose = true;
                this.wsStatus.close();
                this.wsStatus = null;
            }
            this.wsConnected.logs = false;
            this.wsConnected.status = false;
            this.stopWsHeartbeat();
        },
        clearWsReconnect(kind) {
            const timer = this.wsReconnectTimers?.[kind];
            if (timer) {
                clearTimeout(timer);
                this.wsReconnectTimers[kind] = null;
            }
        },
        scheduleWsReconnect(kind, fn) {
            if (this.wsAuthFailed?.[kind]) return;
            this.clearWsReconnect(kind);
            const count = Math.min(this.wsRetryCount[kind] || 0, 6);
            const base = 1000 * Math.pow(2, count); // 1s,2s,4s...64s
            const delay = Math.min(30000, base) + Math.floor(Math.random() * 300);
            this.wsReconnectTimers[kind] = setTimeout(() => fn(), delay);
        },
        handleWsClose(kind, event) {
            this.wsLastClose[kind] = {
                code: event?.code,
                reason: event?.reason || '',
                at: Date.now()
            };
            // 1008: policy violation（这里用作 token 校验失败）
            if (event?.code === 1008) {
                this.wsAuthFailed[kind] = true;
                ElMessage.error('WebSocket 认证失败：请检查/更新 API Token');
            }
        },
        startWsHeartbeat() {
            if (this.wsHeartbeat) return;
            this.wsHeartbeat = setInterval(() => {
                if (this.wsLogs?.readyState === WebSocket.OPEN) {
                    this.wsLogs.send('ping');
                }
                if (this.wsStatus?.readyState === WebSocket.OPEN) {
                    this.wsStatus.send('ping');
                }
            }, 30000);
        },
        stopWsHeartbeat() {
            if (this.wsHeartbeat) {
                clearInterval(this.wsHeartbeat);
                this.wsHeartbeat = null;
            }
        },
        getLogWsTaskId() {
            if (this.activeMenu === 'logs' && this.selectedLogTaskId) {
                return this.selectedLogTaskId;
            }
            return null;
        },
        connectLogSocket(taskId = null) {
            try {
                this.wsLogTaskId = taskId;
                this.wsAuthFailed.logs = false;
                const query = taskId ? `/ws/logs?task_id=${taskId}` : '/ws/logs';
                const url = this.buildWsUrl(query);
                this.wsLogs = new WebSocket(url);
                this.wsLogs.onopen = () => {
                    this.wsConnected.logs = true;
                    this.wsLastHeartbeatAt.logs = Date.now();
                    this.wsRetryCount.logs = 0;
                };
                this.wsLogs.onerror = () => {
                    // 某些浏览器只触发 onerror 不给细节，这里交由 onclose 统一重连
                };
                this.wsLogs.onmessage = (event) => {
                    if (event.data === 'pong') {
                        this.wsLastHeartbeatAt.logs = Date.now();
                        return;
                    }
                    try {
                        const msg = JSON.parse(event.data);
                        if (msg.type === 'log') {
                            this.wsLastHeartbeatAt.logs = Date.now();
                            this.wsLastMessageAt.logs = Date.now();
                            this.handleLogMessage(msg.data);
                        }
                    } catch (error) {
                        console.warn('日志推送解析失败', error);
                    }
                };
                this.wsLogs.onclose = (event) => {
                    this.wsConnected.logs = false;
                    this.wsLogs = null;
                    if (this.wsLogManualClose) {
                        this.wsLogManualClose = false;
                        return;
                    }
                    this.handleWsClose('logs', event);
                    this.wsRetryCount.logs = (this.wsRetryCount.logs || 0) + 1;
                    this.scheduleWsReconnect('logs', () => this.connectLogSocket(this.getLogWsTaskId()));
                };
            } catch (error) {
                console.warn('日志 WS 连接失败', error);
            }
        },
        reconnectLogSocket(taskId) {
            if (this.wsLogs) {
                this.wsLogManualClose = true;
                try {
                    this.wsLogs.close();
                } catch (error) {
                    this.wsLogManualClose = false;
                }
            }
            this.connectLogSocket(taskId);
        },
        connectStatusSocket() {
            try {
                this.wsAuthFailed.status = false;
                const url = this.buildWsUrl('/ws/task-status');
                this.wsStatus = new WebSocket(url);
                this.wsStatus.onopen = () => {
                    this.wsConnected.status = true;
                    this.wsLastHeartbeatAt.status = Date.now();
                    this.wsRetryCount.status = 0;
                };
                this.wsStatus.onerror = () => {
                    // 交由 onclose 统一处理
                };
                this.wsStatus.onmessage = (event) => {
                    if (event.data === 'pong') {
                        this.wsLastHeartbeatAt.status = Date.now();
                        return;
                    }
                    try {
                        const msg = JSON.parse(event.data);
                        if (msg.type === 'task_status_snapshot') {
                            this.wsLastHeartbeatAt.status = Date.now();
                            this.wsLastMessageAt.status = Date.now();
                            this.handleStatusSnapshot(msg.data);
                        } else if (msg.type === 'task_status') {
                            this.wsLastHeartbeatAt.status = Date.now();
                            this.wsLastMessageAt.status = Date.now();
                            this.handleStatusMessage(msg.data);
                        }
                    } catch (error) {
                        console.warn('状态推送解析失败', error);
                    }
                };
                this.wsStatus.onclose = (event) => {
                    this.wsConnected.status = false;
                    this.wsStatus = null;
                    if (this.wsStatusManualClose) {
                        this.wsStatusManualClose = false;
                        return;
                    }
                    this.handleWsClose('status', event);
                    this.wsRetryCount.status = (this.wsRetryCount.status || 0) + 1;
                    this.scheduleWsReconnect('status', () => this.connectStatusSocket());
                };
            } catch (error) {
                console.warn('状态 WS 连接失败', error);
            }
        },
        handleLogMessage(log) {
            if (!log) return;
            this.recentLogs = [log, ...this.recentLogs].slice(0, 10);
            if (this.selectedLogTaskId && log.task_id === this.selectedLogTaskId) {
                this.logs = [log, ...this.logs].slice(0, this.logsLimit);
            }
            this.loadLogStats();
        },
        handleStatusSnapshot(list) {
            if (!Array.isArray(list)) return;
            if (!this.tasks.length) {
                this.loadTasks();
                return;
            }
            list.forEach(item => {
                const task = this.tasks.find(t => t.id === item.task_id);
                if (task) {
                    task.is_running = item.is_running;
                    task.enabled = item.enabled ?? task.enabled;
                    task.name = item.name ?? task.name;
                }
            });
        },
        handleStatusMessage(status) {
            if (!status) return;
            const task = this.tasks.find(t => t.id === status.task_id);
            if (task) {
                if (typeof status.is_running === 'boolean') {
                    task.is_running = status.is_running;
                }
                if (typeof status.enabled === 'boolean') {
                    task.enabled = status.enabled;
                }
                if (status.name) {
                    task.name = status.name;
                }
            }
        },
        resetTasksPage() {
            this.tasksPage = 1;
            this.relayoutTables();
        },
        handleTasksPageChange(page) {
            this.tasksPage = page;
            this.relayoutTables();
        },
        handleTasksPageSizeChange(size) {
            this.tasksPageSize = size;
            this.tasksPage = 1;
            this.relayoutTables();
        },
        getTaskOptionLabel(task) {
            if (!task) return '-';
            return `${task.name}（${task.source_path} → ${task.target_path}）`;
        },
        openTaskDetail(task) {
            this.taskDetail = task;
            this.taskDetailVisible = true;
        },
        normalizeTaskForm(task) {
            const base = {
                id: task.id ?? null,
                name: task.name ?? '',
                mode: task.mode || (task.endpoints ? 'two_way' : 'one_way'),
                source_path: task.source_path ?? '',
                target_type: task.target_type ?? 'local',
                target_host: task.target_host ?? '',
                target_port: task.target_port ?? 22,
                target_username: task.target_username ?? '',
                target_password: '',
                target_ssh_key_path: task.target_ssh_key_path ?? '',
                target_path: task.target_path ?? '',
                endpoint_a: {
                    type: 'local',
                    path: '',
                    host: '',
                    port: 22,
                    username: '',
                    password: '',
                    ssh_key_path: ''
                },
                endpoint_b: {
                    type: 'local',
                    path: '',
                    host: '',
                    port: 22,
                    username: '',
                    password: '',
                    ssh_key_path: ''
                },
                enabled: task.enabled ?? true,
                auto_start: task.auto_start ?? true,
                eol_normalize: task.eol_normalize ?? 'lf',
                exclude_patterns: task.exclude_patterns ?? [],
                file_extensions: task.file_extensions ?? [],
                poll_interval_seconds: task.poll_interval_seconds ?? 5,
                trash_retention_days: task.trash_retention_days ?? 7,
                backup_retention_days: task.backup_retention_days ?? 7
            };

            if (base.mode === 'two_way') {
                const a = task.endpoints?.a;
                const b = task.endpoints?.b;
                base.endpoint_a = {
                    type: a?.type || 'local',
                    path: a?.path || base.source_path || '',
                    host: a?.host || '',
                    port: a?.port || 22,
                    username: a?.username || '',
                    password: '',
                    ssh_key_path: a?.ssh_key_path || ''
                };
                base.endpoint_b = {
                    type: b?.type || base.target_type || 'local',
                    path: b?.path || base.target_path || '',
                    host: b?.host || base.target_host || '',
                    port: b?.port || base.target_port || 22,
                    username: b?.username || base.target_username || '',
                    password: '',
                    ssh_key_path: b?.ssh_key_path || base.target_ssh_key_path || ''
                };
                base.source_path = base.endpoint_a.path;
                base.target_type = base.endpoint_b.type;
                base.target_host = base.endpoint_b.host;
                base.target_port = base.endpoint_b.port;
                base.target_username = base.endpoint_b.username;
                base.target_ssh_key_path = base.endpoint_b.ssh_key_path;
                base.target_path = base.endpoint_b.path;
            } else {
                base.endpoint_a = {
                    type: 'local',
                    path: base.source_path || '',
                    host: '',
                    port: 22,
                    username: '',
                    password: '',
                    ssh_key_path: ''
                };
                base.endpoint_b = {
                    type: base.target_type || 'local',
                    path: base.target_path || '',
                    host: base.target_host || '',
                    port: base.target_port || 22,
                    username: base.target_username || '',
                    password: '',
                    ssh_key_path: base.target_ssh_key_path || ''
                };
            }

            return base;
        },
        handleModeChange() {
            if (this.taskForm.mode === 'two_way') {
                if (!this.taskForm.endpoint_a.path) {
                    this.taskForm.endpoint_a.path = this.taskForm.source_path || '';
                }
                if (!this.taskForm.endpoint_b.path) {
                    this.taskForm.endpoint_b.path = this.taskForm.target_path || '';
                }
                if (!this.taskForm.endpoint_b.type) {
                    this.taskForm.endpoint_b.type = this.taskForm.target_type || 'local';
                }
                if (!this.taskForm.endpoint_b.host) {
                    this.taskForm.endpoint_b.host = this.taskForm.target_host || '';
                }
                if (!this.taskForm.endpoint_b.port) {
                    this.taskForm.endpoint_b.port = this.taskForm.target_port || 22;
                }
                if (!this.taskForm.endpoint_b.username) {
                    this.taskForm.endpoint_b.username = this.taskForm.target_username || '';
                }
                if (!this.taskForm.endpoint_b.ssh_key_path) {
                    this.taskForm.endpoint_b.ssh_key_path = this.taskForm.target_ssh_key_path || '';
                }
            } else {
                if (!this.taskForm.source_path) {
                    this.taskForm.source_path = this.taskForm.endpoint_a.path || '';
                }
                if (!this.taskForm.target_path) {
                    this.taskForm.target_path = this.taskForm.endpoint_b.path || '';
                }
                this.taskForm.target_type = this.taskForm.endpoint_b.type || 'local';
                this.taskForm.target_host = this.taskForm.endpoint_b.host || '';
                this.taskForm.target_port = this.taskForm.endpoint_b.port || 22;
                this.taskForm.target_username = this.taskForm.endpoint_b.username || '';
                this.taskForm.target_ssh_key_path = this.taskForm.endpoint_b.ssh_key_path || '';
            }
        },
        getTargetSummary(task) {
            if (!task) return '-';
            if (task.target_type === 'ssh') {
                const user = task.target_username ? `${task.target_username}@` : '';
                const host = task.target_host || '-';
                const port = task.target_port ? `:${task.target_port}` : '';
                return `${user}${host}${port}`;
            }
            return '本地';
        },
        getEndpointSummary(task, side) {
            const ep = task?.endpoints?.[side];
            if (!ep) return '-';
            if (ep.type === 'ssh') {
                const user = ep.username ? `${ep.username}@` : '';
                const host = ep.host || '-';
                const port = ep.port ? `:${ep.port}` : '';
                return `${user}${host}${port} | ${ep.path || '-'}`;
            }
            return `本地 | ${ep.path || '-'}`;
        },
        getEolLabel(value) {
            const map = { lf: 'LF', crlf: 'CRLF', keep: '保持' };
            return map[value] || (value || '-');
        },
        ensureLogTaskSelection() {
            const ids = new Set(this.tasks.map(t => t.id));
            if (this.selectedLogTaskId && !ids.has(this.selectedLogTaskId)) {
                this.selectedLogTaskId = null;
            }
            if (!this.selectedLogTaskId && this.tasks.length === 1) {
                this.selectedLogTaskId = this.tasks[0].id;
            }
        },
        handleLogTaskChange() {
            this.loadLogs();
            this.reconnectLogSocket(this.getLogWsTaskId());
        },

        // 重新布局表格（Element Plus 表格在容器尺寸变化/切页后可能需要 doLayout）
        relayoutTables() {
            this.$nextTick(() => {
                const tables = [
                    this.$refs.recentLogsTable,
                    this.$refs.tasksTable,
                    this.$refs.logsTable,
                ];
                tables.forEach(t => t?.doLayout?.());
            });
        },

        // 菜单切换
        handleMenuSelect(index) {
            this.activeMenu = index;
            if (index === 'logs') {
                this.ensureLogTaskSelection();
                this.loadLogs();
                this.reconnectLogSocket(this.getLogWsTaskId());
            } else if (index === 'dashboard') {
                this.loadRecentLogs();
                this.reconnectLogSocket(this.getLogWsTaskId());
            }
            this.relayoutTables();
        },

        // 加载任务列表
        async loadTasks() {
            try {
                const response = await this.apiFetch(`/tasks/`);
                if (!response.ok) return;
                this.tasks = await response.json();
                this.ensureLogTaskSelection();
                // 筛选结果变少时，修正分页指针
                const maxPage = Math.max(1, Math.ceil(this.filteredTasks.length / this.tasksPageSize));
                this.tasksPage = Math.min(this.tasksPage, maxPage);
                this.relayoutTables();

                // 如果当前在日志页，且存在默认/选中任务，则刷新日志
                if (this.activeMenu === 'logs' && this.selectedLogTaskId) {
                    this.loadLogs();
                }
            } catch (error) {
                console.error('加载任务失败:', error);
            }
        },

        // 加载日志
        async loadLogs() {
            try {
                if (!this.selectedLogTaskId) {
                    this.logs = [];
                    this.relayoutTables();
                    return;
                }

                const limit = this.logsLimit;
                const response = await this.apiFetch(`/logs/?task_id=${this.selectedLogTaskId}&limit=${limit}&offset=0`);
                if (!response.ok) return;
                this.logs = await response.json();
                this.relayoutTables();
            } catch (error) {
                console.error('加载日志失败:', error);
            }
        },

        // 加载最近日志
        async loadRecentLogs() {
            try {
                const response = await this.apiFetch(`/logs/?limit=10`);
                if (!response.ok) return;
                this.recentLogs = await response.json();
                this.relayoutTables();
            } catch (error) {
                console.error('加载最近日志失败:', error);
            }
        },

        // 加载日志统计
        async loadLogStats() {
            try {
                const response = await this.apiFetch(`/logs/stats`);
                if (!response.ok) return;
                this.logStats = await response.json();
            } catch (error) {
                console.error('加载日志统计失败:', error);
            }
        },

        // 加载全局配置
        async loadGlobalConfig() {
            try {
                const response = await this.apiFetch(`/config/global`);
                if (!response.ok) return;
                const data = await response.json();
                this.globalConfig = {
                    ...this.globalConfig,
                    log_level: data.log_level ?? this.globalConfig.log_level,
                    web_port: data.web_port ?? this.globalConfig.web_port,
                    ssh_host_key_policy: data.ssh_host_key_policy ?? this.globalConfig.ssh_host_key_policy,
                    ssh_known_hosts_path: data.ssh_known_hosts_path ?? this.globalConfig.ssh_known_hosts_path
                };
            } catch (error) {
                console.error('加载配置失败:', error);
            }
        },

        // 保存全局配置
        async saveGlobalConfig() {
            try {
                const response = await this.apiFetch(`/config/global`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        log_level: this.globalConfig.log_level,
                        web_port: this.globalConfig.web_port,
                        ssh_host_key_policy: this.globalConfig.ssh_host_key_policy,
                        ssh_known_hosts_path: this.globalConfig.ssh_known_hosts_path
                    })
                });

                if (response.ok) {
                    ElMessage.success('配置已保存');
                } else {
                    ElMessage.error('保存配置失败');
                }
            } catch (error) {
                ElMessage.error('保存配置失败: ' + error.message);
            }
        },

        // 显示创建任务对话框
        showCreateDialog() {
            this.isEditMode = false;
            this.taskForm = {
                name: '',
                mode: 'one_way',
                source_path: '',
                target_type: 'local',
                target_host: '',
                target_port: 22,
                target_username: '',
                target_password: '',
                target_ssh_key_path: '',
                target_path: '',
                endpoint_a: {
                    type: 'local',
                    path: '',
                    host: '',
                    port: 22,
                    username: '',
                    password: '',
                    ssh_key_path: ''
                },
                endpoint_b: {
                    type: 'local',
                    path: '',
                    host: '',
                    port: 22,
                    username: '',
                    password: '',
                    ssh_key_path: ''
                },
                enabled: true,
                auto_start: true,
                eol_normalize: 'lf',
                exclude_patterns: [],
                file_extensions: [],
                poll_interval_seconds: 5,
                trash_retention_days: 7,
                backup_retention_days: 7
            };
            this.excludePatternsText = '*.pyc\n__pycache__\n.git\nnode_modules';
            this.taskDialogVisible = true;
        },

        // 编辑任务
        editTask(task) {
            this.isEditMode = true;
            this.taskForm = this.normalizeTaskForm(task);
            this.excludePatternsText = (this.taskForm.exclude_patterns || []).join('\n');
            this.taskDialogVisible = true;
        },

        // 保存任务
        async saveTask() {
            // 解析排除规则
            this.taskForm.exclude_patterns = this.excludePatternsText
                .split('\n')
                .map(line => line.trim())
                .filter(line => line.length > 0);

            try {
                const url = this.isEditMode
                    ? `${API_BASE}/tasks/${this.taskForm.id}`
                    : `${API_BASE}/tasks/`;

                const method = this.isEditMode ? 'PUT' : 'POST';

                const payload = { ...this.taskForm };
                if (payload.mode === 'two_way') {
                    payload.endpoints = {
                        a: { ...payload.endpoint_a },
                        b: { ...payload.endpoint_b }
                    };
                    payload.source_path = payload.endpoint_a.path || '';
                    payload.target_type = payload.endpoint_b.type || 'local';
                    payload.target_host = payload.endpoint_b.host || '';
                    payload.target_port = payload.endpoint_b.port || 22;
                    payload.target_username = payload.endpoint_b.username || '';
                    payload.target_password = payload.endpoint_b.password || '';
                    payload.target_ssh_key_path = payload.endpoint_b.ssh_key_path || '';
                    payload.target_path = payload.endpoint_b.path || '';
                } else {
                    delete payload.endpoints;
                }
                delete payload.endpoint_a;
                delete payload.endpoint_b;

                const response = await this.apiFetch(url.replace(API_BASE, ''), {
                    method: method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (response.ok) {
                    ElMessage.success(this.isEditMode ? '任务已更新' : '任务已创建');
                    this.taskDialogVisible = false;
                    this.loadTasks();
                } else {
                    const error = await response.json();
                    ElMessage.error(error.detail || '保存失败');
                }
            } catch (error) {
                ElMessage.error('保存任务失败: ' + error.message);
            }
        },

        // 启动任务
        async startTask(taskId) {
            try {
                const response = await this.apiFetch(`/tasks/${taskId}/start`, {
                    method: 'POST'
                });

                if (response.ok) {
                    ElMessage.success('任务已启动');
                    this.loadTasks();
                } else {
                    const error = await response.json();
                    ElMessage.error(error.detail || '启动失败');
                }
            } catch (error) {
                ElMessage.error('启动任务失败: ' + error.message);
            }
        },

        // 停止任务
        async stopTask(taskId) {
            try {
                const response = await this.apiFetch(`/tasks/${taskId}/stop`, {
                    method: 'POST'
                });

                if (response.ok) {
                    ElMessage.success('任务已停止');
                    this.loadTasks();
                } else {
                    const error = await response.json();
                    ElMessage.error(error.detail || '停止失败');
                }
            } catch (error) {
                ElMessage.error('停止任务失败: ' + error.message);
            }
        },

        // 全量同步
        async syncTaskAll(taskId) {
            try {
                ElMessage.info('开始全量同步...');

                const response = await this.apiFetch(`/tasks/${taskId}/sync`, {
                    method: 'POST'
                });

                if (response.ok) {
                    const result = await response.json();
                    ElMessage.success(
                        `全量同步完成！已同步 ${result.stats.synced} 个文件，` +
                        `跳过 ${result.stats.skipped} 个，失败 ${result.stats.failed} 个`
                    );
                    this.loadLogs();
                } else {
                    const error = await response.json();
                    ElMessage.error(error.detail || '同步失败');
                }
            } catch (error) {
                ElMessage.error('全量同步失败: ' + error.message);
            }
        },

        // 删除任务
        async deleteTask(taskId) {
            try {
                await ElMessageBox.confirm('确定要删除这个任务吗？', '警告', {
                    confirmButtonText: '确定',
                    cancelButtonText: '取消',
                    type: 'warning'
                });

                const response = await this.apiFetch(`/tasks/${taskId}`, {
                    method: 'DELETE'
                });

                if (response.ok) {
                    ElMessage.success('任务已删除');
                    this.loadTasks();
                } else {
                    const error = await response.json();
                    ElMessage.error(error.detail || '删除失败');
                }
            } catch (error) {
                if (error !== 'cancel') {
                    ElMessage.error('删除任务失败: ' + error.message);
                }
            }
        },

        // 格式化时间
        formatTime(timeStr) {
            if (!timeStr) return '-';
            const date = new Date(timeStr);
            return date.toLocaleString('zh-CN');
        },

        // 获取事件类型标签颜色
        getEventTypeTag(type) {
            const map = {
                'created': 'success',
                'modified': 'warning',
                'deleted': 'danger',
                'moved': 'info'
            };
            return map[type] || '';
        },

        // 获取事件类型名称
        getEventTypeName(type) {
            const map = {
                'created': '创建',
                'modified': '修改',
                'deleted': '删除',
                'moved': '移动'
            };
            return map[type] || type;
        }
    }
});

app.use(ElementPlus);
// 注册所有图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
    app.component(key, component);
}
app.mount('#app');
