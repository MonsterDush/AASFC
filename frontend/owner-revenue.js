// Legacy compatibility shim.
// The canonical owner revenue page is /owner-turnover.html.
// Keep this file tiny so there is no second implementation of the same screen.
window.location.replace("/owner-turnover.html" + window.location.search + window.location.hash);
