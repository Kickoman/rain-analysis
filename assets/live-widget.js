/* Live rain-probability widget.
 *
 * Polls the backend's current-values endpoint and renders a small card on
 * the landing page. Ships DISABLED (base: null) until the backend has a
 * public hostname — with base unset the page is byte-for-byte identical
 * to the widget-free site for visitors.
 *
 * The API key below is a PUBLIC read-only key by design (decision in
 * issue #407): anything shipped to a browser is public, and protection
 * comes from the key's conservative per-key rate limits + rotation.
 * Rotating it requires a site redeploy.
 */
(function () {
  "use strict";

  var RAIN_API = {
    base: "https://www.kanstancin.net/rain-api", // null disables the widget
    key: "ra_live_7c5385ff1ac54f6c7e9a35236c479ecc",
    sensor: "sensor.rain_probability",
    pollSeconds: 45,
    staleAfterSeconds: 15 * 60
  };

  var container = document.getElementById("live-rain-widget");
  if (!container || !RAIN_API.base) return;

  var timer = null;

  function render(value, ageSeconds) {
    var age;
    if (ageSeconds < 90) {
      age = "just now";
    } else if (ageSeconds < 3600) {
      age = Math.round(ageSeconds / 60) + " min ago";
    } else {
      age = Math.round(ageSeconds / 3600) + " h ago";
    }
    var stale = ageSeconds > RAIN_API.staleAfterSeconds;
    container.innerHTML =
      '<div class="live-widget' + (stale ? " live-widget-stale" : "") + '">' +
      '<span class="live-widget-label">Live rain probability</span>' +
      '<span class="live-widget-value">' + Math.round(value) + "%</span>" +
      '<span class="live-widget-age">' + (stale ? "last seen " : "") + age + "</span>" +
      "</div>";
  }

  function hide() {
    // Graceful degradation: on any error the widget disappears entirely
    // rather than showing broken chrome. The next poll may bring it back.
    container.innerHTML = "";
  }

  function poll() {
    fetch(
      RAIN_API.base + "/api/v1/data/current?sensors=" + encodeURIComponent(RAIN_API.sensor),
      { headers: { "X-API-Key": RAIN_API.key } }
    )
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (data) {
        var row = data.values && data.values[0];
        if (!row || row.value === null || row.value === undefined) return hide();
        render(row.value, row.age_seconds || 0);
      })
      .catch(hide);
  }

  function start() {
    if (timer !== null) return;
    poll();
    timer = setInterval(poll, RAIN_API.pollSeconds * 1000);
  }

  function stop() {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  }

  // Don't burn requests while the tab is hidden
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) stop();
    else start();
  });

  start();
})();
