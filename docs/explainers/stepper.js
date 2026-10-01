/* Step-through widget, example loader and self-check shared by every explainer page. */
const Stepper = (() => {
  const canonical = (value) => {
    if (Array.isArray(value)) {
      return value.map(canonical).map((item) => JSON.stringify(item)).sort().map((text) => JSON.parse(text));
    }
    if (value !== null && typeof value === "object") {
      return Object.fromEntries(Object.entries(value).map(([name, item]) => [name, canonical(item)]).sort(([a], [b]) => (a < b ? -1 : 1)));
    }
    return value;
  };

  const example = () => JSON.parse(document.getElementById("example").textContent);

  const showProgram = (target) => {
    target.textContent = example().program;
  };

  const verify = (label, actual, expected) => {
    const seen = JSON.stringify(canonical(actual));
    const wanted = JSON.stringify(canonical(expected));
    if (seen === wanted) {
      return true;
    }
    const banner = document.createElement("div");
    banner.className = "banner-error";
    banner.textContent = `This page's model disagrees with its stated answer (${label}). Model: ${seen} Expected: ${wanted}`;
    document.querySelector("main").prepend(banner);
    return false;
  };

  const button = (text, action) => {
    const element = document.createElement("button");
    element.type = "button";
    element.textContent = text;
    element.addEventListener("click", action);
    return element;
  };

  const mount = (container, steps, render) => {
    container.replaceChildren();
    container.classList.add("stepper");
    const controls = document.createElement("div");
    controls.className = "controls";
    const counter = document.createElement("span");
    counter.className = "counter";
    const note = document.createElement("p");
    note.className = "note";
    const body = document.createElement("div");
    body.className = "body";
    let index = 0;
    let timer = 0;

    const stop = () => {
      clearInterval(timer);
      timer = 0;
      play.textContent = "Play";
    };
    const show = (next) => {
      index = Math.max(0, Math.min(steps.length - 1, next));
      counter.textContent = `step ${index + 1} of ${steps.length}`;
      note.textContent = steps[index].note;
      body.innerHTML = render(steps[index], index);
      back.disabled = index === 0;
      forward.disabled = index === steps.length - 1;
      if (index === steps.length - 1) {
        stop();
      }
    };
    const reset = button("Reset", () => { stop(); show(0); });
    const back = button("Back", () => { stop(); show(index - 1); });
    const forward = button("Next", () => { stop(); show(index + 1); });
    const play = button("Play", () => {
      if (timer) {
        stop();
        return;
      }
      if (index === steps.length - 1) {
        show(0);
      }
      play.textContent = "Pause";
      timer = setInterval(() => show(index + 1), 900);
    });

    controls.append(reset, back, forward, play, counter);
    container.append(controls, note, body);
    show(0);
  };

  const escape = (text) => String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

  return { mount, verify, example, showProgram, escape, canonical };
})();
