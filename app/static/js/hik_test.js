(function () {
    const config = window.HIK_TEST_CONFIG || {};
    const statusNode = document.getElementById("hik-status");
    const startButton = document.getElementById("hik-start-btn");
    const stopButton = document.getElementById("hik-stop-btn");
    const playWindowId = "hik-play-window";
    let playerController = null;

    function setStatus(message, type = "info") {
        if (!statusNode) {
            return;
        }

        statusNode.textContent = message;
        statusNode.classList.remove("is-error", "is-success");
        if (type === "error") {
            statusNode.classList.add("is-error");
        }
        if (type === "success") {
            statusNode.classList.add("is-success");
        }
    }

    function appendStatus(message) {
        if (!statusNode) {
            return;
        }
        statusNode.textContent = `${statusNode.textContent}\n${message}`;
    }

    function handleCommonLog(level, message) {
        appendStatus(`[${level}] ${message}`);
    }

    function buildPlayRequest() {
        const request = window.HikCommonPlayer.buildPlayRequest({
            accessUrl: config.accessUrl,
            wsURL: config.wsURL || config.accessUrl,
            playURL: config.previewUrl,
            username: config.username,
            password: config.password,
            streamMode: config.streamMode,
            transMode: config.transMode,
            gpuMode: config.gpuMode,
            cameraIndexCode: config.cameraIndexCode || config.cameraId || "",
            cameraId: config.cameraId || "",
        });
        window.HikCommonPlayer.logPlayRequestComparison("HIK_TEST", request);
        return request;
    }

    async function initPlayer() {
        try {
            playerController = window.HikCommonPlayer.create({
                containerId: playWindowId,
                demoBasePath: config.demoBasePath,
                soundVolume: 100,
                onLog: handleCommonLog,
                onPluginError(iWndIndex, iErrorCode) {
                    setStatus(`播放器内部错误。窗口 ${iWndIndex}，错误码 ${iErrorCode}`, "error");
                },
            });
            await playerController.init();
            setStatus("播放器初始化成功，等待点击“开始播放”。", "success");
        } catch (error) {
            console.error("[HIK_TEST] init failed", error);
            setStatus(`播放器初始化失败\n${error.message || error}`, "error");
        }
    }

    function startPlay() {
        if (!playerController) {
            setStatus("开始播放失败：播放器尚未初始化。", "error");
            return;
        }

        setStatus("开始播放，正在连接海康网关。");
        playerController.play(buildPlayRequest()).then(
            function () {
                setStatus("播放成功，页面已开始显示视频。", "success");
            },
            function (error) {
                const readableError = window.HikCommonPlayer.formatError(error || "JS_Play Promise rejected");
                setStatus(`播放失败\n${readableError}`, "error");
            },
        );
    }

    function stopPlay() {
        if (!playerController) {
            setStatus("停止播放失败：播放器尚未初始化。", "error");
            return;
        }

        playerController.stop().then(function () {
            setStatus("停止播放成功。", "success");
        });
    }

    function bindEvents() {
        if (startButton) {
            startButton.addEventListener("click", startPlay);
        }
        if (stopButton) {
            stopButton.addEventListener("click", stopPlay);
        }
        window.addEventListener("resize", function () {
            if (!playerController) {
                return;
            }
            playerController.resize();
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        bindEvents();
        initPlayer();
    });
})();
