/* global chrome */
/* Scans the current page only after the user opens the extension. */
(function recruitmentAutofillContent() {
  const Matcher = globalThis.RecruitmentAutofillMatcher;
  const Grouping = globalThis.RecruitmentAutofillGrouping;
  const AtsAdapter = globalThis.RecruitmentAutofillAtsAdapter;
  const FORM_ITEM_SELECTORS = AtsAdapter.formItemSelectors({ hostname: location.hostname });
  const CONTROL_SELECTOR = [
    "input:not([type='hidden'])",
    "textarea",
    "select",
    "[role='combobox']",
    "[contenteditable='true']",
    ...AtsAdapter.supplementalControlSelectors({ hostname: location.hostname })
  ].join(", ");
  const FORM_ITEM_LABEL_SELECTOR = [
    ".form-item__text",
    ".ud-formily-item-label",
    "label",
    "[class*='form-item-label']",
    "[class*='formily-item-label']",
    "[class*='formItemLabel']",
    "[class*='filedName___']",
    "[class*='__label']"
  ].join(", ");

  const messageHandler = (message, _sender, sendResponse) => {
    if (message.type === "scan") {
      const fields = scanFields();
      const plan = Matcher.matchFields(fields, message.profile || {});
      highlight(plan);
      sendResponse({ ok: true, context: scanContext(fields), plan: sanitisePlan(plan), summary: Matcher.summarize(plan) });
      return;
    }
    if (message.type === "fill-safe") {
      const fields = scanFields();
      const plan = Matcher.matchFields(fields, message.profile || {});
      const context = scanContext(fields);
      const filled = context.state === "auth-required" ? [] : applySafe(plan);
      highlight(plan);
      sendResponse({
        ok: true,
        context,
        blockedReason: context.state === "auth-required" ? "当前是登录/验证码页面，已禁止自动填写" : "",
        filled,
        plan: sanitisePlan(plan),
        summary: Matcher.summarize(plan)
      });
    }
  };

  if (globalThis.__recruitmentAutofillMessageHandler) {
    try {
      chrome.runtime.onMessage.removeListener(globalThis.__recruitmentAutofillMessageHandler);
    } catch {
      // An older extension context may already be invalidated; registering the new handler is sufficient.
    }
  }
  globalThis.__recruitmentAutofillMessageHandler = messageHandler;
  chrome.runtime.onMessage.addListener(messageHandler);

  function scanFields() {
    const candidates = Array.from(document.querySelectorAll(CONTROL_SELECTOR));
    const described = candidates
      .filter(isCandidate)
      .map((element, index) => describeField(element, index));
    return Grouping.assignGroupIndices(Grouping.recoverSequentialGroups(described));
  }

  function scanContext(fields) {
    const scriptUrls = Array.from(document.scripts).map((script) => script.src).filter(Boolean);
    const buttonLabels = Array.from(document.querySelectorAll("button, [role='button']"))
      .map((button) => compact(button.innerText || button.textContent))
      .filter(Boolean);
    const sectionLabels = Array.from(document.querySelectorAll("h1, h2, h3, h4, p, [class*='section-title' i], [class*='module-title' i]"))
      .map((heading) => compact(heading.innerText || heading.textContent))
      .filter(Boolean);
    const pagination = paginationContext();
    return {
      engine: AtsAdapter.detectEngine({ bodyClass: document.body?.className || "", scriptUrls, hostname: location.hostname }),
      state: AtsAdapter.classifyPage({
        pathname: location.pathname,
        fieldLabels: fields.map((field) => field.label || field.placeholder),
        buttonLabels,
        sectionLabels: [...sectionLabels, ...(pagination?.pages || [])]
      }),
      pagination
    };
  }

  function paginationContext() {
    const tabs = Array.from(document.querySelectorAll(".left-tab .tab-item"));
    const activeIndex = tabs.findIndex((tab) => tab.classList.contains("active"));
    return AtsAdapter.detectPagination({
      hostname: location.hostname,
      tabTexts: tabs.map((tab) => compact(tab.innerText || tab.textContent)),
      activeIndex
    });
  }

  function currentPageLabel() {
    return paginationContext()?.currentPage || "";
  }

  function isCandidate(element) {
    if (element.closest("[aria-hidden='true']")) return false;
    if (element.disabled) return false;
    const customControl = customControlFor(element);
    if (element.readOnly && !AtsAdapter.isReadonlyCustomControl({
      readOnly: true,
      role: element.getAttribute("role") || "",
      className: `${element.className || ""} ${customControl?.className || ""}`
    })) return false;
    if (element.tagName === "INPUT" && ["button", "submit", "reset", "image"].includes(element.type)) return false;
    const owningCombobox = element.closest("[role='combobox']");
    if (owningCombobox && owningCombobox !== element) return false;
    if (element.closest(".phoenix-unmodeled-layer") && !element.closest(".form-item.form-item--phoenix")) return false;
    const item = closestFormItem(element);
    const placeholder = compact(element.getAttribute("placeholder") || "");
    if (AtsAdapter.shouldIgnoreControl({ hostname: location.hostname, placeholder })) return false;
    const meaningfulPlaceholder = placeholder && !/^(请输入|请选择)$/.test(placeholder);
    const hasSemanticHook = Boolean(
      item || element.labels?.length || element.getAttribute("aria-label") || element.name || element.id || meaningfulPlaceholder
    );
    if (!hasSemanticHook) return false;
    const box = element.getBoundingClientRect();
    const isCustomControl = element.getAttribute("role") === "combobox";
    return isCustomControl
      || AtsAdapter.allowZeroSizeControl({ inputType: element.type })
      || box.width > 0
      || box.height > 0;
  }

  function describeField(element, index) {
    const item = closestFormItem(element);
    const dataKey = element.getAttribute("data-cy") || item?.getAttribute("data-cy") || "";
    const contextText = compact(item?.innerText || "");
    const itemLabel = labelFromItem(element, item);
    const group = inferGroupHint(element, dataKey, contextText);
    return {
      index,
      selector: selectorFor(element),
      label: labelFor(element, item, itemLabel),
      formItemLabel: itemLabel,
      ariaLabel: element.getAttribute("aria-label") || "",
      placeholder: element.getAttribute("placeholder") || "",
      name: element.getAttribute("name") || "",
      id: element.id || "",
      dataKey,
      type: controlType(element, item),
      section: group.section || Matcher.inferSection(`${contextText} ${ancestorHints(element)} ${currentPageLabel()}`),
      explicitGroupIndex: group.explicitGroupIndex,
      recordKey: group.recordKey,
      currentValue: "value" in element ? element.value : element.innerText || "",
      element
    };
  }

  function closestFormItem(element) {
    const selector = FORM_ITEM_SELECTORS.join(", ");
    const candidates = [];
    let cursor = element.parentElement;
    for (let depth = 0; depth < 12 && cursor && cursor !== document.body; depth += 1, cursor = cursor.parentElement) {
      if (!cursor.matches(selector)) continue;
      const texts = itemTextCandidates(element, cursor);
      candidates.push({ element: cursor, depth, ...texts });
    }
    const chosenIndex = Grouping.chooseFormItemCandidate(candidates);
    return chosenIndex >= 0 ? candidates[chosenIndex].element : null;
  }

  function labelFor(element, item, itemLabel = labelFromItem(element, item)) {
    if (itemLabel && AtsAdapter.preferFormItemLabel({
      hostname: location.hostname,
      inputType: element.type,
      className: element.className || ""
    })) {
      return compact(itemLabel);
    }
    if (element.labels?.[0]?.innerText) return compact(element.labels[0].innerText);
    if (element.id) {
      const explicit = document.querySelector(`label[for="${cssEscape(element.id)}"]`);
      if (explicit?.innerText) return compact(explicit.innerText);
    }
    const placeholder = compact(element.getAttribute("placeholder") || "");
    const controlCount = item?.querySelectorAll(CONTROL_SELECTOR).length || 0;
    const primaryLabel = Grouping.choosePrimaryLabel({ itemLabel, placeholder, controlCount });
    return compact(primaryLabel || element.getAttribute("aria-label") || element.name || element.id);
  }

  function labelFromItem(element, item) {
    if (!item) return "";
    const { directTexts, semanticTexts } = itemTextCandidates(element, item);
    return Grouping.chooseItemLabel(directTexts, semanticTexts);
  }

  function itemTextCandidates(element, item) {
    const directTexts = Array.from(item.children || [])
      .filter((candidate) => !candidate.contains(element))
      .map((candidate) => compact(candidate.innerText || candidate.textContent));
    const semanticTexts = Array.from(item.querySelectorAll(FORM_ITEM_LABEL_SELECTOR))
      .map((candidate) => compact(candidate.innerText || candidate.textContent));
    return { directTexts, semanticTexts };
  }

  function inferGroupHint(element, dataKey, contextText) {
    const attributeHint = AtsAdapter.groupHintFromAttributes({
      hostname: location.hostname,
      dataKey,
      name: element.name || "",
      id: element.id || ""
    });
    if (attributeHint.section) return attributeHint;
    const keyed = String(dataKey).match(/(education|internship|workExperience|project|projects|language|award|scholarship)\[(\d+)]/i);
    if (keyed) return { section: normaliseSection(keyed[1]), explicitGroupIndex: Number(keyed[2]) };
    const hint = ancestorHints(element);
    const section = inferSiteSection(element)
      || inferSectionFromNearbyLabels(element)
      || Matcher.inferSection(`${contextText} ${hint} ${currentPageLabel()}`);
    const record = findRepeatedRecord(element, section);
    return { section, recordKey: record ? recordKeyFor(record, section) : "" };
  }

  function inferSiteSection(element) {
    const moduleSelector = AtsAdapter.moduleContainerSelector({ hostname: location.hostname });
    const titleSelector = AtsAdapter.moduleTitleSelector({ hostname: location.hostname });
    const sectionContainer = moduleSelector ? element.closest(moduleSelector) : null;
    const moduleTitle = sectionContainer && titleSelector
      ? compact(sectionContainer.querySelector(titleSelector)?.innerText || sectionContainer.querySelector(titleSelector)?.textContent)
      : "";
    const titledSection = Matcher.inferSection(moduleTitle);
    if (titledSection !== "unknown") return titledSection;
    let cursor = element;
    const maxDepth = AtsAdapter.sectionAncestorSearchDepth({ hostname: location.hostname });
    for (let depth = 0; depth < maxDepth && cursor && cursor !== document.body; depth += 1, cursor = cursor.parentElement) {
      const section = AtsAdapter.sectionFromContainerId({ hostname: location.hostname, containerId: cursor.id || "" });
      if (section) return section;
      const textSection = AtsAdapter.sectionFromContainerText({
        hostname: location.hostname,
        text: cursor.innerText || cursor.textContent || ""
      });
      if (textSection) return textSection;
    }
    return "";
  }

  function inferSectionFromNearbyLabels(element) {
    let cursor = closestFormItem(element) || element;
    for (let depth = 0; depth < 10 && cursor && cursor !== document.body; depth += 1, cursor = cursor.parentElement) {
      const section = Grouping.inferSectionFromLabels(labelsIn(cursor));
      if (section) return section;
    }
    return "";
  }

  const recordIds = new WeakMap();
  const nextRecordId = new Map();

  function recordKeyFor(record, section) {
    if (!recordIds.has(record)) {
      const next = nextRecordId.get(section) || 0;
      nextRecordId.set(section, next + 1);
      recordIds.set(record, `${section}:record-${next}`);
    }
    return recordIds.get(record);
  }

  function findRepeatedRecord(element, section) {
    if (!["education", "work", "project", "language", "publication", "patent", "competition", "scholarship", "award", "research"].includes(section)) return null;
    const siteSelector = AtsAdapter.recordContainerSelector({ hostname: location.hostname, section });
    const siteRecord = siteSelector ? element.closest(siteSelector) : null;
    if (siteRecord) return siteRecord;
    let cursor = closestFormItem(element) || element;
    for (let depth = 0; depth < 10 && cursor && cursor !== document.body; depth += 1, cursor = cursor.parentElement) {
      if (isSingleRecordContainer(cursor, section)) return cursor;
    }
    return null;
  }

  function isSingleRecordContainer(container, section) {
    return Grouping.isSingleRecordLabels(labelsIn(container), section);
  }

  function labelsIn(container) {
    const itemSelector = FORM_ITEM_SELECTORS.join(", ");
    const items = Array.from(container.querySelectorAll(itemSelector));
    const itemLabels = items.map((item) => {
      const control = item.querySelector(CONTROL_SELECTOR);
      return control ? labelFromItem(control, item) : "";
    }).filter(Boolean);
    if (itemLabels.length) return itemLabels;
    return Array.from(container.querySelectorAll(FORM_ITEM_LABEL_SELECTOR))
      .map((element) => compact(element.innerText || element.textContent))
      .filter(Boolean);
  }

  function normaliseSection(value) {
    if (/education/i.test(value)) return "education";
    if (/internship|work/i.test(value)) return "work";
    if (/project/i.test(value)) return "project";
    if (/language/i.test(value)) return "language";
    if (/award|scholarship/i.test(value)) return "award";
    if (/research/i.test(value)) return "research";
    return "unknown";
  }

  function ancestorHints(element) {
    const hints = [];
    let cursor = element;
    for (let depth = 0; depth < 7 && cursor; depth += 1, cursor = cursor.parentElement) {
      hints.push(typeof cursor.className === "string" ? cursor.className : "");
      hints.push(cursor.getAttribute?.("data-cy") || "");
      const heading = cursor.querySelector?.(":scope > h1, :scope > h2, :scope > h3, :scope > h4, :scope > [class*='title']");
      if (heading?.innerText) hints.push(heading.innerText);
    }
    return hints.join(" ");
  }

  function controlType(element, item) {
    const atsxControl = customControlFor(element);
    return AtsAdapter.controlType({
      tagName: element.tagName,
      inputType: element.type,
      role: element.getAttribute("role") || "",
      className: `${element.className || ""} ${atsxControl?.className || ""}`,
      itemClassName: item?.className || "",
      contentEditable: element.isContentEditable
    });
  }

  function customControlFor(element) {
    return element.closest(
      ".atsx-select, .ud__select, .el-select, .el-date-editor, ethnic-picker, .ethnicPicker, [class*='atsx-date-picker'], [class*='atsx-calendar-picker'], [class*='atsx-month-picker'], [class*='atsx-range-picker'], [class*='throne-biz-date-range-picker']"
    );
  }

  function selectorFor(element) {
    if (element.id) return `#${cssEscape(element.id)}`;
    const dataCy = element.getAttribute("data-cy");
    if (dataCy) return `[data-cy="${cssEscape(dataCy)}"]`;
    if (element.name) return `${element.tagName.toLowerCase()}[name="${cssEscape(element.name)}"]`;
    const path = [];
    let cursor = element;
    for (let depth = 0; depth < 5 && cursor && cursor !== document.body; depth += 1, cursor = cursor.parentElement) {
      const siblings = Array.from(cursor.parentElement?.children || []).filter((child) => child.tagName === cursor.tagName);
      path.unshift(`${cursor.tagName.toLowerCase()}:nth-of-type(${siblings.indexOf(cursor) + 1})`);
    }
    return path.join(" > ");
  }

  function applySafe(plan) {
    const filled = [];
    for (const item of plan.filter((entry) => entry.status === "safe")) {
      const element = item.field.element;
      if (!element || !document.contains(element)) continue;
      setNativeValue(element, String(item.value));
      filled.push({ path: item.path, label: item.field.label, score: item.score });
    }
    return filled;
  }

  function setNativeValue(element, value) {
    if (element.tagName === "SELECT") {
      const option = Array.from(element.options).find((candidate) => compact(candidate.textContent) === compact(value) || candidate.value === value);
      if (!option) return;
      element.value = option.value;
    } else {
      const prototype = element.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
      if (setter) setter.call(element, value);
      else element.value = value;
    }
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    element.dispatchEvent(new Event("blur", { bubbles: true }));
  }

  function highlight(plan) {
    document.querySelectorAll("[data-recruitment-autofill]").forEach((element) => {
      element.style.outline = "";
      element.removeAttribute("data-recruitment-autofill");
    });
    for (const item of plan) {
      const element = item.field.element;
      if (!element) continue;
      element.dataset.recruitmentAutofill = item.status;
      element.style.outline = item.status === "safe" ? "2px solid #16a34a" : item.status === "review" ? "2px solid #f59e0b" : "";
      element.style.outlineOffset = "2px";
    }
  }

  function sanitisePlan(plan) {
    return plan.map((item) => ({
      status: item.status,
      score: item.score,
      path: item.path,
      reason: item.reason,
      field: {
        label: item.field.label,
        formItemLabel: item.field.formItemLabel,
        section: item.field.section,
        groupIndex: item.field.groupIndex,
        groupConfidence: item.field.groupConfidence,
        groupSource: item.field.groupSource,
        recordKey: item.field.recordKey,
        type: item.field.type,
        dataKey: item.field.dataKey,
        name: item.field.name,
        id: item.field.id
      }
    }));
  }

  function compact(value) {
    return String(value || "").replace(/\s+/g, " ").replace(/[：:*]/g, "").trim();
  }

  function cssEscape(value) {
    return globalThis.CSS?.escape ? CSS.escape(value) : String(value).replace(/["\\]/g, "\\$&");
  }
})();
