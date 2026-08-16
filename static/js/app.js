/* HarmonyBot - application wiring. */

import { fetchHealth, streamChat } from './api.js';
import { Store } from './store.js';
import { $, confirmDialog, copyText, downloadFile, icon, relativeTime, toast } from './ui.js';

const store = new Store();
let controller = null;      // AbortController for the in-flight reply
let pinned = true;          // is the view stuck to the bottom of the scroll?

const els = {
    chat: $('chat'), scroll: $('chat-scroll'), welcome: $('welcome'),
    form: $('composer'), input: $('composer-input'), send: $('send'), stop: $('stop'),
    counter: $('counter'), jump: $('jump-btn'), title: $('chat-title'),
    chip: $('domain-chip'), history: $('history'), search: $('search'),
    sidebar: $('sidebar'), scrim: $('scrim'), menu: $('menu-toggle'),
    conn: $('conn'), statusSummary: $('status-summary'),
};

/* ══════════════════════ Theme ══════════════════════ */

function applyTheme(choice) {
    const dark = choice === 'dark' ||
        (choice === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';

    for (const btn of document.querySelectorAll('[data-theme-value]')) {
        btn.setAttribute('aria-checked', String(btn.dataset.themeValue === choice));
    }
    try { localStorage.setItem('hb-theme', choice); } catch { /* private mode */ }
}

function initTheme() {
    let choice = 'system';
    try { choice = localStorage.getItem('hb-theme') ?? 'system'; } catch { /* ignore */ }
    applyTheme(choice);

    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
        let current = 'system';
        try { current = localStorage.getItem('hb-theme') ?? 'system'; } catch { /* ignore */ }
        if (current === 'system') applyTheme('system');
    });

    for (const btn of document.querySelectorAll('[data-theme-value]')) {
        btn.addEventListener('click', () => applyTheme(btn.dataset.themeValue));
    }
}

/* ══════════════════════ Scrolling ══════════════════════ */

/* Only auto-scroll when the reader is already at the bottom. v2 forced the
   view down on every token, which yanked the page away mid-read. */
function isAtBottom(slack = 80) {
    const { scrollTop, scrollHeight, clientHeight } = els.scroll;
    return scrollHeight - scrollTop - clientHeight < slack;
}

function scrollToBottom(behavior = 'smooth') {
    els.scroll.scrollTo({ top: els.scroll.scrollHeight, behavior });
    pinned = true;
    els.jump.hidden = true;
}

els.scroll.addEventListener('scroll', () => {
    pinned = isAtBottom();
    els.jump.hidden = pinned || !els.chat.children.length;
}, { passive: true });

els.jump.addEventListener('click', () => scrollToBottom());

const keepPinned = () => { if (pinned) els.scroll.scrollTop = els.scroll.scrollHeight; };

/* ══════════════════════ Message rendering ══════════════════════ */

function renderUser(message) {
    const el = document.createElement('article');
    el.className = 'msg msg-user';
    el.dataset.id = message.id;

    const body = document.createElement('div');
    body.className = 'body';
    body.textContent = message.content;

    const actions = document.createElement('div');
    actions.className = 'actions';
    actions.append(timeLabel(message.at), actionButton('Copy', 'copy', async () => {
        const ok = await copyText(message.content);
        toast(ok ? 'Copied to clipboard' : 'Could not copy', ok ? 'info' : 'error');
    }));

    el.append(body, actions);
    els.chat.append(el);
    return el;
}

function renderBot(message) {
    const el = document.createElement('article');
    el.className = 'msg msg-bot';
    el.dataset.id = message.id;

    const head = document.createElement('div');
    head.className = 'head';
    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.append(icon('bot'));
    const who = document.createElement('span');
    who.className = 'who';
    who.textContent = 'HarmonyBot';
    head.append(avatar, who);

    const crisis = document.createElement('div');
    crisis.className = 'crisis-card';
    crisis.hidden = true;

    const body = document.createElement('div');
    body.className = 'body';

    const actions = document.createElement('div');
    actions.className = 'actions';

    el.append(head, crisis, body, actions);
    els.chat.append(el);
    return { el, body, crisis, actions };
}

function timeLabel(at) {
    const span = document.createElement('span');
    span.className = 'time';
    span.textContent = relativeTime(at);
    span.dataset.at = String(at);
    return span;
}

function actionButton(label, iconName, onClick) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'act';
    btn.append(icon(iconName), document.createTextNode(label));
    btn.addEventListener('click', onClick);
    return btn;
}

function thinkingIndicator() {
    const wrap = document.createElement('span');
    wrap.className = 'thinking';
    wrap.setAttribute('aria-label', 'Generating a reply');
    for (let i = 0; i < 3; i += 1) wrap.append(document.createElement('i'));
    return wrap;
}

/** Attach Copy / Regenerate to a finished reply. */
function finishBotActions(parts, message) {
    parts.actions.replaceChildren(timeLabel(message.at));
    parts.actions.append(
        actionButton('Copy', 'copy', async () => {
            const ok = await copyText(message.text);
            toast(ok ? 'Copied to clipboard' : 'Could not copy', ok ? 'info' : 'error');
        }),
        actionButton('Regenerate', 'retry', () => regenerate()),
    );
}

/* ══════════════════════ Conversation view ══════════════════════ */

function renderConversation() {
    const conv = store.active;
    els.chat.replaceChildren();
    els.chip.hidden = true;

    if (!conv || !conv.messages.length) {
        els.welcome.hidden = false;
        els.title.textContent = conv?.title ?? 'New conversation';
        els.jump.hidden = true;
        return;
    }

    els.welcome.hidden = true;
    els.title.textContent = conv.title;

    for (const message of conv.messages) {
        if (message.role === 'user') {
            renderUser(message);
        } else {
            const parts = renderBot(message);
            if (message.crisisHtml) {
                parts.crisis.innerHTML = message.crisisHtml;   // sanitised server-side
                parts.crisis.hidden = false;
            }
            if (message.error) {
                parts.body.classList.add('error');
                parts.body.textContent = message.text;
                parts.actions.replaceChildren(
                    timeLabel(message.at),
                    actionButton('Try again', 'retry', () => regenerate()),
                );
            } else {
                parts.body.innerHTML = message.html ?? '';     // sanitised server-side
                finishBotActions(parts, message);
            }
        }
    }
    scrollToBottom('auto');
}

function renderSidebar() {
    const groups = store.grouped(els.search.value);
    els.history.replaceChildren();

    if (!groups.length) {
        const empty = document.createElement('p');
        empty.className = 'history-empty';
        empty.textContent = els.search.value.trim()
            ? 'No conversations match that search.'
            : 'Your conversations will appear here.';
        els.history.append(empty);
        return;
    }

    for (const [label, list] of groups) {
        const heading = document.createElement('div');
        heading.className = 'history-label';
        heading.textContent = label;
        els.history.append(heading);

        for (const conv of list) {
            const row = document.createElement('div');
            row.className = 'conv';
            row.setAttribute('aria-current', String(conv.id === store.activeId));

            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'conv-title';
            btn.textContent = conv.title;
            btn.addEventListener('click', () => {
                if (store.select(conv.id)) {
                    renderConversation();
                    renderSidebar();
                    closeSidebar();
                }
            });

            const del = document.createElement('button');
            del.type = 'button';
            del.className = 'conv-del';
            del.setAttribute('aria-label', `Delete "${conv.title}"`);
            del.append(icon('trash'));
            del.addEventListener('click', async (e) => {
                e.stopPropagation();
                const ok = await confirmDialog({
                    title: 'Delete conversation?',
                    body: `"${conv.title}" will be permanently removed from this browser.`,
                });
                if (!ok) return;
                store.delete(conv.id);
                renderConversation();
                renderSidebar();
                toast('Conversation deleted');
            });

            row.append(btn, del);
            els.history.append(row);
        }
    }
}

/* Keep relative timestamps honest without re-rendering the whole view. */
setInterval(() => {
    for (const el of document.querySelectorAll('.time[data-at]')) {
        el.textContent = relativeTime(Number(el.dataset.at));
    }
}, 60_000);

/* ══════════════════════ Sending ══════════════════════ */

async function send(text) {
    const conv = store.ensure();
    els.welcome.hidden = true;

    const userMessage = store.addMessage('user', text);
    renderUser(userMessage);
    renderSidebar();
    els.title.textContent = conv.title;
    scrollToBottom();

    await generate(text, conv);
}

async function regenerate() {
    if (controller) return;
    const conv = store.active;
    const lastUser = [...(conv?.messages ?? [])].reverse().find((m) => m.role === 'user');
    if (!lastUser) return;

    store.popLastAssistant();
    renderConversation();
    await generate(lastUser.content, conv);
}

async function generate(text, conv) {
    // history() is read before the placeholder is added, so the model sees the
    // prior turns but not an empty reply.
    const history = store.history().slice(0, -1);
    const parts = renderBot({ id: 'pending' });
    parts.body.append(thinkingIndicator());
    keepPinned();

    controller = new AbortController();
    setBusy(true);

    let streamed = '';
    let crisisHtml = '';
    let finalHtml = '';
    let failed = '';
    let first = true;

    try {
        await streamChat(
            { message: text, sessionId: conv.sessionId, history, signal: controller.signal },
            (event, data) => {
                if (event === 'meta') {
                    els.chip.textContent = String(data).replace('_', ' ');
                    els.chip.hidden = false;
                } else if (event === 'crisis') {
                    crisisHtml = data;
                    parts.crisis.innerHTML = data;      // sanitised server-side
                    parts.crisis.hidden = false;
                    keepPinned();
                } else if (event === 'delta') {
                    if (first) {
                        parts.body.replaceChildren();
                        parts.body.classList.add('streaming');
                        first = false;
                    }
                    streamed += data;
                    // textContent while streaming: raw model output never
                    // becomes markup. The sanitised HTML arrives with `done`.
                    parts.body.textContent = streamed;
                    parts.body.append(caret());
                    keepPinned();
                } else if (event === 'done') {
                    finalHtml = data;
                } else if (event === 'error') {
                    failed = data;
                }
            },
        );
    } catch (err) {
        if (err.name === 'AbortError') {
            failed = streamed ? '' : 'Stopped before a reply arrived.';
        } else {
            failed = 'Could not reach the server. Check your connection and try again.';
            els.conn.dataset.state = 'error';
        }
    } finally {
        controller = null;
        setBusy(false);
    }

    if (failed) {
        parts.body.classList.remove('streaming');
        parts.body.classList.add('error');
        parts.body.textContent = failed;
        const message = store.addMessage('assistant', failed, { text: failed, error: true });
        parts.el.dataset.id = message.id;
        parts.actions.replaceChildren(
            timeLabel(message.at),
            actionButton('Try again', 'retry', () => regenerate()),
        );
        toast(failed, 'error');
        keepPinned();
        return;
    }

    parts.body.classList.remove('streaming');
    parts.body.innerHTML = finalHtml || streamed;   // sanitised server-side
    const message = store.addMessage('assistant', streamed, {
        text: streamed, html: finalHtml, crisisHtml,
    });
    parts.el.dataset.id = message.id;
    finishBotActions(parts, message);
    renderSidebar();
    keepPinned();
}

function caret() {
    const c = document.createElement('span');
    c.className = 'caret';
    return c;
}

function setBusy(busy) {
    els.send.hidden = busy;
    els.stop.hidden = !busy;
    els.conn.dataset.state = busy ? 'busy' : 'ok';
    if (!busy) {
        updateSendState();
        els.input.focus();
    }
}

/* ══════════════════════ Composer ══════════════════════ */

function autoResize() {
    els.input.style.height = 'auto';
    els.input.style.height = `${els.input.scrollHeight}px`;
}

function updateSendState() {
    const len = els.input.value.trim().length;
    els.send.disabled = len === 0 || Boolean(controller);
    const used = els.input.value.length;
    els.counter.textContent = used > 3400 ? `${used} / 4000` : '';
    els.counter.classList.toggle('warn', used > 3800);
}

els.input.addEventListener('input', () => { autoResize(); updateSendState(); });

els.input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        els.form.requestSubmit();
    }
});

els.form.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = els.input.value.trim();
    if (!text || controller) return;
    els.input.value = '';
    autoResize();
    updateSendState();
    send(text);
});

els.stop.addEventListener('click', () => controller?.abort());

els.welcome.addEventListener('click', (e) => {
    const prompt = e.target.closest('.prompt');
    if (!prompt || controller) return;
    send(prompt.textContent.trim());
});

/* ══════════════════════ Chrome ══════════════════════ */

function newConversation() {
    controller?.abort();
    store.create();
    renderConversation();
    renderSidebar();
    closeSidebar();
    els.input.focus();
}

$('new-chat').addEventListener('click', newConversation);

$('delete-btn').addEventListener('click', async () => {
    const conv = store.active;
    if (!conv) return;
    const ok = await confirmDialog({
        title: 'Delete conversation?',
        body: `"${conv.title}" will be permanently removed from this browser.`,
    });
    if (!ok) return;
    store.delete(conv.id);
    renderConversation();
    renderSidebar();
    toast('Conversation deleted');
});

$('export-btn').addEventListener('click', () => {
    const conv = store.active;
    if (!conv?.messages.length) {
        toast('Nothing to export yet', 'error');
        return;
    }
    const slug = conv.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40);
    downloadFile(`harmonybot-${slug || 'conversation'}.md`, store.toMarkdown());
    toast('Conversation exported');
});

els.search.addEventListener('input', renderSidebar);

const openSidebar = () => {
    els.sidebar.classList.add('open');
    els.scrim.hidden = false;
    els.menu.setAttribute('aria-expanded', 'true');
};
const closeSidebar = () => {
    els.sidebar.classList.remove('open');
    els.scrim.hidden = true;
    els.menu.setAttribute('aria-expanded', 'false');
};

els.menu.addEventListener('click', openSidebar);
els.scrim.addEventListener('click', closeSidebar);
$('sidebar-close').addEventListener('click', closeSidebar);

$('shortcuts-btn').addEventListener('click', () => $('shortcuts-dialog').showModal());

/* ══════════════════════ Shortcuts ══════════════════════ */

document.addEventListener('keydown', (e) => {
    const typing = ['INPUT', 'TEXTAREA'].includes(e.target.tagName);
    const mod = e.ctrlKey || e.metaKey;

    if (e.key === 'Escape') {
        if (controller) { controller.abort(); return; }
        closeSidebar();
        return;
    }
    if (mod && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        openSidebar();
        els.search.focus();
        els.search.select();
        return;
    }
    if (mod && e.shiftKey && e.key.toLowerCase() === 'o') {
        e.preventDefault();
        newConversation();
        return;
    }
    if (mod && e.key === '/') {
        e.preventDefault();
        els.input.focus();
        return;
    }
    if (e.key === '?' && !typing) {
        e.preventDefault();
        $('shortcuts-dialog').showModal();
    }
});

/* ══════════════════════ Status ══════════════════════ */

async function loadStatus() {
    try {
        const data = await fetchHealth();
        $('status-model').textContent = data.model.split('/').pop();
        $('status-retrieval').textContent = data.retrieval_ready ? 'Ready' : 'Disabled';
        $('status-docs').textContent = data.indexed_documents.toLocaleString();
        els.statusSummary.textContent = data.retrieval_ready
            ? `Connected · ${data.indexed_documents.toLocaleString()} refs`
            : 'Connected';
        els.conn.dataset.state = 'ok';
    } catch {
        els.statusSummary.textContent = 'Server unreachable';
        els.conn.dataset.state = 'error';
    }
}

/* ══════════════════════ Boot ══════════════════════ */

function showFirstRunNotice() {
    let seen = false;
    try { seen = localStorage.getItem('hb-disclaimer') === '1'; } catch { seen = true; }
    if (seen) return;

    const dialog = $('welcome-dialog');
    dialog.addEventListener('close', () => {
        try { localStorage.setItem('hb-disclaimer', '1'); } catch { /* ignore */ }
        els.input.focus();
    }, { once: true });
    dialog.showModal();
}

initTheme();
renderConversation();
renderSidebar();
updateSendState();
autoResize();
loadStatus();
showFirstRunNotice();
els.input.focus();
