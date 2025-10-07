// Script for mobile category toggle

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
