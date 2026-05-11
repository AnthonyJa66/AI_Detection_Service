(function () {
    const config = window.HIK_FUSION_CONFIG || {};
    const playWindowId = "hik-fusion-play-window";
    const overlayCanvas = document.getElementById("hik-overlay-canvas");
    const statusNode = document.getElementById("fusion-status");
    const startButton = document.getElementById("fusion-start-btn");
    const stopButton = document.getElementById("fusion-stop-btn");
    const cameraSelect = document.getElementById("fusion-camera-select");

    let playerController = null;
    let detectionTimer = null;
    let performanceTimer = null;

    const VIOLATION_LABEL_MAP = {
        smoking: "\u62bd\u70df\u884c\u4e3a",
        smoke: "\u62bd\u70df\u884c\u4e3a",
        no_vest: "\u65e0\u53cd\u5149\u80cc\u5fc3",
        novest: "\u65e0\u53cd\u5149\u80cc\u5fc3",
        no_helmet: "\u65e0\u5b89\u5168\u5e3d",
        nohelmet: "\u65e0\u5b89\u5168\u5e3d",
    };

    const VIOLATION_COLOR_MAP = {
        smoking: "#ef4444",
        smoke: "#ef4444",
        no_vest: "#f59e0b",
        novest: "#f59e0b",
        no_helmet: "#22c55e",
        nohelmet: "#22c55e",
    };

    function setStatus(message, type = "info") {
        if (!statusNode) {
            return;
        }
        statusNode.textContent = message;
        statusNode.dataset.type = type;
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

    function normalizeClassName(value) {
        return String(value || "")
            .trim()
            .toLowerCase()
            .replace(/-/g, "_")
            .replace(/\s+/g, "_");
    }

    function isViolationClass(value) {
        const normalized = normalizeClassName(value);
        return [
            "smoking",
            "smoke",
            "no_vest",
            "novest",
            "no_helmet",
            "nohelmet",
        ].includes(normalized);
    }

    function getLabel(value) {
        const normalized = normalizeClassName(value);
        return VIOLATION_LABEL_MAP[normalized] || normalized;
    }

    function getColor(value) {
        const normalized = normalizeClassName(value);
        return VIOLATION_COLOR_MAP[normalized] || "#38bdf8";
    }

    function getSelectedCameraId() {
        return cameraSelect ? cameraSelect.value : (config.cameraId || "");
    }

    function updateSelectedCameraText() {
        const node = document.getElementById("fusion-camera-id");
        if (node) {
            node.textContent = getSelectedCameraId() || "--";
        }
    }

    function getOverlayContainerRect() {
        if (!overlayCanvas) {
            return { width: 0, height: 0 };
        }
        const container = overlayCanvas.parentElement || overlayCanvas;
        const rect = container.getBoundingClientRect();
        return {
            width: Math.max(1, Math.round(rect.width)),
            height: Math.max(1, Math.round(rect.height)),
        };
    }

    function resizeOverlayCanvas() {
        if (!overlayCanvas) {
            return { width: 0, height: 0 };
        }

        const rect = getOverlayContainerRect();
        overlayCanvas.width = rect.width;
        overlayCanvas.height = rect.height;
        overlayCanvas.style.width = `${rect.width}px`;
        overlayCanvas.style.height = `${rect.height}px`;
        return rect;
    }

    function clearOverlay() {
        if (!overlayCanvas) {
            return;
        }
        const context = overlayCanvas.getContext("2d");
        context.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
    }

    function getSourceSize(data) {
        return {
            width: Number(data.frame_width || data.source_width || 0),
            height: Number(data.frame_height || data.source_height || 0),
        };
    }

    function calculateVideoMapping(data) {
        const container = resizeOverlayCanvas();
        const source = getSourceSize(data);

        if (!container.width || !container.height || !source.width || !source.height) {
            return null;
        }

        const scale = Math.min(
            container.width / source.width,
            container.height / source.height,
        );
        const displayWidth = source.width * scale;
        const displayHeight = source.height * scale;
        const offsetX = (container.width - displayWidth) / 2;
        const offsetY = (container.height - displayHeight) / 2;

        return {
            containerWidth: container.width,
            containerHeight: container.height,
            sourceWidth: source.width,
            sourceHeight: source.height,
            scale,
            displayWidth,
            displayHeight,
            offsetX,
            offsetY,
        };
    }

    function mapBoxToDisplay(bbox, mapping) {
        const x1 = Number(bbox[0]);
        const y1 = Number(bbox[1]);
        const x2 = Number(bbox[2]);
        const y2 = Number(bbox[3]);

        return {
            x: mapping.offsetX + x1 * mapping.scale,
            y: mapping.offsetY + y1 * mapping.scale,
            width: (x2 - x1) * mapping.scale,
            height: (y2 - y1) * mapping.scale,
        };
    }

    function logOverlayDebug(mapping, firstRawBox, firstDrawBox) {
        console.log("[HIK_FUSION_OVERLAY]", {
            containerWidth: mapping.containerWidth,
            containerHeight: mapping.containerHeight,
            sourceWidth: mapping.sourceWidth,
            sourceHeight: mapping.sourceHeight,
            displayWidth: mapping.displayWidth,
            displayHeight: mapping.displayHeight,
            offsetX: mapping.offsetX,
            offsetY: mapping.offsetY,
            firstRawBox,
            firstDrawBox,
        });
    }

    function drawOverlay(data) {
        if (!overlayCanvas) {
            return;
        }

        const context = overlayCanvas.getContext("2d");
        const mapping = calculateVideoMapping(data);
        context.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);

        if (!mapping) {
            return;
        }

        const detections = Array.isArray(data.detections) ? data.detections : [];
        const violationDetections = detections.filter((detection) => (
            isViolationClass(detection.class_name) &&
            Array.isArray(detection.bbox) &&
            detection.bbox.length === 4
        ));

        let firstRawBox = null;
        let firstDrawBox = null;

        context.save();
        // Do not draw boxes in letterbox/pillarbox areas.
        context.beginPath();
        context.rect(
            mapping.offsetX,
            mapping.offsetY,
            mapping.displayWidth,
            mapping.displayHeight,
        );
        context.clip();

        violationDetections.forEach((detection, index) => {
            const className = normalizeClassName(detection.class_name);
            const drawBox = mapBoxToDisplay(detection.bbox, mapping);
            const color = getColor(className);
            const label = `${getLabel(className)} ${Number(detection.confidence || 0).toFixed(2)}`;

            if (index === 0) {
                firstRawBox = detection.bbox.slice();
                firstDrawBox = { ...drawBox };
            }

            context.lineWidth = 2;
            context.strokeStyle = color;
            context.strokeRect(drawBox.x, drawBox.y, drawBox.width, drawBox.height);

            context.font = "14px Microsoft YaHei, sans-serif";
            const textWidth = context.measureText(label).width;
            const textHeight = 22;
            const textX = drawBox.x;
            const textY = Math.max(mapping.offsetY, drawBox.y - textHeight);

            context.fillStyle = color;
            context.fillRect(textX, textY, textWidth + 14, textHeight);
            context.fillStyle = "#ffffff";
            context.fillText(label, textX + 7, textY + 15);
        });

        context.restore();

        if (firstRawBox && firstDrawBox) {
            logOverlayDebug(mapping, firstRawBox, firstDrawBox);
        } else {
            logOverlayDebug(mapping, null, null);
        }
    }

    function setMetric(id, value) {
        const node = document.getElementById(id);
        if (node) {
            node.textContent = value;
        }
    }

    function updateDetectionMetrics(data) {
        setMetric("metric-no-helmet", String(data.no_helmet_count ?? 0));
        setMetric("metric-no-vest", String(data.no_vest_count ?? 0));
        setMetric("metric-smoking", String(data.smoking_count ?? 0));
        setMetric("metric-detection-time", data.timestamp || "--");
    }

    async function refreshDetectionOverlay() {
        const cameraId = getSelectedCameraId();
        if (!cameraId || !config.latestDetectionApiBaseUrl) {
            clearOverlay();
            return;
        }

        const url = config.latestDetectionApiBaseUrl.replace("__camera_id__", cameraId);
        try {
            const response = await fetch(url, { cache: "no-store" });
            const payload = await response.json();
            if (!response.ok || !payload.success) {
                throw new Error(payload.message || "Failed to fetch detection result.");
            }

            const data = payload.data || {};
            drawOverlay(data);
            updateDetectionMetrics(data);
        } catch (error) {
            console.error("[HIK_FUSION] Failed to fetch detection result.", error);
            appendStatus(`Detection fetch failed: ${error.message || error}`);
        }
    }

    async function refreshPerformanceStatus() {
        if (!config.performanceApiUrl) {
            return;
        }

        try {
            const response = await fetch(config.performanceApiUrl, { cache: "no-store" });
            const payload = await response.json();
            if (!response.ok || !payload.success) {
                throw new Error(payload.message || "Failed to fetch performance status.");
            }

            const data = payload.data || {};
            const cpu = data.cpu || {};
            const gpu = data.gpu || {};
            setMetric("metric-cpu", cpu.available ? `${cpu.usage_percent}%` : "N/A");
            setMetric("metric-gpu", gpu.available ? `${gpu.gpu_util_percent}%` : "N/A");
            setMetric(
                "metric-gpu-memory",
                gpu.available ? `${gpu.memory_used_mb} / ${gpu.memory_total_mb} MB` : (gpu.message || "N/A"),
            );
            setMetric("metric-performance-time", data.timestamp || "--");
        } catch (error) {
            console.error("[HIK_FUSION] Failed to fetch performance status.", error);
            setMetric("metric-cpu", "Error");
            setMetric("metric-gpu", "Error");
        }
    }

    function syncOverlayAfterPlayback() {
        [0, 120, 300, 800].forEach((delay) => {
            window.setTimeout(() => {
                resizeOverlayCanvas();
                refreshDetectionOverlay();
            }, delay);
        });
    }

    function startPolling() {
        stopPolling();
        refreshDetectionOverlay();
        refreshPerformanceStatus();
        detectionTimer = window.setInterval(refreshDetectionOverlay, 1200);
        performanceTimer = window.setInterval(refreshPerformanceStatus, 2000);
    }

    function stopPolling() {
        if (detectionTimer) {
            window.clearInterval(detectionTimer);
            detectionTimer = null;
        }
        if (performanceTimer) {
            window.clearInterval(performanceTimer);
            performanceTimer = null;
        }
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
            cameraId: getSelectedCameraId() || config.cameraId || "",
        });
        window.HikCommonPlayer.logPlayRequestComparison("HIK_FUSION", request);
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
                    console.error("[HIK_FUSION] Plugin error:", iWndIndex, iErrorCode);
                    setStatus(`Plugin error. window=${iWndIndex}, code=${iErrorCode}`, "error");
                },
            });
            await playerController.init();
            setStatus("Hikvision player initialized. Click Start.");
            console.log("[HIK_FUSION] Player initialized.");
        } catch (error) {
            console.error("[HIK_FUSION] Player init failed.", error);
            setStatus(
                `Player init failed: ${error.message || error}\nTODO: compare with colleague's working init code if needed.`,
                "error",
            );
        }
    }

    function startPlay() {
        if (!playerController) {
            setStatus("Start failed: player is not initialized.", "error");
            return;
        }

        clearOverlay();
        resizeOverlayCanvas();
        setStatus("Starting Hikvision playback and detection overlay polling.");
        console.log("[HIK_FUSION] Start playback.");

        playerController.play(buildPlayRequest()).then(
            function () {
                console.log("[HIK_FUSION] Playback success.");
                setStatus("Playback success. Overlay is syncing after video render.");
                syncOverlayAfterPlayback();
                startPolling();
            },
            function (error) {
                console.error("[HIK_FUSION] Playback failed.", error);
                setStatus(
                    `Playback failed: ${error || "JS_Play Promise rejected"}\nTODO: compare with colleague's working JS_Play parameters if needed.`,
                    "error",
                );
            },
        );
    }

    function stopPlay() {
        if (!playerController) {
            setStatus("Stop failed: player is not initialized.", "error");
            return;
        }

        console.log("[HIK_FUSION] Stop playback.");
        playerController.stop().then(
            function () {
                stopPolling();
                clearOverlay();
                resizeOverlayCanvas();
                setStatus("Playback stopped. Overlay cleared.");
            },
            function (error) {
                console.error("[HIK_FUSION] Stop failed.", error);
                setStatus(`Stop failed: ${error || "JS_Stop Promise rejected"}`, "error");
            },
        );
    }

    function bindEvents() {
        if (startButton) {
            startButton.addEventListener("click", startPlay);
        }
        if (stopButton) {
            stopButton.addEventListener("click", stopPlay);
        }
        if (cameraSelect) {
            cameraSelect.addEventListener("change", function () {
                updateSelectedCameraText();
                clearOverlay();
                resizeOverlayCanvas();
                refreshDetectionOverlay();
            });
        }

        window.addEventListener("resize", function () {
            resizeOverlayCanvas();
            if (playerController) {
                playerController.resize();
            }
            refreshDetectionOverlay();
        });
    }

    document.addEventListener("DOMContentLoaded", function () {
        updateSelectedCameraText();
        resizeOverlayCanvas();
        bindEvents();
        initPlayer();
        refreshPerformanceStatus();
        refreshDetectionOverlay();
    });
})();
