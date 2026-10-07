/* Read the server cache only; a closed page never stops the automation. */
(function () {
    const label = document.getElementById('doorwayDistance');
    let lastSuccess = 0;
    setInterval(() => {
        if (Date.now() - lastSuccess > 3000) label.textContent = '数据过期 / 连接中断';
    }, 500);
    async function poll() {
        try {
            const response = await fetch('/api/camera/distance', { signal: AbortSignal.timeout(2500), cache: 'no-store' });
            if (!response.ok) throw new Error('unavailable');
            const data = await response.json();
            lastSuccess = Date.now();
            label.textContent = data.valid && Number.isFinite(data.distance_cm)
                ? data.distance_cm.toFixed(1) + ' cm' : '暂无有效距离（检查回波或连接）';
        } catch (_) {
            label.textContent = '测距不可用 / 连接中断';
        } finally {
            setTimeout(poll, 500);
        }
    }
    poll();
})();
