/*
 * Минимальный плеер-слой статус-страницы iptv-ru-monitor.
 *
 * Принципы (по решению о MVP):
 *  - никакого своего декодера: hls.js (лениво, с первого клика ▶) + нативный
 *    HLS на Safari/iOS;
 *  - умный выбор: поток с лучшим score/uptime кандидаты строит страница,
 *    плеер лишь проигрывает их по порядку;
 *  - авто-failover: fatal-ошибка сети/декодирования -> следующий кандидат
 *    с видимой причиной;
 *  - честный fallback: если ни один поток не заиграл (обычно у источника
 *    нет CORS-заголовков) — копирование URL и ссылки на внешний плеер.
 *
 * Публичное API: window.IptvPlayer.open({name, logo, candidates, playlistUrl})
 * candidates: [{url, score, level, uptime, source_id}] — уже отсортированы.
 */
(function () {
  "use strict";

  var HLS_SRC = "../assets/hls.light.min.js";
  var state = null; // { opts, index, hls, mediaRecovered, log[] }
  var hlsReady = null;

  function el(id) {
    return document.getElementById(id);
  }

  /* ---------- ленивая загрузка hls.js ---------- */

  function loadHls() {
    if (window.Hls) return Promise.resolve(window.Hls);
    if (!hlsReady) {
      hlsReady = new Promise(function (resolve, reject) {
        var s = document.createElement("script");
        s.src = HLS_SRC;
        s.onload = function () { resolve(window.Hls); };
        s.onerror = function () { reject(new Error("hls.js load failed")); };
        document.head.appendChild(s);
      });
    }
    return hlsReady;
  }

  /* ---------- утилиты ---------- */

  function fmtScore(s) { return s == null ? "—" : s; }
  function fmtUptime(u) { return u == null ? "—" : u + "%"; }

  function autoplay(video) {
    var p = video.play();
    if (p && p.catch) {
      p.catch(function () {
        // Браузер запретил автозапуск со звуком — гасим и даём включить вручную.
        video.muted = true;
        video.play().catch(function () { /* исчерпаемся через failover */ });
        logOnce("Браузер запретил автозапуск со звуком — включите звук в плеере.");
      });
    }
  }

  function log(msg) {
    if (!state) return;
    state.log.push(msg);
    if (state.log.length > 4) state.log.shift();
    var box = el("iptv-player-log");
    box.innerHTML = state.log
      .map(function (l) { return "<div>" + esc(l) + "</div>"; })
      .join("");
  }

  // Предыдущий hint не заставляем копиться: подменяем последний, если это hint.
  function logOnce(msg) {
    if (!state) return;
    if (state.log.length && state.log[state.log.length - 1].indexOf("Браузер") === 0) {
      state.log.pop();
    }
    log(msg);
  }

  function esc(s) {
    var d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  /* ---------- модалка ---------- */

  function open(opts) {
    if (!opts || !opts.candidates || !opts.candidates.length) return;
    close();
    state = { opts: opts, index: 0, hls: null, mediaRecovered: false, log: [] };
    el("iptv-player-logo").src = opts.logo || "";
    el("iptv-player-logo").style.display = opts.logo ? "" : "none";
    el("iptv-player-name").textContent = opts.name || "";
    el("iptv-player-playlist").href = opts.playlistUrl || "#";
    el("iptv-player-error").style.display = "none";
    el("iptv-player-log").innerHTML = "";
    el("iptv-player").style.display = "flex";
    document.addEventListener("keydown", onKey);
    play(0);
  }

  function close() {
    var overlay = el("iptv-player");
    if (overlay) overlay.style.display = "none";
    document.removeEventListener("keydown", onKey);
    stopPlayback();
    state = null;
  }

  function onKey(e) {
    if (e.key === "Escape") close();
  }

  function stopPlayback() {
    if (state && state.hls) {
      try { state.hls.destroy(); } catch (e) { /* уже разрушен */ }
      state.hls = null;
    }
    var v = el("iptv-player-video");
    if (v) {
      v.pause();
      v.removeAttribute("src");
      try { v.load(); } catch (e) { /* нет источника */ }
    }
  }

  /* ---------- воспроизведение и failover ---------- */

  function play(i) {
    if (!state) return;
    stopPlayback();
    state.mediaRecovered = false;
    state.index = i;
    var c = state.opts.candidates[i];
    var n = state.opts.candidates.length;
    el("iptv-player-status").innerHTML =
      "Поток <b>" + (i + 1) + "/" + n + "</b>" +
      " · score " + esc(fmtScore(c.score)) +
      " · uptime 30д " + esc(fmtUptime(c.uptime)) +
      " · источник " + esc(c.source_id || "—");
    el("iptv-player-copy").dataset.url = c.url;
    el("iptv-player-vlc").href = "vlc://" + c.url.replace(/^https?:\/\//, "");
    el("iptv-player-error").style.display = "none";

    var video = el("iptv-player-video");
    // Сначала лениво грузим hls.js, потом решаем путь: иначе при первом
    // открытии window.Hls ещё нет и плеер ошибочно уходит в нативную ветку.
    loadHls()
      .then(function (Hls) {
        if (!state) return;
        if (Hls && Hls.isSupported()) {
          hlsPlay(Hls, c, video);
        } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
          nativePlay(c, video);
        } else {
          exhausted("Браузер не поддерживает HLS-воспроизведение (нет MSE).");
        }
      })
      .catch(function () {
        // hls.js недоступен (например, битая сборка dist) — пробуем нативный путь.
        if (video.canPlayType("application/vnd.apple.mpegurl")) {
          nativePlay(c, video);
        } else {
          exhausted("Не удалось загрузить плеер (hls.js).");
        }
      });
  }

  function hlsPlay(Hls, c, video) {
    if (!state) return;
    var hls = new Hls({
      enableWorker: true,
      lowLatencyMode: false,
      backBufferLength: 30,
      manifestLoadingTimeOut: 12000,
      manifestLoadingMaxRetry: 2,
      levelLoadingTimeOut: 12000,
      fragLoadingTimeOut: 20000,
      fragLoadingMaxRetry: 4
    });
    state.hls = hls;
    hls.attachMedia(video);
    hls.on(Hls.Events.MEDIA_ATTACHED, function () { hls.loadSource(c.url); });
    hls.on(Hls.Events.MANIFEST_PARSED, function () { autoplay(video); });
    hls.on(Hls.Events.ERROR, function (evt, data) {
      if (!data || !data.fatal || !state) return;
      if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
        if (!state.mediaRecovered) {
          state.mediaRecovered = true;
          hls.recoverMediaError();
          return;
        }
        failover("ошибка декодирования");
      } else if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
        failover(describeNetworkError(data));
      } else {
        failover("ошибка плеера");
      }
    });
  }

  function describeNetworkError(data) {
    if (data.details === "manifestLoadError") {
      return "источник недоступен из браузера (нет CORS-заголовков, смешанный http или сеть)";
    }
    if (data.details === "manifestLoadTimeOut") {
      return "источник не отвечает";
    }
    return "сетевая ошибка источника";
  }

  function nativePlay(c, video) {
    video.src = c.url;
    autoplay(video);
    video.onerror = function () {
      if (state) failover("источник недоступен (нативный HLS)");
    };
  }

  function failover(reason) {
    if (!state) return;
    var n = state.opts.candidates.length;
    var next = state.index + 1;
    log("Поток " + (state.index + 1) + "/" + n + ": " + reason +
        (next < n ? " — переключаюсь на следующий…" : ""));
    stopPlayback();
    if (next < n) {
      play(next);
    } else {
      exhausted("Ни один из " + n + " поток(ов) канала не заиграл в браузере. " +
        "Чаще всего у источника нет CORS-заголовков — тогда скопируйте URL " +
        "или откройте канал во внешнем плеере через плейлист.");
    }
  }

  function exhausted(message) {
    if (!state) return;
    var box = el("iptv-player-error");
    box.textContent = message;
    box.style.display = "block";
  }

  /* ---------- кнопки ---------- */

  function copyUrl() {
    if (!state) return;
    var url = el("iptv-player-copy").dataset.url || "";
    var done = function () {
      var btn = el("iptv-player-copy");
      var old = btn.textContent;
      btn.textContent = "Скопировано ✓";
      setTimeout(function () { btn.textContent = old; }, 1500);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(done, function () { legacyCopy(url, done); });
    } else {
      legacyCopy(url, done);
    }
  }

  function legacyCopy(text, done) {
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); done(); } catch (e) { /* не вышло */ }
    document.body.removeChild(ta);
  }

  /* ---------- инициализация ---------- */

  document.addEventListener("DOMContentLoaded", function () {
    if (!el("iptv-player")) return; // страница без каталога
    el("iptv-player-close").addEventListener("click", close);
    el("iptv-player-next").addEventListener("click", function () {
      if (!state) return;
      play((state.index + 1) % state.opts.candidates.length);
    });
    el("iptv-player-copy").addEventListener("click", copyUrl);
    el("iptv-player").addEventListener("click", function (e) {
      if (e.target === el("iptv-player")) close();
    });
  });

  window.IptvPlayer = { open: open, close: close };
})();
