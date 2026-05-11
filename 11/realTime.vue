<template>
    <div class="video-monitoring-container">
        <camera-sidebar :searchQuery.sync="searchQuery" :cameraGroups="cameraGroups"
            :selectedCameraId="selectedCameraId" :playingIds="playingCameras.map(c => c && c.id).filter(Boolean)"
            :openGroups.sync="openGroups" @select-camera="selectCamera" />
        <div class="right-content" v-loading="loading" :class="{ 'history-mode': isHistory }" ref="playerContainer">
            <!-- <template v-if="isRealTime"> -->
            <div class="realtime-grid">
                <template v-if="splitCount === 1">
                    <div class="realtime-card" v-for="(camera, index) in displaySlots"
                        :key="camera ? camera.id : `empty_${index}`">
                        <div class="card-header" v-if="camera">
                            <div class="card-meta">
                                <div class="video-title">
                                    <img src="@/assets/img/icon_camera.png" alt="camera icon" />
                                    <span>{{ camera.ip }}</span>
                                </div>

                            </div>
                        </div>
                        <div class="card-header empty" v-else>
                            <div class="card-title">未播放</div>
                        </div>
                        <div class="card-video">
                            <div class="video-player" v-if="camera">
                                <video-player v-if="streamSource === 'direct'"
                                    :videoUrls="[camera.rtspUrl || camera.realPlayPath].filter(Boolean)"
                                    :key="`direct_${camera.id}`" ref="videoPlayers"></video-player>
                                <hikvision-player v-else :accessUrl="hikPlayerConfig.accessUrl"
                                    :rtspUrl="camera.rtspUrl" :username="hikPlayerConfig.username"
                                    :password="hikPlayerConfig.password" :key="`${camera.id}`" ref="hikPlayers"
                                    @performance-lack="handlePerformanceLack"></hikvision-player>
                                <!-- <video class="video-player" :src="ceshisrc" controls muted playsinline></video> -->
                            </div>
                            <div class="empty-state" v-else>
                                <i class="el-icon-video-camera"></i>
                                <span>请选择设备并开始播放</span>
                            </div>
                        </div>
                    </div>
                </template>
                <template v-else>
                    <div class="realtime-card multi-player-card">
                        <div class="card-header">
                            <div class="card-meta">
                                <div class="video-title">
                                    <img src="@/assets/img/icon_camera.png" alt="camera icon" />
                                    <span>多画面</span>
                                </div>
                            </div>
                        </div>
                        <div class="card-video">
                            <div class="video-player" v-if="playingCameras.length">
                                <video-player v-if="streamSource === 'direct'"
                                    :videoUrls="playingCameras.filter(Boolean).map(c => c.rtspUrl || c.realPlayPath).filter(Boolean)"
                                    :key="`direct_multi_player`" ref="videoMultiPlayer"></video-player>
                                <hikvision-player v-else :accessUrl="hikPlayerConfig.accessUrl"
                                    :streams="playingCameras" :splitCount="splitCount"
                                    :username="hikPlayerConfig.username" :password="hikPlayerConfig.password"
                                    :key="`multi_player`" ref="hikMultiPlayer"
                                    @performance-lack="handlePerformanceLack"></hikvision-player>
                            </div>
                            <div class="empty-state" v-else>
                                <i class="el-icon-video-camera"></i>
                                <span>请选择设备并开始播放</span>
                            </div>
                        </div>
                    </div>
                </template>
            </div>
            <div class="realtime-toolbar">
                <div class="toolbar-left">

                </div>
                <div class="toolbar-center">
                    <div class="play-controls">
                        <!-- <i class="el-icon-d-arrow-left control-icon" @click="prevPlay" title="上一个"></i> -->
                        <svg xmlns="http://www.w3.org/2000/svg" @click="prevPlay" width="24" height="24"
                            viewBox="0 0 24 24" fill="none">
                            <path
                                d="M4.5 6C4.91422 6 5.25 6.33579 5.25 6.75V10.9999L12.167 6.38855C12.2286 6.34748 12.301 6.32556 12.375 6.32556C12.5821 6.32556 12.75 6.49346 12.75 6.70056V10.9999L19.667 6.38855C19.7286 6.34748 19.801 6.32556 19.875 6.32556C20.0821 6.32556 20.25 6.49346 20.25 6.70056V17.2992C20.25 17.3732 20.2281 17.4456 20.187 17.5072C20.0721 17.6795 19.8393 17.7261 19.667 17.6112L12.75 12.9999V17.2992C12.75 17.3732 12.7281 17.4456 12.687 17.5072C12.5721 17.6795 12.3393 17.7261 12.167 17.6112L5.25 12.9999V17.25C5.25 17.6642 4.91422 18 4.5 18C4.08578 18 3.75 17.6642 3.75 17.25V6.75C3.75 6.33579 4.08578 6 4.5 6Z"
                                fill="#A4A4A4" />
                            <title>上一个</title>
                        </svg>
                        <template v-if="!isPlaying">
                            <svg class="close-icon" xmlns="http://www.w3.org/2000/svg" @click="playNow" width="24"
                                height="24" viewBox="0 0 18 18" fill="none">
                                <path
                                    d="M9 18C4.0293 18 0 13.9707 0 9C0 4.0293 4.0293 0 9 0C13.9707 0 18 4.0293 18 9C18 13.9707 13.9707 18 9 18ZM7.7598 5.7735C7.70563 5.73736 7.64268 5.71659 7.57765 5.7134C7.51261 5.71021 7.44793 5.72471 7.39048 5.75537C7.33304 5.78604 7.28499 5.8317 7.25144 5.88751C7.2179 5.94332 7.20012 6.00719 7.2 6.0723V11.9277C7.20012 11.9928 7.2179 12.0567 7.25144 12.1125C7.28499 12.1683 7.33304 12.214 7.39048 12.2446C7.44793 12.2753 7.51261 12.2898 7.57765 12.2866C7.64268 12.2834 7.70563 12.2626 7.7598 12.2265L12.1509 9.2997C12.2003 9.26684 12.2408 9.22228 12.2688 9.17C12.2968 9.11771 12.3115 9.05932 12.3115 9C12.3115 8.94068 12.2968 8.88229 12.2688 8.83C12.2408 8.77772 12.2003 8.73316 12.1509 8.7003L7.7589 5.7735H7.7598Z"
                                    fill="#A4A4A4" />
                                <title>播放</title>
                            </svg>
                            <!-- <i class="el-icon-video-play play-icon" @click="playNow" title="播放"></i> -->
                        </template>
                        <template v-else>
                            <svg class="close-icon" t="1769673429486" @click="stopPlay" viewBox="0 0 1024 1024"
                                version="1.1" xmlns="http://www.w3.org/2000/svg" p-id="5834" width="24" height="24">
                                <path
                                    d="M149.961654 149.961654c-199.948872 199.948872-199.948872 524.127821 0 724.076692s524.127821 199.948872 724.076692 0 199.948872-524.127821 0-724.076692-524.127821-199.948872-724.076692 0z m519.791553 204.285139a34.461318 34.461318 0 0 1 0 48.579933l-109.173274 109.173274 109.161832 109.161832a34.351482 34.351482 0 0 1-48.579933 48.579933l-109.161832-109.161832-109.161832 109.161832a34.461318 34.461318 0 0 1-48.579933 0 34.461318 34.461318 0 0 1 0-48.579933l109.161832-109.161832-109.161832-109.161832a34.351482 34.351482 0 0 1 48.579933-48.579933l109.161832 109.161832 109.161832-109.161832a34.461318 34.461318 0 0 1 48.579933 0z"
                                    fill="#A3A3A3" p-id="5835"></path>
                                <title>关闭所有</title>
                            </svg>

                            <!-- <i class="el-icon-error close-icon" @click="stopPlay" title="关闭"></i> -->
                        </template>

                        <!-- <i class="el-icon-d-arrow-right control-icon" @click="nextPlay" title="下一个"></i> -->
                        <svg xmlns="http://www.w3.org/2000/svg" @click="nextPlay" width="24" height="24"
                            viewBox="0 0 24 24" fill="none">
                            <path
                                d="M19.5 6C19.0858 6 18.75 6.33579 18.75 6.75V10.9999L11.833 6.38855C11.7714 6.34748 11.699 6.32556 11.625 6.32556C11.4179 6.32556 11.25 6.49346 11.25 6.70056V10.9999L4.33301 6.38855C4.27141 6.34748 4.19903 6.32556 4.125 6.32556C3.91789 6.32556 3.75 6.49346 3.75 6.70056V17.2992C3.75 17.3732 3.77191 17.4456 3.81298 17.5072C3.92786 17.6795 4.16069 17.7261 4.33301 17.6112L11.25 12.9999V17.2992C11.25 17.3732 11.2719 17.4456 11.313 17.5072C11.4279 17.6795 11.6607 17.7261 11.833 17.6112L18.75 12.9999V17.25C18.75 17.6642 19.0858 18 19.5 18C19.9142 18 20.25 17.6642 20.25 17.25V6.75C20.25 6.33579 19.9142 6 19.5 6Z"
                                fill="#A4A4A4" />
                            <title>下一个</title>
                        </svg>
                    </div>

                </div>
                <div class="toolbar-right">
                    <div class="toolbar-group">
                        <span class="toolbar-label">取流</span>
                        <div class="stream-source-toggle">
                            <span class="toggle-option" :class="{ active: streamSource === 'nvr' }"
                                @click="setStreamSource('nvr')">硬盘录像机</span>
                            <span class="toggle-option" :class="{ active: streamSource === 'direct' }"
                                @click="setStreamSource('direct')">实时流</span>
                        </div>
                    </div>
                    <div class="toolbar-group ">
                        <span class="toolbar-label">码流</span>
                        <div class="toolbar-buttons">
                            <img @click="setStreamType('main')"
                                :src="streamType === 'main' ? require('@/assets/img/icon_main_active.png') : require('@/assets/img/icon_main.png')"
                                alt="主码流" title="主码流">
                            <img @click="setStreamType('sub')"
                                :src="streamType === 'sub' ? require('@/assets/img/icon_sub_active.png') : require('@/assets/img/icon_sub.png')"
                                alt="子码流" title="子码流"></img>
                            <!-- <button class="toolbar-btn" :class="{ active: streamType === 'main' }"
                                @click="setStreamType('main')">主码</button>
                            <button class="toolbar-btn" :class="{ active: streamType === 'sub' }"
                                @click="setStreamType('sub')">子码</button> -->
                        </div>
                    </div>
                    <div class="toolbar-group cal">
                        <span class="toolbar-label">分屏</span>
                        <div class="toolbar-buttons">
                            <img :src="splitCount === 1 ? require('@/assets/img/icon_fp1_active.png') : require('@/assets/img/icon_fp1.png')"
                                alt="分屏1" title="分屏1" :class="{ active: splitCount === 1 }" @click="setSplit(1)" />
                            <img :src="splitCount === 4 ? require('@/assets/img/icon_fp4_active.png') : require('@/assets/img/icon_fp4.png')"
                                alt="分屏4" title="分屏4" :class="{ active: splitCount === 4 }" @click="setSplit(4)" />
                        </div>
                    </div>

                    <div class="toolbar-group cal">
                        <span class="toolbar-label">音频</span>
                        <div class="toolbar-buttons">
                            <i v-if="!isAudioOn" class="el-icon-turn-off-microphone" @click="toggleSound"
                                title="开启音频"></i>
                            <i v-else class="el-icon-microphone audio-active" @click="toggleSound" title="关闭音频"></i>
                        </div>
                    </div>



                    <div class="toolbar-group cal">
                        <svg @click="toggleFullscreen" style="cursor: pointer;" xmlns="http://www.w3.org/2000/svg"
                            width="24" height="24" viewBox="0 0 24 24" fill="none" title="切换全屏">
                            <path
                                d="M15.6 3.8999H21V9.2999H19.2V5.6999H15.6V3.8999ZM3 3.8999H8.4V5.6999H4.8V9.2999H3V3.8999ZM19.2 18.2999V14.6999H21V20.0999H15.6V18.2999H19.2ZM4.8 18.2999H8.4V20.0999H3V14.6999H4.8V18.2999Z"
                                fill="#A4A4A4" />

                            <title>切换全屏</title>
                        </svg>
                        <!-- <i class="el-icon-full-screen" style="cursor: pointer;font-size: 21px;"
                            @click="toggleFullscreen"></i> -->
                    </div>




                </div>
            </div>

        </div>
    </div>
</template>

<script>
import DropdownSelect from '@/components/common/DropdownSelect.vue';
import request from '@/api/index';
import HikvisionPlayer from "./HikvisionPlayer";
import VideoPlayer from "./videoPlayer";
import { hkvideoUrl, resolveHostWithPort } from '@/config';
import CameraSidebar from '@/components/common/CameraSidebar.vue';
import JSZip from 'jszip';
import { saveAs } from 'file-saver';

export default {
    name: 'VideoMonitoring',
    data() {
        const today = new Date();
        return {
            searchQuery: '',
            selectedCameraId: 1,


            devices: [],
            history: [],
            dropdownanalysis: '1',
            splitCount: 1,
            playingCameras: [],
            streamType: 'main',
            streamSource: 'nvr',


            calendarYear: today.getFullYear(),
            calendarMonth: today.getMonth(), // 0-based
            calendarDays: [],

            last90Start: (function () {
                const d = new Date();
                d.setDate(d.getDate() - 89);
                d.setHours(0, 0, 0, 0);
                return d;
            })(),
            loading: false,
            openGroups: ['nvr_default'],
            previewRequestId: 0,
            previewTimer: null,
            previewDebounceDelay: 200,


            hikPlayerConfig: {
                // accessUrl: 'ws://192.168.1.100:8090', // 你的网关地址
                // accessUrl: 'ws://128.64.13.172:80', // 你的网关地址
                accessUrl: hkvideoUrl,
                username: 'admin', // 你的用户名
                password: 'cmc.1340', // 你的密码
            },
            isAudioOn: false
        };
    },
    components: {
        HikvisionPlayer,
        VideoPlayer,
        DropdownSelect,
        CameraSidebar,

    },
    computed: {
        filteredCameras() {
            const list = this.devices.flatMap(device => device.channels || []);
            // 全局过滤：去掉 type 为 'zero' 的通道（与侧栏一致）
            const filteredByType = list.filter(c => String(c.type) !== 'zero');
            if (this.searchQuery) {
                const q = this.searchQuery.toLowerCase();


                return filteredByType.filter(camera => (camera.ip || '').toLowerCase().includes(q));
            }

            return filteredByType;
        },
        isPlaying() {
            return !!(this.playingCameras && this.playingCameras.length);
        },
        selectedCamera() {
            return this.filteredCameras.find(c => c.id === this.selectedCameraId);
        },
        isRealTime() {
            return this.dropdownanalysis === '1';
        },
        isHistory() {
            return this.dropdownanalysis === '2';
        },
        displaySlots() {
            const slots = this.playingCameras.slice(0, this.splitCount);
            while (slots.length < this.splitCount) slots.push(null);
            return slots;
        },

        cameraGroups() {
            const keyword = (this.searchQuery || '').toLowerCase();
            return this.devices.map(device => {
                const channels = (device.channels || []).filter(channel => {
                    if (!keyword) return true;
                    // return (channel.name || '').toLowerCase().includes(keyword);
                    return (channel.ip || '').toLowerCase().includes(keyword);
                });
                return {
                    key: String(device.devIndex || 'nvr_default'),
                    title: device.devName || '网络视频录像机',
                    anyOnline: device.devStatus === 'online' ? '使用中' : device.devStatus === 'offline' ? '待机中' : device.devStatus === 'sleep' ? '休眠' : '未知',
                    cameras: channels,
                    //                       "devStatus": "online",
                    // /*必选项，string，设备在线状态："online"（在线），"offline"（离线），"sleep"（休眠）*/
                };
            }).filter(group => group.cameras.length > 0 || !keyword);
        }
    },
    mounted() {
        this.init();

        document.addEventListener('fullscreenchange', this.handleFullscreenChange, false);

    },
    beforeDestroy() {
        document.removeEventListener('fullscreenchange', this.handleFullscreenChange, false);
        if (this.previewTimer) {
            clearTimeout(this.previewTimer);
            this.previewTimer = null;
        }
    },
    methods: {
        // 判断通道是否在线。
        // 兼容两种后端字段：
        // - `deviceStatus` 已经是布尔值时直接返回（部分接口会提前转换）；
        // - 否则通过 `status === 'online'` 来判断在线状态。
        // 返回 true 表示该通道目前可用于播放（优先被加入多画面）。
        isCameraOnline(camera) {
            if (!camera) return false;
            if (typeof camera.deviceStatus === 'boolean') return camera.deviceStatus;
            return camera.status === 'online';
        },
        isCameraPlaying(camera) {
            if (!camera || !this.playingCameras || !this.playingCameras.length) return false;
            return this.playingCameras.some(item => item && item.id === camera.id);
        },
        // 监听并处理浏览器进入/退出全屏后的回调。
        // 作用：当页面全屏状态变化（例如按 ESC 退出、或者点击全屏按钮）时，选择当前播放器实例并调用其 `requestResize()`
        // 以便播放器根据新的容器尺寸重新应用分屏与大小调整，保证显示正确。
        handleFullscreenChange() {
            this.$nextTick(() => {
                const isMulti = this.splitCount !== 1;
                const multiPlayer = this.$refs.hikMultiPlayer;
                const singlePlayers = this.$refs.hikPlayers;
                const targetPlayer = isMulti
                    ? multiPlayer
                    : Array.isArray(singlePlayers)
                        ? singlePlayers[0]
                        : singlePlayers;
                if (targetPlayer && typeof targetPlayer.requestResize === 'function') {
                    targetPlayer.requestResize();
                    return;
                }
                // 如果是 video-player 组件，用它的 requestResize
                const videoMulti = this.$refs.videoMultiPlayer;
                const videoSingles = this.$refs.videoPlayers;
                const videoTarget = isMulti ? videoMulti : (Array.isArray(videoSingles) ? videoSingles[0] : videoSingles);
                if (videoTarget && typeof videoTarget.requestResize === 'function') {
                    videoTarget.requestResize();
                }
            });
        },
        isGroupOpen(key) {
            if (Array.isArray(this.openGroups)) return this.openGroups.includes(key);
            return this.openGroups === key;
        },
        // 初始化：加载设备与通道数据，并准备 UI 所需状态
        // 步骤说明：
        // 1) 标记加载中（loading = true），避免重复渲染或用户在加载时交互。
        // 2) 构建 `params`，用于请求设备列表（可控制分页、过滤条件）。
        // 3) 调用 `request.getDeviceStatus(params)` 获取设备信息：
        //    - 将后端返回的结果规范化为内部 `devices` 数组：每个 device 包含 devIndex, devName, devStatus, channels(empty)
        // 4) 根据 `devices` 初始化左侧折叠面板的展开状态 `openGroups`（展开所有设备组以便用户查看通道）。
        // 5) 对每个 device 发起 `getCameraList` 请求以获取该设备下的通道列表：
        //    - 将后端 ChannelInfo 映射为组件内部的 channel 对象，包含：
        //        id: 唯一键 (devIndex_channelId)
        //        channelId: 通道 id
        //        devIndex: 设备索引
        //        name/status/deviceStatus/deviceId/channelLabel/rtspUrl 等字段
        //    - 使用 `that.$set(device, 'channels', channels)` 保证响应式地设置通道数组
        // 6) 使用 `Promise.all(tasks)` 等待所有 per-device 通道请求完成（无论成功或失败），然后：
        //    - 将 `selectedCameraId` 设置为第一个可用通道（如果当前选中项不存在于新列表中），
        //    - 清除 loading 标志（loading = false）。
        // 7) 在请求链的 catch 分支确保出现错误时也能关闭 loading，避免界面永久处于加载状态。
        init() {
            const that = this;
            // // 1) 标记加载中
            // that.loading = true;

            // TODO: 测试代码，测试完成后需要恢复
            // 模拟设备列表数据
            // that.devices = [
            //     {
            //         devIndex: '1',
            //         devName: '测试设备1',
            //         devStatus: 'online',
            //         channels: [
            //             {
            //                 id: '1_1',
            //                 channelId: '1',
            //                 devIndex: '1',
            //                 name: '测试摄像头1',
            //                 status: 'online',
            //                 deviceStatus: true,
            //                 deviceId: '1',
            //                 channelLabel: '数字通道',
            //                 rtspUrl: 'rtsp://192.168.1.100:554/dac/realplay/68F108CF-522A-4774-A0A7-AC41687839601/MAIN/TCP?streamform=rtp',
            //                 realPlayPath: 'rtsp://192.168.1.100:554/dac/realplay/68F108CF-522A-4774-A0A7-AC41687839601/MAIN/TCP?streamform=rtp',
            //                 ip: '192.168.1.13',
            //                 type: 'digital'
            //             },
            //             {
            //                 id: '1_2',
            //                 channelId: '2',
            //                 devIndex: '1',
            //                 name: '测试摄像头2',
            //                 status: 'online',
            //                 deviceStatus: true,
            //                 deviceId: '2',
            //                 channelLabel: '数字通道',
            //                 rtspUrl: 'rtsp://192.168.1.13:554/h264/ch1/main/av_stream',
            //                 realPlayPath: 'rtsp://192.168.1.13:554/h264/ch1/main/av_stream',
            //                 ip: '192.168.1.13',
            //                 type: 'digital'
            //             }
            //         ]
            //     },

            // ];

            // // 初始化折叠面板展开状态
            // that.openGroups = that.devices.length
            //     ? that.devices.map(device => String(device.devIndex || 'nvr_default'))
            //     : ['nvr_default'];

            // // 收集所有通道扁平列表
            // const allChannels = that.devices.flatMap(device => device.channels || []);
            // // 如果当前 selectedCameraId 不在列表中，则默认选中第一个可用通道
            // if (allChannels.length > 0 && !allChannels.find(c => c.id === that.selectedCameraId)) {
            //     that.selectedCameraId = allChannels[0].id;
            // }
            // // 关闭加载状态
            // that.loading = false;
            // return;

            // 以下是原始接口调用代码，暂时注释掉

            // 2) 构建查询参数（分页 + 过滤条件）
            const params = {
                SearchDescription: {
                    position: 0,
                    maxResult: 100,
                    Filter: {
                        key: "",
                        devType: "",
                        protocolType: ["ehomeV5"],
                        devStatus: ["online", "offline"]
                    }
                }
            };

            // 3) 请求设备列表
            request.getDeviceStatus(params).then((res) => {
                // 规范化后端响应体，兼容 res 或 res.data
                const body = res && (res.data || res);
                const matchList = body && body.SearchResult && body.SearchResult.MatchList ? body.SearchResult.MatchList : [];

                // 3.a 将后端设备项 map 为内部 devices 结构（初始 channels 为空，后续异步填充）
                that.devices = matchList.map(item => {
                    const device = item.Device || item.device || item;
                    return {
                        devIndex: device.devIndex,
                        devName: device.devName,
                        devStatus: device.devStatus,
                        channels: [] // 占位，后续通过 getCameraList 填充
                    };
                });

                // 4) 初始化折叠面板展开状态，默认展开所有设备组以便用户查看
                that.openGroups = that.devices.length
                    ? that.devices.map(device => String(device.devIndex || 'nvr_default'))
                    : ['nvr_default'];

                // 5) 为每个设备发起通道列表请求（并发）
                const tasks = that.devices.map(device => {
                    if (!device.devIndex) return Promise.resolve();
                    // 对每个设备调用后端 API 获取通道
                    return request.getCameraList({ devIndex: device.devIndex }).then((res2) => {

                        const body2 = res2 && (res2.data || res2);
                        const videoChannels = body2 && body2.ChannelInfo && body2.ChannelInfo.VideoChannel ? body2.ChannelInfo.VideoChannel : [];

                        // 5.a 将后端通道数据映射为组件内部使用的格式
                        const channels = videoChannels.map(item => {
                            const channel = item.Channel || item.channel || item;
                            const channelId = channel.id != null ? channel.id : '';
                            const channelKey = `${device.devIndex}_${channelId}`; // 保证在全局唯一
                            return {
                                id: channelKey,
                                channelId,
                                devIndex: device.devIndex,
                                name: channel.ip,
                                status: channel.status,
                                deviceStatus: channel.status === 'online',
                                deviceId: channel.id,
                                channelLabel: channel.type === 'digital' ? '数字通道' : (channel.type == 'zero' ? '零通道' : ''),
                                rtspUrl: channel.rtspUrl || '',
                                realPlayPath: channel.realPlayPath || '',
                                ip: channel.ip,
                                type: channel.type || '',
                            };
                        });

                        // 5.b 使用 $set 保证响应式
                        that.$set(device, 'channels', channels);
                    });
                });

                // 6) 等待所有 device 通道请求完成，设置首选选中并取消 loading
                Promise.all(tasks).finally(() => {
                    // 收集所有通道扁平列表
                    const allChannels = that.devices.flatMap(device => device.channels || []);
                    // 如果当前 selectedCameraId 不在列表中，则默认选中第一个可用通道
                    if (allChannels.length > 0 && !allChannels.find(c => c.id === that.selectedCameraId)) {
                        that.selectedCameraId = allChannels[0].id;
                    }
                    // 关闭加载状态
                    that.loading = false;
                });
            }).catch(() => {
                this.$message.error('获取设备列表失败');
                // 7) 出错时确保关闭 loading，错误可以在控制台或上层统一处理
                that.loading = false;
            });

        },
        handleSelectalysis({ value }) {
            this.dropdownanalysis = value;
        },
        // general helpers
        pad(n) { return (n < 10 ? '0' + n : '' + n); },
        formatDate(d) {
            if (!(d instanceof Date)) d = new Date(d);
            return `${d.getFullYear()}-${this.pad(d.getMonth() + 1)}-${this.pad(d.getDate())}`;
        },
        formatDateTime(d) {
            if (!(d instanceof Date)) d = new Date(d);
            return `${d.getFullYear()}-${this.pad(d.getMonth() + 1)}-${this.pad(d.getDate())} ${this.pad(d.getHours())}:${this.pad(d.getMinutes())}:${this.pad(d.getSeconds())}`;
        },

        // camera selection
        // 选择单个摄像头并开始播放（或切换播放列表首位）。
        selectCamera(id) {
            this.selectedCameraId = id;
            this.updatePlayingCameras('selectedFirst', true);
        },
        // 设置分屏数量（1/4/...）并更新播放摄像头列表，自动触发重连。
        setSplit(count) {
            this.splitCount = count;
            this.updatePlayingCameras('selectedFirst', true);
            if (count > 1 && this.streamType === 'main') {
                // this.streamType = 'sub';
                this.scheduleStartPreview();
            }
        },
        setStreamType(type) {
            if (this.streamType === type) return;
            this.streamType = type;
            if (this.playingCameras && this.playingCameras.length) {
                this.scheduleStartPreview();
            }
        },
        async checkWebRTCStreamerAvailable() {
            try {
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), 500);
                const response = await fetch(`http://${resolveHostWithPort(7000)}/api/getIceServers`, {
                    method: 'GET',
                    signal: controller.signal
                });
                clearTimeout(timeoutId);
                return response.ok;
            } catch (error) {
                console.error('webrtc-streamer 服务检测失败:', error);
                return false;
            }
        },
        async downloadWebRTCBundle() {
            const baseUrl = window.location.origin;
            const files = [
                { name: 'webrtc-streamer.exe', url: `${baseUrl}/webrtc-streamer.exe` },
                { name: 'webrtc.bat', url: `${baseUrl}/webrtc.bat` }
            ];

            try {
                const zip = new JSZip();

                for (const file of files) {
                    const response = await fetch(file.url, { credentials: 'omit' });
                    if (!response.ok) {
                        throw new Error(`下载 ${file.name} 失败: ${response.status}`);
                    }
                    const blob = await response.blob();
                    zip.file(file.name, blob);
                }

                const content = await zip.generateAsync({ type: 'blob' });
                saveAs(content, 'webrtc-streamer运行包.zip');
                this.$message.success('已生成压缩包，解压后双击 webrtc.bat 运行即可');
                return true;
            } catch (error) {
                console.error('downloadWebRTCBundle failed:', error);
                return false;
            }
        },
        showWebRTCStreamerTip() {
            this.$notify({
                title: '提示',
                message: '实时流播放需要启动 webrtc-streamer.exe 程序，请下载压缩包并运行 webrtc.bat',
                type: 'warning',
                duration: 5000,
                position: 'top-right',
                onClick: async () => {
                    const ok = await this.downloadWebRTCBundle();
                    if (!ok) {
                        this.$message.warning('压缩包生成失败，请检查 webrtc-streamer.exe 和 webrtc.bat 是否可访问');
                    }
                }
            });
        },
        // 切换音频
        toggleSound() {
            if (this.streamSource === 'nvr') {
                const isMulti = this.splitCount !== 1;
                const multiPlayer = this.$refs.hikMultiPlayer;
                const singlePlayers = this.$refs.hikPlayers;
                const targetPlayer = isMulti
                    ? multiPlayer
                    : Array.isArray(singlePlayers)
                        ? singlePlayers[0]
                        : singlePlayers;
                if (targetPlayer) {
                    if (this.isAudioOn) {
                        // 关闭音频
                        if (typeof targetPlayer.closeSound === 'function') {
                            targetPlayer.closeSound().then(() => {
                                this.isAudioOn = false;
                                this.$message.info('已关闭音频');
                            }).catch(err => {
                                console.error('关闭音频失败:', err);
                                this.$message.error('关闭音频失败');
                            });
                        }
                    } else {
                        // 开启音频
                        if (typeof targetPlayer.openSound === 'function') {
                            targetPlayer.openSound().then(() => {
                                this.isAudioOn = true;
                                this.$message.success('已开启音频');
                            }).catch(err => {
                                console.error('开启音频失败:', err);
                                this.$message.error('开启音频失败');
                            });
                        }
                    }
                }
            }
        },
        async setStreamSource(source) {
            if (this.streamSource === source) return;
            if (source === 'direct') {
                const available = await this.checkWebRTCStreamerAvailable();
                if (!available) {
                    this.showWebRTCStreamerTip();
                }
            }
            this.streamSource = source;
            if (this.playingCameras && this.playingCameras.length) {
                this.scheduleStartPreview();
            }
        },
        applyDirectStreamUrls() {
            this.playingCameras = this.playingCameras.map(c => {
                if (!c) return c;
                const directUrl = c.realPlayPath || '';
                return directUrl ? { ...c, rtspUrl: directUrl } : c;
            });
        },
        getCameraList() {

            return this.filteredCameras || [];
        },
        /**
         * 构建播放列表（优先在线）
         * mode:
         *  - 'selectedFirst'：以当前选中摄像头为首（若在线则保证首位），其他位从在线列表或总列表补足；
         *  - 'defaultList'：直接取前 N 个（优先来自在线列表，如果没有在线则回退到全部列表）。
         * 策略说明：
         * 1. 当存在在线通道时，优先使用在线通道填充分屏，避免在多画面中出现空白/离线窗口；
         * 2. 若当前选中摄像头在线，则把它放到首位，再从在线通道中补足剩余位；
         * 3. 若没有任何在线通道，则回退到全部通道（保证在离线环境下仍能显示通道占位）。
         */
        buildPlayingCameras(mode = 'selectedFirst') {

            //       const list = this.getCameraList();
            // if (!list.length) return [];
            // const selected = list.find(c => c.id === this.selectedCameraId) || list[0];
            // if (!selected) return [];
            // if (this.splitCount === 1) return [selected];
            // if (mode === 'defaultList') {
            //     return list.slice(0, this.splitCount);
            // }
            // const others = list.filter(c => c.id !== selected.id);
            // return [selected, ...others].slice(0, this.splitCount);
            const list = this.getCameraList();
            if (!list.length) return [];
            const selected = list.find(c => c.id === this.selectedCameraId) || list[0];
            if (!selected) return [];
            // 单画面直接返回选中；多画面始终保持“当前选中 + 原列表顺序”的稳定展示顺序
            if (this.splitCount === 1) return [selected];

            const ordered = [selected, ...list.filter(c => c.id !== selected.id)];
            return ordered.slice(0, this.splitCount);
        },
        // 根据当前策略生成并设置正在播放的摄像头数组。
        // mode: 'selectedFirst'（以当前选中为首）或 'defaultList'（取列表前 N 个）。
        // autoStart: 若为 true，则在设置后立即发起预览请求开始播放。
        updatePlayingCameras(mode = 'selectedFirst', autoStart = false) {
            const nextList = this.buildPlayingCameras(mode);
            this.playingCameras = nextList;
            if (nextList.length) {
                this.selectedCameraId = nextList[0].id;
            }
            if (autoStart) {
                this.scheduleStartPreview();
            }
        },
        scheduleStartPreview() {
            if (this.previewTimer) {
                clearTimeout(this.previewTimer);
            }
            if (this.streamSource === 'direct') {
                this.applyDirectStreamUrls();
                return;
            }
            this.previewTimer = setTimeout(() => {
                this.previewTimer = null;
                this.startPreviewForPlayingCameras();
            }, this.previewDebounceDelay);
        },
        // 为当前 `playingCameras` 列表逐个向后端请求直播预览地址（startPreview），并把返回的 RTSP URL 更新到对应项。
        // 实现要点：并发请求所有目标，使用 `previewRequestId` 做幂等（避免网络慢时覆盖新请求结果）。
        async startPreviewForPlayingCameras() {
            if (!this.playingCameras || !this.playingCameras.length) return;
            if (this.streamSource === 'direct') {
                this.applyDirectStreamUrls();
                return;
            }
            try {
                const requestId = ++this.previewRequestId;
                const targets = this.playingCameras.filter(Boolean).map(c => ({
                    devIndex: c.devIndex,
                    channelId: c.channelId || c.deviceId || '',
                    streamType: this.streamType
                }));
                if (!targets.length) return;
                const results = await Promise.all(targets.map(async ({ devIndex, channelId, streamType }) => {
                    try {
                        const res = await request.startPreview({
                            StreamInfo: {
                                id: String(channelId),
                                streamType: streamType,
                                method: 'preview'
                            }
                        }, devIndex);
                        const body = res && (res.data || res);
                        const url = body && body.MediaAccessInfo && body.MediaAccessInfo.URL;
                        if (!url) return null;
                        return {
                            key: `${devIndex}_${channelId}`,
                            url
                        };
                    } catch (err) {
                        console.error('startPreview error for', devIndex, channelId, err);
                        return null;
                    }
                }));

                if (requestId !== this.previewRequestId) return;

                const urlMap = new Map(results.filter(Boolean).map(item => [item.key, item.url]));
                if (!urlMap.size) return;

                this.playingCameras = this.playingCameras.map(c => {
                    if (!c) return c;
                    const key = `${c.devIndex}_${c.channelId || c.deviceId || ''}`;
                    const nextUrl = urlMap.get(key);
                    return nextUrl ? { ...c, rtspUrl: nextUrl } : c;
                });
            } catch (e) {
                console.error('startPlay error', e);
            }
        },
        // 启动播放入口：根据当前选择构建播放列表并开始播放。
        async startPlay() {
            this.updatePlayingCameras('selectedFirst', true);
        },
        // 停止播放并清空播放列表（会触发子组件卸载并停止解码器）。
        stopPlay() {
            this.playingCameras = [];
        },
        prevPlay() {
            const list = this.getCameraList();
            if (!list.length) return;
            const currentIndex = list.findIndex(c => c.id === this.selectedCameraId);
            const nextIndex = currentIndex <= 0 ? list.length - 1 : currentIndex - 1;
            this.selectedCameraId = list[nextIndex].id;
            this.updatePlayingCameras('selectedFirst', true);
        },
        nextPlay() {
            const list = this.getCameraList();
            if (!list.length) return;
            const currentIndex = list.findIndex(c => c.id === this.selectedCameraId);
            const nextIndex = currentIndex >= list.length - 1 ? 0 : currentIndex + 1;
            this.selectedCameraId = list[nextIndex].id;
            this.updatePlayingCameras('selectedFirst', true);
        },
        // 立即播放（强制重新创建播放器实例），用于显式的“立即播放”按钮。
        // 实现：先停止并卸载当前播放器，短期 nextTick 后再重新启动播放，确保 DOM 已更新。
        playNow() {
            this.stopPlay();
            this.$nextTick(() => {
                this.startPlay();
            });
        },
        togglePlay() {
            // 兼容旧调用：直接触发重新播放
            this.playNow();
        },
        handlePerformanceLack() {
            //1.重新拉流会闪烁窗口
            // const isMulti = this.splitCount !== 1;
            // const multiPlayer = this.$refs.hikMultiPlayer;
            // const singlePlayers = this.$refs.hikPlayers;
            // const targetPlayer = isMulti
            //     ? multiPlayer
            //     : Array.isArray(singlePlayers)
            //         ? singlePlayers[0]
            //         : singlePlayers;
            // if (targetPlayer && typeof targetPlayer.restartPlayback === 'function') {
            //     targetPlayer.restartPlayback();
            //     return;
            // }
            // this.scheduleStartPreview();
            //2.降低为子码流
            if (this.streamType === 'main') {
                this.streamType = 'sub';
                this.scheduleStartPreview();
            }

        },

        // 说明：先让播放器内部进入全屏显示（调用插件方法），再请求浏览器对播放器容器进行 DOM 全屏。
        toggleFullscreen() {
            const el = this.$refs.playerContainer;
            const isMulti = this.splitCount !== 1;
            // 优先查找 hikvision player 引用
            const multiPlayer = this.$refs.hikMultiPlayer;
            const singlePlayers = this.$refs.hikPlayers;
            const hikTarget = isMulti
                ? multiPlayer
                : Array.isArray(singlePlayers)
                    ? singlePlayers[0]
                    : singlePlayers;

            // 其次查找我们的视频组件引用
            const videoMulti = this.$refs.videoMultiPlayer;
            const videoSingles = this.$refs.videoPlayers;
            const videoTarget = isMulti ? videoMulti : (Array.isArray(videoSingles) ? videoSingles[0] : videoSingles);

            // 调用优先级：hikvision player -> video-player
            if (hikTarget && typeof hikTarget.fullScreenAll === 'function') {
                hikTarget.fullScreenAll();
            } else if (videoTarget && typeof videoTarget.fullScreenAll === 'function') {
                videoTarget.fullScreenAll();
            }
            if (!el) return;
            if (!document.fullscreenElement) {
                if (el.requestFullscreen) {
                    el.requestFullscreen();
                }
            } else if (document.exitFullscreen) {
                document.exitFullscreen();
            }
        },


        prevMonth() {
            if (this.calendarMonth === 0) {
                this.calendarMonth = 11;
                this.calendarYear -= 1;
            } else {
                this.calendarMonth -= 1;
            }
            this.generateCalendar(this.calendarYear, this.calendarMonth);
        },
        nextMonth() {
            if (this.calendarMonth === 11) {
                this.calendarMonth = 0;
                this.calendarYear += 1;
            } else {
                this.calendarMonth += 1;
            }
            this.generateCalendar(this.calendarYear, this.calendarMonth);
        },


    }
};
</script>

<style lang="scss" scoped>
.video-monitoring-container {
    display: flex;
    height: 100%;
    width: 100%;
    background-color: #f0f2f5;
    gap: 10px;

    box-sizing: border-box;
}

.left-sidebar {
    width: 280px;
    flex-shrink: 0;
    background-color: #fff;
    border-radius: 8px;
    padding: 12px 10px;
    display: flex;
    flex-direction: column;
    justify-content: flex-start;
    gap: 12px;
    min-height: 0;
}

.sidebar-search {
    padding: 4px 2px;
}

::v-deep .sidebar-search .el-input__inner {
    border-radius: 6px;
}

.left-sidebar.history-mode {
    height: auto;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    justify-content: flex-start;
}

.device-collapse {
    flex: 1 1 auto;
    min-height: 0;
    overflow: auto;
}

::v-deep .device-collapse.el-collapse {
    border-top: 0;
    border-bottom: 0;
}

::v-deep .device-collapse .el-collapse-item__header {
    height: auto;
    line-height: normal;
    padding: 0;
    border-bottom: 0;
    background: transparent;
}

::v-deep .device-collapse .el-collapse-item__arrow {
    display: none;
}

::v-deep .device-collapse .el-collapse-item__wrap {
    border-bottom: 0;
}

::v-deep .device-collapse .el-collapse-item__content {
    padding-bottom: 8px;
}

.device-group {
    display: flex;
    flex-direction: column;
    background: #fff;
    border-radius: 8px;
    padding: 4px 6px;
    gap: 8px;
    flex: 1 1 auto;
}

.group-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 8px;
    border-radius: 6px;
    // background: #f6f8fb;
    color: #343b4c;
    font-size: 14px;
    width: 100%;
    box-sizing: border-box;
}

.group-header-right {
    width: 45px;
    display: flex;
    align-items: center;
    gap: 10px;
}

.expand-icon {
    color: #8a96ab;
    transition: transform 0.2s ease;
}

.expand-icon.expanded {
    transform: rotate(90deg);
}

.group-header-left {
    display: flex;
    align-items: center;
    gap: 6px;

    i {
        color: #2b6de6;
        font-size: 16px;
    }
}

.group-title {
    font-weight: 600;
}

.group-status {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    color: #46b250;
}

.group-status.offline {
    color: #7B7B7B;
}

.group-status .status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    display: inline-block;
}

.group-status .status-dot.online {
    background: #45c04d;
}

.group-status .status-dot.offline {
    background: #7B7B7B;
}

.history-section {
    /* 固定高度避免与上方列表累加导致换行 */
    min-height: 340px;
    display: flex;
    flex-direction: column;
    margin-top: 12px;
    flex-grow: 0;
    min-height: 0;
}

.camera-list,
.history-list {
    flex-grow: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-height: 0;
}

/* Calendar styles */
.calendar {
    width: 100%;
    box-sizing: border-box;
    padding: 8px;
}

.calendar-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 6px;
}

.nav-btn {
    border: none;
    background: transparent;
    font-size: 18px;
    color: #606266;
    cursor: pointer;
    padding: 4px 8px;
}

.month-label {
    font-size: 14px;
    color: #333;
}



.weekday {
    padding: 4px 0;
}

.days-grid {
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 6px;
}

.day-cell {
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 4px;
    cursor: pointer;
    color: #333;
    font-size: 13px;
}

.day-cell.empty {
    background: transparent;
    cursor: default;
}

.day-cell.disabled {
    color: #c0c4cc;
    cursor: default;
}

.day-cell.selected {
    background: #4080FF;
    color: #fff;
}

.day-cell.today {
    box-shadow: inset 0 0 0 1px rgba(64, 128, 255, 0.15);
}

.camera-item,
.history-item {
    padding: 10px 8px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 14px;
    transition: background-color 0.2s, border 0.2s;
    border: 1px solid transparent;

    &:hover {
        background-color: #f4f8ff;
    }

    &.active {
        background: #eef5ff;
        border: 1px solid #d1e2ff;
    }
}

.camera-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 6px;

    &.active {
        .camera-name {
            color: #1f73f1;
        }

        // .camera-id,
        // .camera-channel {
        //     color: #2b6de6;
        // }
    }

    .camera-main {
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .custom-radio {
        width: 16px;
        height: 16px;
        border-radius: 50%;
        border: 1px solid #8fa4c8;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        box-sizing: border-box;
        position: relative;

        &.checked {
            border-color: #1f73f1;
            box-shadow: 0 0 0 3px rgba(31, 115, 241, 0.15);
        }

        &.checked::after {
            content: '';
            width: 8px;
            height: 8px;
            background: #1f73f1;
            border-radius: 50%;
            display: block;
        }
    }

    .playing-indicator {
        position: absolute;
        right: -3px;
        bottom: -3px;
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: #31c48d;
        border: 1px solid #ffffff;
        box-shadow: 0 0 0 1px rgba(49, 196, 141, 0.3);
    }

    .camera-info {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }

    .camera-name {
        font-weight: 600;
        color: #1f2f4d;
        line-height: 1.2;
    }

    .camera-name.is-offline {
        color: #8a96ab;
    }

    .camera-id {
        font-size: 12px;
        color: #8a96ab;
    }

    .camera-status {
        display: flex;
        flex-direction: column;
        align-items: flex-end;
        gap: 6px;
        font-size: 12px;
    }

    .status-line {
        display: flex;
        align-items: center;
        gap: 6px;
    }

    .camera-channel {
        color: #8a96ab;
    }

    .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        display: inline-block;

        &.online {
            background-color: #45c04d;
        }

        &.offline {
            background-color: #7B7B7B;
        }

        &.sleep {
            background-color: #f09b1b;
        }
    }

    .status-text {
        font-size: 13px;

        &.text-online {
            color: #45c04d;
        }

        &.text-offline {
            color: #7B7B7B;
        }
    }
}

.history-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.right-content {
    flex-grow: 1;
    background-color: #fff;
    border-radius: 8px;
    padding: 16px;
    display: flex;
    flex-direction: column;
}

.right-content.history-mode {
    padding-bottom: 24px;
}

// .realtime-grid {
//     display: grid;
//     grid-template-columns: repeat(2, minmax(0, 1fr));
//     grid-auto-rows: 1fr;
//     gap: 16px;
//     height: 100%;
// }
.realtime-grid {
    display: grid;
    /* 保证网格行在内容溢出时能正确收缩/扩展 */
    grid-auto-rows: minmax(0, 1fr);
    gap: 16px;
    height: 100%;
    grid-template-columns: repeat(1, minmax(0, 1fr));
    flex: 1 1 auto;
    min-height: 0;

    /* 自动生成行，每行等分高度 */
}


.realtime-card {
    background: #fff;
    border-radius: 8px;
    border: 1px solid #edf0f5;
    padding: 14px 16px;
    display: flex;
    flex-direction: column;
    box-shadow: 0 4px 18px rgba(39, 80, 156, 0.05);
    /* 允许卡片在网格中正确收缩，避免内部视频撑开父容器 */
    // min-height: 0;
    // overflow: hidden;
}

.multi-player-card {
    grid-column: 1 / -1;
    grid-row: 1 / -1;
    min-height: 0;
}

.card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
}

.card-header-right {
    display: flex;
    align-items: center;
    gap: 8px;
}

.stream-source-toggle {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 12px;
    color: #606266;
}

.stream-source-toggle .toggle-label {
    color: #8a96ab;
}

.stream-source-toggle .toggle-option {
    padding: 2px 5px;
    border-radius: 12px;
    border: 1px solid #e5e7eb;
    cursor: pointer;
    background: #f8fafc;
    color: #606266;
}

.stream-source-toggle .toggle-option.active {
    border-color: #2d5bff;
    color: #2d5bff;
    background: #eef3ff;
}

.card-header.empty {
    color: #8a96ab;
    font-size: 14px;
    margin-bottom: 12px;
}

.card-meta {
    display: flex;
    flex-direction: column;
    gap: 2px;

    .video-title {
        display: flex;
        align-items: center;
        font-size: 18px;
        font-weight: 500;

        img {
            width: 24px;
            height: 24px;
            margin-right: 8px;
        }
    }
}

.card-title {
    font-size: 16px;
    font-weight: 600;
    color: #1d2129;
}

.card-time {
    font-size: 12px;
    color: #86909c;
}

.card-action {
    font-size: 16px;
    color: #b2b7c3;
}

.card-video {
    flex: 1 1 auto;
    background: #010101;
    border-radius: 8px;
    display: flex;
    align-items: stretch;
    justify-content: center;
    position: relative;
    margin-bottom: 12px;
    min-height: 0;
    /* 允许子元素高度受限，不撑开网格行 */

    // ::v-deep .video-player,
    // ::v-deep .video-player video,
    // ::v-deep .video-player rtsp-video {
    //     width: 100%;
    //     height: 100%;
    //     max-width: 100%;
    //     max-height: 100%;
    //     object-fit: cover;
    //     border-radius: 6px;
    //     background: #000;
    //     display: block;
    // }

    ::v-deep .video-player {
        width: 100%;
        height: 100%;
        object-fit: cover;
        border-radius: 6px;
        background: #000;
    }
}

.empty-state {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    color: #9aa3b2;
    font-size: 14px;
    background: #0b0b0b;
    border-radius: 6px;

    i {
        font-size: 18px;
    }
}

.realtime-toolbar {
    margin-top: 5px;
    padding: 8px 14px;
    min-height: 44px;
    background: #f6f7fb;
    border: 1px solid #e6e9f0;
    border-radius: 5px;
    display: flex;
    align-items: center;
    position: relative;
}

.toolbar-left {
    display: flex;
    align-items: center;
}

.toolbar-center {
    position: absolute;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
    display: flex;
    align-items: center;
}

.toolbar-right {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 10px;
}

.toolbar-group {
    display: flex;
    align-items: center;
    gap: 10px;
}

.cal {
    border-left: 1px solid #d8dbe6;
    padding-left: 10px;
}

.toolbar-label {
    color: #5b6678;
    font-size: 12px;
    font-weight: 500;
}

.toolbar-buttons {
    display: flex;
    align-items: center;
    gap: 6px;


    img {
        width: 24px;
        height: 24px;
        cursor: pointer;
    }

    i {
        font-size: 24px;
        cursor: pointer;
        color: #A4A4A4;
    }

    i.active {
        color: #409EFF;
    }

    i.audio-active {
        color: #409EFF;
    }
}

.toolbar-btn {
    min-width: 32px;
    height: 26px;
    padding: 0 8px;
    border-radius: 6px;
    border: 1px solid #d8dbe6;
    background: #ffffff;
    color: #6b7280;
    cursor: pointer;
    font-size: 12px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: all 0.2s ease;

    &.active {
        border-color: #3a7afe;
        color: #3a7afe;
        background: #eef4ff;
        box-shadow: inset 0 0 0 1px rgba(58, 122, 254, 0.2);
    }
}

.toolbar-right {
    display: flex;
    align-items: center;
    gap: 10px;
}

.toolbar-icon-btn {
    height: 28px;
    padding: 0 10px;
    border-radius: 6px;
    border: 1px solid #d8dbe6;
    background: #ffffff;
    color: #495365;
    cursor: pointer;
    font-size: 12px;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    transition: all 0.2s ease;
}

.toolbar-icon-btn i {
    font-size: 14px;
}

.toolbar-icon-btn:hover {
    border-color: #3a7afe;
    color: #3a7afe;
    background: #eef4ff;
}

.play-controls {
    display: flex;
    align-items: center;
    gap: 12px;
}

.control-btn {
    width: 32px;
    height: 32px;
    border-radius: 6px;
    border: 1px solid #d8dbe6;
    background: #fff;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
}

.play-btn {
    width: 44px;
    height: 44px;
    border-radius: 22px;
    border: 1px solid #d8dbe6;
    background: #fff;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.06);
}

.play-btn i {
    font-size: 18px;
}

.control-icon {
    font-size: 18px;
    color: #6b7280;
    cursor: pointer;
    padding: 6px;
    border-radius: 6px;
    transition: all 0.15s ease;
}

.control-icon:hover {
    color: #3a7afe;
    background: #eef4ff;
}

.play-icon {
    font-size: 26px;
    // font-size: 22px;
    color: #fff;
    background: #A3A3A3;
    border-radius: 50%;

    cursor: pointer;
}

.close-icon {

    font-size: 24px;

    color: #ff5b5b;
    cursor: pointer;
}

// .play-icon {
//     font-size: 32px;
//     color: #fff;
//     opacity: 0.8;
// }

.card-footer {
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    color: #4e5969;
}

.video-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;

    .video-title {
        display: flex;
        align-items: center;
        font-size: 18px;
        font-weight: 500;

        img {
            width: 24px;
            height: 24px;
            margin-right: 8px;
        }
    }

    .video-timestamp {
        font-size: 14px;
        color: #606266;
    }
}

.video-player-wrapper {
    flex-grow: 1;
    background-color: #000;
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
}

.video-player {
    width: 100%;
    height: 100%;
}

.video-footer {
    padding-top: 10px;
    display: flex;
    justify-content: flex-start;
    font-size: 14px;
    color: #909399;



    .footer-info {
        &:nth-child(1) {
            width: 50%;
        }

        &:nth-child(2) {
            width: 50%;
        }

        .label {
            font-size: 14px;

            margin-right: 4px;
        }

        .vlaue {
            color: #171717;
            font-size: 16px;
            font-weight: 400;
        }
    }

}
</style>
