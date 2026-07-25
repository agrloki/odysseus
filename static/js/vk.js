/* VK Messenger integration settings widget */
(function() {
    'use strict';

    const VK_PANEL_ID = 'vk-settings-panel';

    function getT(key, fallback) {
        return (window.__t || (k => k))(key) || fallback;
    }

    function render() {
        const existing = document.getElementById(VK_PANEL_ID);
        if (existing) existing.remove();

        const panel = document.createElement('div');
        panel.id = VK_PANEL_ID;
        panel.className = 'settings-section';
        panel.innerHTML = `
            <h3 style="margin:0 0 12px">\u{1F4AC} VK Messenger</h3>
            <div style="display:flex;flex-direction:column;gap:8px;max-width:400px">
                <label style="font-size:12px;color:var(--fg-muted)">${getT('vk.token', 'API Token')}</label>
                <input type="password" id="vk-token" placeholder="vk1.a....." style="padding:6px 8px;border:1px solid var(--border);border-radius:4px;background:var(--bg);color:var(--fg);font-size:13px">
                <label style="font-size:12px;color:var(--fg-muted)">${getT('vk.groupId', 'Community ID')}</label>
                <input type="text" id="vk-group-id" placeholder="123456789" style="padding:6px 8px;border:1px solid var(--border);border-radius:4px;background:var(--bg);color:var(--fg);font-size:13px">
                <label style="font-size:12px;color:var(--fg-muted)">${getT('vk.apiVersion', 'API Version')}</label>
                <input type="text" id="vk-api-version" value="5.199" style="padding:6px 8px;border:1px solid var(--border);border-radius:4px;background:var(--bg);color:var(--fg);font-size:13px">
                <label style="font-size:12px;color:var(--fg-muted)">${getT('vk.pollInterval', 'Poll interval (sec)')}</label>
                <input type="number" id="vk-poll-interval" value="5" min="1" max="60" style="padding:6px 8px;border:1px solid var(--border);border-radius:4px;background:var(--bg);color:var(--fg);font-size:13px;width:100px">
                <div style="display:flex;gap:8px;margin-top:8px">
                    <button id="vk-save-btn" style="padding:6px 12px;border:none;border-radius:4px;background:var(--accent);color:#fff;cursor:pointer;font-size:12px">${getT('vk.save', 'Save')}</button>
                    <button id="vk-test-btn" style="padding:6px 12px;border:1px solid var(--border);border-radius:4px;background:transparent;color:var(--fg);cursor:pointer;font-size:12px">${getT('vk.test', 'Test')}</button>
                    <button id="vk-start-btn" style="padding:6px 12px;border:1px solid var(--green,#4caf50);border-radius:4px;background:transparent;color:var(--green,#4caf50);cursor:pointer;font-size:12px">${getT('vk.start', 'Start')}</button>
                    <button id="vk-stop-btn" style="padding:6px 12px;border:1px solid var(--red,#f44336);border-radius:4px;background:transparent;color:var(--red,#f44336);cursor:pointer;font-size:12px;display:none">${getT('vk.stop', 'Stop')}</button>
                </div>
                <div id="vk-status" style="font-size:12px;color:var(--fg-muted);margin-top:4px"></div>
            </div>
        `;
        return panel;
    }

    async function loadConfig() {
        try {
            const resp = await fetch('/api/vk/config');
            const data = await resp.json();
            const tokenInput = document.getElementById('vk-token');
            const groupIdInput = document.getElementById('vk-group-id');
            const apiVersionInput = document.getElementById('vk-api-version');
            const pollIntervalInput = document.getElementById('vk-poll-interval');
            if (tokenInput && data.token_masked) tokenInput.placeholder = data.token_masked;
            if (groupIdInput) groupIdInput.value = data.group_id || '';
            if (apiVersionInput) apiVersionInput.value = data.api_version || '5.199';
            if (pollIntervalInput) pollIntervalInput.value = data.poll_interval || 5;
        } catch (e) {
            console.error('VK: load config error', e);
        }
    }

    async function loadStatus() {
        try {
            const resp = await fetch('/api/vk/status');
            const data = await resp.json();
            const statusEl = document.getElementById('vk-status');
            const startBtn = document.getElementById('vk-start-btn');
            const stopBtn = document.getElementById('vk-stop-btn');
            if (statusEl) {
                statusEl.textContent = data.running
                    ? `${getT('vk.connected', 'Connected')} (${data.status})`
                    : `${getT('vk.disconnected', 'Disconnected')}${data.error ? ': ' + data.error : ''}`;
                statusEl.style.color = data.running ? 'var(--green,#4caf50)' : 'var(--fg-muted)';
            }
            if (startBtn) startBtn.style.display = data.running ? 'none' : '';
            if (stopBtn) stopBtn.style.display = data.running ? '' : 'none';
        } catch (e) {
            console.error('VK: load status error', e);
        }
    }

    function bindEvents() {
        document.getElementById('vk-save-btn')?.addEventListener('click', async () => {
            const body = {
                token: document.getElementById('vk-token')?.value || '',
                group_id: document.getElementById('vk-group-id')?.value || '',
                api_version: document.getElementById('vk-api-version')?.value || '5.199',
                poll_interval: parseInt(document.getElementById('vk-poll-interval')?.value || '5'),
            };
            try {
                await fetch('/api/vk/config', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(body),
                });
                document.getElementById('vk-status').textContent = 'Saved';
            } catch (e) {
                document.getElementById('vk-status').textContent = 'Error: ' + e.message;
            }
        });

        document.getElementById('vk-test-btn')?.addEventListener('click', async () => {
            const statusEl = document.getElementById('vk-status');
            statusEl.textContent = 'Testing...';
            try {
                const resp = await fetch('/api/vk/test', {method: 'POST'});
                const data = await resp.json();
                statusEl.textContent = data.ok ? `Connected to "${data.name}"` : `Error: ${data.error}`;
                statusEl.style.color = data.ok ? 'var(--green,#4caf50)' : 'var(--red,#f44336)';
            } catch (e) {
                statusEl.textContent = 'Error: ' + e.message;
            }
        });

        document.getElementById('vk-start-btn')?.addEventListener('click', async () => {
            const statusEl = document.getElementById('vk-status');
            statusEl.textContent = 'Starting...';
            try {
                const resp = await fetch('/api/vk/start', {method: 'POST'});
                const data = await resp.json();
                if (data.ok) {
                    await loadStatus();
                } else {
                    statusEl.textContent = 'Error: ' + data.error;
                }
            } catch (e) {
                statusEl.textContent = 'Error: ' + e.message;
            }
        });

        document.getElementById('vk-stop-btn')?.addEventListener('click', async () => {
            await fetch('/api/vk/stop', {method: 'POST'});
            await loadStatus();
        });
    }

    window.VKSettings = {
        render,
        init() {
            loadConfig();
            loadStatus();
            bindEvents();
        },
    };
})();
