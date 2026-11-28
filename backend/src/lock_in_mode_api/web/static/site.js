/* The waitlist page (ADR 0037). No framework, no trackers: plain DOM and fetch.
 *
 * What the browser keeps (localStorage, this site only):
 *   lockin.waitlist  {code, key?}  your link code, and the private key to leave the list
 *   lockin.ref       the friend's code from ?r=, so it still counts if you join later
 *   lockin.source    ?s= from the bio link (tiktok, instagram...)
 *   lockin.visit     the day this browser last counted as a visit
 * Storage can be missing (private mode, blocked): every read and write is wrapped, and the
 * page still works, it just won't remember you.
 */
(function () {
  "use strict";

  var API = "/api/v1/waitlist";
  var $ = function (id) { return document.getElementById(id); };

  function load(name) {
    try { return window.localStorage.getItem(name); } catch (e) { return null; }
  }
  function save(name, value) {
    try {
      if (value === null) window.localStorage.removeItem(name);
      else window.localStorage.setItem(name, value);
    } catch (e) { /* the page still works without storage */ }
  }
  function loadJson(name) {
    try { return JSON.parse(load(name) || "null"); } catch (e) { return null; }
  }

  function send(method, path, body) {
    return fetch(API + path, {
      method: method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
      credentials: "omit"
    });
  }

  // --- where they came from --------------------------------------------------------
  var params = new URLSearchParams(window.location.search);
  if (params.get("r")) save("lockin.ref", params.get("r").slice(0, 16));
  if (params.get("s")) save("lockin.source", params.get("s").slice(0, 64));

  // One visit per browser per day: close to "people who opened the page".
  var today = new Date().toISOString().slice(0, 10);
  if (load("lockin.visit") !== today) {
    save("lockin.visit", today);
    send("POST", "/visits", { source: load("lockin.source") }).catch(function () {});
  }

  // --- the count ("1,240 people locked in"), only once it's a real crowd ------------
  send("GET", "/count").then(function (r) { return r.ok ? r.json() : null; }).then(function (data) {
    if (data && typeof data.count === "number") {
      $("count").textContent = data.count.toLocaleString("en-US") + " people locked in";
      $("count").hidden = false;
    }
  }).catch(function () {});

  // --- showing the spot ---------------------------------------------------------------
  function shareLink(code) {
    return window.location.origin + "/?r=" + encodeURIComponent(code);
  }

  function friendsLine(n) {
    if (n === 0) return "No friends joined with your link yet.";
    return n === 1 ? "1 friend joined with your link." : n + " friends joined with your link.";
  }

  function showSpot(spot, opts) {
    var link = shareLink(spot.referral_code);
    $("join").hidden = true;
    $("left-notice").hidden = true;
    $("status").hidden = false;
    $("status-title").textContent = opts.already ? "You're already on the list." : "You're in.";
    $("spot-number").textContent = "#" + spot.position.toLocaleString("en-US");
    $("spot-of").textContent = "of " + spot.on_list.toLocaleString("en-US");
    $("status-line").textContent = spot.in_top
      ? "You're in the top " + spot.top_spots + " right now. Stay there for an Android test invite before launch."
      : "The top " + spot.top_spots + " get an Android test invite before launch. Each friend who joins with your link moves you up.";
    $("friends").textContent = friendsLine(spot.friends_joined);
    $("share-link").value = link;
    var message = "I'm locking in. Join the Lock In Mode waitlist with my link: " + link;
    $("whatsapp").href = "https://wa.me/?text=" + encodeURIComponent(message);
    if (navigator.share) {
      $("native-share").hidden = false;
      $("native-share").onclick = function () {
        navigator.share({ title: "Lock In Mode", text: "I'm locking in. Join the waitlist with my link:", url: link }).catch(function () {});
      };
    }
    var hasKey = Boolean(opts.key);
    $("leave").hidden = !hasKey;
    $("no-key-line").hidden = hasKey;
    $("sticky").hidden = true;
  }

  function showForm() {
    $("status").hidden = true;
    $("join").hidden = false;
  }

  // Back on the page: show the spot as it is now (friends may have joined since).
  var saved = loadJson("lockin.waitlist");
  if (saved && saved.code) {
    send("GET", "/" + encodeURIComponent(saved.code)).then(function (r) {
      if (r.status === 404) { save("lockin.waitlist", null); showForm(); return null; }
      return r.ok ? r.json() : null;
    }).then(function (spot) {
      if (spot) showSpot(spot, { key: saved.key, already: false });
    }).catch(function () {});
  }

  // --- joining ------------------------------------------------------------------------
  var form = $("join-form");
  var emailInput = $("email");
  var button = $("join-button");
  var error = $("join-error");

  function fail(text) {
    error.textContent = text;
    error.hidden = false;
    button.disabled = false;
    button.textContent = "Lock me in";
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    error.hidden = true;
    emailInput.removeAttribute("aria-invalid");
    var email = emailInput.value.trim();
    if (!emailInput.checkValidity() || email === "") {
      emailInput.setAttribute("aria-invalid", "true");
      emailInput.focus();
      fail("That email doesn't look right. Check it and try again.");
      return;
    }
    var picked = form.querySelector('input[name="trains_at"]:checked');
    button.disabled = true;
    button.textContent = "Locking you in…";
    send("POST", "", {
      email: email,
      trains_at: picked ? picked.value : null,
      ref: load("lockin.ref"),
      source: load("lockin.source")
    }).then(function (r) {
      if (r.status === 201 || r.status === 200) return r.json();
      if (r.status === 422) throw new Error("That email doesn't look right. Check it and try again.");
      if (r.status === 429) throw new Error("Too many tries from this network. Wait a bit and try again.");
      throw new Error("Something went wrong on our side. Try again in a minute.");
    }).then(function (joined) {
      save("lockin.waitlist", JSON.stringify({ code: joined.referral_code, key: joined.key || null }));
      button.disabled = false;
      button.textContent = "Lock me in";
      showSpot(joined, { key: joined.key, already: joined.already_on_list });
      $("status").scrollIntoView({ block: "start" });
    }).catch(function (e) {
      fail(e instanceof TypeError ? "Couldn't reach the server. Check your connection and try again." : e.message);
    });
  });

  // --- copying the link ---------------------------------------------------------------
  $("copy-button").addEventListener("click", function () {
    var input = $("share-link");
    var done = function () {
      $("copy-button").textContent = "Copied";
      setTimeout(function () { $("copy-button").textContent = "Copy"; }, 1600);
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(input.value).then(done, function () { input.select(); });
    } else {
      input.select();
      try { document.execCommand("copy"); done(); } catch (e) { /* selected: they can copy */ }
    }
  });

  // --- leaving ------------------------------------------------------------------------
  $("leave-ask").addEventListener("click", function () {
    $("leave-confirm").hidden = false;
    $("leave-ask").hidden = true;
  });
  $("leave-no").addEventListener("click", function () {
    $("leave-confirm").hidden = true;
    $("leave-ask").hidden = false;
  });
  $("leave-yes").addEventListener("click", function () {
    var current = loadJson("lockin.waitlist");
    if (!current || !current.key) return;
    $("leave-yes").disabled = true;
    send("POST", "/leave", { key: current.key }).then(function (r) {
      $("leave-yes").disabled = false;
      if (r.status !== 204 && r.status !== 404) throw new Error("leave failed");
      save("lockin.waitlist", null);
      $("leave-confirm").hidden = true;
      $("leave-ask").hidden = false;
      form.reset();
      showForm();
      $("left-notice").hidden = false;
    }).catch(function () {
      $("leave-yes").disabled = false;
      $("leave-confirm").querySelector("p").textContent = "Couldn't reach the server. Try again.";
    });
  });

  // --- the sticky button on phones, once the form has scrolled away --------------------
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (entries) {
      var formVisible = entries[0].isIntersecting;
      $("sticky").hidden = formVisible || !$("status").hidden;
    }).observe($("join"));
  }
})();
