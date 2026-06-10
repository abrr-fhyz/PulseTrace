/* sentiment timeline chart */
function renderSentChart(cs) {
  const labels = cs.map(c => String(c.label || "?").slice(0, 18));
  const pos = cs.map(c => Math.round((c.sentiment && c.sentiment.pos || 0) * 100));
  const neu = cs.map(c => Math.round((c.sentiment && c.sentiment.neu || 0) * 100));
  const neg = cs.map(c => Math.round((c.sentiment && c.sentiment.neg || 0) * 100));
  const ctx = $("#sentChart");
  if (sentChart) sentChart.destroy();
  // Sentiment is semantic, not branding: positive=green, neutral=gray, negative=red.
  const text = cssVar("--text"), muted = cssVar("--muted"), grid = cssVar("--border");
  sentChart = new Chart(ctx, {
    type: "bar",
    data: { labels, datasets: [
      { label: "Positive", data: pos, backgroundColor: cssVar("--pos") },
      { label: "Neutral", data: neu, backgroundColor: cssVar("--neu") },
      { label: "Negative", data: neg, backgroundColor: cssVar("--neg") },
    ]},
    options: {
      responsive: true,
      plugins: {
        legend: { labels: { color: text } },
        tooltip: { callbacks: { label: (i) => i.dataset.label + ": " + i.parsed.y + "%" } },
      },
      scales: {
        x: { stacked: true, ticks: { color: muted }, grid: { color: grid } },
        y: { stacked: true, ticks: { color: muted }, grid: { color: grid }, max: 100 },
      },
    },
  });
}
