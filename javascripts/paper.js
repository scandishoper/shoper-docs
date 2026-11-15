/* Small enhancements; article lists and navigation work without JavaScript. */
(() => {
  const searchToggle = document.getElementById("__search");
  const searchButton = document.querySelector("[data-paper-search]");
  if (searchToggle && searchButton) {
    const query = document.querySelector('[data-md-component="search-query"]');
    const close = () => {
      searchToggle.checked = false;
      searchToggle.dispatchEvent(new Event("change", { bubbles: true }));
      searchButton.focus();
    };
    searchButton.addEventListener("click", () => {
      searchToggle.checked = true;
      searchToggle.dispatchEvent(new Event("change", { bubbles: true }));
      query?.focus();
    });
    // Material watches keyup; also support pasted text and IME input events.
    query?.addEventListener("input", () => query.dispatchEvent(new Event("keyup", { bubbles: true })));
    document.querySelector("[data-paper-search-close]")?.addEventListener("click", close);
    const dialog = document.querySelector('[data-md-component="search"]');
    dialog?.addEventListener("keydown", event => {
      if (event.key !== "Tab" || !searchToggle.checked) return;
      const controls = Array.from(dialog.querySelectorAll('input, button, a[href], [tabindex]')).filter(element => element.tabIndex >= 0 && element.getClientRects().length);
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && searchToggle.checked) {
        close();
      }
    });
  }

  // Add a language caption outside <code>, so copied source remains unchanged.
  document.querySelectorAll(".paper-body .highlight").forEach(block => {
    const language = Array.from(block.classList).find(name => name.startsWith("language-"))?.slice(9);
    if (!language || block.querySelector(".filename") || !block.querySelector("pre")) return;
    const label = document.createElement("div");
    label.className = "paper-code-label";
    label.textContent = language;
    label.setAttribute("aria-hidden", "true");
    block.prepend(label);
  });

  // Material derives code IDs from the nearest ancestor ID. Our article anchor
  // is shared by every block, so repair only collisions after the theme mounts.
  function repairCodeCopyTargets() {
    document.querySelectorAll(".paper-body pre").forEach((pre, index) => {
      const buttons = pre.querySelectorAll('[data-md-type="copy"][data-clipboard-target]');
      if (!buttons.length) return;
      if (!pre.id || document.getElementById(pre.id) !== pre) {
        let id = `__paper_code_${index + 1}`;
        while (document.getElementById(id)) id += "_";
        pre.id = id;
      }
      buttons.forEach(button => { button.dataset.clipboardTarget = `#${CSS.escape(pre.id)} > code`; });
    });
  }
  if (typeof document$ !== "undefined") {
    document$.subscribe(() => requestAnimationFrame(repairCodeCopyTargets));
  } else {
    requestAnimationFrame(repairCodeCopyTargets);
  }

  const tocs = Array.from(document.querySelectorAll(".paper-toc, .paper-mobile-toc"));
  const article = document.querySelector(".paper-article");
  if (tocs.length && article) {
    const links = tocs.flatMap(toc => Array.from(toc.querySelectorAll('a[href^="#"]')));
    const targets = new Map();
    for (const link of links) {
      const heading = document.getElementById(decodeURIComponent(link.hash.slice(1)));
      if (!heading) continue;
      if (!targets.has(heading)) targets.set(heading, []);
      targets.get(heading).push(link);
      link.addEventListener("click", () => select(heading));
    }
    let current;
    let positions = [];
    let scrollPending = false;
    let measurePending = false;
    function select(heading) {
      if (current === heading) return;
      current = heading;
      links.forEach(link => link.removeAttribute("aria-current"));
      tocs.forEach(toc => toc.querySelectorAll(".is-current").forEach(item => item.classList.remove("is-current")));
      for (const link of targets.get(heading) || []) {
        link.setAttribute("aria-current", "location");
        const toc = link.closest(".paper-toc, .paper-mobile-toc");
        let item = link.closest("li");
        while (item && toc.contains(item)) {
          item.classList.add("is-current");
          item = item.parentElement.closest("li");
        }
      }
    }
    function update() {
      scrollPending = false;
      // Keep the current section selected through long paragraphs and when
      // scrolling back upward. Geometry is measured only after layout changes.
      const readingLine = window.scrollY + Math.min(128, window.innerHeight * .2);
      let active = positions[0]?.heading;
      for (const item of positions) {
        if (item.top > readingLine) break;
        active = item.heading;
      }
      if (active) select(active);
    }
    function measure() {
      measurePending = false;
      positions = Array.from(targets.keys(), heading => ({ heading, top: heading.getBoundingClientRect().top + window.scrollY }));
      update();
    }
    function scheduleMeasure() {
      if (measurePending) return;
      measurePending = true;
      requestAnimationFrame(measure);
    }
    window.addEventListener("scroll", () => {
      if (scrollPending) return;
      scrollPending = true;
      requestAnimationFrame(update);
    }, { passive: true });
    window.addEventListener("resize", scheduleMeasure);
    window.addEventListener("load", scheduleMeasure);
    article.addEventListener("load", scheduleMeasure, true);
    article.querySelectorAll("details").forEach(detail => detail.addEventListener("toggle", scheduleMeasure));
    if ("ResizeObserver" in window) new ResizeObserver(scheduleMeasure).observe(article);
    document.fonts?.ready.then(scheduleMeasure);
    measure();
  }

  const comments = document.querySelector("[data-paper-comments]");
  if (comments) {
    const button = comments.querySelector("button");
    const status = comments.querySelector("[role=status]");
    const container = comments.querySelector(".giscus");
    const theme = () => document.body.dataset.mdColorScheme === "slate" ? "transparent_dark" : "light";
    button.addEventListener("click", () => {
      if (container.querySelector("script")) return;
      button.disabled = true;
      button.textContent = "正在加载评论…";
      const script = document.createElement("script");
      script.src = "https://giscus.app/client.js";
      script.async = true;
      script.crossOrigin = "anonymous";
      const attributes = { repo: "scandishoper/shoper-docs", "repo-id": "R_kgDORRSjbg", category: "General", "category-id": "DIC_kwDORRSjbs4C2iWN", mapping: "pathname", strict: "0", "reactions-enabled": "1", "emit-metadata": "0", "input-position": "bottom", theme: theme(), lang: "zh-CN" };
      Object.entries(attributes).forEach(([key, value]) => script.setAttribute(`data-${key}`, value));
      script.addEventListener("load", () => { button.hidden = true; status.textContent = "评论由 GitHub Discussions 提供。"; });
      script.addEventListener("error", () => { script.remove(); button.disabled = false; button.textContent = "重试加载评论"; status.textContent = "评论暂时无法加载，也可以通过下方链接前往 GitHub 交流。"; });
      container.appendChild(script);
    });
    new MutationObserver(() => {
      const frame = container.querySelector("iframe.giscus-frame");
      frame?.contentWindow?.postMessage({ giscus: { setConfig: { theme: theme() } } }, "https://giscus.app");
    }).observe(document.body, { attributes: true, attributeFilter: ["data-md-color-scheme"] });
  }
})();
