/* Server communication. */

/** Parse an SSE body into {event, data} frames.
 *  Hand-rolled because EventSource cannot issue a POST. */
async function* parseEvents(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let cut;
        while ((cut = buffer.indexOf('\n\n')) !== -1) {
            const frame = buffer.slice(0, cut);
            buffer = buffer.slice(cut + 2);

            let event = 'message';
            const data = [];
            for (const line of frame.split('\n')) {
                if (line.startsWith('event:')) event = line.slice(6).trim();
                else if (line.startsWith('data:')) data.push(line.slice(5).trim());
            }
            if (!data.length) continue;
            try {
                yield { event, data: JSON.parse(data.join('\n')) };
            } catch { /* ignore a malformed frame rather than kill the stream */ }
        }
    }
}

/**
 * Stream a reply.
 * @param {{message:string, sessionId:string, history:Array, signal:AbortSignal}} opts
 * @param {(event:string, data:any) => void} onEvent
 */
export async function streamChat({ message, sessionId, history, signal }, onEvent) {
    const res = await fetch('/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, session_id: sessionId, history }),
        signal,
    });

    if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

    for await (const { event, data } of parseEvents(res)) {
        onEvent(event, data);
    }
}

export async function fetchHealth() {
    const res = await fetch('/health');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
}
