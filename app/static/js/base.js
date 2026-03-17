// Global session expiry handling
(function () {
  'use strict';

  var _sessionExpired = false;
  var _loginUrl = '/auth/login';

  function showSessionExpiredModal() {
    if (_sessionExpired) return; // Only show once
    _sessionExpired = true;

    // Stop all tracked intervals (like sync polling)
    if (window._syncDashboardIntervals) {
      window._syncDashboardIntervals.forEach(function (id) { clearInterval(id); });
    }

    // Create modal backdrop
    var backdrop = document.createElement('div');
    backdrop.id = 'session-expired-backdrop';
    backdrop.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;'
      + 'background:rgba(0,0,0,0.5);z-index:9999;display:flex;'
      + 'align-items:center;justify-content:center;';

    backdrop.innerHTML =
      '<div class="card shadow" style="max-width:400px;margin:1rem;">'
      + '<div class="card-body text-center p-4">'
      + '<i class="fa-solid fa-clock-rotate-left fa-3x text-warning mb-3"></i>'
      + '<h5 class="card-title">Session Expired</h5>'
      + '<p class="card-text text-muted small mb-3">'
      + 'Your session has timed out. Please log in again to continue.'
      + '</p>'
      + '<a href="' + _loginUrl + '" class="btn btn-primary w-100">'
      + '<i class="fa-solid fa-right-to-bracket me-2"></i>Log In'
      + '</a>'
      + '</div></div>';

    document.body.appendChild(backdrop);

    // Prevent further fetch calls from making API requests
    console.log('[session] Session expired - API requests blocked');
  }

  // Intercept fetch to handle 401 responses
  var originalFetch = window.fetch;
  window.fetch = function (url, options) {
    var requestUrl = typeof url === 'string' ? url : url.url || '';

    // Skip non-API requests (static files, etc.)
    var isApiRequest = requestUrl.indexOf('/api/') !== -1
      || requestUrl.indexOf('/admin/api/') !== -1
      || requestUrl.indexOf('/auth/') === -1; // Most app routes require auth

    // Block all requests if session expired
    if (_sessionExpired && isApiRequest) {
      console.log('[session] Blocked API request to:', requestUrl);
      return Promise.resolve({
        ok: false,
        status: 401,
        json: function () { return Promise.resolve({ error: 'Session expired' }); },
        text: function () { return Promise.resolve('Session expired'); },
      });
    }

    return originalFetch.apply(this, arguments).then(function (response) {
      if (response.status === 401 && !_sessionExpired) {
        // Check if this is an API request (not a page navigation)
        if (isApiRequest) {
          console.log('[session] 401 response from:', requestUrl);
          showSessionExpiredModal();
        }
      }
      return response;
    });
  };

  // Also handle HTMX 401 responses (wait for DOM to be ready)
  if (document.body) {
    document.body.addEventListener('htmx:beforeSwap', function (evt) {
      if (evt.detail.xhr && evt.detail.xhr.status === 401) {
        showSessionExpiredModal();
        evt.preventDefault();
      }
    });
  } else {
    document.addEventListener('DOMContentLoaded', function () {
      document.body.addEventListener('htmx:beforeSwap', function (evt) {
        if (evt.detail.xhr && evt.detail.xhr.status === 401) {
          showSessionExpiredModal();
          evt.preventDefault();
        }
      });
    });
  }

})();

// Shared app-wide toast helper. Available anywhere that extends va_base.html,
// including coder/reviewer/site-PI screens and the admin console.

window.showAppToast = function (message, type, options) {
  var container = document.getElementById("app-toast-container");
  if (!container || !message) return;

  var config = options || {};
  var timeoutMs = typeof config.timeoutMs === "number" ? config.timeoutMs : 5000;
  var level = type || "info";

  var toast = document.createElement("div");
  toast.className =
    "alert alert-" + level + " shadow-sm border-0 mb-2 app-toast-message";
  toast.setAttribute("role", "alert");
  toast.style.pointerEvents = "auto";
  toast.style.minWidth = "320px";
  toast.style.maxWidth = "420px";
  toast.style.opacity = "0";
  toast.style.transform = "translateY(8px)";
  toast.style.transition = "opacity 180ms ease, transform 180ms ease";

  var closeButton =
    '<button type="button" class="btn-close ms-3" aria-label="Close"></button>';

  toast.innerHTML =
    '<div class="d-flex align-items-start">' +
    '<div class="me-2 mt-1"><i class="fas ' +
    ({
      success: "fa-circle-check",
      danger: "fa-circle-xmark",
      warning: "fa-triangle-exclamation",
      info: "fa-circle-info",
      primary: "fa-circle-info",
      secondary: "fa-circle-info",
    }[level] || "fa-circle-info") +
    '"></i></div>' +
    '<div class="flex-grow-1 small">' +
    message +
    "</div>" +
    closeButton +
    "</div>";

  function removeToast() {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(8px)";
    setTimeout(function () {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    }, 180);
  }

  toast.querySelector(".btn-close").addEventListener("click", removeToast);
  container.appendChild(toast);

  requestAnimationFrame(function () {
    toast.style.opacity = "1";
    toast.style.transform = "translateY(0)";
  });

  if (timeoutMs > 0) {
    setTimeout(removeToast, timeoutMs);
  }
};

function initImageViewer() {
  const image = document.getElementById("zoomableImage");
  const brightnessSlider = document.getElementById("brightnessSlider");
  const contrastSlider = document.getElementById("contrastSlider");

  // Only initialize if the image viewer elements exist on this page
  if (!image || !brightnessSlider || !contrastSlider) {
    return;
  }

  // Make cropper globally accessible
  window.cropper = new Cropper(image, {
    viewMode: 1,
    autoCrop: false,
    background: false,
    zoomable: true,
    movable: true,
    dragMode: "move",
    ready() {
      // Expose internal image for brightness/contrast
      window.cropperImage = image.nextElementSibling.querySelector("img");
    },
  });

  function updateFilters() {
    const brightness = brightnessSlider.value;
    const contrast = contrastSlider.value;
    if (window.cropperImage) {
      cropperImage.style.filter = `brightness(${brightness}%) contrast(${contrast}%)`;
    }
  }

  brightnessSlider.addEventListener("input", updateFilters);
  contrastSlider.addEventListener("input", updateFilters);

  window.resetAdjustments = function () {
    brightnessSlider.value = 100;
    contrastSlider.value = 100;
    if (window.cropperImage) {
      cropperImage.style.filter = "";
    }
    cropper.reset();
  };
}
