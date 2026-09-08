(function () {
  'use strict';

  if (!document.querySelector('link[rel~="icon"]')) {
    const favicon = document.createElement('link');
    favicon.rel = 'icon';
    favicon.type = 'image/png';
    favicon.href = '/assets/img/favicon.png';
    document.head.appendChild(favicon);
  }

  const navbar = document.getElementById('navbar');
  const menuToggle = document.getElementById('mobileMenuToggle');
  const navMenu = document.getElementById('navMenu');
  const navLinks = document.querySelectorAll('.nav-menu a');

  function updateNavbar() {
    if (navbar) navbar.classList.toggle('scrolled', window.scrollY > 20);
  }

  updateNavbar();
  window.addEventListener('scroll', updateNavbar, { passive: true });

  if (menuToggle && navMenu) {
    menuToggle.addEventListener('click', function () {
      const open = navMenu.classList.toggle('open');
      menuToggle.setAttribute('aria-expanded', String(open));
    });

    navLinks.forEach(function (link) {
      link.addEventListener('click', function () {
        navMenu.classList.remove('open');
        menuToggle.setAttribute('aria-expanded', 'false');
      });
    });
  }

  function updateActiveLink() {
    const position = window.scrollY + 180;
    navLinks.forEach(function (link) {
      const id = link.getAttribute('href');
      if (!id || !id.startsWith('#')) return;
      const section = document.querySelector(id);
      if (!section) return;
      const active = position >= section.offsetTop && position < section.offsetTop + section.offsetHeight;
      link.classList.toggle('active', active);
    });
  }

  updateActiveLink();
  window.addEventListener('scroll', updateActiveLink, { passive: true });
})();
