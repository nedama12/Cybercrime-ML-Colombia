/* Renders the charts of the reports and monitoring pages from an embedded JSON block. */
(function () {
    if (typeof Chart === "undefined") return;
    const source = document.getElementById("report-data");
    if (!source) return;
    const data = JSON.parse(source.textContent);

    Chart.defaults.color = "#9aa2ad";
    Chart.defaults.borderColor = "#252a31";
    Chart.defaults.font.family = 'Inter, "Segoe UI", Arial, sans-serif';
    const RED = "#ff354b", CYAN = "#39d9e8", AMBER = "#ffb547", GREEN = "#3ddc84", GREY = "#59616b";

    function draw(id, config) {
        const el = document.getElementById(id);
        if (el) new Chart(el, Object.assign({ options: { maintainAspectRatio: false } }, config));
    }

    const c = data.charts;
    if (c) {
        draw("chart-weeks", { type: "bar", data: { labels: c.weeks, datasets: [{ label: "Cases", data: c.week_counts, backgroundColor: CYAN }] },
            options: { maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } } });
        draw("chart-risk", { type: "doughnut", data: { labels: c.risk_labels, datasets: [{ data: c.risk_counts, backgroundColor: [RED, AMBER, GREEN, GREY], borderWidth: 0 }] } });
        draw("chart-status", { type: "bar", data: { labels: c.status_labels, datasets: [{ label: "Cases", data: c.status_counts, backgroundColor: [CYAN, AMBER, AMBER, GREEN] }] },
            options: { maintainAspectRatio: false, indexAxis: "y", plugins: { legend: { display: false } }, scales: { x: { beginAtZero: true, ticks: { precision: 0 } } } } });
        draw("chart-channel", { type: "bar", data: { labels: c.channel_labels, datasets: [{ label: "Cases", data: c.channel_counts, backgroundColor: RED }] },
            options: { maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } } });
    }
    const co = data.colombia;
    if (co) {
        draw("chart-colombia", { type: "line", data: { labels: co.trend_years, datasets: [
            { label: "Phishing / spoofing (art. 269G)", data: co.trend_phishing, borderColor: RED, backgroundColor: RED, tension: .25 },
            { label: "Electronic theft (art. 269I)", data: co.trend_theft, borderColor: CYAN, backgroundColor: CYAN, tension: .25 }] } });
    }
    const m = data.monitoring;
    if (m) {
        draw("chart-latency", { type: "line", data: { labels: m.days, datasets: [
            { label: "p95 response time (ms)", data: m.p95, borderColor: AMBER, backgroundColor: AMBER, tension: .25 },
            { label: "Requests", data: m.requests, borderColor: CYAN, backgroundColor: CYAN, tension: .25, yAxisID: "y1" }] },
            options: { maintainAspectRatio: false, scales: { y: { beginAtZero: true }, y1: { beginAtZero: true, position: "right", grid: { drawOnChartArea: false } } } } });
        draw("chart-predictions", { type: "bar", data: { labels: m.days, datasets: [
            { label: "High", data: m.high, backgroundColor: RED }, { label: "Medium", data: m.medium, backgroundColor: AMBER },
            { label: "Low", data: m.low, backgroundColor: GREEN }] },
            options: { maintainAspectRatio: false, scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } } } } });
    }
})();
