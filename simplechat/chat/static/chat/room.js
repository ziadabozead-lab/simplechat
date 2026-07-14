/* ==========================================================================
   SimpleChat — room.js
   ---------------------------------------------------------------------
   Matches the actual chat/views.py + chat/urls.py contract:

   - POST {{ SEND_URL }}         ("/send/")        body: text=...
        -> { "ok": true }                          (no message payload back,
                                                     so we re-poll after send)

   - GET  {{ MESSAGES_URL }}?after=<id>  ("/messages/")
        -> { "messages": [ { id, sender, type, time, is_me,
                              text?, audio_url?, audio_type? }, ... ] }

   - POST {{ SEND_VOICE_URL }}   ("/send-voice/")  FormData: audio=<blob>
        -> { "ok": true, "message": { same shape as above } }

   Requires these globals to already be defined in room.html's inline
   <script> block (SEND_VOICE_URL is already there; SEND_URL and
   MESSAGES_URL need to be added alongside it):
        const SEND_URL = "{% url 'send_message' %}";
        const MESSAGES_URL = "{% url 'get_messages' %}";
   ========================================================================== */

(function () {
    "use strict";

    /* ---------------------------------------------------------------- */
    /* Shared helpers                                                    */
    /* ---------------------------------------------------------------- */

    function getCookie(name) {
        const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
        return match ? decodeURIComponent(match[2]) : null;
    }

    const CSRF_TOKEN = getCookie('csrftoken');

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str == null ? '' : str;
        return div.innerHTML;
    }

    const chatBox = document.getElementById('chat-box');

    function scrollToBottom(smooth) {
        chatBox.scrollTo({ top: chatBox.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
    }

    /* ---------------------------------------------------------------- */
    /* Theme toggle (light / dark), persisted in localStorage           */
    /* ---------------------------------------------------------------- */

    (function initTheme() {
        const btn = document.getElementById('theme-toggle');
        if (!btn) return;
        const icon = btn.querySelector('.icon');
        const label = btn.querySelector('.label');

        function applyThemeUI(theme) {
            if (theme === 'dark') {
                icon.textContent = '☀️';
                label.textContent = 'Light';
            } else {
                icon.textContent = '🌙';
                label.textContent = 'Dark';
            }
        }

        applyThemeUI(document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light');

        btn.addEventListener('click', function () {
            const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
            const next = isDark ? 'light' : 'dark';
            if (next === 'dark') {
                document.documentElement.setAttribute('data-theme', 'dark');
            } else {
                document.documentElement.removeAttribute('data-theme');
            }
            localStorage.setItem('chat-theme', next);
            applyThemeUI(next);
        });
    })();

    /* ---------------------------------------------------------------- */
    /* Mobile sidebar drawer (only runs if #members-sidebar exists)      */
    /* ---------------------------------------------------------------- */

    (function initSidebar() {
        const sidebar = document.getElementById('members-sidebar');
        const topbarRight = document.querySelector('.topbar-right');
        if (!sidebar || !topbarRight) return;

        const toggleBtn = document.createElement('button');
        toggleBtn.id = 'sidebar-toggle';
        toggleBtn.type = 'button';
        toggleBtn.title = 'Members';
        toggleBtn.innerHTML = '<span>☰</span>';
        topbarRight.insertBefore(toggleBtn, topbarRight.firstChild);

        const overlay = document.createElement('div');
        overlay.id = 'sidebar-overlay';
        document.body.appendChild(overlay);

        function closeSidebar() {
            sidebar.classList.remove('open');
            overlay.classList.remove('visible');
        }

        toggleBtn.addEventListener('click', function () {
            sidebar.classList.toggle('open');
            overlay.classList.toggle('visible');
        });
        overlay.addEventListener('click', closeSidebar);

        window.addEventListener('resize', function () {
            if (window.innerWidth > 720) closeSidebar();
        });
    })();

    /* ---------------------------------------------------------------- */
    /* WhatsApp/Chrome WebM duration fix                                 */
    /* Chrome's MediaRecorder omits duration in the EBML header, so the  */
    /* <audio> element reports Infinity/NaN until we force a seek.       */
    /* ---------------------------------------------------------------- */

    function fixAudioDuration(audio) {
        if (!audio || audio.dataset.durationFixed) return;

        function trySeek() {
            if (isFinite(audio.duration) && audio.duration > 0) {
                audio.dataset.durationFixed = '1';
                return;
            }
            audio.currentTime = 1e101;
            audio.addEventListener('timeupdate', function onTimeUpdate() {
                audio.removeEventListener('timeupdate', onTimeUpdate);
                audio.currentTime = 0;
                audio.dataset.durationFixed = '1';
            }, { once: true });
        }

        if (audio.readyState >= 1) {
            trySeek();
        } else {
            audio.addEventListener('loadedmetadata', trySeek, { once: true });
        }
    }

    function fixAllVoiceNotes(scope) {
        (scope || document).querySelectorAll('audio.voice-note').forEach(fixAudioDuration);
    }

    /* ---------------------------------------------------------------- */
    /* Rendering a message bubble                                        */
    /* Matches _serialize_message() in views.py:                        */
    /*   { id, sender, type, time, is_me, text? , audio_url?, audio_type? } */
    /* ---------------------------------------------------------------- */

    function renderMessage(m) {
        const wrap = document.createElement('div');
        wrap.className = 'msg ' + (m.is_me ? 'me' : 'them');
        wrap.dataset.id = m.id;
        wrap.dataset.sender = m.sender;

        let inner = '';
        if (!m.is_me) {
            inner += '<div class="sender">' + escapeHtml(m.sender) + '</div>';
        }
        if (m.type === 'audio') {
            inner += '<audio class="voice-note" controls preload="metadata">'
                + '<source src="' + m.audio_url + '" type="' + (m.audio_type || 'audio/webm') + '">'
                + '</audio>';
            inner += '<div class="voice-error hidden"></div>';
        } else {
            inner += '<div class="text">' + escapeHtml(m.text) + '</div>';
        }
        inner += '<div class="time">' + escapeHtml(m.time) + '</div>';
        wrap.innerHTML = inner;

        chatBox.appendChild(wrap);
        if (m.type === 'audio') {
            fixAudioDuration(wrap.querySelector('audio.voice-note'));
        }
        return wrap;
    }

    /* ---------------------------------------------------------------- */
    /* Sending a text message                                            */
    /* send_message only returns {"ok": true}, so on success we          */
    /* immediately poll for anything newer than lastId to pick it up.    */
    /* ---------------------------------------------------------------- */

    let lastId = typeof LAST_ID !== 'undefined' ? LAST_ID : 0;
    let polling = false;

    function sendTextMessage(text) {
        return fetch(SEND_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': CSRF_TOKEN,
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: 'text=' + encodeURIComponent(text)
        })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (data && data.ok) {
                    pollForMessages();
                } else {
                    console.error('send_message rejected the message:', data);
                }
            })
            .catch(function (err) {
                console.error('Failed to send message:', err);
            });
    }

    const sendForm = document.getElementById('send-form');
    const textInput = document.getElementById('text-input');

    if (sendForm) {
        sendForm.addEventListener('submit', function (e) {
            e.preventDefault();
            const text = textInput.value.trim();
            if (!text) return;
            textInput.value = '';
            sendTextMessage(text);
        });
    }

    /* ---------------------------------------------------------------- */
    /* Polling for new messages                                          */
    /* ---------------------------------------------------------------- */

    function pollForMessages() {
        if (polling) return; // avoid overlapping requests
        polling = true;
        fetch(MESSAGES_URL + '?after=' + lastId, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (!data || !data.messages || !data.messages.length) return;
                const shouldScroll = chatBox.scrollTop + chatBox.clientHeight >= chatBox.scrollHeight - 40;
                data.messages.forEach(function (m) {
                    if (m.id <= lastId) return;
                    renderMessage(m);
                    lastId = Math.max(lastId, m.id);
                });
                if (shouldScroll) scrollToBottom(true);
            })
            .catch(function (err) {
                console.debug('Polling error:', err);
            })
            .finally(function () {
                polling = false;
            });
    }

    setInterval(pollForMessages, 3000);

    /* ---------------------------------------------------------------- */
    /* Voice recording                                                   */
    /* ---------------------------------------------------------------- */

    (function initVoiceRecording() {
        const micBtn = document.getElementById('mic-btn');
        const banner = document.getElementById('recording-banner');
        const timeLabel = document.getElementById('recording-time');
        const cancelBtn = document.getElementById('rec-cancel');
        const stopBtn = document.getElementById('rec-stop');

        if (!micBtn || !banner) return;

        let mediaRecorder = null;
        let chunks = [];
        let stream = null;
        let startTime = 0;
        let timerHandle = null;
        let cancelled = false;

        function formatTime(ms) {
            const totalSec = Math.floor(ms / 1000);
            const m = Math.floor(totalSec / 60);
            const s = totalSec % 60;
            return m + ':' + String(s).padStart(2, '0');
        }

        function updateTimer() {
            timeLabel.textContent = formatTime(Date.now() - startTime);
        }

        function showBanner() {
            banner.classList.remove('hidden');
            micBtn.classList.add('recording');
        }

        function hideBanner() {
            banner.classList.add('hidden');
            micBtn.classList.remove('recording');
            clearInterval(timerHandle);
        }

        async function startRecording() {
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                alert('Voice messages are not supported in this browser.');
                return;
            }
            try {
                stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            } catch (err) {
                alert('Microphone access was denied.');
                return;
            }

            chunks = [];
            cancelled = false;

            const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
                ? 'audio/webm;codecs=opus'
                : 'audio/webm';

            mediaRecorder = new MediaRecorder(stream, { mimeType: mimeType });

            mediaRecorder.addEventListener('dataavailable', function (e) {
                if (e.data && e.data.size > 0) chunks.push(e.data);
            });

            mediaRecorder.addEventListener('stop', function () {
                stream.getTracks().forEach(function (t) { t.stop(); });
                hideBanner();
                if (cancelled || chunks.length === 0) return;
                const blob = new Blob(chunks, { type: mimeType });
                uploadVoiceMessage(blob);
            });

            mediaRecorder.start();
            startTime = Date.now();
            showBanner();
            timeLabel.textContent = '0:00';
            timerHandle = setInterval(updateTimer, 250);
        }

        function stopRecording(shouldCancel) {
            if (!mediaRecorder || mediaRecorder.state === 'inactive') return;
            cancelled = !!shouldCancel;
            mediaRecorder.stop();
        }

        function uploadVoiceMessage(blob) {
            const formData = new FormData();
            formData.append('audio', blob, 'voice-message.webm');

            fetch(SEND_VOICE_URL, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': CSRF_TOKEN,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: formData
            })
                .then(function (res) { return res.json(); })
                .then(function (data) {
                    if (data && data.ok && data.message) {
                        lastId = Math.max(lastId, data.message.id);
                        renderMessage(data.message);
                        scrollToBottom(true);
                    } else if (data && data.error) {
                        console.error('Voice upload rejected:', data.error);
                    }
                })
                .catch(function (err) {
                    console.error('Failed to upload voice message:', err);
                });
        }

        micBtn.addEventListener('click', function () {
            if (mediaRecorder && mediaRecorder.state === 'recording') {
                stopRecording(false);
            } else {
                startRecording();
            }
        });

        if (cancelBtn) {
            cancelBtn.addEventListener('click', function () { stopRecording(true); });
        }
        if (stopBtn) {
            stopBtn.addEventListener('click', function () { stopRecording(false); });
        }
    })();

    /* ---------------------------------------------------------------- */
    /* Init                                                              */
    /* ---------------------------------------------------------------- */

    fixAllVoiceNotes(chatBox);
    scrollToBottom(false);
})();