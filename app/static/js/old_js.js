// Script for mobile category toggle
document.addEventListener("DOMContentLoaded", function () {
  const toggleBtn = document.querySelector(".toggle-categories");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", function () {
      const categoriesPanel = document.querySelector(".categories-collapse");
      categoriesPanel.classList.toggle("show");

      const icon = this.querySelector("i");
      if (categoriesPanel.classList.contains("show")) {
        icon.classList.remove("fa-bars");
        icon.classList.add("fa-times");
        this.textContent = " Hide Categories";
        this.prepend(icon);
      } else {
        icon.classList.remove("fa-times");
        icon.classList.add("fa-bars");
        this.textContent = " Show Categories";
        this.prepend(icon);
      }
    });
  }
});

// Notes Panel Functionality - Fixed JSON Error
document.addEventListener("DOMContentLoaded", function () {
  // Get elements
  const notesTab = document.getElementById("notesTab");
  const notesPanel = document.getElementById("notesPanel");
  const closeNotes = document.getElementById("closeNotes");
  const saveNotes = document.getElementById("saveNotes");
  const notesContent = document.getElementById("notesContent");
  const notesHeader = document.querySelector(".notes-header h5");

  // Initialize localStorage with valid JSON if needed
  try {
    // Try to parse existing notes
    JSON.parse(localStorage.getItem("vaFormNotes"));
  } catch (e) {
    // If there's an error, reset to empty object
    console.log("Resetting corrupted notes storage");
    localStorage.setItem("vaFormNotes", "{}");
  }

  // Update these lines in your existing code
  function updateNotes() {
    // Get current SID
    const activeSidElement = document.getElementById("active-sid");
    const currentSid = activeSidElement ? activeSidElement.value : "";

    const formSidInfo = document.getElementById("formSidInfo");

    if (!currentSid) {
      // Keep header simple
      notesHeader.textContent = "Notes";
      formSidInfo.innerHTML =
        '<small class="text-muted">No form selected</small>';
      notesContent.value = "";
      notesContent.placeholder = "Please select a form first...";
      return;
    }

    // Keep header simple, just "Notes"
    notesHeader.textContent = "Notes";

    // Update SID info with the full SID in smaller text
    formSidInfo.innerHTML =
      '<small class="text-muted">Form ID:</small>' +
      '<small class="fw-semibold">' +
      currentSid +
      "</small>";

    // Rest of your code remains the same...
    let allNotes = {};
    try {
      allNotes = JSON.parse(localStorage.getItem("vaFormNotes") || "{}");
    } catch (e) {
      console.error("Error parsing notes:", e);
      localStorage.setItem("vaFormNotes", "{}");
    }

    notesContent.value = allNotes[currentSid] || "";
    notesContent.placeholder = "Add your notes here...";
  }

  // Save notes
  function saveCurrentNotes() {
    const activeSidElement = document.getElementById("active-sid");
    const currentSid = activeSidElement ? activeSidElement.value : "";

    if (!currentSid) {
      alert("No form selected. Please select a form first.");
      return;
    }

    // Get all notes with error handling
    let allNotes = {};
    try {
      allNotes = JSON.parse(localStorage.getItem("vaFormNotes") || "{}");
    } catch (e) {
      console.error("Error parsing notes:", e);
      // Reset to empty if corrupted
      localStorage.setItem("vaFormNotes", "{}");
      allNotes = {};
    }

    // Update notes for current SID
    allNotes[currentSid] = notesContent.value;

    // Save back to localStorage
    localStorage.setItem("vaFormNotes", JSON.stringify(allNotes));

    // Show notification
    showNotification(`Notes saved for ${currentSid}`);
  }

  // Function to show notification
  function showNotification(message) {
    // Remove any existing notification
    const existingNotification = document.querySelector(".notes-notification");
    if (existingNotification) {
      document.body.removeChild(existingNotification);
    }

    // Create notification element
    const notification = document.createElement("div");
    notification.className = "notes-notification";
    notification.textContent = message;
    document.body.appendChild(notification);

    // Display with animation
    setTimeout(() => {
      notification.classList.add("show");
      setTimeout(() => {
        notification.classList.remove("show");
        setTimeout(() => {
          if (notification.parentNode) {
            document.body.removeChild(notification);
          }
        }, 300);
      }, 2000);
    }, 50);
  }

  // Event listeners
  notesTab.addEventListener("click", function () {
    notesPanel.classList.add("active");
    updateNotes(); // Update notes when panel opens
  });

  closeNotes.addEventListener("click", function () {
    notesPanel.classList.remove("active");
  });

  saveNotes.addEventListener("click", saveCurrentNotes);

  // Listen for the "Load Form" button clicks to update notes
  document.addEventListener("click", function (e) {
    if (
      e.target.id === "load-form-btn" ||
      (e.target.tagName === "BUTTON" && e.target.innerText === "Load Form")
    ) {
      // Give a moment for the SID to be updated
      setTimeout(updateNotes, 500);
    }
  });
});

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
