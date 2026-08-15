(function () {
    'use strict';

    // Public STUN only. This is enough for most home/office networks to
    // find a direct path, but some networks (symmetric NAT, locked-down
    // corporate wifi) need a TURN relay to connect at all. If calls fail
    // to connect for some people, add a TURN server here, e.g.:
    //   { urls: 'turn:your-turn-host:3478', username: '...', credential: '...' }
    const ICE_SERVERS = [
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: 'stun:stun1.l.google.com:19302' },
    ];

    const overlay = document.getElementById('call-overlay');
    const statusText = document.getElementById('call-status-text');
    const grid = document.getElementById('call-video-grid');
    const micBtn = document.getElementById('call-toggle-mic');
    const camBtn = document.getElementById('call-toggle-cam');
    const hangupBtn = document.getElementById('call-hangup');
    const voiceBtn = document.getElementById('call-voice-btn');
    const videoBtn = document.getElementById('call-video-btn');
    const banner = document.getElementById('call-banner');
    const bannerText = document.getElementById('call-banner-text');
    const bannerJoin = document.getElementById('call-banner-join');

    if (!overlay || typeof CALL_WS_URL === 'undefined') return;

    let ws = null;
    let localStream = null;
    let inCall = false;
    let wantVideo = false;
    let micOn = true;
    let camOn = true;
    const peerConnections = {};   // username -> RTCPeerConnection
    const remoteTiles = {};       // username -> tile <div>

    function setStatus(text) {
        statusText.textContent = text;
    }

    function makeTile(username, isLocal) {
        const tile = document.createElement('div');
        tile.className = 'call-tile';
        tile.dataset.username = username;

        const video = document.createElement('video');
        video.autoplay = true;
        video.playsInline = true;
        if (isLocal) video.muted = true;
        tile.appendChild(video);

        const label = document.createElement('span');
        label.className = 'call-tile-label';
        label.textContent = isLocal ? `${username} (you)` : username;
        tile.appendChild(label);

        grid.appendChild(tile);
        return tile;
    }

    function attachStreamToTile(tile, stream, hasVideo) {
        const video = tile.querySelector('video');
        video.srcObject = stream;
        tile.classList.toggle('audio-only', !hasVideo);
    }

    function removeTile(username) {
        const tile = remoteTiles[username];
        if (tile) {
            tile.remove();
            delete remoteTiles[username];
        }
    }

    function closePeerConnection(username) {
        const pc = peerConnections[username];
        if (pc) {
            pc.close();
            delete peerConnections[username];
        }
        removeTile(username);
    }

    function sendSignal(to, data) {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'signal', to: to, data: data }));
        }
    }

    function createPeerConnection(username, initiator) {
        const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
        peerConnections[username] = pc;

        localStream.getTracks().forEach(function (track) {
            pc.addTrack(track, localStream);
        });

        pc.onicecandidate = function (event) {
            if (event.candidate) {
                sendSignal(username, { candidate: event.candidate });
            }
        };

        pc.ontrack = function (event) {
            let tile = remoteTiles[username];
            if (!tile) {
                tile = makeTile(username, false);
                remoteTiles[username] = tile;
            }
            attachStreamToTile(tile, event.streams[0], event.track.kind === 'video' || wantVideo);
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

    function openOverlay() {
        overlay.classList.remove('hidden');
        banner.classList.add('hidden');
    }

    function closeOverlay() {
        overlay.classList.add('hidden');
        grid.innerHTML = '';
    }

    async function startCall(video) {
        if (inCall) return;
        wantVideo = video;

        try {
            localStream = await navigator.mediaDevices.getUserMedia({
                audio: true,
                video: video ? { width: 640, height: 480 } : false,
            });
        } catch (err) {
            alert('Could not access microphone/camera: ' + err.message);
            return;
        }

        inCall = true;
        micOn = true;
        camOn = video;
        micBtn.classList.remove('active-off');
        camBtn.classList.toggle('hidden', !video);
        openOverlay();
        setStatus('Connecting…');

        const localTile = makeTile(CURRENT_USERNAME, true);
        attachStreamToTile(localTile, localStream, video);

        ws = new WebSocket(CALL_WS_URL);

        ws.onopen = function () {
            setStatus('On the call');
        };

        ws.onmessage = function (event) {
            const msg = JSON.parse(event.data);

            if (msg.type === 'peers') {
                msg.peers.forEach(function (username) {
                    createPeerConnection(username, true);
                });
                setStatus(msg.peers.length ? 'On the call' : 'Waiting for others to join…');
            } else if (msg.type === 'peer-joined') {
                setStatus('On the call');
                // The newcomer initiates the offer to us; nothing to do here.
            } else if (msg.type === 'peer-left') {
                closePeerConnection(msg.username);
            } else if (msg.type === 'signal') {
                handleSignal(msg.from, msg.data);
            }
        };

        ws.onclose = function () {
            if (inCall) endCall();
        };
    }

    function endCall() {
        inCall = false;

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

        closeOverlay();
        pollCallStatus();
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
    }

    // --- "someone's on a call" banner, polled like the rest of the app ---

    function pollCallStatus() {
        if (inCall) return;
        fetch(CALL_STATUS_URL, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                const others = data.participants.filter(function (u) { return u !== CURRENT_USERNAME; });
                if (others.length) {
                    bannerText.textContent = others.length === 1
                        ? `${others[0]} is on a call`
                        : `${others.length} people are on a call`;
                    banner.classList.remove('hidden');
                } else {
                    banner.classList.add('hidden');
                }
            })
            .catch(function () { /* ignore transient errors */ });
    }

    voiceBtn.addEventListener('click', function () { startCall(false); });
    videoBtn.addEventListener('click', function () { startCall(true); });
    bannerJoin.addEventListener('click', function () { startCall(true); });
    hangupBtn.addEventListener('click', endCall);
    micBtn.addEventListener('click', toggleMic);
    camBtn.addEventListener('click', toggleCam);

    window.addEventListener('beforeunload', function () {
        if (inCall) endCall();
    });

    pollCallStatus();
    setInterval(pollCallStatus, 5000);
})();
