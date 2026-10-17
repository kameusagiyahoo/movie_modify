/* Responsive workspace for iPhone touch and PC mouse/keyboard.
   No external assets or API services; uses the existing Movie Modify editor. */
(function (global) {
  "use strict";
  const $ = id => document.getElementById(id);
  const mobile = () => matchMedia("(max-width: 900px)").matches;
  let zoom = 1;
  let activeProject = null;
  let playheadElement = null;

  function closeLibrary() {
    document.body.classList.remove("library-open");
    const trigger = $("mobileLibraryToggle");
    if (trigger) trigger.setAttribute("aria-expanded", "false");
  }
  function init() {
    const header = document.querySelector(".shell > header");
    if (!header || $("mobileLibraryToggle")) return;
    const trigger = document.createElement("button");
    trigger.id = "mobileLibraryToggle";
    trigger.className = "mobile-library";
    trigger.type = "button";
    trigger.textContent = "素材・履歴";
    trigger.setAttribute("aria-controls", "libraryPanel");
    trigger.setAttribute("aria-expanded", "false");
    trigger.addEventListener("click", () => {
      const nowOpen = !document.body.classList.contains("library-open");
      document.body.classList.toggle("library-open", nowOpen);
      trigger.setAttribute("aria-expanded", String(nowOpen));
    });
    header.append(trigger);
    const aside = document.querySelector(".layout > aside");
    if (aside) {
      aside.id = "libraryPanel";
      aside.setAttribute("aria-label", "動画の読み込みとプロジェクト一覧");
    }
    const shade = document.createElement("button");
    shade.type = "button";
    shade.className = "library-shade";
    shade.id = "libraryShade";
    shade.setAttribute("aria-label", "素材一覧を閉じる");
    shade.onclick = closeLibrary;
    document.body.append(shade);
    document.addEventListener("keydown", event => {
      if (event.key === "Escape") {
        closeLibrary();
        return;
      }
      if (!activeProject || mobile()) return;
      if (event.metaKey || event.ctrlKey || event.altKey || event.repeat) return;
      const el = document.activeElement;
      if (el && (el.matches("input,textarea,select,button,a,[contenteditable]") ||
                 el.closest("[contenteditable=true]"))) return;
      const video = $("player");
      if (!video) return;
      if (event.code === "Space") {
        event.preventDefault();
        const toggle = $("livePlay");
        if (toggle) toggle.click();
        else if (video.paused) video.play().catch(() => {});
        else video.pause();
      } else if (event.code === "KeyS") {
        event.preventDefault();
        $("split")?.click();
      } else if (event.code === "ArrowLeft" || event.code === "ArrowRight") {
        event.preventDefault();
        const delta = event.code === "ArrowLeft" ? -5 : 5;
        video.currentTime = Math.max(0, Math.min(activeProject.duration - .02, video.currentTime + delta));
      }
    });
  }

  function switchTab(name) {
    const editor = $("editor");
    if (!editor || !["timeline", "cut", "export"].includes(name)) return;
    editor.dataset.mobileTab = name;
    editor.querySelectorAll(".mobile-tabs [data-tab]").forEach(button => {
      button.setAttribute("aria-selected", String(button.dataset.tab === name));
    });
    if (mobile()) {
      const heading = editor.querySelector(".mobile-tabs");
      if (heading) heading.scrollIntoView({block: "nearest", behavior: "auto"});
    }
  }

  function mount(project) {
    init();
    activeProject = project;
    zoom = 1;
    playheadElement = null;
    closeLibrary();
    document.body.classList.add("has-project");
    const editor = $("editor");
    if (!editor) return;
    editor.classList.add("has-editor");
    editor.dataset.mobileTab = "timeline";
    const blocks = Array.from(editor.children).filter(node => node.matches("section.panel"));
    if (blocks.length < 4) return;
    const [viewer, cut, timeline, output] = blocks;
    viewer.classList.add("viewer-panel");
    cut.classList.add("cut-panel");
    timeline.classList.add("timeline-panel");
    output.classList.add("export-panel");

    const primary = document.createElement("div");
    primary.className = "editor-column primary-column";
    const secondary = document.createElement("div");
    secondary.className = "editor-column secondary-column";
    primary.append(viewer, timeline);
    secondary.append(cut, output);

    const tabs = document.createElement("nav");
    tabs.className = "mobile-tabs";
    tabs.setAttribute("aria-label", "編集機能");
    tabs.setAttribute("role", "tablist");
    tabs.innerHTML = [
      ["timeline", "タイムライン"],
      ["cut", "自動カット"],
      ["export", "書き出す"]
    ].map(([id, label]) =>
      '<button type="button" role="tab" data-tab="' + id +
      '" aria-selected="' + (id === "timeline") + '">' + label + '</button>'
    ).join("");
    tabs.querySelectorAll("button").forEach(button => {
      button.onclick = () => switchTab(button.dataset.tab);
    });

    const actions = document.createElement("nav");
    actions.className = "mobile-actions";
    actions.setAttribute("aria-label", "すばやく編集");
    actions.innerHTML =
      '<button type="button" data-command="split">分割</button>' +
      '<button type="button" data-command="scenery">景色</button>' +
      '<button type="button" data-command="toggle">残す／カット</button>' +
      '<button type="button" class="primary" data-command="save">保存</button>';
    const sceneButton = actions.querySelector('[data-command="scenery"]');
    if (project.projection !== "equirect") {
      sceneButton.textContent = "自動カット";
    }
    actions.querySelectorAll("button").forEach(button => {
      button.onclick = () => {
        const key = button.dataset.command;
        if (key === "scenery" && project.projection !== "equirect") {
          switchTab("cut"); return;
        }
        const id = {split: "split", scenery: "sceneryHere", toggle: "toggle", save: "save"}[key];
        const command = $(id);
        if (command && !command.disabled) {
          command.click();
          if (key === "scenery") switchTab("timeline");
        }
      };
    });

    editor.replaceChildren(primary, secondary, tabs, actions);
    const track = $("timeline");
    if (track && !track.parentElement.classList.contains("timeline-scroll")) {
      const viewport = document.createElement("div");
      viewport.id = "timelineViewport";
      viewport.className = "timeline-scroll";
      viewport.tabIndex = 0;
      viewport.setAttribute("aria-label", "拡大縮小できるタイムライン。左右へスクロール可能");
      track.parentNode.insertBefore(viewport, track);
      viewport.appendChild(track);
      const panel = document.createElement("div");
      panel.className = "zoom-panel";
      panel.innerHTML =
        '<div class="zoom-group"><span class="zoom-label">タイムライン</span>' +
        '<button id="zoomOut" type="button" aria-label="縮小">−</button>' +
        '<span id="zoomLabel" class="zoom-label">1×</span>' +
        '<button id="zoomIn" type="button" aria-label="拡大">＋</button></div>' +
        '<span class="zoom-help">拡大後は左右にスクロール</span>';
      viewport.parentElement.insertBefore(panel, viewport);
      $("zoomOut").onclick = () => changeZoom(zoom / 2);
      $("zoomIn").onclick = () => changeZoom(zoom * 2);
      const hint = document.createElement("p");
      hint.className = "timeline-hint";
      hint.textContent = "タップまたはクリックで再生位置を移動。区間の編集は下の一覧からも選べます。";
      viewport.after(hint);
    }
    decorate();
  }

  function changeZoom(next) {
    zoom = Math.max(1, Math.min(16, next));
    const label = $("zoomLabel");
    if (label) label.textContent = zoom + "×";
    const inButton = $("zoomIn"), outButton = $("zoomOut");
    if (inButton) inButton.disabled = zoom === 16;
    if (outButton) outButton.disabled = zoom === 1;
    const track = $("timeline");
    if (!track) return;
    track.style.width = (zoom * 100) + "%";
    updatePlayhead(true);
  }
  function updatePlayhead(center = false) {
    if (!activeProject || !playheadElement) return;
    const video = $("player"), track = $("timeline");
    const viewport = $("timelineViewport");
    if (!video || !track || !viewport) return;
    const relative = Math.min(1, Math.max(0, video.currentTime / activeProject.duration));
    playheadElement.style.left = (relative * 100) + "%";
    if (!center && (video.paused || zoom === 1)) return;
    const x = relative * track.clientWidth;
    if (center || x < viewport.scrollLeft + 18 || x > viewport.scrollLeft + viewport.clientWidth - 18) {
      viewport.scrollLeft = Math.max(0, x - viewport.clientWidth * .5);
    }
  }
  function decorate(project) {
    if (project) activeProject = project;
    const track = $("timeline");
    if (!track || !activeProject || !track.closest(".has-editor")) return;
    if (!track.parentElement.classList.contains("timeline-scroll")) return;
    track.style.width = (zoom * 100) + "%";
    if (!$("timelinePlayhead")) {
      playheadElement = document.createElement("div");
      playheadElement.id = "timelinePlayhead";
      playheadElement.className = "playhead";
      playheadElement.setAttribute("aria-hidden", "true");
      track.append(playheadElement);
    } else {
      playheadElement = $("timelinePlayhead");
    }
    track.querySelectorAll(".bar").forEach(bar => {
      if (bar.dataset.preciseSeek) return;
      bar.dataset.preciseSeek = "1";
      bar.addEventListener("click", event => {
        // Original bar handler selects the segment; refine its seek position.
        const index = Number(bar.dataset.i);
        const segment = activeProject.segments[index];
        const video = $("player");
        if (!segment || !video) return;
        const rect = bar.getBoundingClientRect();
        const fraction = Math.max(0, Math.min(1, (event.clientX - rect.left) / Math.max(rect.width, 1)));
        video.currentTime = Math.min(activeProject.duration - .02,
          segment.start + fraction * (segment.end - segment.start));
        updatePlayhead();
      });
    });
    if (track.dataset.playheadWatcher !== "1") {
      track.dataset.playheadWatcher = "1";
      const video = $("player");
      if (video) {
        video.addEventListener("timeupdate", () => updatePlayhead());
        video.addEventListener("seeked", () => updatePlayhead());
      }
    }
    updatePlayhead();
  }

  global.MovieModifyUI = {init, mount, decorate, closeLibrary, switchTab};
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, {once: true});
  } else init();
})(window);
