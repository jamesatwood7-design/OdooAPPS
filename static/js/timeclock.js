document.addEventListener('DOMContentLoaded', function () {
    const elapsedEl = document.getElementById('elapsedTime');
    if (!elapsedEl) return;

    const sinceStr = elapsedEl.dataset.since;
    if (!sinceStr) return;

    const sinceDate = new Date(sinceStr + 'Z'); // Odoo datetimes are UTC

    function updateElapsed() {
        const now = new Date();
        const diffMs = now - sinceDate;
        if (diffMs < 0) {
            elapsedEl.textContent = '0h 00m 00s';
            return;
        }

        const totalSeconds = Math.floor(diffMs / 1000);
        const hours = Math.floor(totalSeconds / 3600);
        const minutes = Math.floor((totalSeconds % 3600) / 60);
        const seconds = totalSeconds % 60;

        elapsedEl.textContent =
            hours + 'h ' +
            String(minutes).padStart(2, '0') + 'm ' +
            String(seconds).padStart(2, '0') + 's';
    }

    updateElapsed();
    setInterval(updateElapsed, 1000);

    // Poll status every 30 seconds to keep in sync
    setInterval(function () {
        fetch('/timeclock/api/status')
            .then(function (resp) { return resp.json(); })
            .then(function (data) {
                if (data.state === 'checked_out') {
                    // Employee was clocked out elsewhere, reload the page
                    window.location.reload();
                }
            })
            .catch(function () {
                // Silently ignore poll errors
            });
    }, 30000);
});
