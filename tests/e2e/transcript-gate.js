(() => {
    const fetch = window.fetch.bind(window);
    const waiting = {};
    const settled = {};
    const started = {};
    window.__transcriptGate = {
        waiting, settled, started,
        release(url) {
            const callbacks = waiting[url];
            if (!callbacks || !callbacks.length) throw new Error('No held transcript: ' + url);
            delete waiting[url];
            callbacks.forEach(resolve => resolve());
        }
    };
    window.fetch = async (...args) => {
        const url = new URL(typeof args[0] === 'string' ? args[0] : args[0].url, location.href);
        if (url.pathname.includes('player-transcript')) {
            started[url.href] = (started[url.href] || 0) + 1;
        }
        const response = await fetch(...args);
        if (new URL(response.url).pathname.includes('player-transcript')) {
            await new Promise(resolve => (waiting[response.url] ||= []).push(resolve));
            const json = response.json.bind(response);
            response.json = async () => {
                try {
                    return await json();
                } finally {
                    // A retired player aborts the body; rejection also settles
                    // the consumer. Signal the next task, after its continuation.
                    setTimeout(() => { settled[response.url] = true; }, 0);
                }
            };
        }
        return response;
    };
})();
