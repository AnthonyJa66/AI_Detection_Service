// 主界面前端控制脚本。
// 负责摄像头切换、播放分流、检测叠框轮询、实时报警展示，以及 NVR 声音开关。

const STATUS_CLASS_MAP = {
    running: "status-running",
    connecting: "status-connecting",
    reconnecting: "status-reconnecting",
    stopped: "status-stopped",
    error: "status-error"
};

const STATUS_TEXT_MAP = {
    running: "在线",
    connecting: "连接中",
    reconnecting: "重连中",
    stopped: "离线",
    error: "异常"
};

const VIOLATION_LABEL_MAP = {
    smoking: "抽烟行为",
    smoke: "抽烟行为",
    no_vest: "无反光背心",
    novest: "无反光背心",
    no_helmet: "无安全帽",
    nohelmet: "无安全帽"
};

const VIOLATION_STYLE_MAP = window.CAMERA_PAGE_CONFIG?.annotationStyles || {};

// 页面级状态：播放和检测展示需要围绕同一个 selectedCameraId 协同工作。
let alarmSocket = null;
let alarmReconnectTimer = null;
let alarmReconnectDelay = 1000;
let selectedCameraId = window.CAMERA_PAGE_CONFIG.defaultCameraId || "";
let latestStatusMap = {};
let latestAlarmSignature = "";
let latestAlarmMap = new Map();

let hikPlayerController = null;
let activePlayerType = "";
let mjpegPlayerElement = null;
let overlayTimer = null;
let overlayCanvas = null;
let overlayContext = null;
let currentPlaybackConfig = null;
let playbackRequestId = 0;
let currentPlayingCameraId = "";
let hasScheduledInitialPlayback = false;
let nvrSoundEnabled = false;

document.addEventListener("DOMContentLoaded", () => {
    overlayCanvas = document.getElementById("overlayCanvas");
    overlayContext = overlayCanvas ? overlayCanvas.getContext("2d") : null;
    mjpegPlayerElement = document.getElementById("video-player");

    bindCameraSwitcher();
    bindNvrSoundToggle();
    resetNvrSoundState();
    fetchCameraStatus();
    fetchLatestAlarms();
    connectAlarmSocket();
    // 检测轮询与播放解耦，只要 camera_id 一致就持续拉取检测结果。
    startOverlayPolling();
    ensureMainPlayback(selectedCameraId, "initial");

    window.setInterval(fetchCameraStatus, 3000);
    window.setInterval(fetchLatestAlarms, 10000);

    window.addEventListener("resize", () => {
        syncMainVideoStageSize();
        refreshOverlayDetections();
    });
});

function bindCameraSwitcher() {
    const buttons = document.querySelectorAll("[data-camera-select]");
    buttons.forEach((button) => {
        button.addEventListener("click", () => {
            switchMainCamera(button.dataset.cameraSelect);
        });
    });
}

function getNvrSoundToggleButton() {
    return document.getElementById("nvr-sound-toggle");
}

function updateNvrSoundToggleButton() {
    const button = getNvrSoundToggleButton();
    if (!button) {
        return;
    }
    const shouldShow = activePlayerType === "hik";
    button.hidden = !shouldShow;
    button.textContent = nvrSoundEnabled ? "关闭声音" : "开启声音";
}

function resetNvrSoundState() {
    nvrSoundEnabled = false;
    updateNvrSoundToggleButton();
}

function bindNvrSoundToggle() {
    const button = getNvrSoundToggleButton();
    if (!button) {
        return;
    }
    button.addEventListener("click", async () => {
        if (activePlayerType !== "hik" || !hikPlayerController) {
            return;
        }
        try {
            if (nvrSoundEnabled) {
                await hikPlayerController.closeSound();
                nvrSoundEnabled = false;
            } else {
                const enabled = await hikPlayerController.enableSound(100);
                if (!enabled) {
                    return;
                }
                nvrSoundEnabled = true;
            }
            updateNvrSoundToggleButton();
        } catch (error) {
            console.error("[INDEX_PLAYER] sound toggle failed", error);
        }
    });
}

function getCameraButton(cameraId) {
    if (!cameraId) {
        return null;
    }
    return document.querySelector(`[data-camera-select='${cameraId}']`);
}

function getCameraMeta(cameraId) {
    const button = getCameraButton(cameraId);
    if (!button) {
        return null;
    }

    return {
        camera_id: button.dataset.cameraId || cameraId,
        type: button.dataset.cameraType || "rtsp",
        name: button.querySelector(".camera-list-name")?.textContent || "",
    };
}

function switchMainCamera(cameraId) {
    if (!cameraId) {
        return;
    }
    if (cameraId === selectedCameraId && cameraId === currentPlayingCameraId) {
        return;
    }
    selectedCameraId = cameraId;
    const buttonNodes = document.querySelectorAll("[data-camera-select]");
    buttonNodes.forEach((node) => {
        node.classList.toggle("is-active", node.dataset.cameraSelect === cameraId);
    });

    updateSelectedCameraPanel();
    clearOverlayCanvas();
    resetLiveViolationStats();
    // 切摄像头时先更新检测展示，再异步切播放，避免统计卡片依赖播放成功。
    startOverlayPolling();
    setPlayerOverlayText("正在切换视频流...");
    ensureMainPlayback(cameraId, "switch");
}

function updateCameraSidebar(statusMap) {
    const items = document.querySelectorAll("[data-role='camera-list-status']");
    items.forEach((item) => {
        const cameraId = item.dataset.cameraId;
        const status = statusMap[cameraId] || { status: "stopped" };
        item.textContent = STATUS_TEXT_MAP[status.status] || "未知";
        item.className = `camera-runtime-status ${STATUS_CLASS_MAP[status.status] || "status-stopped"}`;
    });
}

function updateSelectedCameraPanel() {
    const selectedButton = document.querySelector(`[data-camera-select='${selectedCameraId}']`);
    const selectedNameNode = document.getElementById("selected-camera-name");
    const selectedMetaNode = document.getElementById("selected-camera-meta");
    const selectedStatusNode = document.getElementById("selected-camera-status");
    const selectedFpsNode = document.getElementById("selected-camera-fps");

    if (!selectedButton || !selectedNameNode || !selectedMetaNode || !selectedStatusNode || !selectedFpsNode) {
        return;
    }

    const nameText = selectedButton.querySelector(".camera-list-name")?.textContent || "未命名摄像头";
    const locationText = selectedButton.querySelector(".camera-list-location")?.textContent || "未设置位置";
    const status = latestStatusMap[selectedCameraId] || { status: "stopped", fps: 0 };
    const camera = getCameraMeta(selectedCameraId);

    selectedNameNode.textContent = nameText;
    selectedMetaNode.textContent = locationText;
    selectedStatusNode.textContent = STATUS_TEXT_MAP[status.status] || "未知";
    selectedStatusNode.className = `status-badge ${STATUS_CLASS_MAP[status.status] || "status-stopped"}`;
    // NVR 真实播放帧率无法直接从海康 SDK 读取，这里只展示运行态文案，不再伪装成 FPS。
    if (status.status === "running") {
        selectedFpsNode.textContent = camera?.type === "nvr" ? "实时播放 / 检测中" : "检测中";
    } else if (status.status === "connecting") {
        selectedFpsNode.textContent = "检测连接中";
    } else if (status.status === "reconnecting") {
        selectedFpsNode.textContent = "检测重连中";
    } else if (status.status === "error") {
        selectedFpsNode.textContent = "检测异常";
    } else {
        selectedFpsNode.textContent = "检测离线";
    }
}

function setPlayerOverlayText(text, hidden = false) {
    const overlay = document.getElementById("main-camera-overlay");
    const overlayText = document.getElementById("main-camera-overlay-text");
    if (!overlay || !overlayText) {
        return;
    }

    overlayText.textContent = text;
    overlay.classList.toggle("is-hidden", hidden);
}

function formatPlayError(error) {
    if (window.HikCommonPlayer && typeof window.HikCommonPlayer.formatError === "function") {
        return window.HikCommonPlayer.formatError(error);
    }
    if (error && typeof error === "object") {
        try {
            return JSON.stringify(error);
        } catch (_jsonError) {
            return String(error);
        }
    }
    return String(error || "Unknown error");
}

async function initHikPlayer() {
    try {
        if (hikPlayerController) {
            return;
        }
        hikPlayerController = window.HikCommonPlayer.create({
            containerId: "hikPlayerContainer",
            demoBasePath: window.CAMERA_PAGE_CONFIG.hikDemoBasePath,
            onLog(level, message, extra) {
                if (level === "error") {
                    setPlayerOverlayText(`播放器错误：${message}`, false);
                }
                console.log("[INDEX_HIK_BRIDGE]", message, extra || {});
            },
            onPluginError(iWndIndex, iErrorCode) {
                setPlayerOverlayText(`播放器内部错误：${iErrorCode}`, false);
                console.error("[INDEX_HIK_BRIDGE] plugin error", { iWndIndex, iErrorCode });
            },
        });
        await hikPlayerController.init();
        syncMainVideoStageSize();
        setPlayerOverlayText("海康播放器初始化成功，准备播放...", false);
    } catch (error) {
        console.error("[INDEX_HIK] init failed", error);
        setPlayerOverlayText(`播放器初始化失败：${error.message || error}`, false);
        throw error;
    }
}

function legacyEnsureMainPlayback_DoNotUse(cameraId, reason = "manual") {
    if (!hikPlayerController || !cameraId) {
        return;
    }
    if (reason === "initial") {
        if (hasScheduledInitialPlayback) {
            return;
        }
        hasScheduledInitialPlayback = true;
    }
    if (cameraId === currentPlayingCameraId && reason !== "switch") {
        console.log("[INDEX_HIK] skip duplicate play", { cameraId, reason });
        return;
    }
    legacyStartCameraPlayback_DoNotUse(cameraId, reason);
}

async function legacyStartCameraPlayback_DoNotUse(cameraId, reason = "manual") {
    if (!hikPlayerController || !cameraId) {
        return;
    }

    stopOverlayPolling();
    clearOverlayCanvas();
    const requestId = ++playbackRequestId;

    try {
        currentPlaybackConfig = await fetchPlaybackConfigNormalized(cameraId);
        if (requestId !== playbackRequestId) {
            console.log("[INDEX_HIK] skip stale play request", { cameraId, reason });
            return;
        }
        validatePlaybackConfig(currentPlaybackConfig);
        await hikPlayerController.play(buildCommonPlayRequest(currentPlaybackConfig));

        if (requestId !== playbackRequestId) {
            return;
        }

        setPlayerOverlayText("", true);
        console.log("[INDEX_HIK] 播放成功", {
            cameraId,
            reason,
            accessUrl: currentPlaybackConfig.access_url,
            playURL: currentPlaybackConfig.play_url
        });
        currentPlayingCameraId = cameraId;
        syncMainVideoStageAfterPlayback();
        startOverlayPolling();
    } catch (error) {
        const readableError = formatPlayError(error);
        console.error("[INDEX_HIK] start play failed", {
            error: readableError,
            reason,
            accessUrl: currentPlaybackConfig?.access_url || "",
            playURL: currentPlaybackConfig?.play_url || "",
            authEmpty: !currentPlaybackConfig?.username || !currentPlaybackConfig?.password,
            authInUrl: Boolean(currentPlaybackConfig?.auth_in_url),
            rawPlayURL: currentPlaybackConfig?.raw_play_url || ""
        });
        currentPlayingCameraId = "";
        setPlayerOverlayText(`播放失败：${readableError}`, false);
    }
}

function resizeHikPlayer() {
    if (!hikPlayerController) {
        return;
    }
    hikPlayerController.resize();
}

function syncMainVideoStageSize() {
    const stage = document.getElementById("mainVideoStage");
    const playerLayer = document.getElementById("hikPlayerContainer");
    if (!stage || !playerLayer) {
        return { width: 0, height: 0 };
    }

    const width = Math.max(1, Math.round(stage.clientWidth));
    const height = Math.max(1, Math.round(stage.clientHeight));
    playerLayer.style.width = `${width}px`;
    playerLayer.style.height = `${height}px`;

    if (overlayCanvas) {
        overlayCanvas.width = width;
        overlayCanvas.height = height;
        overlayCanvas.style.width = `${width}px`;
        overlayCanvas.style.height = `${height}px`;
    }

    if (hikPlayerController) {
        hikPlayerController.resize();
    }

    return { width, height };
}

function syncMainVideoStageAfterPlayback() {
    syncMainVideoStageSize();
    if (hikPlayerController && typeof hikPlayerController.scheduleResizeSync === "function") {
        hikPlayerController.scheduleResizeSync([100, 300, 800]);
    } else {
        [100, 300, 800].forEach((delay) => {
            window.setTimeout(() => {
                syncMainVideoStageSize();
            }, delay);
        });
    }
    [100, 300, 800].forEach((delay) => {
        window.setTimeout(() => {
            syncOverlayCanvasSize();
            refreshOverlayDetections();
        }, delay);
    });
}

function validatePlaybackConfig(config) {
    const missingKeys = ["access_url", "play_url", "username", "password"]
        .filter((key) => !config?.[key]);
    if (missingKeys.length) {
        throw new Error(`播放配置缺失：${missingKeys.join(", ")}`);
    }
}

function logPlaybackAttempt(stage, config) {
    console.log(`[INDEX_HIK] ${stage}`, {
        accessUrl: config.access_url,
        playURL: config.play_url,
        rawPlayURL: config.raw_play_url || "",
        authEmpty: !config.username || !config.password,
        authInUrl: Boolean(config.auth_in_url),
        sourceType: config.source_type || ""
    });
}

function buildCommonPlayRequest(config) {
    logPlaybackAttempt("准备播放", config);
    return {
        accessUrl: config.access_url,
        playURL: config.play_url,
        username: config.username,
        password: config.password,
        cameraId: config.camera_id || selectedCameraId || "",
    };
}

async function stopCurrentPlayer() {
    // 播放切换统一走“关声音 -> 停旧流 -> 销毁实例 -> 清空当前状态”。
    resetNvrSoundState();
    if (mjpegPlayerElement) {
        mjpegPlayerElement.removeAttribute("src");
        mjpegPlayerElement.style.display = "none";
    }
    const hikContainer = document.getElementById("hikPlayerContainer");
    if (hikContainer) {
        hikContainer.style.display = "none";
    }
    if (hikPlayerController) {
        try {
            await hikPlayerController.stop();
            await hikPlayerController.destroy();
        } catch (error) {
            console.warn("[INDEX_PLAYER] stop previous player failed", error);
        }
        hikPlayerController = null;
    }
    activePlayerType = "";
    currentPlayingCameraId = "";
}

async function initHikPlayer(config) {
    if (!config?.ws_url || !config?.rtsp_url) {
        throw new Error("NVR播放配置缺少 ws_url 或 rtsp_url");
    }
    await stopCurrentPlayer();
    const hikContainer = document.getElementById("hikPlayerContainer");
    if (hikContainer) {
        hikContainer.style.display = "block";
    }
    hikPlayerController = window.HikCommonPlayer.create({
        containerId: "hikPlayerContainer",
        demoBasePath: window.CAMERA_PAGE_CONFIG.hikDemoBasePath,
        soundVolume: 100,
        autoEnableSound: false,
        onLog(level, message, extra) {
            if (level === "error") {
                setPlayerOverlayText(`播放器错误：${message}`, false);
            }
            console.log("[INDEX_HIK_BRIDGE]", message, extra || {});
        },
        onPluginError(iWndIndex, iErrorCode) {
            setPlayerOverlayText(`播放器内部错误：${iErrorCode}`, false);
            console.error("[INDEX_HIK_BRIDGE] plugin error", { iWndIndex, iErrorCode });
        },
    });
    await hikPlayerController.init();
    syncMainVideoStageSize();
    await hikPlayerController.play({
        accessUrl: config.ws_url,
        wsURL: config.ws_url,
        playURL: config.rtsp_url,
        username: config.username || "",
        password: config.password || "",
        cameraId: config.camera_id || selectedCameraId || "",
    });
    activePlayerType = "hik_sdk";
    setPlayerOverlayText("", true);
}

async function legacyInitMJPEGPlayer_DoNotUse(config) {
    if (!config?.mjpeg_url) {
        throw new Error("MJPEG播放配置缺少 mjpeg_url");
    }
    await stopCurrentPlayer();
    if (!mjpegPlayerElement) {
        mjpegPlayerElement = document.getElementById("video-player");
    }
    if (!mjpegPlayerElement) {
        throw new Error("MJPEG播放器容器不存在");
    }
    mjpegPlayerElement.style.display = "block";
    mjpegPlayerElement.src = `${config.mjpeg_url}${config.mjpeg_url.includes("?") ? "&" : "?"}_=${Date.now()}`;
    activePlayerType = "mjpeg";
    setPlayerOverlayText("", true);
}

function legacyEnsureMainPlaybackPlayer_DoNotUse(cameraId, reason = "manual") {
    if (!cameraId) {
        return;
    }
    if (reason === "initial") {
        if (hasScheduledInitialPlayback) {
            return;
        }
        hasScheduledInitialPlayback = true;
    }
    if (cameraId === currentPlayingCameraId && activePlayerType && reason !== "switch") {
        console.log("[INDEX_PLAYER] skip duplicate play", { cameraId, reason, activePlayerType });
        return;
    }
    legacyStartCameraPlaybackPlayer_DoNotUse(cameraId, reason);
}

async function legacyStartCameraPlaybackPlayer_DoNotUse(cameraId, reason = "manual") {
    if (!cameraId) {
        return;
    }

    clearOverlayCanvas();
    const requestId = ++playbackRequestId;

    try {
        currentPlaybackConfig = await fetchPlaybackConfigNormalized(cameraId);
        if (requestId !== playbackRequestId) {
            console.log("[INDEX_PLAYER] skip stale play request", { cameraId, reason });
            return;
        }
        validatePlaybackConfig(currentPlaybackConfig);
        if (currentPlaybackConfig.play_type === "hik_sdk") {
            await initHikPlayer(currentPlaybackConfig);
        } else {
            await legacyInitMJPEGPlayer_DoNotUse(currentPlaybackConfig);
        }

        if (requestId !== playbackRequestId) {
            return;
        }

        setPlayerOverlayText("", true);
        console.log("[INDEX_PLAYER] play success", {
            cameraId,
            reason,
            playType: currentPlaybackConfig.play_type,
            wsUrl: currentPlaybackConfig.ws_url,
            rtspUrl: currentPlaybackConfig.rtsp_url,
            mjpegUrl: currentPlaybackConfig.mjpeg_url,
        });
        currentPlayingCameraId = cameraId;
        syncMainVideoStageAfterPlayback();
        startOverlayPolling();
    } catch (error) {
        const readableError = formatPlayError(error);
        console.error("[INDEX_PLAYER] start play failed", {
            error: readableError,
            reason,
            playType: currentPlaybackConfig?.play_type || "",
            wsUrl: currentPlaybackConfig?.ws_url || "",
            rtspUrl: currentPlaybackConfig?.rtsp_url || "",
            mjpegUrl: currentPlaybackConfig?.mjpeg_url || "",
        });
        currentPlayingCameraId = "";
        setPlayerOverlayText(`播放失败：${readableError}`, false);
    }
}

function validatePlaybackConfig(config) {
    const missingKeys = ["camera_id", "play_type", "rtsp_url", "mjpeg_url"]
        .filter((key) => !config?.[key]);
    if (missingKeys.length) {
        throw new Error(`播放配置缺失：${missingKeys.join(", ")}`);
    }
    if (config.play_type === "hik_sdk" && !config.ws_url) {
        throw new Error("海康播放配置缺失：ws_url");
    }
}

function getPlayerBridgeOptions() {
    // 主界面 NVR 默认静音，必须由用户点击按钮后再开启声音。
    return {
        containerId: "hikPlayerContainer",
        demoBasePath: window.CAMERA_PAGE_CONFIG.hikDemoBasePath,
        soundVolume: 100,
        autoEnableSound: false,
        onLog(level, message, extra) {
            if (level === "error") {
                setPlayerOverlayText(`播放器错误：${message}`, false);
            }
            console.log("[INDEX_HIK_BRIDGE]", message, extra || {});
        },
        onPluginError(iWndIndex, iErrorCode) {
            const readable = window.HikCommonPlayer.describeLastErrorCode(iErrorCode);
            setPlayerOverlayText(`播放器内部错误：${iErrorCode} (${readable})`, false);
            console.error("[INDEX_HIK_BRIDGE] plugin error", { iWndIndex, iErrorCode, readable });
        },
    };
}

function getPlaybackMode(config) {
    const mode = String(config?.playback_mode || config?.play_type || "").trim().toLowerCase();
    if (mode === "hik" || mode === "hik_sdk") {
        return "hik";
    }
    return "mjpeg";
}

function buildHikPlayRequest(config) {
    // 主界面与 hik_test / hik_fusion_test 共用同一套请求拼装逻辑。
    const request = window.HikCommonPlayer.buildPlayRequest({
        accessUrl: config.access_url || config.ws_url || "",
        wsURL: config.ws_url || config.access_url || "",
        playURL: config.play_url || config.rtsp_url || "",
        username: config.username || "",
        password: config.password || "",
        streamMode: config.stream_mode ?? null,
        transMode: config.trans_mode ?? null,
        gpuMode: config.gpu_mode ?? null,
        cameraIndexCode: config.camera_index_code || "",
        cameraId: config.camera_id || selectedCameraId || "",
    });

    window.HikCommonPlayer.logPlayRequestComparison("INDEX_MAIN", request);
    console.log("[INDEX_MAIN] playback config", {
        accessUrl: config.access_url || "",
        wsURL: config.ws_url || "",
        playURL: config.play_url || "",
        rawPlayURL: config.raw_play_url || "",
        streamMode: config.stream_mode ?? null,
        transMode: config.trans_mode ?? null,
        gpuMode: config.gpu_mode ?? null,
        cameraIndexCode: config.camera_index_code || "",
        authInUrl: Boolean(config.auth_in_url),
        sourceType: config.source_type || "",
    });
    return request;
}

function syncMainVideoStageSize() {
    const stage = document.getElementById("mainVideoStage");
    const playerLayer = document.getElementById("hikPlayerContainer");
    if (!stage || !playerLayer) {
        return { width: 0, height: 0 };
    }

    const width = Math.max(1, Math.round(stage.clientWidth));
    const height = Math.max(1, Math.round(stage.clientHeight));
    playerLayer.style.width = `${width}px`;
    playerLayer.style.height = `${height}px`;

    if (overlayCanvas) {
        overlayCanvas.width = width;
        overlayCanvas.height = height;
        overlayCanvas.style.width = `${width}px`;
        overlayCanvas.style.height = `${height}px`;
    }

    if (hikPlayerController) {
        hikPlayerController.resize();
    }

    return { width, height };
}

function syncMainVideoStageAfterPlayback() {
    syncMainVideoStageSize();
    if (hikPlayerController && typeof hikPlayerController.scheduleResizeSync === "function") {
        hikPlayerController.scheduleResizeSync([100, 300, 800]);
    } else {
        [100, 300, 800].forEach((delay) => {
            window.setTimeout(() => {
                syncMainVideoStageSize();
            }, delay);
        });
    }
    [100, 300, 800].forEach((delay) => {
        window.setTimeout(() => {
            syncOverlayCanvasSize();
            refreshOverlayDetections();
        }, delay);
    });
}

async function createHikPlayerController() {
    if (hikPlayerController) {
        return hikPlayerController;
    }
    hikPlayerController = window.HikCommonPlayer.create(getPlayerBridgeOptions());
    await hikPlayerController.init();
    return hikPlayerController;
}

async function stopCurrentPlayer() {
    stopOverlayPolling();
    if (mjpegPlayerElement) {
        mjpegPlayerElement.removeAttribute("src");
        mjpegPlayerElement.style.display = "none";
    }
    const hikContainer = document.getElementById("hikPlayerContainer");
    if (hikContainer) {
        hikContainer.style.display = "none";
    }
    if (hikPlayerController) {
        try {
            await hikPlayerController.stop();
            await hikPlayerController.destroy();
        } catch (error) {
            console.warn("[INDEX_PLAYER] stop previous player failed", error);
        }
        hikPlayerController = null;
    }
    activePlayerType = "";
    currentPlayingCameraId = "";
}

async function initHikPlayer(config) {
    const request = buildHikPlayRequest(config);
    await stopCurrentPlayer();

    const hikContainer = document.getElementById("hikPlayerContainer");
    if (hikContainer) {
        hikContainer.style.display = "block";
    }

    setPlayerOverlayText("正在初始化海康播放器...", false);
    await createHikPlayerController();
    syncMainVideoStageSize();
    await hikPlayerController.play(request);

    activePlayerType = "hik";
    resetNvrSoundState();
    setPlayerOverlayText("", true);
}

async function startRTSPPlayback(camera) {
    // RTSP 摄像头主界面播放继续沿用 MJPEG 路线。
    await stopCurrentPlayer();
    if (!mjpegPlayerElement) {
        mjpegPlayerElement = document.getElementById("video-player");
    }
    if (!mjpegPlayerElement) {
        throw new Error("RTSP player element not found.");
    }
    mjpegPlayerElement.style.display = "block";
    mjpegPlayerElement.src = `/video_feed/${camera.camera_id}`;
    currentPlaybackConfig = {
        camera_id: camera.camera_id,
        type: camera.type,
        mjpeg_url: mjpegPlayerElement.src,
    };
    activePlayerType = "rtsp";
    resetNvrSoundState();
    setPlayerOverlayText("", true);
}

function ensureMainPlayback(cameraId, reason = "manual") {
    // 这里只负责按摄像头类型分流，不在这里掺入检测逻辑。
    const camera = getCameraMeta(cameraId);
    if (!camera) {
        return;
    }
    if (reason === "initial") {
        if (hasScheduledInitialPlayback) {
            return;
        }
        hasScheduledInitialPlayback = true;
    }
    if (camera.camera_id === currentPlayingCameraId && activePlayerType && reason !== "switch") {
        console.log("[INDEX_PLAYER] skip duplicate play", {
            cameraId: camera.camera_id,
            cameraType: camera.type,
            reason,
            activePlayerType,
        });
        return;
    }
    if (camera.type === "nvr") {
        startNVRPlayback(camera.camera_id, reason);
        return;
    }
    startRTSPPlayback(camera).then(() => {
        console.log("[INDEX_PLAYER] RTSP play success", {
            cameraId: camera.camera_id,
            cameraType: camera.type,
            reason,
            imgSrc: mjpegPlayerElement?.src || "",
        });
        currentPlayingCameraId = camera.camera_id;
        syncMainVideoStageAfterPlayback();
        startOverlayPolling();
    }).catch((error) => {
        const readableError = formatPlayError(error);
        console.error("[INDEX_PLAYER] RTSP play failed", {
            error: readableError,
            cameraId: camera.camera_id,
            cameraType: camera.type,
            reason,
        });
        currentPlayingCameraId = "";
        setPlayerOverlayText(`播放失败：${readableError}`, false);
    });
}

async function startNVRPlayback(cameraId, reason = "manual") {
    // NVR 摄像头主界面播放统一走海康 Web SDK 公共播放器。
    if (!cameraId) {
        return;
    }

    stopOverlayPolling();
    clearOverlayCanvas();
    const requestId = ++playbackRequestId;

    try {
        currentPlaybackConfig = await fetchPlaybackConfigNormalized(cameraId);
        if (requestId !== playbackRequestId) {
            console.log("[INDEX_PLAYER] skip stale play request", { cameraId, reason });
            return;
        }

        validatePlaybackConfig(currentPlaybackConfig);
        await initHikPlayer(currentPlaybackConfig);

        if (requestId !== playbackRequestId) {
            return;
        }

        setPlayerOverlayText("", true);
        console.log("[INDEX_PLAYER] NVR play success", {
            cameraId,
            reason,
            playbackMode: getPlaybackMode(currentPlaybackConfig),
            accessUrl: currentPlaybackConfig.access_url || "",
            wsURL: currentPlaybackConfig.ws_url || "",
            playURL: currentPlaybackConfig.play_url || "",
            mjpegUrl: currentPlaybackConfig.mjpeg_url || "",
        });
        currentPlayingCameraId = cameraId;
        syncMainVideoStageAfterPlayback();
        startOverlayPolling();
    } catch (error) {
        const readableError = formatPlayError(error);
        console.error("[INDEX_PLAYER] NVR play failed", {
            error: readableError,
            reason,
            playbackMode: getPlaybackMode(currentPlaybackConfig),
            accessUrl: currentPlaybackConfig?.access_url || "",
            wsURL: currentPlaybackConfig?.ws_url || "",
            playURL: currentPlaybackConfig?.play_url || "",
            rawPlayURL: currentPlaybackConfig?.raw_play_url || "",
            authInUrl: Boolean(currentPlaybackConfig?.auth_in_url),
            lastErrorCode: error?.lastErrorCode,
            lastErrorDescription: error?.lastErrorDescription,
            mjpegUrl: currentPlaybackConfig?.mjpeg_url || "",
        });
        currentPlayingCameraId = "";
        setPlayerOverlayText(`播放失败：${readableError}`, false);
    }
}

function validatePlaybackConfig(config) {
    const missingKeys = ["camera_id", "mjpeg_url"]
        .filter((key) => !config?.[key]);
    if (missingKeys.length) {
        throw new Error(`Playback config missing: ${missingKeys.join(", ")}`);
    }

    if (getPlaybackMode(config) === "hik") {
        const hikMissingKeys = ["access_url", "play_url"]
            .filter((key) => !config?.[key]);
        if (hikMissingKeys.length) {
            throw new Error(`Hik playback config missing: ${hikMissingKeys.join(", ")}`);
        }
        buildHikPlayRequest(config);
    }
}

function validatePlaybackConfig(config) {
    const missingKeys = ["camera_id", "access_url", "play_url", "username", "password"]
        .filter((key) => !config?.[key]);
    if (missingKeys.length) {
        throw new Error(`Playback config missing: ${missingKeys.join(", ")}`);
    }
    if (getPlaybackMode(config) !== "hik") {
        throw new Error("NVR playback config is not hik mode.");
    }
    buildHikPlayRequest(config);
}

function syncOverlayCanvasSize() {
    if (!overlayCanvas) {
        return { width: 0, height: 0 };
    }
    const container = document.getElementById("mainVideoStage") || overlayCanvas.parentElement || overlayCanvas;
    const rect = container.getBoundingClientRect();
    const width = Math.max(1, Math.round(rect.width));
    const height = Math.max(1, Math.round(rect.height));
    overlayCanvas.width = width;
    overlayCanvas.height = height;
    overlayCanvas.style.width = `${width}px`;
    overlayCanvas.style.height = `${height}px`;
    return { width, height };
}

function syncOverlayCanvasAfterPlayback() {
    [0, 120, 300, 700].forEach((delay) => {
        window.setTimeout(() => {
            syncMainVideoStageSize();
            refreshOverlayDetections();
        }, delay);
    });
}

function clearOverlayCanvas() {
    if (!overlayContext || !overlayCanvas) {
        return;
    }
    overlayContext.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
}

function startOverlayPolling() {
    // 叠框接口统一读取后端最新检测结果，不区分当前前端播放方式。
    stopOverlayPolling();
    refreshOverlayDetections();
    overlayTimer = window.setInterval(refreshOverlayDetections, 1200);
}

function stopOverlayPolling() {
    if (overlayTimer) {
        window.clearInterval(overlayTimer);
        overlayTimer = null;
    }
}

async function legacyFetchPlaybackConfig_DoNotUse(cameraId) {
    const url = window.CAMERA_PAGE_CONFIG.playbackConfigApiBaseUrl.replace("__camera_id__", cameraId);
    const response = await fetch(url, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) {
        throw new Error(payload.message || "获取海康播放配置失败。");
    }
    return payload;
}

async function fetchPlaybackConfigNormalized(cameraId) {
    const url = window.CAMERA_PAGE_CONFIG.playbackConfigApiBaseUrl.replace("__camera_id__", cameraId);
    const response = await fetch(url, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok || !payload.success) {
        throw new Error(payload.message || "获取海康播放配置失败。");
    }
    return payload.data || {};
}

async function refreshOverlayDetections() {
    // 播放失败不应带崩检测展示；接口异常时仅清空叠框并保留后续重试。
    if (!selectedCameraId || !overlayCanvas || !overlayContext) {
        return;
    }

    const url = window.CAMERA_PAGE_CONFIG.overlayDetectionApiBaseUrl.replace("__camera_id__", selectedCameraId);
    try {
        const response = await fetch(url, { cache: "no-store" });
        const payload = await response.json();
        if (!response.ok || !payload.success) {
            throw new Error(payload.message || "获取叠框检测结果失败。");
        }
        const data = payload.data || {};
        const cameraStatus = data.camera_status || latestStatusMap[selectedCameraId] || {};
        updateLiveViolationStats(data.stats || {});
        if (cameraStatus.status && cameraStatus.status !== "running") {
            clearOverlayCanvas();
            return;
        }
        drawViolationOverlay(data);
    } catch (error) {
        console.error("[INDEX_HIK] refreshOverlayDetections failed", error);
        resetLiveViolationStats();
        clearOverlayCanvas();
    }
}

function drawViolationOverlay(data) {
    const canvasRect = syncOverlayCanvasSize();
    clearOverlayCanvas();

    const sourceWidth = Number(data.frame_width || 0);
    const sourceHeight = Number(data.frame_height || 0);
    const violations = Array.isArray(data.violations) ? data.violations : [];
    if (!sourceWidth || !sourceHeight || !violations.length) {
        return;
    }

    const scale = Math.min(canvasRect.width / sourceWidth, canvasRect.height / sourceHeight);
    const displayWidth = sourceWidth * scale;
    const displayHeight = sourceHeight * scale;
    const offsetX = (canvasRect.width - displayWidth) / 2;
    const offsetY = (canvasRect.height - displayHeight) / 2;

    overlayContext.save();
    overlayContext.beginPath();
    overlayContext.rect(offsetX, offsetY, displayWidth, displayHeight);
    overlayContext.clip();

    violations.forEach((item) => {
        const type = normalizeViolationType(item.type);
        const bbox = item.bbox || {};
        const x1 = Number(bbox.x1 || 0);
        const y1 = Number(bbox.y1 || 0);
        const x2 = Number(bbox.x2 || 0);
        const y2 = Number(bbox.y2 || 0);

        const drawX = offsetX + x1 * scale;
        const drawY = offsetY + y1 * scale;
        const drawW = (x2 - x1) * scale;
        const drawH = (y2 - y1) * scale;
        const style = getViolationStyle(type);
        const color = style.color || "#38bdf8";
        const labelText = `${item.type_label || VIOLATION_LABEL_MAP[type] || type} ${Number(item.confidence || 0).toFixed(2)}`;

        overlayContext.lineWidth = Number(style.lineWidth || 2);
        overlayContext.strokeStyle = color;
        overlayContext.strokeRect(drawX, drawY, drawW, drawH);

        overlayContext.font = `${Number(style.fontSize || 14)}px Microsoft YaHei, sans-serif`;
        const textWidth = overlayContext.measureText(labelText).width;
        const textHeight = Number(style.textBoxHeight || 22);
        const textPaddingX = Number(style.textPaddingX || 7);
        const textX = drawX;
        const textY = Math.max(offsetY, drawY - textHeight);
        overlayContext.fillStyle = color;
        overlayContext.fillRect(textX, textY, textWidth + textPaddingX * 2, textHeight);
        overlayContext.fillStyle = style.textColor || "#ffffff";
        overlayContext.fillText(labelText, textX + textPaddingX, textY + 15);
    });

    overlayContext.restore();
}

function normalizeViolationType(value) {
    return String(value || "")
        .trim()
        .toLowerCase()
        .replace(/-/g, "_")
        .replace(/\s+/g, "_");
}

function getViolationStyle(type) {
    const normalizedType = normalizeViolationType(type);
    return VIOLATION_STYLE_MAP[normalizedType]
        || VIOLATION_STYLE_MAP.default
        || {
            color: "#38bdf8",
            textColor: "#ffffff",
            lineWidth: 2,
            fontSize: 14,
            textBoxHeight: 22,
            textPaddingX: 7
        };
}

async function fetchCameraStatus() {
    try {
        const response = await fetch(window.CAMERA_PAGE_CONFIG.statusApiUrl, { cache: "no-store" });
        const payload = await response.json();
        if (!response.ok || !payload.success) {
            throw new Error(payload.message || "摄像头状态获取失败。");
        }
        latestStatusMap = payload.data || {};
        updateCameraSidebar(latestStatusMap);
        updateSelectedCameraPanel();
    } catch (error) {
        console.error("获取摄像头状态失败:", error);
        latestStatusMap = {};
        updateCameraSidebar({});
        updateSelectedCameraPanel();
    }
}

async function fetchLatestAlarms() {
    try {
        const response = await fetch(`${window.CAMERA_PAGE_CONFIG.latestAlarmsApiUrl}?limit=10`, { cache: "no-store" });
        const payload = await response.json();
        if (!response.ok || !payload.success) {
            throw new Error(payload.message || "最近报警获取失败。");
        }
        renderAlarmList(payload.data.items || []);
    } catch (error) {
        console.error("获取最近报警失败:", error);
    }
}

function renderAlarmList(items) {
    const nextSignature = buildAlarmSignature(items);
    if (nextSignature === latestAlarmSignature) {
        return;
    }

    latestAlarmSignature = nextSignature;
    latestAlarmMap = new Map();

    items.forEach((item) => {
        const normalized = normalizeAlarmItem(item);
        const existing = latestAlarmMap.get(normalized.aggregate_key);
        latestAlarmMap.set(
            normalized.aggregate_key,
            existing ? mergeAlarmItems(existing, normalized) : normalized
        );
    });

    renderAlarmNodes();
}

function appendAlarmEvent(event) {
    const normalized = normalizeAlarmItem(event);
    const existing = latestAlarmMap.get(normalized.aggregate_key);
    latestAlarmMap.set(
        normalized.aggregate_key,
        existing ? mergeAlarmItems(existing, normalized) : normalized
    );

    trimAlarmMap(10);
    latestAlarmSignature = "";
    renderAlarmNodes();
}

function renderAlarmNodes() {
    const list = document.getElementById("alarm-live-list");
    if (!list) {
        return;
    }

    list.innerHTML = "";
    const items = Array.from(latestAlarmMap.values())
        .sort((left, right) => String(right.timestamp || "").localeCompare(String(left.timestamp || "")))
        .slice(0, 10);

    if (!items.length) {
        const empty = document.createElement("div");
        empty.className = "alarm-empty-item";
        empty.textContent = "暂无报警信息";
        list.appendChild(empty);
        return;
    }

    items.forEach((event) => {
        list.appendChild(buildAlarmNode(event));
    });
}

function buildAlarmNode(event) {
    const cameraName = event.camera_name || lookupCameraName(event.camera_id) || event.camera_id || "未知摄像头";
    const snapshotUrl = event.snapshot_url || buildSnapshotUrl(event.snapshot_path);
    const snapshotBlock = snapshotUrl
        ? `
            <a class="alarm-snapshot-link" href="${escapeHtml(snapshotUrl)}" target="_blank" rel="noopener noreferrer">
                <img class="alarm-snapshot-thumb" src="${escapeHtml(snapshotUrl)}" alt="报警快照">
            </a>
          `
        : "";

    const snapshotText = snapshotUrl
        ? `<a class="snapshot-text-link" href="${escapeHtml(snapshotUrl)}" target="_blank" rel="noopener noreferrer">查看图片</a>`
        : "暂无快照";

    const item = document.createElement("article");
    item.className = "alarm-item";
    item.dataset.aggregateKey = event.aggregate_key || "";
    item.innerHTML = `
        <div class="alarm-item-top">
            <span class="alarm-item-type">${escapeHtml(formatViolationType(event))}</span>
            <span class="alarm-item-camera">${escapeHtml(cameraName)}</span>
        </div>
        <div class="alarm-item-meta">
            <span>${escapeHtml(resolveDisplayTime(event))}</span>
            <span>${formatConfidence(event.confidence)}</span>
        </div>
        ${snapshotBlock}
        <div class="alarm-item-id">事件 ID：${escapeHtml(event.event_id || "")}</div>
        <div class="alarm-item-snapshot">快照：${snapshotText}</div>
    `;
    return item;
}

function normalizeAlarmItem(event) {
    const aggregateKey = String(event.aggregate_key || event.event_id || `${event.camera_id || "camera"}:${event.timestamp || ""}`);
    const violationTypes = Array.isArray(event.violation_types)
        ? event.violation_types.filter(Boolean)
        : (event.violation_type ? [event.violation_type] : []);
    const violationTypeText = event.violation_type_text || violationTypes.join(" / ") || event.violation_type || "未知类型";
    const rawEventIds = Array.isArray(event.raw_event_ids)
        ? event.raw_event_ids.filter(Boolean)
        : (event.event_id ? [event.event_id] : []);

    return {
        aggregate_key: aggregateKey,
        event_id: String(event.event_id || aggregateKey),
        camera_id: event.camera_id || "",
        camera_name: event.camera_name || lookupCameraName(event.camera_id) || event.camera_id || "",
        violation_type: event.violation_type || violationTypes[0] || "",
        violation_types: violationTypes,
        violation_type_text: violationTypeText,
        timestamp: event.timestamp || "",
        display_time: event.display_time || "",
        confidence: typeof event.confidence === "number" ? event.confidence : Number(event.confidence || 0),
        snapshot_path: event.snapshot_path || "",
        snapshot_url: event.snapshot_url || buildSnapshotUrl(event.snapshot_path),
        raw_event_ids: rawEventIds,
        violation_counts: { ...(event.violation_counts || {}) }
    };
}

function mergeAlarmItems(existing, incoming) {
    const violationTypes = Array.from(new Set([...(existing.violation_types || []), ...(incoming.violation_types || [])]));
    const violationTypeText = formatViolationTypeList(violationTypes, existing.violation_type_text, incoming.violation_type_text);
    const rawEventIds = Array.from(new Set([...(existing.raw_event_ids || []), ...(incoming.raw_event_ids || [])]));
    const violationCounts = { ...(existing.violation_counts || {}) };
    Object.entries(incoming.violation_counts || {}).forEach(([key, value]) => {
        violationCounts[key] = Number(value || 0);
    });

    return {
        ...existing,
        event_id: existing.event_id || incoming.event_id,
        camera_name: existing.camera_name || incoming.camera_name,
        confidence: Math.max(Number(existing.confidence || 0), Number(incoming.confidence || 0)),
        snapshot_path: existing.snapshot_path || incoming.snapshot_path,
        snapshot_url: existing.snapshot_url || incoming.snapshot_url,
        violation_type: violationTypes[0] || existing.violation_type || incoming.violation_type,
        violation_types: violationTypes,
        violation_type_text: violationTypeText,
        raw_event_ids: rawEventIds,
        violation_counts: violationCounts
    };
}

function formatViolationTypeList(violationTypes, fallbackLeft, fallbackRight) {
    if (violationTypes.length <= 1) {
        return fallbackRight || fallbackLeft || violationTypes[0] || "未知类型";
    }

    const textByType = new Map();
    [fallbackLeft, fallbackRight].filter(Boolean).forEach((text) => {
        const parts = String(text).split(" / ").map((item) => item.trim()).filter(Boolean);
        parts.forEach((part, index) => {
            const violationType = violationTypes[index];
            if (violationType && !textByType.has(violationType)) {
                textByType.set(violationType, part);
            }
        });
    });

    const displayTexts = violationTypes.map((type) => textByType.get(type) || VIOLATION_LABEL_MAP[type] || type);
    return displayTexts.join(" / ");
}

function trimAlarmMap(limit) {
    const sortedKeys = Array.from(latestAlarmMap.values())
        .sort((left, right) => String(right.timestamp || "").localeCompare(String(left.timestamp || "")))
        .slice(0, limit)
        .map((item) => item.aggregate_key);

    const nextMap = new Map();
    sortedKeys.forEach((key) => {
        const value = latestAlarmMap.get(key);
        if (value) {
            nextMap.set(key, value);
        }
    });
    latestAlarmMap = nextMap;
}

function lookupCameraName(cameraId) {
    const button = document.querySelector(`[data-camera-select='${cameraId}']`);
    return button?.querySelector(".camera-list-name")?.textContent || "";
}

function connectAlarmSocket() {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const socketUrl = `${protocol}://${window.location.host}${window.CAMERA_PAGE_CONFIG.alarmWsPath}`;

    setAlarmSocketStatus("连接中", "status-connecting");

    try {
        alarmSocket = new WebSocket(socketUrl);
    } catch (error) {
        console.error("创建报警 WebSocket 失败:", error);
        scheduleAlarmReconnect();
        return;
    }

    alarmSocket.onopen = () => {
        alarmReconnectDelay = 1000;
        setAlarmSocketStatus("已连接", "status-running");
        startSocketHeartbeat(alarmSocket);
    };

    alarmSocket.onmessage = (event) => {
        try {
            const payload = JSON.parse(event.data);
            if (payload.type === "alarm_event" && payload.data) {
                appendAlarmEvent(payload.data);
            }
        } catch (error) {
            console.error("解析报警消息失败:", error);
        }
    };

    alarmSocket.onerror = (error) => {
        console.error("报警 WebSocket 异常:", error);
    };

    alarmSocket.onclose = () => {
        stopSocketHeartbeat(alarmSocket);
        setAlarmSocketStatus("重连中", "status-reconnecting");
        scheduleAlarmReconnect();
    };
}

function startSocketHeartbeat(socket) {
    if (!socket) {
        return;
    }

    stopSocketHeartbeat(socket);
    socket._heartbeatTimer = window.setInterval(() => {
        if (socket.readyState === WebSocket.OPEN) {
            socket.send("ping");
        }
    }, 20000);
}

function stopSocketHeartbeat(socket) {
    if (!socket || !socket._heartbeatTimer) {
        return;
    }
    window.clearInterval(socket._heartbeatTimer);
    socket._heartbeatTimer = null;
}

function scheduleAlarmReconnect() {
    if (alarmReconnectTimer) {
        window.clearTimeout(alarmReconnectTimer);
    }

    alarmReconnectTimer = window.setTimeout(() => {
        alarmReconnectTimer = null;
        connectAlarmSocket();
    }, alarmReconnectDelay);

    alarmReconnectDelay = Math.min(alarmReconnectDelay * 2, 10000);
}

function setAlarmSocketStatus(text, className) {
    const statusNode = document.getElementById("alarm-ws-status");
    if (!statusNode) {
        return;
    }

    statusNode.textContent = text;
    statusNode.className = `status-badge ${className}`;
}

function formatConfidence(confidence) {
    if (typeof confidence !== "number" || Number.isNaN(confidence)) {
        return "置信度 --";
    }
    return `置信度 ${confidence.toFixed(2)}`;
}

function formatViolationType(event) {
    if (typeof event === "object" && event !== null) {
        return event.violation_type_text || event.violation_type || "未知类型";
    }
    return event || "未知类型";
}

function buildSnapshotUrl(snapshotPath) {
    if (!snapshotPath) {
        return "";
    }

    if (snapshotPath.startsWith("/snapshots/")) {
        return snapshotPath;
    }

    let normalized = snapshotPath.replaceAll("\\", "/").replace(/^\/+/, "");
    if (normalized.startsWith("snapshots/")) {
        normalized = normalized.slice("snapshots/".length);
    }

    const encodedPath = normalized
        .split("/")
        .filter(Boolean)
        .map((segment) => encodeURIComponent(segment))
        .join("/");

    return encodedPath ? `/snapshots/${encodedPath}` : "";
}

function resolveDisplayTime(event) {
    if (event.display_time) {
        return event.display_time;
    }
    return formatDisplayTime(event.timestamp);
}

function formatDisplayTime(value) {
    if (!value) {
        return "--";
    }

    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return "--";
    }

    const formatter = new Intl.DateTimeFormat("zh-CN", {
        timeZone: "Asia/Shanghai",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false
    });

    const parts = formatter.formatToParts(parsed);
    const valueMap = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return `${valueMap.year}-${valueMap.month}-${valueMap.day} ${valueMap.hour}:${valueMap.minute}:${valueMap.second}`;
}

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function buildAlarmSignature(items) {
    return items
        .map((item) => `${item.aggregate_key || item.event_id || ""}:${item.snapshot_path || ""}:${(item.violation_types || []).join(",")}:${JSON.stringify(item.violation_counts || {})}`)
        .join("|");
}

function updateLiveViolationStats(stats) {
    setCountText("no-helmet-count", stats.no_helmet);
    setCountText("no-vest-count", stats.no_vest);
    setCountText("smoking-count", stats.smoking);
}

function resetLiveViolationStats() {
    updateLiveViolationStats({
        no_helmet: 0,
        no_vest: 0,
        smoking: 0
    });
}

function setCountText(elementId, value) {
    const node = document.getElementById(elementId);
    if (!node) {
        return;
    }
    node.textContent = String(Number(value || 0));
}
