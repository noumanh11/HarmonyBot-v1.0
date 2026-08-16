/* Conversation persistence.
 *
 * Everything lives in localStorage - the server keeps no record of what was
 * said once the reply is sent. Each conversation carries its own session id,
 * so switching conversations switches server-side context too, and the recent
 * turns are replayed on send so a restored chat keeps its memory. */

const KEY = 'hb-conversations';
const MAX_CONVERSATIONS = 50;
const HISTORY_TURNS = 8;   // must not exceed the server's cap of 20 messages

const newId = () =>
    (crypto.randomUUID?.() ?? String(Date.now() + Math.random())).replace(/-/g, '');

export class Store {
    constructor() {
        this.conversations = this._load();
        this.activeId = this.conversations[0]?.id ?? null;
    }

    _load() {
        try {
            const raw = JSON.parse(localStorage.getItem(KEY) ?? '[]');
            return Array.isArray(raw) ? raw.filter((c) => c?.id && Array.isArray(c.messages)) : [];
        } catch {
            return [];
        }
    }

    save() {
        try {
            localStorage.setItem(
                KEY, JSON.stringify(this.conversations.slice(0, MAX_CONVERSATIONS))
            );
        } catch {
            // Quota exhausted: drop the oldest and retry once so the current
            // conversation is never the one lost.
            this.conversations = this.conversations.slice(0, 12);
            try { localStorage.setItem(KEY, JSON.stringify(this.conversations)); } catch { /* give up */ }
        }
    }

    get active() {
        return this.conversations.find((c) => c.id === this.activeId) ?? null;
    }

    create() {
        const conv = {
            id: newId(),
            sessionId: newId(),
            title: 'New conversation',
            messages: [],
            updatedAt: Date.now(),
        };
        this.conversations.unshift(conv);
        this.activeId = conv.id;
        this.save();
        return conv;
    }

    /** The active conversation, creating one on first use. */
    ensure() {
        return this.active ?? this.create();
    }

    addMessage(role, content, extra = {}) {
        const conv = this.ensure();
        const message = { id: newId(), role, content, at: Date.now(), ...extra };
        conv.messages.push(message);

        if (role === 'user' && conv.messages.filter((m) => m.role === 'user').length === 1) {
            conv.title = content.length > 52 ? `${content.slice(0, 52).trimEnd()}…` : content;
        }
        conv.updatedAt = Date.now();
        this.save();
        return message;
    }

    updateMessage(id, patch) {
        const conv = this.active;
        const message = conv?.messages.find((m) => m.id === id);
        if (!message) return;
        Object.assign(message, patch);
        conv.updatedAt = Date.now();
        this.save();
    }

    removeMessage(id) {
        const conv = this.active;
        if (!conv) return;
        conv.messages = conv.messages.filter((m) => m.id !== id);
        this.save();
    }

    /** Drop the trailing assistant reply so it can be regenerated. */
    popLastAssistant() {
        const conv = this.active;
        const last = conv?.messages.at(-1);
        if (last?.role === 'assistant') {
            conv.messages.pop();
            this.save();
            return last;
        }
        return null;
    }

    select(id) {
        if (this.conversations.some((c) => c.id === id)) {
            this.activeId = id;
            return true;
        }
        return false;
    }

    delete(id) {
        this.conversations = this.conversations.filter((c) => c.id !== id);
        if (this.activeId === id) this.activeId = this.conversations[0]?.id ?? null;
        this.save();
    }

    /** Recent turns, shaped for the API and capped to the server's limit. */
    history() {
        const conv = this.active;
        if (!conv) return [];
        return conv.messages
            .filter((m) => m.role === 'user' || (m.role === 'assistant' && !m.error))
            .slice(-HISTORY_TURNS * 2)
            .map((m) => ({ role: m.role, content: m.text ?? m.content }));
    }

    /** Conversations grouped into Today / Previous 7 days / Older. */
    grouped(query = '') {
        const q = query.trim().toLowerCase();
        const matches = q
            ? this.conversations.filter(
                (c) => c.title.toLowerCase().includes(q) ||
                       c.messages.some((m) => (m.text ?? m.content ?? '').toLowerCase().includes(q)))
            : this.conversations;

        const sorted = [...matches].sort((a, b) => b.updatedAt - a.updatedAt);
        const day = 86_400_000;
        const now = Date.now();
        const groups = new Map([['Today', []], ['Previous 7 days', []], ['Older', []]]);

        for (const conv of sorted) {
            const age = now - conv.updatedAt;
            const bucket = age < day ? 'Today' : age < day * 7 ? 'Previous 7 days' : 'Older';
            groups.get(bucket).push(conv);
        }
        return [...groups].filter(([, list]) => list.length);
    }

    toMarkdown() {
        const conv = this.active;
        if (!conv) return '';
        const lines = [`# ${conv.title}`, '', `_${new Date(conv.updatedAt).toLocaleString()}_`, ''];
        for (const m of conv.messages) {
            lines.push(m.role === 'user' ? '## You' : '## HarmonyBot', '', m.text ?? m.content, '');
        }
        lines.push('---', '', '_Generated by HarmonyBot. Not medical advice._');
        return lines.join('\n');
    }
}
