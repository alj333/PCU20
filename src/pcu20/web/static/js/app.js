/* CNC Network Manager — Frontend */

document.addEventListener('DOMContentLoaded', () => {
    const statusEl = document.getElementById('ws-status');
    const dotEl = document.getElementById('ws-dot');
    const activityFeed = document.getElementById('activity-feed');
    const connectedCount = document.getElementById('connected-count');
    const alarmBanner = document.getElementById('alarm-banner');
    const alarmBannerText = document.getElementById('alarm-banner-text');

    const isDashboard = !!activityFeed;

    let ws = null;
    let reconnectTimer = null;
    let activeAlarms = {};  // machine_id -> [alarms]

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
            try { handleEvent(JSON.parse(event.data)); } catch (e) {}
        };
    }

    function handleEvent(event) {
        // Connected count
        if (event.type === 'machine.connected' && connectedCount) {
            connectedCount.textContent = parseInt(connectedCount.textContent || '0') + 1;
        }
        if (event.type === 'machine.disconnected' && connectedCount) {
            connectedCount.textContent = Math.max(0, parseInt(connectedCount.textContent || '1') - 1);
        }

        // Machine status updates — update machine cards in real-time
        if (event.type === 'machine.status' && event.data) {
            updateMachineCard(event.data);
        }

        // Alarm tracking
        if (event.type === 'machine.status' && event.data) {
            const mid = event.data.machine_id;
            const alarms = event.data.alarms || [];
            if (alarms.length > 0) {
                activeAlarms[mid] = alarms;
            } else {
                delete activeAlarms[mid];
            }
            updateAlarmBanner();
        }

        if (event.type === 'machine.alarm' && event.data) {
            // Flash activity for individual alarm events
        }

        // Activity feed
        if (activityFeed && event.type !== 'machine.status') {
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
            if (event.type === 'machine.alarm') {
                type.classList.add('activity-type--disconnect'); // red
            }
            type.textContent = event.type;

            const detail = document.createElement('span');
            const parts = [];
            if (event.data?.machine_id) parts.push(event.data.machine_id);
            else if (event.data?.peer_ip) parts.push(event.data.peer_ip);
            if (event.data?.name) parts.push(event.data.name);
            if (event.data?.alarm_code) parts.push('ALM ' + event.data.alarm_code);
            if (event.data?.message) parts.push(event.data.message);
            detail.textContent = parts.join(' | ');

            item.appendChild(time);
            item.appendChild(type);
            item.appendChild(detail);
            activityFeed.prepend(item);

            while (activityFeed.children.length > 100) {
                activityFeed.lastChild.remove();
            }
        }
    }

    function updateMachineCard(data) {
        const card = document.getElementById('machine-' + data.machine_id);
        if (!card) return;

        // Update CNC status badge
        const statusEl = card.querySelector('.machine-cnc-status');
        if (statusEl && data.status) {
            const run = data.status.run || 'unknown';
            statusEl.textContent = run.toUpperCase();
            statusEl.className = 'machine-cnc-status machine-cnc-status--' + run;
        }

        // Update mode
        const modeEl = card.querySelector('.machine-mode');
        if (modeEl && data.status && data.status.mode) {
            modeEl.textContent = data.status.mode.toUpperCase();
        }

        // Update program
        const progEl = card.querySelector('.machine-program');
        if (progEl && data.program != null) {
            progEl.textContent = 'O' + data.program;
        }

        // Update axis positions
        const axisDisplay = card.querySelector('.axis-display');
        if (axisDisplay && data.position && Object.keys(data.position).length > 0) {
            axisDisplay.innerHTML = '';
            for (const [axis, pos] of Object.entries(data.position)) {
                const row = document.createElement('div');
                row.className = 'axis-row';
                row.innerHTML = `<span class="axis-label">${axis}</span><span class="axis-value">${pos.toFixed(3)}</span>`;
                axisDisplay.appendChild(row);
            }
        }

        // Update alarm state on card
        const alarms = data.alarms || [];
        if (alarms.length > 0) {
            card.classList.add('machine-card--alarm');
        } else {
            card.classList.remove('machine-card--alarm');
        }

        // Update alarm list
        let alarmContainer = card.querySelector('.machine-alarms');
        if (alarms.length > 0) {
            if (!alarmContainer) {
                alarmContainer = document.createElement('div');
                alarmContainer.className = 'machine-alarms';
                card.querySelector('.machine-card-body').appendChild(alarmContainer);
            }
            alarmContainer.innerHTML = alarms.map(a =>
                `<div class="alarm-item">ALM ${a.code}: ${a.message || ''}</div>`
            ).join('');
        } else if (alarmContainer) {
            alarmContainer.remove();
        }
    }

    function updateAlarmBanner() {
        if (!alarmBanner) return;
        const totalAlarms = Object.values(activeAlarms).flat();
        if (totalAlarms.length > 0) {
            const machines = Object.keys(activeAlarms);
            alarmBannerText.textContent = `${totalAlarms.length} alarm(s) on ${machines.length} machine(s): ${machines.join(', ')}`;
            alarmBanner.style.display = 'flex';
        } else {
            alarmBanner.style.display = 'none';
        }
    }

    // Dashboard: full WebSocket. Other pages: status probe only.
    if (isDashboard) {
        connectWebSocket();
    } else {
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
