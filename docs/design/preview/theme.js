// Reference pages only: pick the theme from the address (#theme-dark or #theme-light),
// otherwise follow the system setting.
(function () {
  var asked = (location.hash.match(/theme-(light|dark)/) || [])[1];
  if (asked) document.documentElement.setAttribute('data-theme', asked);
})();
