(() => {
  const body = document.body;
  if (!body) return;

  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const markReady = () => body.classList.add("is-ready");
  if (document.readyState === "complete" || document.readyState === "interactive") {
    requestAnimationFrame(markReady);
  } else {
    document.addEventListener("DOMContentLoaded", () => requestAnimationFrame(markReady), { once: true });
  }

  const pressables = document.querySelectorAll(".tab, .primary-btn, .secondary-btn, button");

  const addRipple = (element, event) => {
    if (prefersReducedMotion) return;

    const rect = element.getBoundingClientRect();
    const ripple = document.createElement("span");
    ripple.className = "interaction-ripple";

    let x = rect.width / 2;
    let y = rect.height / 2;

    if (event && typeof event.clientX === "number" && typeof event.clientY === "number") {
      x = event.clientX - rect.left;
      y = event.clientY - rect.top;
    }

    ripple.style.left = `${x}px`;
    ripple.style.top = `${y}px`;

    element.appendChild(ripple);
    ripple.addEventListener("animationend", () => ripple.remove(), { once: true });
  };

  pressables.forEach((element) => {
    element.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      element.classList.add("is-pressed");
      addRipple(element, event);
    });

    element.addEventListener("pointerup", () => element.classList.remove("is-pressed"));
    element.addEventListener("pointerleave", () => element.classList.remove("is-pressed"));
    element.addEventListener("blur", () => element.classList.remove("is-pressed"));

    element.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        element.classList.add("is-pressed");
      }
    });

    element.addEventListener("keyup", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        element.classList.remove("is-pressed");
      }
    });
  });

  const tabs = document.querySelectorAll(".tab[href]");
  tabs.forEach((tab) => {
    tab.addEventListener("click", (event) => {
      if (prefersReducedMotion) return;
      if (event.defaultPrevented) return;
      if (event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

      const href = tab.getAttribute("href");
      if (!href) return;

      const current = `${window.location.pathname}${window.location.search}`;
      if (href === current || href === window.location.pathname) return;

      event.preventDefault();

      body.classList.add("is-transitioning");
      tab.classList.add("is-active");

      window.setTimeout(() => {
        window.location.assign(href);
      }, 120);
    });
  });

  const comingSoonButton = document.querySelector(".coming-soon-btn");
  if (comingSoonButton) {
    const comingSoonLabel = comingSoonButton.querySelector(".coming-soon-label");
    const textTarget = comingSoonLabel || comingSoonButton;

    // Lock width so shorter replacement text does not shrink the button.
    comingSoonButton.style.minWidth = `${Math.ceil(comingSoonButton.getBoundingClientRect().width)}px`;

    if (comingSoonLabel) {
      comingSoonLabel.style.display = "inline-block";
    }

    const defaultLabel = (textTarget.textContent || "Coming Soon...").trim();
    const upcomingLabel = (comingSoonButton.dataset.upcomingText || "Upcoming").trim();
    let restoreTimer = null;

    const showUpcoming = () => {
      if (restoreTimer) {
        window.clearTimeout(restoreTimer);
      }

      textTarget.textContent = upcomingLabel;
      if (!prefersReducedMotion) {
        textTarget.animate(
          [
            { opacity: 0, transform: "translateX(14px)" },
            { opacity: 1, transform: "translateX(0)" },
          ],
          {
            duration: 220,
            easing: "cubic-bezier(0.22, 0.8, 0.18, 1)",
            fill: "both",
          }
        );
      }

      restoreTimer = window.setTimeout(() => {
        textTarget.textContent = defaultLabel;
      }, 800);
    };

    comingSoonButton.addEventListener("click", (event) => {
      event.preventDefault();
      showUpcoming();
    });
  }

  const qaDropdowns = document.querySelectorAll(".qa-dropdown");
  qaDropdowns.forEach((dropdown) => {
    const summary = dropdown.querySelector("summary");
    const content = dropdown.querySelector(".qa-dropdown-content");
    if (!summary || !content) return;

    const replayAnimation = () => {
      summary.classList.remove("qa-animate");
      content.classList.remove("qa-animate");
      void summary.offsetWidth;
      void content.offsetWidth;
      summary.classList.add("qa-animate");
      content.classList.add("qa-animate");
    };

    dropdown.addEventListener("toggle", () => {
      if (dropdown.open) {
        replayAnimation();
      } else {
        summary.classList.remove("qa-animate");
        content.classList.remove("qa-animate");
      }
    });
  });
})();
