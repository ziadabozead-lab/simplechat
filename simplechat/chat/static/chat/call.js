(function () {
    'use strict';

    // This file runs on the chat room page only. It does NOT touch
    // WebRTC/microphone/camera - it just shows a "someone's on a call"
    // banner (polled like the rest of the app) and sends people to the
    // dedicated call page. All the actual call logic lives in
    // call_room.js, loaded on chat/call.html.

    const voiceBtn = document.getElementById('call-voice-btn');
    const videoBtn = document.getElementById('call-video-btn');
    const banner = document.getElementById('call-banner');
    const bannerText = document.getElementById('call-banner-text');
    const bannerJoin = document.getElementById('call-banner-join');

    if (typeof CALL_ROOM_URL === 'undefined') return;

    function goToCall(video) {
        window.location.href = CALL_ROOM_URL + '?video=' + (video ? '1' : '0');
    }

    function pollCallStatus() {
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

    if (voiceBtn) voiceBtn.addEventListener('click', function () { goToCall(false); });
    if (videoBtn) videoBtn.addEventListener('click', function () { goToCall(true); });
    if (bannerJoin) bannerJoin.addEventListener('click', function () { goToCall(true); });

    pollCallStatus();
    setInterval(pollCallStatus, 5000);
})();
