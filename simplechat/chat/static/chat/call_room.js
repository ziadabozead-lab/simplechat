(function () {
    'use strict';

    // Public STUN only. Enough for most home/office networks to find a
    // direct path, but some networks (symmetric NAT, locked-down
    // corporate wifi) need a TURN relay to connect at all. If calls fail
    // to connect for some people, add a TURN server here, e.g.:
    //   { urls: 'turn:your-turn-host:3478', username: '...', credential: '...' }
    const ICE_SERVERS = [
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: 'stun:stun1.l.google.com:19302' },
    ];

    const grid = document.getElementById('meet-video-grid');
    const waiting = document.getElementById('meet-waiting');
    const errorBox = document.getElementById('meet-error');
    const timerEl = document.getElementById('meet-timer');
    const countEl = document.getElementById('meet-participant-count');
    const micBtn = document.getElementById('meet-toggle-mic');
    const camBtn = document.getElementById('meet-toggle-cam');
    const leaveBtn = document.getElementById('meet-leave');

    const params = new URLSearchParams(window.location.search);
    const wantVideo = params.get('video') === '1';

    let ws = null;
    let localStream = null;
    let micOn = true;
    let camOn = wantVideo;
    let timerHandle = null;
    let startedAt = null;
    const peerConnections = {};   // username -> RTCPeerConnection
    const tiles = {};             // username -> tile <div>

    function initials(name) {
        return (name || '?').trim().slice(0, 2).toUpperCase();
    }

    function updateParticipantCount() {
        const n = Object.keys(tiles).length;
        countEl.textContent = String(n);
    }

    function updateWaitingState() {
        waiting.classList.toggle('hidden', Object.keys(peerConnections).length > 0);
    }

    function makeTile(username, isLocal) {
        const tile = document.createElement('div');
        tile.className = 'meet-tile' + (isLocal ? ' is-local' : '');
        tile.dataset.username = username;

        const video = document.createElement('video');
        video.autoplay = true;
        video.playsInline = true;
        if (isLocal) video.muted = true;
        tile.appendChild(video);

        const avatar = document.createElement('div');
        avatar.className = 'meet-avatar';
        avatar.textContent = initials(username);
        tile.appendChild(avatar);

        const label = document.createElement('span');
        label.className = 'meet-tile-label';
        label.textContent = isLocal ? `${username} (you)` : username;
        tile.appendChild(label);

        grid.appendChild(tile);
        tiles[username] = tile;
        updateParticipantCount();
        return tile;
    }

    function attachStreamToTile(tile, stream, hasVideo) {
        const video = tile.querySelector('video');
        video.srcObject = stream;
        tile.classList.toggle('audio-only', !hasVideo);
    }

    function removeTile(username) {
        const tile = tiles[username];
        if (tile) {
            tile.remove();
            delete tiles[username];
            updateParticipantCount();
        }
    }

    function closePeerConnection(username) {
        const pc = peerConnections[username];
        if (pc) {
            pc.close();
            delete peerConnections[username];
        }
        removeTile(username);
        updateWaitingState();
    }

    function sendSignal(to, data) {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'signal', to: to, data: data }));
        }
    }

    function createPeerConnection(username, initiator) {
        const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
        peerConnections[username] = pc;
        updateWaitingState();

        localStream.getTracks().forEach(function (track) {
            pc.addTrack(track, localStream);
        });

        pc.onicecandidate = function (event) {
            if (event.candidate) {
                sendSignal(username, { candidate: event.candidate });
            }
        };

        pc.ontrack = function (event) {
            let tile = tiles[username];
            if (!tile) tile = makeTile(username, false);
            attachStreamToTile(tile, event.streams[0], event.track.kind === 'video');
        };

        pc.onconnectionstatechange = function () {
            if (pc.connectionState === 'failed' || pc.connectionState === 'closed') {
                closePeerConnection(username);
            }
        };

        if (initiator) {
            pc.createOffer().then(function (offer) {
                return pc.setLocalDescription(offer);
            }).then(function () {
                sendSignal(username, { sdp: pc.localDescription });
            });
        }

        return pc;
    }

    function handleSignal(from, data) {
        let pc = peerConnections[from];

        if (data.sdp) {
            if (!pc) pc = createPeerConnection(from, false);
            const desc = new RTCSessionDescription(data.sdp);
            pc.setRemoteDescription(desc).then(function () {
                if (desc.type === 'offer') {
                    return pc.createAnswer().then(function (answer) {
                        return pc.setLocalDescription(answer);
                    }).then(function () {
                        sendSignal(from, { sdp: pc.localDescription });
                    });
                }
            });
        } else if (data.candidate && pc) {
            pc.addIceCandidate(new RTCIceCandidate(data.candidate)).catch(function () {
                // Harmless if it arrives after the connection already closed.
            });
        }
    }

    function startTimer() {
        startedAt = Date.now();
        timerHandle = setInterval(function () {
            const secs = Math.floor((Date.now() - startedAt) / 1000);
            const m = String(Math.floor(secs / 60)).padStart(2, '0');
            const s = String(secs % 60).padStart(2, '0');
            timerEl.textContent = `${m}:${s}`;
        }, 1000);
    }

    function showError(message) {
        errorBox.textContent = message;
        errorBox.classList.remove('hidden');
    }

    async function start() {
        try {
            localStream = await navigator.mediaDevices.getUserMedia({
                audio: true,
                video: wantVideo ? { width: 640, height: 480 } : false,
            });
        } catch (err) {
            showError('Could not access microphone/camera: ' + err.message + '. Check your browser permissions and try again.');
            return;
        }

        camBtn.classList.toggle('hidden', !wantVideo);

        const localTile = makeTile(CURRENT_USERNAME, true);
        attachStreamToTile(localTile, localStream, wantVideo);
        updateWaitingState();
        startTimer();

        ws = new WebSocket(CALL_WS_URL);

        ws.onmessage = function (event) {
            const msg = JSON.parse(event.data);

            if (msg.type === 'peers') {
                msg.peers.forEach(function (username) {
                    createPeerConnection(username, true);
                });
            } else if (msg.type === 'peer-left') {
                closePeerConnection(msg.username);
            } else if (msg.type === 'signal') {
                handleSignal(msg.from, msg.data);
            }
            // 'peer-joined' needs no action here - the newcomer initiates
            // the offer to us, we just wait for it via 'signal'.
        };

        ws.onclose = function () {
            leave();
        };
    }

    function leave() {
        Object.keys(peerConnections).forEach(closePeerConnection);

        if (localStream) {
            localStream.getTracks().forEach(function (track) { track.stop(); });
            localStream = null;
        }

        if (ws) {
            ws.onclose = null;
            ws.close();
            ws = null;
        }

        if (timerHandle) clearInterval(timerHandle);

        window.location.href = ROOM_URL;
    }

    function toggleMic() {
        if (!localStream) return;
        micOn = !micOn;
        localStream.getAudioTracks().forEach(function (t) { t.enabled = micOn; });
        micBtn.classList.toggle('active-off', !micOn);
    }

    function toggleCam() {
        if (!localStream || !wantVideo) return;
        camOn = !camOn;
        localStream.getVideoTracks().forEach(function (t) { t.enabled = camOn; });
        camBtn.classList.toggle('active-off', !camOn);
        const localTile = tiles[CURRENT_USERNAME];
        if (localTile) localTile.classList.toggle('audio-only', !camOn);
    }

    micBtn.addEventListener('click', toggleMic);
    camBtn.addEventListener('click', toggleCam);
    leaveBtn.addEventListener('click', leave);

    window.addEventListener('beforeunload', function () {
        if (ws) ws.close();
        if (localStream) localStream.getTracks().forEach(function (t) { t.stop(); });
    });

    start();
})();
