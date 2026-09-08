(function () {
  'use strict';

  if (!document.querySelector('link[rel~="icon"]')) {
    const favicon = document.createElement('link');
    favicon.rel = 'icon';
    favicon.type = 'image/png';
    favicon.href = '/assets/img/favicon.png';
    document.head.appendChild(favicon);
  }

  document.querySelectorAll('form[action*="your-form-id"]').forEach(function (form) {
    form.action = 'https://formsubmit.co/contact@cylatic.com';
    form.method = 'POST';
    const fields = [
      ['_subject', 'New Cylatic website enquiry'],
      ['_captcha', 'true'],
      ['_template', 'table'],
      ['_next', 'https://cylatic.com/contact/?sent=1']
    ];
    fields.forEach(function (item) {
      if (!form.querySelector('input[name="' + item[0] + '"]')) {
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = item[0];
        input.value = item[1];
        form.appendChild(input);
      }
    });
  });

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
