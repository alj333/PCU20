/* PCU20 Network Manager — Frontend */

document.addEventListener('DOMContentLoaded', () => {
    const statusEl = document.getElementById('ws-status');
    const dotEl = document.getElementById('ws-dot');
    const activityFeed = document.getElementById('activity-feed');
    const connectedCount = document.getElementById('connected-count');

    // Only open our own WebSocket on the dashboard page (where activity-feed exists).
    // Other pages (logs) use htmx ws-connect instead.
    const isDashboard = !!activityFeed;

    let ws = null;
    let reconnectTimer = null;

    function connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

        ws.onopen = () => {
            if (statusEl) statusEl.textContent = 'Server Online';
            if (dotEl) dotEl.classList.remove('disconnected');
            if (reconnectTimer) {
                clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }
        };

        ws.onclose = () => {
            if (statusEl) statusEl.textContent = 'Reconnecting...';
            if (dotEl) dotEl.classList.add('disconnected');
            reconnectTimer = setTimeout(connectWebSocket, 3000);
        };

        ws.onerror = () => ws.close();

        ws.onmessage = (event) => {
            try {
                handleEvent(JSON.parse(event.data));
            } catch (e) {}
        };
    }

    function handleEvent(event) {
        // Update connected count
        if (event.type === 'machine.connected' && connectedCount) {
            connectedCount.textContent = parseInt(connectedCount.textContent || '0') + 1;
        }
        if (event.type === 'machine.disconnected' && connectedCount) {
            connectedCount.textContent = Math.max(0, parseInt(connectedCount.textContent || '1') - 1);
        }

        // Activity feed (dashboard only)
        if (activityFeed) {
            const empty = activityFeed.querySelector('.empty-state');
            if (empty) empty.remove();

            const item = document.createElement('div');
            item.className = 'activity-item';

            const time = document.createElement('span');
            time.className = 'activity-time';
            time.textContent = new Date(event.ts * 1000).toLocaleTimeString();

            const type = document.createElement('span');
            type.className = 'activity-type';
            if (event.type.includes('connected')) {
                type.classList.add(event.type === 'machine.connected' ? 'activity-type--connect' : 'activity-type--disconnect');
            }
            type.textContent = event.type;

            const detail = document.createElement('span');
            const ip = event.data?.peer_ip || '';
            const user = event.data?.username || '';
            detail.textContent = [ip, user].filter(Boolean).join(' ');

            item.appendChild(time);
            item.appendChild(type);
            item.appendChild(detail);
            activityFeed.prepend(item);

            while (activityFeed.children.length > 100) {
                activityFeed.lastChild.remove();
            }
        }
    }

    // On dashboard: open our own WS for the activity feed.
    // On other pages: just ping /ws to check server status (no event subscription).
    if (isDashboard) {
        connectWebSocket();
    } else {
        // Lightweight status check — just test if WS connects, then close
        function checkStatus() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const probe = new WebSocket(`${protocol}//${window.location.host}/ws`);
            probe.onopen = () => {
                if (statusEl) statusEl.textContent = 'Server Online';
                if (dotEl) dotEl.classList.remove('disconnected');
                probe.close();
            };
            probe.onerror = () => {
                if (statusEl) statusEl.textContent = 'Disconnected';
                if (dotEl) dotEl.classList.add('disconnected');
            };
        }
        checkStatus();
        setInterval(checkStatus, 30000);
    }
});
