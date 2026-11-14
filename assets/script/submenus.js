// Dropdowns in the navigation on small screens (below 960px, where the menu
// is a vertical list, see partials/_header.scss): a click on a parent item
// opens or closes its dropdown. The class "open" is used for that; "active"
// marks the current page and its parent.
document.addEventListener('DOMContentLoaded', function() {
  const small = window.matchMedia('(max-width: 959.98px)');
  const menuItems = document.querySelectorAll('.has-children > a');

  menuItems.forEach(item => {
    item.addEventListener('click', function(e) {
      if (!small.matches) return;
      e.preventDefault();
      const parent = this.parentElement;
      parent.classList.toggle('open');
      menuItems.forEach(other => {
        if (other !== this) other.parentElement.classList.remove('open');
      });
    });
  });

  // close dropdowns when clicking outside the navigation
  document.addEventListener('click', function(e) {
    if (!e.target.closest('nav')) {
      menuItems.forEach(item => item.parentElement.classList.remove('open'));
    }
  });
});
