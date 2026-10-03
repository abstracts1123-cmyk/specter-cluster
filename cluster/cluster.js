/* SPECTER cluster: static, no build step. Talks only to the page's own origin. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const MAX_ALERTS = 5;
  const THREAT_RANGE_M = 800;
  const ARC_START = -135, ARC_SPAN = 270; // degrees clockwise from 12 o'clock

  const state = { units: "mph", alerts: [], sound: false, audio: null };

  // ---- dial geometry ----
  const polar = (r, deg) => {
    const a = (deg * Math.PI) / 180;
    return [r * Math.sin(a), -r * Math.cos(a)];
  };
  const arcPath = (r) => {
    const [x0, y0] = polar(r, ARC_START);
    const [x1, y1] = polar(r, ARC_START + ARC_SPAN);
    return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 1 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
  };
  const NS = "http://www.w3.org/2000/svg";
  const svgEl = (name, attrs, text) => {
    const el = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    if (text !== undefined) el.textContent = text;
    return el;
  };
  const scaleMax = () => (state.units === "kmh" ? 200 : 120);

  function drawTicks() {
    const g = $("ticks");
    g.replaceChildren();
    const max = scaleMax(), minor = state.units === "kmh" ? 10 : 5, major = state.units === "kmh" ? 20 : 20;
    for (let v = 0; v <= max; v += minor) {
      const isMajor = v % major === 0;
      const deg = ARC_START + (v / max) * ARC_SPAN;
      const [x0, y0] = polar(166, deg), [x1, y1] = polar(isMajor ? 152 : 159, deg);
      g.append(svgEl("line", { x1: x0, y1: y0, x2: x1, y2: y1, class: isMajor ? "tick" : "tick minor" }));
      if (isMajor) {
        const [tx, ty] = polar(138, deg);
        g.append(svgEl("text", { x: tx, y: ty, class: "tick-label" }, String(v)));
      }
    }
    for (const id of ["speed-track", "speed-arc"]) $(id).setAttribute("d", arcPath(126));
    for (const id of ["threat-track", "threat-arc"]) $(id).setAttribute("d", arcPath(108));
    $("unit").textContent = state.units === "kmh" ? "KMH" : "MPH";
  }

  const setArc = (id, frac) => {
    const pct = Math.max(0, Math.min(1, frac)) * 100;
    $(id).setAttribute("stroke-dasharray", `${pct.toFixed(1)} 100`);
  };

  // ---- sound: short local tones, only after a user gesture ----
  const TONES = {
    ADVISORY: [[660, 0.12]],
    NEAR: [[880, 0.1], [880, 0.1]],
    PASSING: [[1100, 0.08], [1100, 0.08], [1100, 0.08]],
    TRACKER: [[440, 0.15], [330, 0.2]],
  };
  function beep(name) {
    if (!state.sound || !state.audio) return;
    let t = state.audio.currentTime;
    for (const [freq, dur] of TONES[name] || []) {
      const osc = state.audio.createOscillator(), gain = state.audio.createGain();
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.15, t);
      gain.gain.exponentialRampToValueAtTime(0.001, t + dur);
      osc.connect(gain).connect(state.audio.destination);
      osc.start(t);
      osc.stop(t + dur);
      t += dur + 0.07;
    }
  }

  // ---- rendering ----
  const fmtTime = (ts) => new Date(ts * 1000).toTimeString().slice(0, 8);
  const cardinal = (b) => ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][Math.round(b / 45) % 8];
  const pad3 = (n) => String(Math.round(n)).padStart(3, "0");

  function renderStack() {
    const ol = $("stack");
    ol.replaceChildren();
    if (!state.alerts.length) {
      const li = document.createElement("li");
      li.className = "empty";
      li.textContent = "NO ALERTS";
      ol.append(li);
      return;
    }
    for (const a of state.alerts) {
      const li = document.createElement("li");
      li.className = a.level.toLowerCase();
      const time = document.createElement("time");
      time.textContent = fmtTime(a.ts);
      const lvl = document.createElement("b");
      lvl.textContent = a.level;
      const txt = document.createElement("span");
      txt.textContent = a.text + (a.distance_m != null ? ` · ${a.distance_m} m` : "");
      li.append(time, lvl, txt);
      ol.append(li);
    }
  }

  function addAlert(ev) {
    const d = ev.data;
    state.alerts.unshift({ ts: ev.ts, level: d.level, kind: d.kind, text: d.text, distance_m: d.distance_m });
    state.alerts.length = Math.min(state.alerts.length, MAX_ALERTS);
    renderStack();
    if (Date.now() / 1000 - ev.ts < 3) beep(d.kind === "tracker" ? "TRACKER" : d.level); // not on replay
  }

  const handlers = {
    hello(d) {
      state.units = d.units;
      $("banner").hidden = !d.sample;
      $("demo").hidden = !d.demo;
      $("synthetic").hidden = !d.survey_synthetic;
      $("fabric-label").textContent = d.plates_dropped ? "FABRIC (PLATES DROPPED)" : "FABRIC (PLATES LOCAL)";
      $("ble-note").textContent = d.ble_footnote;
      const explicit = localStorage.getItem("specter-theme") || new URLSearchParams(location.search).get("theme");
      if (!explicit) setTheme(d.theme);
      drawTicks();
    },
    gps(d) {
      $("speed").textContent = String(Math.round(d.speed));
      setArc("speed-arc", d.speed / scaleMax());
      if (d.course == null) {
        $("course").textContent = "---";
      } else {
        $("course").textContent = pad3(d.course);
        $("sweep").style.transform = `rotate(${d.course}deg)`;
      }
    },
    camera(d) {
      const dial = $("dial");
      dial.setAttribute("class", d.level.toLowerCase());
      $("level").textContent = d.level;
      $("ahead").textContent = String(d.ahead_count);
      const n = d.next;
      if (!n) {
        $("next-name").textContent = "— NONE AHEAD —";
        $("next-kind").textContent = "\u00a0";
        $("next-brg").textContent = "—";
        $("next-m").textContent = "—";
        setArc("threat-arc", 0);
        return;
      }
      $("next-name").textContent = n.operator || n.name || "UNNAMED";
      $("next-kind").textContent = n.kind.toUpperCase();
      $("next-brg").textContent = `${pad3(n.bearing)}° ${cardinal(n.bearing)}`;
      $("next-m").textContent = String(n.distance_m);
      setArc("threat-arc", 1 - n.distance_m / THREAT_RANGE_M);
    },
    alert: null, // handled separately so replayed snapshots never re-beep
    tracker() {},
    aircraft(d) {
      const tb = $("air-rows");
      tb.replaceChildren();
      for (const r of d.rows) {
        tb.append(row([r.label, r.icao, r.callsign || "—", r.alt_ft ?? "—", r.distance_m ?? "—"]));
      }
    },
    survey(d) {
      const tb = $("survey-rows");
      tb.replaceChildren();
      for (const r of d.rows) {
        tb.append(row([fmtTime(r.ts), r.bssid, r.ssid || "(hidden)", r.rssi ?? "—", r.channel ?? "—", r.note || ""]));
      }
    },
    status(d) {
      $("r-optic").textContent = d.optic;
      $("r-cortex").textContent = d.cortex;
      $("r-optic").classList.toggle("bad", d.optic === "DOWN");
      $("r-cortex").classList.toggle("bad", d.cortex === "DOWN");
      $("r-survey").textContent = `${d.survey_aps_min} aps/min`;
      $("r-ble").textContent = d.ble;
      $("r-air").textContent = String(d.air);
      $("r-fabric").textContent = String(d.fabric);
    },
  };

  function row(cells) {
    const tr = document.createElement("tr");
    for (const c of cells) {
      const td = document.createElement("td");
      td.textContent = String(c);
      tr.append(td);
    }
    return tr;
  }

  // ---- controls ----
  function setTheme(name) {
    document.documentElement.className = name === "day" ? "day" : "night";
    $("theme").textContent = name === "day" ? "NIGHT" : "DAY";
  }
  $("theme").addEventListener("click", () => {
    const next = document.documentElement.classList.contains("day") ? "night" : "day";
    localStorage.setItem("specter-theme", next);
    setTheme(next);
  });
  $("sound").addEventListener("click", () => {
    state.sound = !state.sound;
    if (state.sound && !state.audio) state.audio = new (window.AudioContext || window.webkitAudioContext)();
    $("sound").textContent = state.sound ? "SOUND ON" : "SOUND OFF";
  });
  const showView = (survey) => {
    $("gauge-view").hidden = survey;
    $("survey-view").hidden = !survey;
  };
  $("to-survey").addEventListener("click", () => showView(true));
  $("to-gauge").addEventListener("click", () => showView(false));

  // ---- websocket ----
  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => { $("link").textContent = "LINK OK"; };
    ws.onmessage = (m) => {
      let ev;
      try { ev = JSON.parse(m.data); } catch { return; }
      if (ev.type === "alert") addAlert(ev);
      else if (Object.hasOwn(handlers, ev.type) && handlers[ev.type]) handlers[ev.type](ev.data);
    };
    ws.onclose = () => {
      $("link").textContent = "LINK –";
      setTimeout(connect, 2000);
    };
  }

  const qTheme = new URLSearchParams(location.search).get("theme");
  if (qTheme) setTheme(qTheme);
  if (location.hash === "#survey") showView(true);
  drawTicks();
  renderStack();
  connect();
})();
