(function () {
    // 海康 Web SDK 公共播放器桥接层。
    // 主界面、hik_test、hik_fusion_test 统一复用这里的初始化、播放和声音控制逻辑。
    // 海康 Web SDK 公共播放器桥接层。
    // 主界面、hik_test、hik_fusion_test 统一复用这里的初始化、播放和声音控制逻辑。
    const LAST_ERROR_DESCRIPTION_MAP = Object.freeze({
        0: "参数错误",
        1: "成功",
        2: "调用接口顺序错误",
        3: "创建多媒体时钟错误",
        4: "视频设备错误",
        5: "音频设备错误",
        6: "申请内存失败",
        7: "打开文件失败",
        11: "缓存溢出",
        12: "创建音频设备失败",
        13: "设置音频音量失败",
        14: "只支持文件模式",
        15: "只支持流模式",
        16: "当前环境或能力不支持",
        17: "无文件头信息",
        18: "解码库版本不正确",
        19: "初始化解码库失败",
        20: "数据有误",
        21: "初始化多媒体时钟失败",
        22: "Blt 失败",
        24: "打开文件失败，码流是复合流",
        25: "打开文件失败，码流是纯视频",
        26: "JPEG 编码失败",
        27: "当前版本不支持该能力",
        28: "解析数据失败",
        29: "密钥错误",
        30: "解码关键帧失败",
        31: "需要更多数据才能解析",
        33: "未找到目标数据",
        34: "需要更大的缓存",
        40: "RTP 解析库初始化错误",
        41: "RTP 解析句柄创建失败",
        42: "RTP 解析输出数据不足",
        43: "句柄创建失败",
        44: "解码失败",
        45: "new 失败",
        46: "前置条件不满足",
        47: "码流解析错误",
        48: "收到的不是关键帧",
        60: "Worker 错误",
        61: "创建渲染句柄失败",
        62: "播放相关 JS 文件未加载完成",
        63: "获取音量失败",
        71: "音频编码参数错误",
        72: "音频编码前置条件不满足",
        73: "音频编码失败",
        74: "创建音频编码器失败",
        75: "音频编码不支持",
        76: "音频编码内存申请失败",
        77: "音频编码缓冲区已满",
        78: "音频编码需要更多数据",
        79: "音频编码调用顺序错误",
        99: "未知错误",
        100: "定位后送入的第一帧 I 帧解码失败",
        101: "定位后送入的第一帧不是对应 I 帧",
    });

    let player = null;
    let initialized = false;
    let isPlaying = false;
    let lastCameraId = "";
    let activeContainerId = "";
    let operationChain = Promise.resolve();

    function formatError(error) {
        if (!error) {
            return "Unknown error";
        }
        if (typeof error === "string") {
            return error;
        }
        if (error instanceof Error) {
            return error.message || String(error);
        }
        if (typeof error === "object") {
            const parts = [];
            if (error.iErrorNum !== undefined) {
                parts.push(`iErrorNum=${error.iErrorNum}`);
            }
            if (error.errorCode !== undefined) {
                parts.push(`errorCode=${error.errorCode}`);
            }
            if (error.statusString) {
                parts.push(`status=${error.statusString}`);
            }
            if (error.subStatusCode) {
                parts.push(`subStatusCode=${error.subStatusCode}`);
            }
            if (error.message) {
                parts.push(`message=${error.message}`);
            }
            if (error.lastErrorCode !== undefined) {
                parts.push(`lastErrorCode=${error.lastErrorCode}`);
            }
            if (error.lastErrorDescription) {
                parts.push(`lastErrorDescription=${error.lastErrorDescription}`);
            }
            if (parts.length) {
                return parts.join(", ");
            }
            try {
                return JSON.stringify(error);
            } catch (_jsonError) {
                return String(error);
            }
        }
        return String(error);
    }

    function describeLastErrorCode(code) {
        if (code === undefined || code === null || code === "") {
            return "未返回错误码";
        }
        return LAST_ERROR_DESCRIPTION_MAP[code] || "未知错误码，请结合控制台完整日志排查";
    }

    function readLastError(currentPlayer) {
        if (!currentPlayer || typeof currentPlayer.JS_GetLastError !== "function") {
            return {
                code: null,
                description: "播放器实例不支持 JS_GetLastError",
            };
        }

        try {
            const code = currentPlayer.JS_GetLastError();
            console.log("player.JS_GetLastError()", code);
            console.log("player.JS_GetLastError() 说明", describeLastErrorCode(code));
            return {
                code,
                description: describeLastErrorCode(code),
            };
        } catch (error) {
            return {
                code: null,
                description: `读取 JS_GetLastError 失败: ${formatError(error)}`,
            };
        }
    }

    function urlContainsCredentials(value) {
        if (!value) {
            return false;
        }
        try {
            const parsed = new URL(String(value));
            return Boolean(parsed.username || parsed.password);
        } catch (_error) {
            return /^rtsp:\/\/[^/@:\s]+:[^/@\s]+@/i.test(String(value));
        }
    }

    function normalizePlayRequest(request) {
        const source = request || {};
        return {
            accessUrl: source.accessUrl || source.access_url || source.wsURL || source.ws_url || "",
            wsURL: source.wsURL || source.ws_url || source.accessUrl || source.access_url || "",
            playURL: source.playURL || source.play_url || source.previewUrl || source.rtsp_url || "",
            username: source.username || "",
            password: source.password || "",
            streamMode: source.streamMode ?? source.stream_mode ?? null,
            transMode: source.transMode ?? source.trans_mode ?? null,
            gpuMode: source.gpuMode ?? source.gpu_mode ?? null,
            cameraIndexCode: source.cameraIndexCode ?? source.camera_index_code ?? "",
            cameraId: source.cameraId || source.camera_id || "",
        };
    }

    function buildPlayRequest(config) {
        return normalizePlayRequest(config || {});
    }

    function logPlayRequestComparison(tag, request) {
        const normalized = normalizePlayRequest(request);
        console.log(`[${tag}] 参数对比`, {
            playURL: normalized.playURL,
            wsURL: normalized.wsURL,
            streamMode: normalized.streamMode,
            transMode: normalized.transMode,
            gpuMode: normalized.gpuMode,
            cameraIndexCode: normalized.cameraIndexCode || normalized.cameraId || "",
        });
        return normalized;
    }

    function maskAuth(value) {
        if (!value) {
            return "";
        }
        const index = String(value).indexOf(":");
        if (index === -1) {
            return "********";
        }
        return `${String(value).slice(0, index)}:********`;
    }

    function createLogger(callback) {
        return function log(level, message, extra) {
            const payload = extra || {};
            if (level === "error") {
                console.error("[HIK_COMMON]", message, payload);
            } else if (level === "warn") {
                console.warn("[HIK_COMMON]", message, payload);
            } else {
                console.log("[HIK_COMMON]", message, payload);
            }
            if (typeof callback === "function") {
                callback(level, message, payload);
            }
        };
    }

    function getContainerSize(container) {
        if (!container) {
            throw new Error("Player container not found.");
        }
        const rect = container.getBoundingClientRect();
        const width = Math.max(1, Math.round(rect.width || container.clientWidth || 0));
        const height = Math.max(1, Math.round(rect.height || container.clientHeight || 0));
        if (!width || !height) {
            throw new Error("Player container size is unavailable.");
        }
        return { width, height };
    }

    function validateInitConfig(config) {
        const missingKeys = ["containerId", "demoBasePath"]
            .filter((key) => !config[key]);
        if (missingKeys.length) {
            throw new Error(`Player init config missing: ${missingKeys.join(", ")}`);
        }
        if (typeof window.JSPlugin === "undefined") {
            throw new Error("JSPlugin is not loaded.");
        }
    }

    function validatePlayRequest(request) {
        const missingKeys = ["accessUrl", "playURL"]
            .filter((key) => !request[key]);
        if (missingKeys.length) {
            throw new Error(`Play config missing: ${missingKeys.join(", ")}`);
        }
        if (urlContainsCredentials(request.playURL)) {
            // 海康 SDK 要求用户名密码走 auth，不能继续放在 playURL 中。
            throw new Error("playURL must not include username/password.");
        }
    }

    function nextFrame() {
        return new Promise(function (resolve) {
            window.requestAnimationFrame(function () {
                resolve();
            });
        });
    }

    function callPlayerMethod(currentPlayer, methodNames, args) {
        const names = Array.isArray(methodNames) ? methodNames : [methodNames];
        for (let index = 0; index < names.length; index += 1) {
            const methodName = names[index];
            if (currentPlayer && typeof currentPlayer[methodName] === "function") {
                try {
                    return Promise.resolve(currentPlayer[methodName].apply(currentPlayer, args || []));
                } catch (error) {
                    return Promise.reject(error);
                }
            }
        }
        return Promise.resolve();
    }

    function hasPlayerMethod(currentPlayer, methodName) {
        return Boolean(currentPlayer && typeof currentPlayer[methodName] === "function");
    }

    function create(config) {
        validateInitConfig(config || {});

        const logger = createLogger(config.onLog);
        const container = document.getElementById(config.containerId);
        let soundUnlockHandler = null;
        let soundEnabled = false;

        function clearSoundUnlockHandler() {
            if (!soundUnlockHandler) {
                return;
            }
            document.removeEventListener("click", soundUnlockHandler, true);
            soundUnlockHandler = null;
        }

        async function ensureContainerReady() {
            // 容器未渲染或尺寸为 0 时，海康播放器很容易出现初始化失败或黑屏。
            for (let attempt = 0; attempt < 6; attempt += 1) {
                try {
                    const size = getContainerSize(container);
                    const computedStyle = window.getComputedStyle(container);
                    if (computedStyle.display !== "none" && computedStyle.visibility !== "hidden") {
                        logger("info", "container size", {
                            width: size.width,
                            height: size.height,
                            display: computedStyle.display,
                            visibility: computedStyle.visibility,
                            attempt,
                        });
                        return size;
                    }
                } catch (_error) {
                    // ignore and retry
                }
                await nextFrame();
                await new Promise(function (resolve) {
                    window.setTimeout(resolve, 40);
                });
            }
            throw new Error("Player container is hidden or has zero size.");
        }

        async function init() {
            if (initialized && player) {
                return player;
            }

            if (player && activeContainerId && activeContainerId !== config.containerId) {
                await destroy();
            }

            const size = await ensureContainerReady();
            player = new window.JSPlugin({
                szId: config.containerId,
                iWidth: Math.max(640, size.width),
                iHeight: Math.max(360, size.height),
                iMaxSplit: 1,
                iCurrentSplit: 1,
                szBasePath: config.demoBasePath,
                oStyle: {
                    border: "#243041",
                    borderSelect: "#2563eb",
                    background: "#020617",
                },
                bOnlySupportJSDecoder: true,
            });
            activeContainerId = config.containerId;

            player.JS_SetWindowControlCallback({
                windowEventSelect(iWndIndex) {
                    logger("info", "window selected", { iWndIndex });
                },
                pluginErrorHandler(iWndIndex, iErrorCode, oError) {
                    logger("error", "plugin error", { iWndIndex, iErrorCode, oError });
                    console.log("plugin error code description", describeLastErrorCode(iErrorCode));
                    if (typeof config.onPluginError === "function") {
                        config.onPluginError(iWndIndex, iErrorCode, oError);
                    }
                },
                performanceLack() {
                    logger("warn", "performance lack");
                    if (typeof config.onPerformanceLack === "function") {
                        config.onPerformanceLack();
                    }
                },
            });

            initialized = true;
            logger("info", "init success", {
                containerId: config.containerId,
                basePath: config.demoBasePath,
            });
            return player;
        }

        async function resize() {
            if (!player || typeof player.JS_Resize !== "function") {
                return;
            }
            try {
                const size = await ensureContainerReady();
                container.style.width = `${size.width}px`;
                container.style.height = `${size.height}px`;
                logger("info", "resize", size);
                player.JS_Resize(size.width, size.height);
            } catch (error) {
                logger("warn", "resize skipped", { error: error.message || String(error) });
            }
        }

        function scheduleResizeSync(delays) {
            const waitDelays = Array.isArray(delays) && delays.length
                ? delays
                : [0, 100, 300, 800];
            waitDelays.forEach(function (delay) {
                window.setTimeout(function () {
                    resize();
                }, delay);
            });
        }

        async function closeSoundFor(currentPlayer) {
            clearSoundUnlockHandler();
            soundEnabled = false;
            if (!hasPlayerMethod(currentPlayer, "JS_CloseSound")) {
                return false;
            }
            try {
                await currentPlayer.JS_CloseSound();
                logger("info", "sound closed", { iWndIndex: 0 });
                return true;
            } catch (error) {
                logger("warn", "close sound skipped", {
                    iWndIndex: 0,
                    error: formatError(error),
                });
                return false;
            }
        }

        async function enableSound(volume) {
            // 当前项目真实使用的开声接口是 JS_OpenSound / JS_SetVolume。
            if (!player || !isPlaying || !hasPlayerMethod(player, "JS_OpenSound")) {
                return false;
            }

            const soundVolume = Number.isFinite(Number(volume))
                ? Math.max(0, Math.min(100, Number(volume)))
                : 100;

            try {
                await player.JS_OpenSound(0);
                if (hasPlayerMethod(player, "JS_SetVolume")) {
                    await player.JS_SetVolume(0, soundVolume);
                }
                soundEnabled = true;
                clearSoundUnlockHandler();
                logger("info", "sound enabled", {
                    iWndIndex: 0,
                    volume: soundVolume,
                    audioMethod: "JS_OpenSound",
                });
                return true;
            } catch (error) {
                const lastError = readLastError(player);
                logger("warn", "enable sound failed", {
                    iWndIndex: 0,
                    error: formatError(error),
                    lastErrorCode: lastError.code,
                    lastErrorDescription: lastError.description,
                    audioMethod: "JS_OpenSound",
                });
                return false;
            }
        }

        function bindSoundUnlockOnce() {
            // 浏览器自动播放策略要求通过一次用户交互来解锁声音。
            if (soundUnlockHandler || soundEnabled) {
                return;
            }
            soundUnlockHandler = function () {
                clearSoundUnlockHandler();
                enableSound(config.soundVolume);
            };
            document.addEventListener("click", soundUnlockHandler, {
                capture: true,
                once: true,
            });
            logger("info", "sound unlock awaiting user gesture", {
                iWndIndex: 0,
                audioMethod: "JS_OpenSound",
            });
        }

        async function stop() {
            if (!player) {
                return;
            }
            // 先关旧声音，再停流，避免切流后声音叠加或延迟累计。
            logger("info", "stop previous stream", {
                iWndIndex: 0,
                cameraId: lastCameraId || "",
            });
            await closeSoundFor(player);
            try {
                await callPlayerMethod(player, ["JS_StopRealPlay", "JS_StopRealPlayAll", "JS_Stop"], [0]);
            } finally {
                isPlaying = false;
            }
        }

        async function safeResetPlayer() {
            if (!player) {
                return;
            }
            const currentPlayer = player;
            await closeSoundFor(currentPlayer);
            try {
                await callPlayerMethod(currentPlayer, ["JS_StopRealPlay", "JS_StopRealPlayAll", "JS_Stop"], [0]);
            } catch (error) {
                logger("warn", "stop before play failed", { error: formatError(error) });
            }
            try {
                await callPlayerMethod(currentPlayer, ["JS_DestroyWnd", "JS_DestroyWorker"], []);
            } catch (error) {
                logger("warn", "destroy before play failed", { error: formatError(error) });
            }

            player = null;
            initialized = false;
            isPlaying = false;
            lastCameraId = "";
            activeContainerId = "";
        }

        function play(request) {
            const normalizedRequest = normalizePlayRequest(request);
            validatePlayRequest(normalizedRequest);

            operationChain = operationChain.catch(function () {
                return undefined;
            }).then(async function () {
                await safeResetPlayer();
                await init();
                await resize();

                // 认证信息单独放在 auth 中，playURL 保持无凭证地址。
                const auth = normalizedRequest.username || normalizedRequest.password
                    ? `${normalizedRequest.username || ""}:${normalizedRequest.password || ""}`
                    : "";
                const params = {
                    accessUrl: normalizedRequest.accessUrl,
                    playParams: {
                        playURL: normalizedRequest.playURL,
                        wsURL: normalizedRequest.wsURL || normalizedRequest.accessUrl,
                    },
                    iWndIndex: 0,
                };
                if (auth) {
                    params.playParams.auth = auth;
                }

                logger("info", "prepare play", {
                    cameraId: normalizedRequest.cameraId || "",
                    wndId: 0,
                });
                logger("info", "play request params", {
                    accessUrl: normalizedRequest.accessUrl,
                    wsURL: normalizedRequest.wsURL || normalizedRequest.accessUrl,
                    playURL: normalizedRequest.playURL,
                    auth: maskAuth(auth),
                    streamMode: normalizedRequest.streamMode,
                    transMode: normalizedRequest.transMode,
                    gpuMode: normalizedRequest.gpuMode,
                    cameraIndexCode: normalizedRequest.cameraIndexCode || normalizedRequest.cameraId || "",
                    iWndIndex: 0,
                });

                return player.JS_Play(
                    params.accessUrl,
                    params.playParams,
                    params.iWndIndex,
                ).then(
                    async function (result) {
                        isPlaying = true;
                        soundEnabled = false;
                        lastCameraId = normalizedRequest.cameraId || "";
                        logger("info", "play success", {
                            iWndIndex: 0,
                            cameraId: lastCameraId,
                        });
                        if (config.autoEnableSound !== false) {
                            const opened = await enableSound(config.soundVolume);
                            if (!opened) {
                                bindSoundUnlockOnce();
                            }
                        } else {
                            clearSoundUnlockHandler();
                            logger("info", "auto sound disabled for this player", {
                                iWndIndex: 0,
                            });
                        }
                        return result;
                    },
                    function (error) {
                        isPlaying = false;
                        soundEnabled = false;
                        const lastError = readLastError(player);
                        logger("error", "play failed", {
                            iWndIndex: 0,
                            cameraId: normalizedRequest.cameraId || "",
                            error: formatError(error || "JS_Play Promise rejected"),
                            lastErrorCode: lastError.code,
                            lastErrorDescription: lastError.description,
                        });
                        const playbackError = new Error(formatError(error || "JS_Play Promise rejected"));
                        playbackError.originalError = error;
                        playbackError.lastErrorCode = lastError.code;
                        playbackError.lastErrorDescription = lastError.description;
                        throw playbackError;
                    },
                );
            });

            return operationChain;
        }

        async function destroy() {
            if (!player) {
                return;
            }
            const currentPlayer = player;
            await closeSoundFor(currentPlayer);
            player = null;
            initialized = false;
            isPlaying = false;
            lastCameraId = "";
            activeContainerId = "";
            try {
                await callPlayerMethod(currentPlayer, ["JS_DestroyWnd", "JS_DestroyWorker"], []);
            } catch (_error) {
                // ignore destroy cleanup errors
            }
        }

        return {
            init,
            play,
            stop,
            resize,
            scheduleResizeSync,
            enableSound,
            closeSound: function () {
                return closeSoundFor(player);
            },
            destroy,
            getWindowIndex: function () {
                return 0;
            },
            getLastErrorInfo: function () {
                return readLastError(player);
            },
        };
    }

    window.HikCommonPlayer = {
        create,
        buildPlayRequest,
        formatError,
        logPlayRequestComparison,
        describeLastErrorCode,
    };
})();
