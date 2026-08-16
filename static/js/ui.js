/* Presentational helpers: icons, toasts, dialogs, time formatting. */

export const $ = (id) => document.getElementById(id);

const ICON_PATHS = {
    bot:      "M4 12h3.5l2-4.5 3.2 9 2.1-4.5H20",
    copy:     "M9 9h10v12H9zM5 15V3h10v2",
    retry:    "M4 12a8 8 0 1 1 2.3 5.6M4 18v-5h5",
    trash:    "M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13",
    check:    "M5 13l4 4L19 7",
    alert:    "M12 8v5M12 17h.01M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
    info:     "M12 16v-5M12 8h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z",
};

/** Build an inline SVG icon without going through innerHTML. */
export function icon(name, cls = 'ico') {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('class', cls);
    svg.setAttribute('aria-hidden', 'true');
    for (const d of (ICON_PATHS[name] ?? '').split('|')) {
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', d);
        svg.append(path);
    }
    return svg;
}

/** Short relative time: "just now", "4m", "2h", then a date. */
export function relativeTime(ts) {
    const diff = Date.now() - ts;
    if (diff < 60_000) return 'just now';
    if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
    if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
    if (diff < 604_800_000) return `${Math.floor(diff / 86_400_000)}d ago`;
    return new Date(ts).toLocaleDateString();
}

let toastTimer = 0;

export function toast(message, kind = 'info') {
    const host = $('toasts');
    const el = document.createElement('div');
    el.className = `toast ${kind}`;
    el.append(icon(kind === 'error' ? 'alert' : 'check'));

    const span = document.createElement('span');
    span.textContent = message;
    el.append(span);
    host.append(el);

    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
        el.classList.add('out');
        el.addEventListener('animationend', () => el.remove(), { once: true });
    }, 3200);
}

/** Promise-based confirm built on <dialog>, so focus and Esc are handled. */
export function confirmDialog({ title, body, confirmLabel = 'Delete' }) {
    const dialog = $('confirm-dialog');
    $('confirm-title').textContent = title;
    $('confirm-body').textContent = body;
    dialog.querySelector('.btn-danger').textContent = confirmLabel;

    return new Promise((resolve) => {
        dialog.addEventListener(
            'close', () => resolve(dialog.returnValue === 'confirm'), { once: true }
        );
        dialog.showModal();
    });
}

export async function copyText(text) {
    try {
        await navigator.clipboard.writeText(text);
        return true;
    } catch {
        // clipboard API needs a secure context; fall back for plain http hosts.
        try {
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.cssText = 'position:fixed;opacity:0';
            document.body.append(ta);
            ta.select();
            const ok = document.execCommand('copy');
            ta.remove();
            return ok;
        } catch {
            return false;
        }
    }
}

export function downloadFile(filename, text) {
    const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}
