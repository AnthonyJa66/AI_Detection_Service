<template>
    <div ref="host" class="hik-player-container"></div>
</template>

<script>
let activePlayers = 0;
let sharedDecoder = null;
let sharedContainer = null;
const sharedContainerId = 'hikvision-global-container';

export default {
    name: 'HikvisionPlayer',
    props: {
        // WebSocket 网关地址, e.g., wss://172.7.203.17:443
        accessUrl: {
            type: String,
            required: true,
        },
        // 播放模式：live(实时) / playback(回放)
        playMode: {
            type: String,
            default: 'live'
        },
        // 摄像头的 RTSP 地址
        rtspUrl: {
            type: String,
            required: false,
            default: '',
        },
        // 认证用户名
        username: {
            type: String,
            required: true,
        },
        // 认证密码
        password: {
            type: String,
            required: true,
        },
        // 多路流列表（多分屏）
        streams: {
            type: Array,
            default: () => []
        },
        // 分屏数量
        splitCount: {
            type: Number,
            default: 1
        },
        // 播放器宽度
        width: {
            type: Number,
        },
        // 播放器高度
        height: {
            type: Number,
        },
        // 页面不可见时是否自动暂停（减少多页面并发解码卡顿）
        autoPauseOnHide: {
            type: Boolean,
            default: true
        }
    },
    data() {
        return {
            playerId: 'hikplayer-' + Date.now() + Math.random().toString(36).substr(2, 9),
            jsDecoder: null,
            isPlaying: false,
            isDestroying: false,
            currentWindowIndex: 0,
            playTimer: null,
            playTaskId: 0,
            playStreamsLock: false,
            lastPlaySignature: '',
            lastSplitCount: 1,
            resizeTimer: null,
            retryTimer: null,
            retryCount: 0,
            maxRetry: 2,
            wasAutoPaused: false,
            initialSize: { width: 0, height: 0 },
        };
    },
    mounted() {
        activePlayers += 1;

        this.$nextTick(() => {
            const container = this.$el;
            if (container) {
                this.initialSize.width = container.clientWidth;
                this.initialSize.height = container.clientHeight;
            }
            // 脚本已在 index.html 中全局引入，这里直接初始化
            if (typeof JSPlugin === 'undefined') {
                console.error('JSPlugin is not loaded. Please make sure jsPlugin-1.2.0.min.js and its dependencies are included in your index.html.');
            } else {
                this.ensureSharedContainer();
                this.attachSharedContainer();
                this.initPlayer();
            }
        });


        window.addEventListener('resize', this.handleResize, false);
        document.addEventListener('fullscreenchange', this.handleResize, false);
        document.addEventListener('visibilitychange', this.handleVisibilityChange, false);



    },
    activated() {
        if (this.isDestroying) return;
        this.ensureSharedContainer();
        this.attachSharedContainer();
        if (!this.jsDecoder) {
            this.initPlayer();
            return;
        }
        this.applySplit();
        this.resizePlayer();
        if (this.wasAutoPaused) {
            this.wasAutoPaused = false;
        }
        if (this.streams && this.streams.length) {
            this.schedulePlayStreams(true);
        } else if (this.rtspUrl) {
            this.startPlay();
        }
    },
    deactivated() {
        if (this.isDestroying) return;
        if (this.autoPauseOnHide) {
            this.wasAutoPaused = true;
            this.stop();
        }
    },
    beforeDestroy() {
        this.isDestroying = true;
        if (this.playTimer) {
            clearTimeout(this.playTimer);
            this.playTimer = null;
        }
        this.playTaskId += 1;
        this.playStreamsLock = false;
        if (this.resizeTimer) {
            clearTimeout(this.resizeTimer);
            this.resizeTimer = null;
        }
        if (this.retryTimer) {
            clearTimeout(this.retryTimer);
            this.retryTimer = null;
        }
        window.removeEventListener('resize', this.handleResize, false);
        document.removeEventListener('fullscreenchange', this.handleResize, false);
        document.removeEventListener('visibilitychange', this.handleVisibilityChange, false);
        this.detachSharedContainer();
        this.stop();
        activePlayers = Math.max(activePlayers - 1, 0);
        if (activePlayers === 0 && sharedDecoder && sharedDecoder.JS_DestroyWorker) {
            try {
                sharedDecoder.JS_DestroyWorker().then(() => {
                    console.log(`Player ${this.playerId}: DestroyWorker success.`);
                }).catch(() => { });
            } catch (e) {
                // ignore destroy errors
            }
            sharedDecoder = null;
        }
        this.jsDecoder = null;
    },
    watch: {
        rtspUrl(newUrl, oldUrl) {
            if (this.isDestroying) return;
            if (this.streams && this.streams.length) return;
            if (newUrl && newUrl !== oldUrl) {
                console.log(`Player ${this.playerId}: rtspUrl changed, restarting play.`);
                this.startPlay();
            }
        },
        streams: {
            handler() {
                if (this.isDestroying) return;
                this.schedulePlayStreams();
            },
            deep: true
        },
        splitCount() {
            if (this.isDestroying) return;
            if (this.jsDecoder) {
                this.applySplit();
                this.schedulePlayStreams();
            } else {
                this.reinitPlayer();
            }
        }
    },
    methods: {
        // 处理浏览器或文档尺寸变化的回调。
        // 作用：响应 `resize` 与 `fullscreenchange` 事件，确保播放器在进入/退出全屏或窗口尺寸变化时正确调整。
        // 实现要点：当检测到退出全屏（`document.fullscreenElement` 为 null）时，强制恢复为初始化记录的尺寸；
        // 否则根据容器当前尺寸调用 `resizePlayer()` 动态调整。
        handleResize() {
            if (this.isDestroying) return;
            if (this.resizeTimer) {
                clearTimeout(this.resizeTimer);
            }
            this.resizeTimer = setTimeout(() => {
                this.resizeTimer = null;
                this.$nextTick(() => {
                    if (!this.jsDecoder || typeof this.jsDecoder.JS_Resize !== 'function') return;
                    // 如果已退出全屏模式，则恢复到初始尺寸
                    if (!document.fullscreenElement && this.initialSize.width > 0) {
                        this.jsDecoder.JS_Resize(this.initialSize.width, this.initialSize.height);
                    } else {
                        this.resizePlayer();
                    }
                });
            }, 80);
        },
        // 页面可见性变化：隐藏时暂停，显示时恢复（多页面同时播放时可明显减轻卡顿）
        handleVisibilityChange() {
            if (!this.autoPauseOnHide) return;
            if (this.isDestroying) return;
            if (document.hidden) {
                if (this.isPlaying) {
                    this.wasAutoPaused = true;
                    this.stop();
                }
                return;
            }
            if (this.wasAutoPaused) {
                this.wasAutoPaused = false;
                if (this.streams && this.streams.length) {
                    this.schedulePlayStreams(true);
                } else if (this.rtspUrl) {
                    this.startPlay();
                }
            }
        },
        // 根据容器或传入的 `width/height` 调整播放器内部解码器显示尺寸。
        // 说明：这是与解码器通信的封装，用于在布局变化时告诉插件新的宽高。
        resizePlayer() {
            if (!this.jsDecoder || typeof this.jsDecoder.JS_Resize !== 'function') return;
            const container = this.$el;
            if (!container) return;
            const width = this.width || container.clientWidth;
            const height = this.height || container.clientHeight;
            if (!width || !height) return;
            this.jsDecoder.JS_Resize(width, height);
        },
        ensureSharedContainer() {
            if (sharedContainer) return;
            const container = document.createElement('div');
            container.id = sharedContainerId;
            container.style.width = '100%';
            container.style.height = '100%';
            container.style.display = 'block';
            sharedContainer = container;
        },
        attachSharedContainer() {
            if (!sharedContainer) return;
            const host = this.$el;
            if (!host) return;
            if (sharedContainer.parentNode !== host) {
                host.appendChild(sharedContainer);
            }
        },
        detachSharedContainer() {
            if (!sharedContainer) return;
            if (sharedContainer.parentNode) {
                document.body.appendChild(sharedContainer);
            }
        },
        // 对外暴露的请求调整方法。父组件调用时会触发分屏布局应用并立即调整尺寸。
        requestResize() {
            this.applySplit();
            this.resizePlayer();
        },

        // 对外暴露的重播方法：在性能不足时尝试快速重拉流
        restartPlayback() {
            if (this.isDestroying) return;
            if (this.streams && this.streams.length) {
                this.schedulePlayStreams(true);
                return;
            }
            if (this.rtspUrl) {
                this.startPlay();
            }
        },
        // 触发插件的全屏显示（所有窗口），并在进入全屏前后确保分屏和尺寸被同步应用。
        // 目的是避免插件在内部切换期间短暂显示不期望的默认分屏（例如 3x3），从而减少闪烁。
        fullScreenAll() {
            if (!this.jsDecoder || typeof this.jsDecoder.JS_FullScreenDisplay !== 'function') return;
            this.applySplit();
            this.jsDecoder.JS_FullScreenDisplay(true);
            this.$nextTick(() => {
                this.applySplit();
                this.resizePlayer();
            });
        },
        // 将分屏数量（1、4、9、16）映射为插件所需的行/列值（1、2、3、4）。
        // 用于 `JS_ArrangeWindow` 的参数计算。
        getArrangeNumber() {
            if (this.splitCount === 1) return 1;
            if (this.splitCount === 4) return 2;
            if (this.splitCount === 9) return 3;
            if (this.splitCount === 16) return 4;
            const grid = Math.sqrt(this.splitCount || 1);
            return Number.isInteger(grid) ? grid : 1;
        },
        // 将当前组件的分屏设置应用到解码器插件上。
        // 优先调用 `JS_ArrangeWindow(arrange)`，若不可用则降级到 `JS_SetSplit`。
        applySplit() {
            if (!this.jsDecoder) return;
            const arrange = this.getArrangeNumber();
            if (typeof this.jsDecoder.JS_ArrangeWindow === 'function') {
                this.jsDecoder.JS_ArrangeWindow(arrange);
                return;
            }
            if (typeof this.jsDecoder.JS_SetSplit === 'function') {
                this.jsDecoder.JS_SetSplit(this.splitCount || 1);
            }
        },
        // 延迟调度播放多个流，合并连续调用以避免重复初始化。
        // `force` 表示是否强制重新拉流。
        schedulePlayStreams(force = false) {
            if (this.playTimer) {
                clearTimeout(this.playTimer);
            }
            const taskId = ++this.playTaskId;
            this.playTimer = setTimeout(() => {
                this.playTimer = null;
                if (taskId === this.playTaskId) {
                    this.playStreams(force);
                }
            }, 100);
        },
        scheduleRetry(type = 'single') {
            if (this.isDestroying) return;
            if (this.retryTimer) {
                clearTimeout(this.retryTimer);
            }
            if (this.retryCount >= this.maxRetry) return;
            this.retryCount += 1;
            this.retryTimer = setTimeout(() => {
                this.retryTimer = null;
                if (this.isDestroying) return;
                if (type === 'streams') {
                    this.schedulePlayStreams(true);
                } else {
                    this.startPlay();
                }
            }, 800);
        },
        resetRetry() {
            this.retryCount = 0;
            if (this.retryTimer) {
                clearTimeout(this.retryTimer);
                this.retryTimer = null;
            }
        },
        // 动态加载外部脚本（备用），在某些环境中用于按需加载插件依赖。
        loadScript(src, callback) {
            const script = document.createElement('script');
            script.src = src;
            script.onload = () => callback && callback();
            script.onerror = () => console.error(`Failed to load script: ${src}`);
            document.head.appendChild(script);
        },
        // 初始化解码器插件实例（JSPlugin），并设置回调与初始分屏/尺寸。
        // 说明：使用记录的初始尺寸作为插件的启动尺寸，随后应用分屏并尝试开始播放。
        initPlayer() {
            if (typeof JSPlugin === 'undefined') {

                return;
            }

            const container = this.$el;
            const containerWidth = this.initialSize.width || container.offsetWidth;
            const containerHeight = this.initialSize.height || container.offsetHeight;
            const desiredSplit = Math.max(this.splitCount || 1, (this.streams && this.streams.length) || 1);

            if (!sharedDecoder) {
                this.jsDecoder = new JSPlugin({
                    szId: sharedContainerId,
                    iWidth: containerWidth,
                    iHeight: containerHeight,
                    iMaxSplit: Math.min(Math.max(desiredSplit, 1), 16),
                    iCurrentSplit: this.splitCount || 1,
                    szBasePath: "./HikvisionPlayer", // 插件资源文件（如.wasm）的根路径
                    oStyle: {
                        border: "#343434",
                        borderSelect: "red",
                        background: "#4C4B4B"
                    },
                    bOnlySupportJSDecoder: true
                });
                sharedDecoder = this.jsDecoder;
            } else {
                this.jsDecoder = sharedDecoder;
            }

            this.jsDecoder.JS_SetWindowControlCallback({
                windowEventSelect: (iWndIndex) => {
                    this.currentWindowIndex = iWndIndex;
                    console.log(`Player ${this.playerId}: window ${iWndIndex} selected.`);
                },
                pluginErrorHandler: (iWndIndex, iErrorCode, oError) => {
                    console.error(`Player ${this.playerId}: Error in window ${iWndIndex}`, {
                        code: iErrorCode,
                        error: oError
                    });
                },
                performanceLack: () => {
                    console.warn(`Player ${this.playerId}: Performance lack detected.`);
                    this.$emit('performance-lack');
                }
            });

            this.applySplit();
            this.resizePlayer();

            // 初始化后开始播放
            if (this.streams && this.streams.length) {
                this.schedulePlayStreams(true);
            } else {
                this.startPlay();
            }
        },
        // 在需要时重建插件实例（例如配置变更或插件异常后尝试重建）。
        reinitPlayer() {
            if (this.isDestroying) return;
            this.jsDecoder = null;
            this.initPlayer();
        },
        // 生成当前播放流的签名字符串，用于判断流列表或分屏数是否发生变化，避免重复拉流。
        buildStreamsSignature(streams, splitCount) {
            const count = splitCount || 1;
            const list = (streams || []).slice(0, count);
            return list.map(item => `${item && item.id ? item.id : ''}:${item && item.rtspUrl ? item.rtspUrl : ''}`).join('|');
        },
        // 停止并清空指定数量窗口的播放（用于重新布局前先停止已有窗口）。
        async stopAllWindows(total) {
            if (!this.jsDecoder || !this.jsDecoder.JS_Stop) return;
            if (typeof this.jsDecoder.JS_StopRealPlayAll === 'function') {
                try {
                    await this.jsDecoder.JS_StopRealPlayAll();
                    return;
                } catch (e) {
                    // ignore
                }
            }
            const stopTotal = total || this.lastSplitCount || this.splitCount || 1;
            const tasks = [];
            for (let i = 0; i < stopTotal; i += 1) {
                try {
                    tasks.push(this.jsDecoder.JS_Stop(i));
                } catch (e) {
                    // ignore
                }
            }
            if (tasks.length) {
                try {
                    await Promise.allSettled(tasks);
                } catch (e) {
                    // ignore
                }
            }
        },
        // 开始单路播放（用于非多路 streams 场景）。
        // 如果已有播放则先停止再重新开始，确保状态清晰。
        startPlay() {
            if (this.isDestroying) return;
            if (!this.jsDecoder || !this.rtspUrl) {
                return;
            }

            // 如果正在播放，先停止
            if (this.isPlaying) {
                this.stop().then(() => {
                    this.playInternal();
                });
            } else {
                this.playInternal();
            }
        },
        // 内部调用：向插件发起单窗口播放请求并处理成功/失败回调。
        playInternal() {
            const auth = `${this.username}:${this.password}`;
            console.log(`Player ${this.playerId}: Starting play with url: ${this.rtspUrl}`);
            try {
                const playArgs = [
                    this.accessUrl,
                    {
                        playURL: this.rtspUrl,
                        auth: auth
                    },
                    0
                ];
                if (this.playMode === 'playback') {
                    playArgs.push(' ', ' ');
                }
                this.jsDecoder.JS_Play(...playArgs).then(
                    () => {
                        this.isPlaying = true;
                        this.resetRetry();
                        console.log(`Player ${this.playerId}: realplay success.`);
                        this.$emit('play-success');
                    },
                    () => {
                        this.isPlaying = false;
                        console.error(`Player ${this.playerId}: realplay failed.`);
                        this.$emit('play-error');
                        this.scheduleRetry('single');
                    }
                );
            } catch (e) {
                this.isPlaying = false;
                this.scheduleRetry('single');
            }
        },
        // 支持多路流播放：根据当前分屏数依次在各窗口发起播放请求。
        // 包含去重逻辑（签名对比）以避免重复拉取相同流，以及在改变分屏前停止已有窗口。
        async playStreams(force = false) {
            if (this.isDestroying) return;
            if (!this.jsDecoder) return;
            if (!this.streams || !this.streams.length) return;
            if (this.playStreamsLock) return;
            this.playStreamsLock = true;
            try {
                const total = this.splitCount || 1;
                console.log(` count: ${total}`);

                const signature = this.buildStreamsSignature(this.streams, total);
                if (!force && signature === this.lastPlaySignature && this.lastSplitCount === total) {
                    return;
                }
                this.lastPlaySignature = signature;
                this.lastSplitCount = total;

                this.applySplit();

                await this.stopAllWindows(Math.max(total, this.streams.length));

                let startedCount = 0;
                for (let i = 0; i < total; i += 1) {
                    const stream = this.streams[i];
                    const url = stream && stream.rtspUrl;
                    if (!url) continue;
                    try {
                        const playArgs = [
                            this.accessUrl,
                            {
                                playURL: url,
                                auth: `${this.username}:${this.password}`
                            },
                            i
                        ];
                        if (this.playMode === 'playback') {
                            playArgs.push(' ', ' ');
                        }
                        await this.jsDecoder.JS_Play(...playArgs);
                        startedCount += 1;
                    } catch (e) {
                        // ignore individual window errors
                    }
                }
                this.isPlaying = startedCount > 0;
                if (this.isPlaying) {
                    this.resetRetry();
                } else {
                    this.scheduleRetry('streams');
                }
            } catch (e) {
                this.isPlaying = false;
                this.scheduleRetry('streams');
            } finally {
                this.playStreamsLock = false;
            }
        },
        // 停止播放：根据当前是否为多路播放决定停止全部窗口或单窗口停止。
        // 返回一个 Promise，便于上层按需等待停止完成。
        stop() {
            if (!this.jsDecoder || !this.isPlaying || !this.jsDecoder.JS_Stop) {
                return Promise.resolve();
            }
            console.log(`Player ${this.playerId}: Stopping play.`);
            try {
                if (this.streams && this.streams.length) {
                    const total = Math.max(this.splitCount || 1, this.streams.length || 0, this.lastSplitCount || 1);
                    return this.stopAllWindows(total).then(() => {
                        this.isPlaying = false;
                        this.resetRetry();
                    });
                }
                return this.jsDecoder.JS_Stop(0).then(
                    () => {
                        this.isPlaying = false;
                        this.resetRetry();
                        console.log(`Player ${this.playerId}: stop success.`);
                    },
                    () => {
                        console.error(`Player ${this.playerId}: stop failed.`);
                    }
                );
            } catch (e) {
                this.isPlaying = false;
                this.resetRetry();
                return Promise.resolve();
            }
        },
        stopPlayback() {
            if (!this.jsDecoder || !this.jsDecoder.JS_Stop) {
                return Promise.resolve();
            }
            try {
                if (this.streams && this.streams.length) {
                    const total = Math.max(this.splitCount || 1, this.streams.length || 0, this.lastSplitCount || 1);
                    return this.stopAllWindows(total);
                }
                const index = Number.isInteger(this.currentWindowIndex) ? this.currentWindowIndex : 0;
                return this.jsDecoder.JS_Stop(index);
            } catch (e) {
                return Promise.resolve();
            }
        },
        slowPlay() {
            if (!this.jsDecoder || typeof this.jsDecoder.JS_Slow !== 'function') {
                return Promise.reject(new Error('JS_Slow not available'));
            }
            const index = Number.isInteger(this.currentWindowIndex) ? this.currentWindowIndex : 0;
            try {
                return this.jsDecoder.JS_Slow(index);
            } catch (e) {
                return Promise.reject(e);
            }
        },
        fastPlay(step = 1) {
            if (!this.jsDecoder || typeof this.jsDecoder.JS_Fast !== 'function') {
                return Promise.reject(new Error('JS_Fast not available'));
            }
            const index = Number.isInteger(this.currentWindowIndex) ? this.currentWindowIndex : 0;
            const speedStep = typeof step === 'number' ? step : 1;
            try {
                return this.jsDecoder.JS_Fast(index, speedStep);
            } catch (e) {
                return Promise.reject(e);
            }
        },
        // 开启音频
        openSound() {
            if (!this.jsDecoder || typeof this.jsDecoder.JS_OpenSound !== 'function') {
                return Promise.reject(new Error('JS_OpenSound not available'));
            }
            const index = Number.isInteger(this.currentWindowIndex) ? this.currentWindowIndex : 0;
            try {
                this.jsDecoder.JS_OpenSound(index);
                return Promise.resolve();
            } catch (e) {
                return Promise.reject(e);
            }
        },
        // 关闭音频
        closeSound() {
            if (!this.jsDecoder || typeof this.jsDecoder.JS_CloseSound !== 'function') {
                return Promise.reject(new Error('JS_CloseSound not available'));
            }
            try {
                // 按 demo 行为强制关闭全局音频，避免传 index 时插件无效但不抛错。
                this.jsDecoder.JS_CloseSound();
                return Promise.resolve();
            } catch (e) {
                return Promise.reject(e);
            }
        },
        setActiveWindow(index) {
            const nextIndex = Number.isInteger(index) ? index : 0;
            this.currentWindowIndex = nextIndex;
            if (!this.jsDecoder) return;
            if (typeof this.jsDecoder.JS_SelectWindow === 'function') {
                try {
                    this.jsDecoder.JS_SelectWindow(nextIndex);
                } catch (e) {
                    // ignore select errors
                }
            }
        }
    }
};
</script>

<style scoped>
.hik-player-container {
    width: 100%;
    height: 100%;
    background-color: #000;
}
</style>
