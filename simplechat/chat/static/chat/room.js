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

    function renderPollOptionsHtml(m) {
        const poll = m.poll || { options: [], total_votes: 0, voted_option_id: null };
        let html = '<div class="poll-msg" data-poll-id="' + m.id + '" data-voted-option-id="' + (poll.voted_option_id || '') + '">';
        html += '<div class="poll-question">📊 ' + escapeHtml(m.question || m.text) + '</div>';
        html += '<div class="poll-options">';
        poll.options.forEach(function (opt) {
            const voted = opt.id === poll.voted_option_id ? ' voted' : '';
            html += '<button type="button" class="poll-option-row' + voted + '" data-option-id="' + opt.id + '">'
                + '<span class="poll-option-fill" style="width:' + opt.percent + '%"></span>'
                + '<span class="poll-option-label">' + escapeHtml(opt.text) + '</span>'
                + '<span class="poll-option-pct">' + opt.percent + '%</span>'
                + '</button>';
        });
        html += '</div>';
        html += '<div class="poll-total-votes">' + poll.total_votes + (poll.total_votes === 1 ? ' vote' : ' votes') + '</div>';
        html += '</div>';
        return html;
    }

    function updatePollDom(pollEl, poll) {
        pollEl.dataset.votedOptionId = poll.voted_option_id || '';
        poll.options.forEach(function (opt) {
            const row = pollEl.querySelector('.poll-option-row[data-option-id="' + opt.id + '"]');
            if (!row) return;
            row.classList.toggle('voted', opt.id === poll.voted_option_id);
            row.querySelector('.poll-option-fill').style.width = opt.percent + '%';
            row.querySelector('.poll-option-pct').textContent = opt.percent + '%';
        });
        const totalEl = pollEl.querySelector('.poll-total-votes');
        if (totalEl) totalEl.textContent = poll.total_votes + (poll.total_votes === 1 ? ' vote' : ' votes');
    }

    function renderMessage(m) {
        const wrap = document.createElement('div');
        wrap.className = 'msg ' + (m.is_me ? 'me' : 'them') + (m.is_deleted ? ' deleted' : '');
        wrap.dataset.id = m.id;
        wrap.dataset.sender = m.sender;
        wrap.dataset.type = m.type;
        wrap.dataset.canDelete = m.can_delete ? '1' : '0';
        wrap.dataset.canViewInfo = m.can_view_info ? '1' : '0';

        let inner = '';
        if (!m.is_me) {
            inner += '<div class="sender">' + escapeHtml(m.sender) + '</div>';
        }
        if (m.is_deleted) {
            inner += '<div class="text deleted-text">🚫 This message was deleted</div>';
        } else if (m.type === 'audio') {
            inner += '<audio class="voice-note" controls preload="metadata">'
                + '<source src="' + m.audio_url + '" type="' + (m.audio_type || 'audio/webm') + '">'
                + '</audio>';
            inner += '<div class="voice-error hidden"></div>';
        } else if (m.type === 'video') {
            inner += '<video class="video-note" controls preload="metadata" src="' + m.video_url + '"></video>';
        } else if (m.type === 'photo') {
            inner += '<img class="photo-msg" src="' + m.photo_url + '" alt="photo">';
        } else if (m.type === 'document') {
            inner += '<a class="doc-msg" href="' + m.document_url + '" download="' + escapeHtml(m.document_name) + '">'
                + '<span class="doc-icon">📄</span>'
                + '<span class="doc-name">' + escapeHtml(m.document_name) + '</span>'
                + '</a>';
        } else if (m.type === 'sticker') {
            inner += '<img class="sticker-img" src="' + m.sticker_url + '" alt="sticker">';
        } else if (m.type === 'poll') {
            inner += renderPollOptionsHtml(m);
        } else {
            inner += '<div class="text">' + escapeHtml(m.text) + '</div>';
        }
        inner += '<div class="time">' + escapeHtml(m.time) + '</div>';
        wrap.innerHTML = inner;

        chatBox.appendChild(wrap);
        if (m.type === 'audio') {
            fixAudioDuration(wrap.querySelector('audio.voice-note'));
        }
        observeForReadReceipt(wrap, m.is_me);
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
    /* Polling for member online/offline status                          */
    /* ---------------------------------------------------------------- */

    function pollForMembers() {
        if (typeof MEMBERS_URL === 'undefined') return;
        fetch(MEMBERS_URL, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (!data || !data.members) return;
                data.members.forEach(function (member) {
                    const li = document.querySelector(
                        '#members-list li[data-username="' + CSS.escape(member.username) + '"]'
                    );
                    if (!li) return;
                    const dot = li.querySelector('.status-dot');
                    if (!dot) return;
                    dot.classList.toggle('online', member.is_online);
                    dot.classList.toggle('offline', !member.is_online);
                });
            })
            .catch(function (err) {
                console.debug('Member polling error:', err);
            });
    }

    if (document.getElementById('members-list')) {
        setInterval(pollForMembers, 5000);
    }

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

        // Without a cap, a recording left running (e.g. the person locks
        // their phone or switches tabs mid-recording) just keeps capturing
        // audio in the background - MediaRecorder doesn't stop on its own.
        // Opus compresses near-silence to almost nothing, so the resulting
        // file can sail under MAX_VOICE_MESSAGE_BYTES while still being
        // 30+ minutes long. Auto-stopping (and sending what was captured
        // so far) puts a hard ceiling on that.
        const MAX_RECORDING_MS = 3 * 60 * 1000;

        function formatTime(ms) {
            const totalSec = Math.floor(ms / 1000);
            const m = Math.floor(totalSec / 60);
            const s = totalSec % 60;
            return m + ':' + String(s).padStart(2, '0');
        }

        function updateTimer() {
            const elapsed = Date.now() - startTime;
            timeLabel.textContent = formatTime(elapsed);
            if (elapsed >= MAX_RECORDING_MS) {
                stopRecording(false);
            }
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

        // Backgrounding the tab (switching apps, locking the phone) mid
        // recording is almost never intentional, and letting it keep
        // capturing audio the person isn't aware of is both a privacy
        // problem and exactly what produced the 33-minute clip this was
        // added to fix. Discard rather than send, since a recording made
        // while the person wasn't looking at the screen isn't one they
        // meant to send.
        document.addEventListener('visibilitychange', function () {
            if (document.hidden && mediaRecorder && mediaRecorder.state === 'recording') {
                stopRecording(true);
            }
        });
    })();

    /* ---------------------------------------------------------------- */
    /* Generic "upload a file to an endpoint, render what comes back"    */
    /* helper - used by every attach-menu option below.                 */
    /* ---------------------------------------------------------------- */

    function uploadFile(url, fieldName, file, errorPrefix) {
        const formData = new FormData();
        formData.append(fieldName, file);

        fetch(url, {
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
                    alert(data.error);
                }
            })
            .catch(function (err) {
                console.error(errorPrefix + ':', err);
            });
    }

    /* ---------------------------------------------------------------- */
    /* Attach menu ("+" button) - WhatsApp-style popup with Document,    */
    /* Photos & videos, Camera, Audio, and a shortcut into the sticker   */
    /* picker. Each option just clicks its matching hidden <input>,      */
    /* except "New sticker" which opens the sticker picker instead.      */
    /* ---------------------------------------------------------------- */

    (function initAttachMenu() {
        const attachBtn = document.getElementById('attach-btn');
        const menu = document.getElementById('attach-menu');
        if (!attachBtn || !menu) return;

        const videoInput = document.getElementById('video-input');
        const cameraInput = document.getElementById('camera-input');
        const audioFileInput = document.getElementById('audio-file-input');
        const documentInput = document.getElementById('document-input');
        const stickerPicker = document.getElementById('sticker-picker');
        const stickerOption = document.getElementById('attach-sticker-option');

        function closeMenu() {
            menu.classList.add('hidden');
            attachBtn.classList.remove('open');
        }

        attachBtn.addEventListener('click', function () {
            menu.classList.toggle('hidden');
            attachBtn.classList.toggle('open', !menu.classList.contains('hidden'));
        });

        menu.querySelectorAll('.attach-option[data-target]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                closeMenu();
                const input = document.getElementById(btn.dataset.target);
                if (input) input.click();
            });
        });

        if (stickerOption && stickerPicker) {
            stickerOption.addEventListener('click', function (e) {
                e.stopPropagation(); // don't let this reach sticker-picker's outside-click handler
                closeMenu();
                stickerPicker.classList.remove('hidden');
            });
        }

        // "Photos & videos" and "Camera" share one input type (image or
        // video); route to send-photo or send-video based on what the
        // picked file actually is.
        function handleMediaPick(input) {
            input.addEventListener('change', function () {
                const file = input.files && input.files[0];
                input.value = '';
                if (!file) return;

                if (file.type.startsWith('image/')) {
                    uploadFile(SEND_PHOTO_URL, 'photo', file, 'Failed to upload photo');
                } else if (file.type.startsWith('video/')) {
                    uploadFile(SEND_VIDEO_URL, 'video', file, 'Failed to upload video');
                } else {
                    alert('Please choose a photo or video file.');
                }
            });
        }

        if (videoInput) handleMediaPick(videoInput);
        if (cameraInput) handleMediaPick(cameraInput);

        if (audioFileInput) {
            audioFileInput.addEventListener('change', function () {
                const file = audioFileInput.files && audioFileInput.files[0];
                audioFileInput.value = '';
                if (!file) return;
                // send_voice already accepts any file with an allowed
                // audio mime type, regardless of whether it came from
                // the mic recorder or a plain file picker.
                uploadFile(SEND_VOICE_URL, 'audio', file, 'Failed to upload audio file');
            });
        }

        if (documentInput) {
            documentInput.addEventListener('change', function () {
                const file = documentInput.files && documentInput.files[0];
                documentInput.value = '';
                if (!file) return;
                uploadFile(SEND_DOCUMENT_URL, 'document', file, 'Failed to upload document');
            });
        }

        // Close the menu if you tap/click elsewhere
        document.addEventListener('click', function (e) {
            if (menu.classList.contains('hidden')) return;
            if (menu.contains(e.target) || attachBtn.contains(e.target)) return;
            closeMenu();
        });
    })();

    /* ---------------------------------------------------------------- */
    /* Sticker picker                                                    */
    /* ---------------------------------------------------------------- */

    (function initStickers() {
        const stickerBtn = document.getElementById('sticker-btn');
        const picker = document.getElementById('sticker-picker');
        const createBtn = document.getElementById('create-sticker-btn');
        const createInput = document.getElementById('create-sticker-input');
        if (!stickerBtn || !picker) return;

        stickerBtn.addEventListener('click', function () {
            picker.classList.toggle('hidden');
        });

        function sendSticker(params) {
            picker.classList.add('hidden');
            fetch(SEND_STICKER_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-CSRFToken': CSRF_TOKEN,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: params
            })
                .then(function (res) { return res.json(); })
                .then(function (data) {
                    if (data && data.ok && data.message) {
                        lastId = Math.max(lastId, data.message.id);
                        renderMessage(data.message);
                        scrollToBottom(true);
                    } else if (data && data.error) {
                        alert(data.error);
                    }
                })
                .catch(function (err) {
                    console.error('Failed to send sticker:', err);
                });
        }

        // Delegated click - covers built-in stickers rendered on load AND
        // custom ones (server-rendered or added dynamically after upload).
        picker.addEventListener('click', function (e) {
            const btn = e.target.closest('.sticker-option');
            if (!btn || btn === createBtn) return;

            if (btn.dataset.customStickerId) {
                sendSticker('custom_sticker_id=' + encodeURIComponent(btn.dataset.customStickerId));
            } else if (btn.dataset.sticker) {
                sendSticker('sticker=' + encodeURIComponent(btn.dataset.sticker));
            }
        });

        // "+" tile - upload an image to turn it into a new sticker anyone
        // in the room can then pick, including yourself, right away.
        if (createBtn && createInput) {
            createBtn.addEventListener('click', function () {
                createInput.click();
            });

            createInput.addEventListener('change', function () {
                const file = createInput.files && createInput.files[0];
                createInput.value = '';
                if (!file) return;

                const formData = new FormData();
                formData.append('image', file);

                fetch(CREATE_STICKER_URL, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': CSRF_TOKEN, 'X-Requested-With': 'XMLHttpRequest' },
                    body: formData
                })
                    .then(function (res) { return res.json(); })
                    .then(function (data) {
                        if (data && data.ok && data.sticker) {
                            const btn = document.createElement('button');
                            btn.type = 'button';
                            btn.className = 'sticker-option';
                            btn.dataset.customStickerId = data.sticker.id;
                            btn.innerHTML = '<img src="' + data.sticker.url + '" alt="custom sticker">';
                            picker.insertBefore(btn, createBtn);
                        } else if (data && data.error) {
                            alert(data.error);
                        }
                    })
                    .catch(function (err) {
                        console.error('Failed to create sticker:', err);
                    });
            });
        }

        // Close the picker if you tap/click elsewhere
        document.addEventListener('click', function (e) {
            if (picker.classList.contains('hidden')) return;
            if (picker.contains(e.target) || stickerBtn.contains(e.target)) return;
            picker.classList.add('hidden');
        });
    })();

    /* ---------------------------------------------------------------- */
    /* Read receipts: mark a message read once it actually scrolls into */
    /* view (not just because it was fetched/delivered).                */
    /*                                                                  */
    /* Previously this fired one POST per message the instant it        */
    /* intersected - fine for messages arriving one at a time while     */
    /* chatting, but on page load the observer can see a whole screen's */
    /* worth of messages become visible in the same tick, which fired   */
    /* a burst of concurrent requests and produced SQLite "database is  */
    /* locked" errors server-side. Instead, ids are queued and flushed  */
    /* together in one request after a short quiet period.              */
    /* ---------------------------------------------------------------- */

    const pendingReadIds = new Set();
    let readFlushTimer = null;

    function flushReadReceipts() {
        readFlushTimer = null;
        if (pendingReadIds.size === 0 || typeof MARK_READ_BULK_URL === 'undefined') return;
        const ids = Array.from(pendingReadIds);
        pendingReadIds.clear();
        const params = new URLSearchParams();
        ids.forEach(function (id) { params.append('message_ids', id); });
        fetch(MARK_READ_BULK_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': CSRF_TOKEN,
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: params.toString()
        }).catch(function () { /* non-critical, ignore */ });
    }

    function queueReadReceipt(id) {
        if (!id) return;
        pendingReadIds.add(id);
        // Debounce: each new id arriving resets the timer, so a burst of
        // messages becoming visible together (page load, fast scroll)
        // collapses into a single request once things settle down.
        if (readFlushTimer) clearTimeout(readFlushTimer);
        readFlushTimer = setTimeout(flushReadReceipts, 300);
    }

    const readObserver = ('IntersectionObserver' in window)
        ? new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (!entry.isIntersecting) return;
                const el = entry.target;
                readObserver.unobserve(el);
                queueReadReceipt(el.dataset.id);
            });
        }, { root: chatBox, threshold: 0.1 })
        : null;

    function observeForReadReceipt(wrap, isMe) {
        if (!readObserver || isMe) return;
        readObserver.observe(wrap);
    }

    /* ---------------------------------------------------------------- */
    /* "Played" tracking - fires once per <audio>/<video>, on first play.*/
    /* The 'play' event doesn't bubble, so this listens on the capture   */
    /* phase at chatBox to catch it from any descendant media element.   */
    /* ---------------------------------------------------------------- */

    chatBox.addEventListener('play', function (e) {
        const media = e.target;
        if (!media || (media.tagName !== 'AUDIO' && media.tagName !== 'VIDEO') || media.dataset.playedTracked) return;
        const wrap = media.closest('.msg');
        if (!wrap || wrap.classList.contains('me')) return;
        media.dataset.playedTracked = '1';
        const id = wrap.dataset.id;
        if (!id || typeof MARK_PLAYED_URL_TEMPLATE === 'undefined') return;
        fetch(MARK_PLAYED_URL_TEMPLATE.replace('0', id), {
            method: 'POST',
            headers: { 'X-CSRFToken': CSRF_TOKEN, 'X-Requested-With': 'XMLHttpRequest' }
        }).catch(function () { /* non-critical, ignore */ });
    }, true);


    /* ---------------------------------------------------------------- */
    /* Long-press (touch) / right-click (desktop) message action menu.   */
    /* Delete (own messages, or any message if staff) and Message info   */
    /* (sender or staff) - matches the WhatsApp long-press pattern.      */
    /* ---------------------------------------------------------------- */

    (function initMessageMenu() {
        const menu = document.getElementById('message-menu');
        const overlay = document.getElementById('message-menu-overlay');
        const infoBtn = document.getElementById('message-menu-info');
        const deleteBtn = document.getElementById('message-menu-delete');
        if (!menu || !overlay) return;

        let activeMessageEl = null;
        let pressTimer = null;

        function closeMenu() {
            menu.classList.add('hidden');
            overlay.classList.remove('visible');
            activeMessageEl = null;
        }

        function openMenuFor(msgEl, clientX, clientY) {
            if (msgEl.classList.contains('deleted')) return; // nothing to do on a tombstone
            activeMessageEl = msgEl;
            const canDelete = msgEl.dataset.canDelete === '1';
            const canViewInfo = msgEl.dataset.canViewInfo === '1';
            if (!canDelete && !canViewInfo) return;

            infoBtn.style.display = canViewInfo ? '' : 'none';
            deleteBtn.style.display = canDelete ? '' : 'none';

            menu.classList.remove('hidden');
            overlay.classList.add('visible');

            // Keep the menu on-screen near the tap/click point.
            const menuWidth = 190;
            const menuHeight = 100;
            let left = clientX;
            let top = clientY;
            if (left + menuWidth > window.innerWidth) left = window.innerWidth - menuWidth - 12;
            if (top + menuHeight > window.innerHeight) top = window.innerHeight - menuHeight - 12;
            menu.style.left = Math.max(12, left) + 'px';
            menu.style.top = Math.max(12, top) + 'px';
        }

        overlay.addEventListener('click', closeMenu);

        // Desktop: right-click
        chatBox.addEventListener('contextmenu', function (e) {
            const msgEl = e.target.closest('.msg');
            if (!msgEl) return;
            e.preventDefault();
            openMenuFor(msgEl, e.clientX, e.clientY);
        });

        // Mobile: long-press via touch timer
        chatBox.addEventListener('touchstart', function (e) {
            const msgEl = e.target.closest('.msg');
            if (!msgEl) return;
            const touch = e.touches[0];
            pressTimer = setTimeout(function () {
                openMenuFor(msgEl, touch.clientX, touch.clientY);
            }, 550);
        }, { passive: true });

        ['touchend', 'touchmove', 'touchcancel'].forEach(function (evt) {
            chatBox.addEventListener(evt, function () {
                clearTimeout(pressTimer);
            }, { passive: true });
        });

        if (deleteBtn) {
            deleteBtn.addEventListener('click', function () {
                if (!activeMessageEl) return;
                const id = activeMessageEl.dataset.id;
                closeMenu();
                if (!confirm('Delete this message?')) return;

                fetch(DELETE_URL_TEMPLATE.replace('0', id), {
                    method: 'POST',
                    headers: { 'X-CSRFToken': CSRF_TOKEN, 'X-Requested-With': 'XMLHttpRequest' }
                })
                    .then(function (res) { return res.json(); })
                    .then(function (data) {
                        if (!data || !data.ok) {
                            if (data && data.error) alert(data.error);
                            return;
                        }
                        const el = chatBox.querySelector('.msg[data-id="' + id + '"]');
                        if (!el) return;
                        el.classList.add('deleted');
                        el.dataset.canDelete = '0';
                        const contentEls = el.querySelectorAll(
                            '.text, .voice-note, .voice-error, .video-note, .photo-msg, .doc-msg, .sticker-img, .poll-msg'
                        );
                        contentEls.forEach(function (n) { n.remove(); });
                        const timeEl = el.querySelector('.time');
                        const tomb = document.createElement('div');
                        tomb.className = 'text deleted-text';
                        tomb.textContent = '🚫 This message was deleted';
                        el.insertBefore(tomb, timeEl);
                    })
                    .catch(function (err) { console.error('Failed to delete message:', err); });
            });
        }

        if (infoBtn) {
            infoBtn.addEventListener('click', function () {
                if (!activeMessageEl) return;
                const id = activeMessageEl.dataset.id;
                closeMenu();
                openMessageInfo(id);
            });
        }
    })();

    /* ---------------------------------------------------------------- */
    /* Message info panel (delivered / read / played breakdown)          */
    /* ---------------------------------------------------------------- */

    function renderMemberList(listEl, members, key) {
        listEl.innerHTML = '';
        const present = members.filter(function (m) { return m[key]; });
        if (!present.length) {
            const li = document.createElement('li');
            li.className = 'info-empty';
            li.textContent = 'No one yet';
            listEl.appendChild(li);
            return;
        }
        present.forEach(function (m) {
            const li = document.createElement('li');
            li.innerHTML = '<span class="info-check">✓</span> ' + escapeHtml(m.username);
            listEl.appendChild(li);
        });
    }

    function openMessageInfo(id) {
        const panel = document.getElementById('message-info-panel');
        const overlay = document.getElementById('info-panel-overlay');
        if (!panel || !overlay) return;

        fetch(MESSAGE_INFO_URL_TEMPLATE.replace('0', id))
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (!data || !data.ok) {
                    if (data && data.error) alert(data.error);
                    return;
                }
                renderMemberList(document.getElementById('info-read-list'), data.members, 'read');
                renderMemberList(document.getElementById('info-delivered-list'), data.members, 'delivered');
                const playedSection = document.getElementById('info-played-section');
                if (data.show_played) {
                    playedSection.classList.remove('hidden');
                    renderMemberList(document.getElementById('info-played-list'), data.members, 'played');
                } else {
                    playedSection.classList.add('hidden');
                }
                panel.classList.remove('hidden');
                overlay.classList.add('visible');
            })
            .catch(function (err) { console.error('Failed to load message info:', err); });
    }

    (function initInfoPanelClose() {
        const panel = document.getElementById('message-info-panel');
        const overlay = document.getElementById('info-panel-overlay');
        const closeBtn = document.getElementById('info-panel-close');
        if (!panel || !overlay) return;

        function close() {
            panel.classList.add('hidden');
            overlay.classList.remove('visible');
        }
        if (closeBtn) closeBtn.addEventListener('click', close);
        overlay.addEventListener('click', close);
    })();

    /* ---------------------------------------------------------------- */
    /* Poll voting - delegated click on any .poll-option-row, whether it */
    /* was server-rendered on load or added dynamically afterwards.      */
    /* ---------------------------------------------------------------- */

    chatBox.addEventListener('click', function (e) {
        const row = e.target.closest('.poll-option-row');
        if (!row) return;
        const pollEl = row.closest('.poll-msg');
        if (!pollEl) return;
        const pollId = pollEl.dataset.pollId;
        const optionId = row.dataset.optionId;

        fetch(VOTE_URL_TEMPLATE.replace('0', pollId), {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': CSRF_TOKEN,
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: 'option_id=' + encodeURIComponent(optionId)
        })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (data && data.ok && data.message && data.message.poll) {
                    updatePollDom(pollEl, data.message.poll);
                } else if (data && data.error) {
                    alert(data.error);
                }
            })
            .catch(function (err) { console.error('Failed to vote:', err); });
    });

    /* ---------------------------------------------------------------- */
    /* Poll creation panel, opened from the attach menu                  */
    /* ---------------------------------------------------------------- */

    (function initPollCompose() {
        const pollOption = document.getElementById('attach-poll-option');
        const panel = document.getElementById('poll-compose');
        if (!pollOption || !panel) return;

        const questionInput = document.getElementById('poll-question');
        const rowsWrap = document.getElementById('poll-option-rows');
        const addBtn = document.getElementById('poll-add-option');
        const cancelBtn = document.getElementById('poll-cancel');
        const createBtn = document.getElementById('poll-create');

        function resetPanel() {
            questionInput.value = '';
            rowsWrap.innerHTML =
                '<div class="poll-option-input-row"><input type="text" class="poll-option-input" placeholder="Option 1" maxlength="100"></div>'
                + '<div class="poll-option-input-row"><input type="text" class="poll-option-input" placeholder="Option 2" maxlength="100"></div>';
        }

        pollOption.addEventListener('click', function () {
            const attachMenu = document.getElementById('attach-menu');
            if (attachMenu) attachMenu.classList.add('hidden');
            const attachBtn = document.getElementById('attach-btn');
            if (attachBtn) attachBtn.classList.remove('open');
            resetPanel();
            panel.classList.remove('hidden');
            questionInput.focus();
        });

        if (cancelBtn) {
            cancelBtn.addEventListener('click', function () {
                panel.classList.add('hidden');
            });
        }

        if (addBtn) {
            addBtn.addEventListener('click', function () {
                const count = rowsWrap.querySelectorAll('.poll-option-input').length;
                if (count >= 10) return;
                const row = document.createElement('div');
                row.className = 'poll-option-input-row';
                row.innerHTML = '<input type="text" class="poll-option-input" placeholder="Option ' + (count + 1) + '" maxlength="100">';
                rowsWrap.appendChild(row);
            });
        }

        if (createBtn) {
            createBtn.addEventListener('click', function () {
                const question = questionInput.value.trim();
                const options = Array.from(rowsWrap.querySelectorAll('.poll-option-input'))
                    .map(function (inp) { return inp.value.trim(); })
                    .filter(Boolean);

                if (!question) { alert('Please enter a question.'); return; }
                if (options.length < 2) { alert('Please enter at least 2 options.'); return; }

                const params = new URLSearchParams();
                params.append('question', question);
                options.forEach(function (o) { params.append('options', o); });

                fetch(SEND_POLL_URL, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'X-CSRFToken': CSRF_TOKEN,
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: params.toString()
                })
                    .then(function (res) { return res.json(); })
                    .then(function (data) {
                        if (data && data.ok && data.message) {
                            panel.classList.add('hidden');
                            lastId = Math.max(lastId, data.message.id);
                            renderMessage(data.message);
                            scrollToBottom(true);
                        } else if (data && data.error) {
                            alert(data.error);
                        }
                    })
                    .catch(function (err) { console.error('Failed to create poll:', err); });
            });
        }
    })();

    /* ---------------------------------------------------------------- */
    /* Init                                                              */
    /* ---------------------------------------------------------------- */

    fixAllVoiceNotes(chatBox);
    // Wire up read-receipt tracking for the messages that were already
    // in the page on load (renderMessage() only covers ones added later).
    chatBox.querySelectorAll('.msg:not(.me)').forEach(function (el) {
        observeForReadReceipt(el, false);
    });
    scrollToBottom(false);

    // Flush any still-pending (debounced) read receipts before the page
    // goes away, using sendBeacon since a plain fetch() can get cancelled
    // mid-flight during unload.
    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState !== 'hidden') return;
        if (pendingReadIds.size === 0 || typeof MARK_READ_BULK_URL === 'undefined') return;
        if (readFlushTimer) { clearTimeout(readFlushTimer); readFlushTimer = null; }
        const params = new URLSearchParams();
        pendingReadIds.forEach(function (id) { params.append('message_ids', id); });
        pendingReadIds.clear();
        if (navigator.sendBeacon) {
            // sendBeacon can't set custom headers, so the CSRF token has
            // to travel as a normal POST field here instead of the
            // X-CSRFToken header the fetch() path above uses.
            params.append('csrfmiddlewaretoken', CSRF_TOKEN);
            const blob = new Blob([params.toString()], { type: 'application/x-www-form-urlencoded' });
            navigator.sendBeacon(MARK_READ_BULK_URL, blob);
        }
    });
})();