/* ============================================================
   Smart Resource Allocation — Shared JS utilities
   ============================================================ */

(function () {
  // ----- Toast region ---------------------------------------------------
  let region;
  function ensureRegion() {
    if (!region) {
      region = document.createElement("div");
      region.className = "toast-region";
      region.setAttribute("aria-live", "polite");
      region.setAttribute("role", "status");
      document.body.appendChild(region);
    }
    return region;
  }

  const ICONS = {
    success: "✓",
    error:   "!",
    warn:    "⚠",
    info:    "i",
  };
  const TITLES = {
    success: "Success",
    error:   "Error",
    warn:    "Heads up",
    info:    "Info",
  };

  /**
   * Show a toast message.
   * @param {string} message
   * @param {('success'|'error'|'warn'|'info')} type
   * @param {{title?: string, duration?: number}} opts
   */
  window.toast = function (message, type = "info", opts = {}) {
    const root = ensureRegion();
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.setAttribute("role", "status");
    el.innerHTML = `
      <div class="toast-icon">${ICONS[type] || "i"}</div>
      <div class="toast-body">
        <p class="toast-title">${escapeHTML(opts.title || TITLES[type] || "Notice")}</p>
        <p class="toast-msg">${escapeHTML(message)}</p>
      </div>
      <button class="toast-close" aria-label="Close">×</button>
    `;
    root.appendChild(el);

    const close = () => {
      el.classList.add("leaving");
      el.addEventListener("animationend", () => el.remove(), { once: true });
    };
    el.querySelector(".toast-close").addEventListener("click", close);

    const duration = opts.duration ?? 4200;
    if (duration > 0) setTimeout(close, duration);
    return close;
  };

  // ----- Modal / confirm ------------------------------------------------

  /**
   * Show a confirmation modal. Returns a Promise<boolean>.
   * @param {{title:string, message:string, confirmText?:string, cancelText?:string,
   *          variant?:'danger'|'warn'|'info'|'success'}} opts
   */
  window.confirmDialog = function (opts) {
    return new Promise((resolve) => {
      const variant = opts.variant || "info";
      const iconChar = {
        danger: "!", warn: "⚠", info: "?", success: "✓"
      }[variant] || "?";

      const backdrop = document.createElement("div");
      backdrop.className = "modal-backdrop";
      backdrop.innerHTML = `
        <div class="modal" role="dialog" aria-modal="true">
          <div class="modal-head">
            <div class="modal-icon ${variant}">${iconChar}</div>
            <h3 class="modal-title">${escapeHTML(opts.title || "Are you sure?")}</h3>
          </div>
          <div class="modal-body">${escapeHTML(opts.message || "")}</div>
          <div class="modal-foot">
            <button class="btn btn-outline" data-act="cancel">${escapeHTML(opts.cancelText || "Cancel")}</button>
            <button class="btn ${variant === "danger" ? "btn-danger" : "btn-primary"}" data-act="ok">
              ${escapeHTML(opts.confirmText || "Confirm")}
            </button>
          </div>
        </div>
      `;
      document.body.appendChild(backdrop);

      const cleanup = (result) => {
        backdrop.classList.add("leaving");
        backdrop.addEventListener("animationend", () => {
          backdrop.remove();
          resolve(result);
        }, { once: true });
      };

      backdrop.addEventListener("click", (e) => {
        if (e.target === backdrop) cleanup(false);
      });
      backdrop.querySelector('[data-act="cancel"]').addEventListener("click", () => cleanup(false));
      backdrop.querySelector('[data-act="ok"]').addEventListener("click", () => cleanup(true));

      const escHandler = (e) => {
        if (e.key === "Escape") {
          document.removeEventListener("keydown", escHandler);
          cleanup(false);
        }
      };
      document.addEventListener("keydown", escHandler);

      // focus the confirm button
      setTimeout(() => backdrop.querySelector('[data-act="ok"]').focus(), 30);
    });
  };

  // ----- Fetch helpers --------------------------------------------------

  window.api = {
    async get(url) {
      // Cache-bust to guarantee the browser doesn't serve a stale list
      // after the user adds/edits/deletes records.
      const sep = url.includes("?") ? "&" : "?";
      const r = await fetch(url + sep + "_=" + Date.now(), {
        headers: { "Accept": "application/json" },
        cache: "no-store",
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new ApiError(data.error || "Request failed", r.status, data);
      return data;
    },
    async post(url, body) {
      const r = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify(body || {}),
        cache: "no-store",
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new ApiError(data.error || "Request failed", r.status, data);
      return data;
    },
    async del(url) {
      const r = await fetch(url, {
        method: "DELETE",
        headers: { "Accept": "application/json" },
        cache: "no-store",
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new ApiError(data.error || "Request failed", r.status, data);
      return data;
    },
  };

  class ApiError extends Error {
    constructor(message, status, payload) {
      super(message);
      this.status = status;
      this.payload = payload;
    }
  }
  window.ApiError = ApiError;

  // ----- Utils ----------------------------------------------------------

  function escapeHTML(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }
  window.escapeHTML = escapeHTML;

  window.fmtDate = function (iso) {
    if (!iso) return "—";
    const d = new Date(iso + (iso.endsWith("Z") ? "" : "Z"));
    if (isNaN(d)) return iso;
    return d.toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  };

  window.urgencyBar = function (level) {
    let html = '<span class="urgency-bar" title="Urgency ' + level + '/5">';
    for (let i = 1; i <= 5; i++) {
      html += `<span class="${i <= level ? "on-" + level : ""}"></span>`;
    }
    html += "</span>";
    return html;
  };

  // ----- Highlight active nav link -------------------------------------
  document.addEventListener("DOMContentLoaded", () => {
    const path = window.location.pathname;
    document.querySelectorAll(".nav-link").forEach((a) => {
      const href = a.getAttribute("href");
      if (href === path || (href !== "/" && path.startsWith(href))) {
        a.classList.add("active");
      } else if (href === "/" && path === "/") {
        a.classList.add("active");
      }
    });
  });
})();
