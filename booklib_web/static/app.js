// booklib_web static/app.js - Pure vanilla JavaScript for interactions
document.addEventListener("DOMContentLoaded", function () {
  const csrfMeta = document.querySelector('meta[name="csrf-token"]');
  const csrfToken = csrfMeta ? csrfMeta.getAttribute("content") : "";

  // Handle status update
  const statusSelect = document.getElementById("detail-status-select");
  if (statusSelect) {
    statusSelect.addEventListener("change", async function () {
      const bookId = statusSelect.getAttribute("data-book-id");
      const status = statusSelect.value;
      try {
        const res = await fetch(`/api/books/${bookId}/status`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken,
          },
          body: JSON.stringify({ status: status || null }),
        });
        if (!res.ok) {
          const err = await res.json();
          alert(err.description || "Failed to update status.");
        }
      } catch (e) {
        alert("Error connecting to server.");
      }
    });
  }

  // Handle rating update
  const ratingButtons = document.querySelectorAll(".btn-rating");
  ratingButtons.forEach(btn => {
    btn.addEventListener("click", async function () {
      const bookId = btn.getAttribute("data-book-id");
      const rating = parseInt(btn.getAttribute("data-rating"), 10);
      try {
        const res = await fetch(`/api/books/${bookId}/rating`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken,
          },
          body: JSON.stringify({ rating: rating || null }),
        });
        if (res.ok) {
          ratingButtons.forEach(b => {
            const r = parseInt(b.getAttribute("data-rating"), 10);
            if (r <= rating) {
              b.classList.add("active");
            } else {
              b.classList.remove("active");
            }
          });
        }
      } catch (e) {
        alert("Error connecting to server.");
      }
    });
  });
});
