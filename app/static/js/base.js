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
