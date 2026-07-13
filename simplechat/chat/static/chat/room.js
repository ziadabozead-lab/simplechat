const chatBox = document.getElementById('chat-box');
const form = document.getElementById('send-form');
const input = document.getElementById('text-input');
const themeToggle = document.getElementById('theme-toggle');
let lastId = LAST_ID;

// ---- Theme toggle ----
// (The <html> element may already carry data-theme="dark" from the
// inline anti-flash script in the template; this just keeps the
// button in sync and handles clicks.)
const themeIcon = themeToggle.querySelector('.icon');
const themeLabel = themeToggle.querySelector('.label');

function setToggleUI(isDark) {
    themeIcon.textContent = isDark ? '☀️' : '🌙';
    themeLabel.textContent = isDark ? 'Light' : 'Dark';
}

setToggleUI(document.documentElement.getAttribute('data-theme') === 'dark');

themeToggle.addEventListener('click', () => {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    if (isDark) {
        document.documentElement.removeAttribute('data-theme');
        localStorage.setItem('chat-theme', 'light');
        setToggleUI(false);
    } else {
        document.documentElement.setAttribute('data-theme', 'dark');
        localStorage.setItem('chat-theme', 'dark');
        setToggleUI(true);
    }
});

// ---- Nametag colors ----
// Deterministic color per username, so each person keeps the same tag color.
function nameColor(name) {
    let hash = 0;
    for (let i = 0; i < name.length; i++) {
        hash = name.charCodeAt(i) + ((hash << 5) - hash);
    }
    const hue = Math.abs(hash) % 360;
    return `hsl(${hue}, 65%, 38%)`;
}

// Color the sender tags already rendered by Django.
document.querySelectorAll('.msg.them .sender').forEach(el => {
    el.style.color = nameColor(el.textContent);
});

// ---- Chat scroll + rendering ----
function scrollToBottom() {
    chatBox.scrollTop = chatBox.scrollHeight;
}
scrollToBottom();

function appendMessage(m) {
    const div = document.createElement('div');
    div.className = 'msg ' + (m.is_me ? 'me' : 'them');
    div.dataset.id = m.id;
    let html = '';
    if (!m.is_me) html += '<div class="sender"></div>';
    html += '<div class="text"></div><div class="time"></div>';
    div.innerHTML = html;
    if (!m.is_me) {
        const senderEl = div.querySelector('.sender');
        senderEl.textContent = m.sender;
        senderEl.style.color = nameColor(m.sender);
    }
    div.querySelector('.text').textContent = m.text;
    div.querySelector('.time').textContent = m.time;
    chatBox.appendChild(div);
}

// ---- Polling ----
async function poll() {
    const res = await fetch(`/messages/?after=${lastId}`);
    if (res.redirected || res.url.includes('/login/')) {
        window.location.href = LOGIN_URL;
        return;
    }
    const data = await res.json();
    if (data.messages && data.messages.length) {
        data.messages.forEach(m => { appendMessage(m); lastId = m.id; });
        scrollToBottom();
    }
}

setInterval(poll, 2000);

// ---- Sending ----
form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;
    const res = await fetch('/send/', {
        method: 'POST',
        headers: {'X-CSRFToken': csrf, 'Content-Type': 'application/x-www-form-urlencoded'},
        body: 'text=' + encodeURIComponent(text),
    });
    if (res.redirected || res.url.includes('/login/')) {
        window.location.href = LOGIN_URL;
        return;
    }
    poll();
});