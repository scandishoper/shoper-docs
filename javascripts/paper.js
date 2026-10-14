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

  const toc = document.querySelector(".paper-toc");
  if (toc && "IntersectionObserver" in window) {
    const links = Array.from(toc.querySelectorAll('a[href^="#"]'));
    const targets = new Map();
    for (const link of links) {
      const heading = document.getElementById(decodeURIComponent(link.hash.slice(1)));
      if (heading) targets.set(heading, link);
    }
    function select(link) {
      for (const item of links) item.removeAttribute("aria-current");
      toc.querySelectorAll(".is-current").forEach(item => item.classList.remove("is-current"));
      link.setAttribute("aria-current", "location");
      let item = link.closest("li");
      while (item && toc.contains(item)) { item.classList.add("is-current"); item = item.parentElement.closest("li"); }
    }
    const observer = new IntersectionObserver(entries => {
      const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (visible.length) select(targets.get(visible[0].target));
    }, { rootMargin: "-5% 0px -65% 0px" });
    targets.forEach((link, heading) => observer.observe(heading));
    if (links.length) select(links[0]);
    links.forEach(link => link.addEventListener("click", () => select(link)));
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
