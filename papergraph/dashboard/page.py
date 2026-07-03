"""Dashboard HTML page with EventSource client."""
from __future__ import annotations

PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>papergraph dashboard</title>
  <style>
    * { box-sizing: border-box; }
    body {
      font-family: monospace;
      background: #0d1117;
      color: #c9d1d9;
      margin: 0;
      padding: 16px;
    }
    h1 { color: #58a6ff; margin: 0 0 16px 0; }
    .banner { padding: 8px 12px; margin-bottom: 16px; border-radius: 4px; }
    .banner.done { background: #238636; color: #fff; font-weight: bold; }
    .lanes {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }
    .lane {
      border: 1px solid #30363d;
      border-radius: 4px;
      padding: 12px;
      background: #161b22;
    }
    .lane-name { font-weight: bold; color: #58a6ff; margin-bottom: 8px; }
    .lane-status { font-size: 0.9em; color: #8b949e; margin-bottom: 4px; }
    .lane-status.running { color: #d29922; }
    .lane-status.done { color: #238636; }
    .lane-status.failed { color: #f85149; }
    .lane-latest { font-size: 0.85em; color: #79c0ff; white-space: pre-wrap; }
    .feed {
      border: 1px solid #30363d;
      border-radius: 4px;
      padding: 12px;
      background: #161b22;
      max-height: 400px;
      overflow-y: auto;
      font-size: 0.9em;
    }
    .feed-item {
      border-left: 2px solid #30363d;
      padding-left: 8px;
      margin-bottom: 8px;
      padding-bottom: 8px;
    }
    .feed-item:last-child { margin-bottom: 0; }
    .feed-kind { color: #58a6ff; font-weight: bold; }
    .feed-text { color: #c9d1d9; }
    h2 { font-size: 1em; color: #8b949e; margin: 0 0 12px 0; }
  </style>
</head>
<body>
  <h1>papergraph</h1>
  <div id="banner"></div>
  <div id="lanes" class="lanes"></div>
  <h2>Findings Feed</h2>
  <div id="feed" class="feed"></div>
  <script>
    const laneStates = {};
    const feedEl = document.getElementById('feed');
    const lanesEl = document.getElementById('lanes');
    const bannerEl = document.getElementById('banner');

    function esc(s) {
      return String(s).replace(/[&<>"']/g, function(c) {
        return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c];
      });
    }

    function renderLanes() {
      lanesEl.innerHTML = '';
      for (const [name, data] of Object.entries(laneStates)) {
        const laneDiv = document.createElement('div');
        laneDiv.className = 'lane';
        const statusClass = data.status ? esc(data.status.toLowerCase()) : '';
        laneDiv.innerHTML = '<div class="lane-name">' + esc(name) + '</div>'
          + '<div class="lane-status ' + statusClass + '">' + esc(data.status || 'idle') + '</div>'
          + '<div class="lane-latest">' + esc(data.latest || '-') + '</div>';
        lanesEl.appendChild(laneDiv);
      }
    }

    function addFindingToFeed(kind, summary) {
      const item = document.createElement('div');
      item.className = 'feed-item';
      item.innerHTML = '<span class="feed-kind">[' + esc(kind) + ']</span> <span class="feed-text">' + esc(summary) + '</span>';
      feedEl.insertBefore(item, feedEl.firstChild);
    }

    const es = new EventSource('/events');
    es.onmessage = (e) => {
      try {
        const evt = JSON.parse(e.data);
        if (evt.event === 'agent_started') {
          laneStates[evt.agent] = { status: 'running', latest: '' };
          renderLanes();
        } else if (evt.event === 'agent_done') {
          laneStates[evt.agent] = { status: 'done', latest: evt.summary || 'done' };
          renderLanes();
        } else if (evt.event === 'agent_error') {
          laneStates[evt.agent] = { status: 'failed', latest: evt.error };
          renderLanes();
        } else if (evt.event === 'finding') {
          if (!laneStates[evt.agent]) {
            laneStates[evt.agent] = { status: 'running', latest: '' };
          }
          laneStates[evt.agent].latest = evt.summary;
          renderLanes();
          addFindingToFeed(evt.kind, evt.summary);
        }
      } catch (err) {
        console.error('parse error:', err);
      }
    };

    setInterval(async () => {
      try {
        const resp = await fetch('/state');
        const data = await resp.json();
        if (data.done) {
          bannerEl.className = 'banner done';
          bannerEl.textContent = 'Complete!';
        }
      } catch (err) {
        console.error('state poll error:', err);
      }
    }, 2000);
  </script>
</body>
</html>
"""
