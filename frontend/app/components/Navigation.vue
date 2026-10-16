<template>
  <header class="nav" role="banner">
    <div class="nav__inner">
      <!-- Logo -->
      <a href="/" class="nav__logo font-display" aria-label="Genlab homepage">
        Genlab<span class="nav__logo-reg">®</span>
      </a>

      <!-- Desktop links -->
      <!-- <nav class="nav__links" aria-label="Main navigation">
        <a href="#work" class="nav__link">Work</a>
        <a href="#agency" class="nav__link">Agency</a>
        <a href="#careers" class="nav__link">Careers</a>
        <a href="#store" class="nav__link">Store</a>
      </nav> -->

      <!-- CTA -->
      <!-- <a href="#contact" class="nav__cta">Let's talk</a> -->

      <!-- Mobile toggle -->
      <button
        class="nav__burger"
        :aria-expanded="mobileOpen"
        aria-controls="mobile-menu"
        aria-label="Toggle navigation menu"
        @click="mobileOpen = !mobileOpen"
      >
        <span class="nav__burger-line" :class="{ open: mobileOpen }"></span>
        <span class="nav__burger-line" :class="{ open: mobileOpen }"></span>
      </button>
    </div>

    <!-- Mobile menu -->
    <Transition name="mobile-menu">
      <div
        v-if="mobileOpen"
        id="mobile-menu"
        class="nav__mobile"
        role="navigation"
        aria-label="Mobile navigation"
      >
        <a href="#work" class="nav__mobile-link" @click="mobileOpen = false">Work</a>
        <a href="#agency" class="nav__mobile-link" @click="mobileOpen = false">Agency</a>
        <a href="#careers" class="nav__mobile-link" @click="mobileOpen = false">Careers</a>
        <a href="#store" class="nav__mobile-link" @click="mobileOpen = false">Store</a>
        <a href="#contact" class="nav__mobile-cta" @click="mobileOpen = false">Let's talk</a>
      </div>
    </Transition>
  </header>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const mobileOpen = ref(false)
</script>

<style scoped>
.nav {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  z-index: 100;
  padding: 0 clamp(1.5rem, 4vw, 3.5rem);
  opacity: 1;
  transform: translateY(0);
  pointer-events: auto;
  transition:
    opacity 0.85s cubic-bezier(0.16, 1, 0.3, 1),
    transform 0.85s cubic-bezier(0.16, 1, 0.3, 1);
}

.nav--visible {
  opacity: 1;
  transform: translateY(0);
  pointer-events: auto;
}

.nav__inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 72px;
  max-width: 1600px;
  margin: 0 auto;
}

/* Logo */
.nav__logo {
  font-size: 1.25rem;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: #0f172a;
  transition: opacity 0.3s ease;
}

.nav__logo:hover {
  opacity: 0.8;
}

.nav__logo-reg {
  font-size: 0.65em;
  vertical-align: super;
  margin-left: 1px;
  color: #5B325B;
  opacity: 1;
}

/* Desktop links */
.nav__links {
  display: flex;
  gap: 2.5rem;
}

.nav__link {
  font-size: 0.875rem;
  font-weight: 500;
  color: #475569;
  letter-spacing: 0.01em;
  transition: color 0.3s ease;
  position: relative;
}

.nav__link::after {
  content: '';
  position: absolute;
  bottom: -4px;
  left: 0;
  width: 0;
  height: 2px;
  background: #5B325B;
  border-radius: 2px;
  transition: width 0.3s ease;
}

.nav__link:hover {
  color: #5B325B;
}

.nav__link:hover::after {
  width: 100%;
}

/* CTA */
.nav__cta {
  font-size: 0.875rem;
  font-weight: 500;
  color: #5B325B;
  padding: 0.5rem 1.25rem;
  border: 1px solid rgba(91, 50, 91, 0.35);
  background: rgba(255, 255, 255, 0.85);
  border-radius: 100px;
  box-shadow: 0 2px 8px rgba(91, 50, 91, 0.08);
  transition: all 0.3s ease;
}

.nav__cta:hover {
  background: #5B325B;
  color: #ffffff;
  border-color: #5B325B;
  box-shadow: 0 4px 16px rgba(91, 50, 91, 0.32);
}

/* Burger */
.nav__burger {
  display: none;
  flex-direction: column;
  gap: 6px;
  width: 28px;
  padding: 4px 0;
}

.nav__burger-line {
  display: block;
  width: 100%;
  height: 1.5px;
  background: #5B325B;
  transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
  transform-origin: center;
}

.nav__burger-line.open:first-child {
  transform: translateY(3.75px) rotate(45deg);
}

.nav__burger-line.open:last-child {
  transform: translateY(-3.75px) rotate(-45deg);
}

/* Mobile menu */
.nav__mobile {
  position: fixed;
  top: 72px;
  left: 0;
  width: 100%;
  background: rgba(255, 255, 255, 0.96);
  border-bottom: 1px solid rgba(91, 50, 91, 0.12);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  padding: 2rem clamp(1.5rem, 4vw, 3.5rem) 3rem;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.nav__mobile-link {
  font-size: 1.5rem;
  font-weight: 500;
  font-family: 'Outfit', sans-serif;
  color: #0f172a;
  transition: all 0.3s ease;
}

.nav__mobile-link:hover {
  color: #5B325B;
  opacity: 1;
}

.nav__mobile-cta {
  display: inline-block;
  margin-top: 1rem;
  font-size: 0.875rem;
  font-weight: 500;
  color: #ffffff;
  background: #5B325B;
  padding: 0.75rem 1.5rem;
  border-radius: 100px;
  text-align: center;
  box-shadow: 0 4px 14px rgba(91, 50, 91, 0.3);
  transition: all 0.3s ease;
}

.nav__mobile-cta:hover {
  background: #482448;
  box-shadow: 0 6px 18px rgba(91, 50, 91, 0.4);
}

/* Transition */
.mobile-menu-enter-active,
.mobile-menu-leave-active {
  transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
}

.mobile-menu-enter-from,
.mobile-menu-leave-to {
  opacity: 0;
  transform: translateY(-12px);
}

/* Responsive */
@media (max-width: 768px) {
  .nav__links,
  .nav__cta {
    display: none;
  }

  .nav__burger {
    display: flex;
  }
}
</style>
