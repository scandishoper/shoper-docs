window.MathJax = {
  tex: { inlineMath: [["\\(", "\\)"]], displayMath: [["\\[", "\\]"]], processEscapes: true },
  options: { ignoreHtmlClass: ".*|", processHtmlClass: "arithmatex" },
  startup: {
    ready: () => {
      // Older notes use single-line $$...$$ within lists. Arithmatex can
      // wrap those as inline math with one extra dollar on either side.
      document.querySelectorAll(".arithmatex").forEach(element => {
        const source = element.textContent.trim();
        if (source.startsWith("\\($") && source.endsWith("$\\)")) {
          element.textContent = "\\[" + source.slice(3, -3) + "\\]";
        }
      });
      MathJax.startup.defaultReady();
    }
  }
};
