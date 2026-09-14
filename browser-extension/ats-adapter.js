/* Pure ATS fingerprints and control classification. No DOM access. */
(function exposeAtsAdapter(root) {
  const FORM_ITEM_SELECTORS = [
    ".ud-formily-item",
    ".form-item.form-item--phoenix",
    ".form-item",
    ".atsx-form-item",
    ".ant-form-item",
    ".el-form-item",
    ".ivu-form-item",
    ".chose-container",
    "[class*='apply-field-']"
  ];

  const TP_LINK_FORM_ITEM_SELECTORS = [
    "#information .name",
    "#information .credit",
    "#information .folk",
    "#information .phone",
    "#information .mail",
    "#information .emergency",
    "#education .degree",
    "#education .time",
    "#education .country",
    "#education .info",
    "#education .score",
    "#education .rank",
    "#language .skill1",
    "#language .skill2",
    "#more .source",
    "#more .info",
    "#more .code"
  ];

  const TP_LINK_SECTIONS = {
    education: "education",
    practice: "work",
    project: "project",
    award: "award",
    language: "language"
  };

  const TP_LINK_RECORD_SELECTORS = {
    education: "#education .progress > .view1",
    work: "#practice .progress > .view1",
    project: "#project .progress > .view1",
    award: "#award .progress > .view1"
  };

  const JD_SECTION_IDS = {
    info: "basic",
    edu: "education",
    experience: "work",
    program: "project",
    honor: "award",
    thesis: "publication",
    patent: "patent"
  };

  function compact(value) {
    return String(value || "").replace(/\s+/g, " ").replace(/[：:*]/g, "").trim();
  }

  function detectEngine({ bodyClass = "", scriptUrls = [], hostname = "" } = {}) {
    const scripts = scriptUrls.join(" ");
    if (/maker\.haier\.net$/i.test(hostname)) return "haier-campus";
    if (/jobs\.hisense\.com$/i.test(hostname) || /ux-recruitment-portal-2022-form-pc/i.test(scripts)) {
      return "beisen-phoenix";
    }
    if (/campus\.jd\.com$/i.test(hostname)) return "jd-campus";
    if (/career\.sicarrier\.com$/i.test(hostname)) return "sicarrier-element";
    if (/hr\.tp-link\.com\.cn$/i.test(hostname)) return "tplink-angular";
    if (/career\.honor\.com$/i.test(hostname)) return "honor-career";
    if (/saas-career/i.test(bodyClass) || /atsx-throne\/hire-fe-prod\/portal\/saas-career/i.test(scripts)) {
      return "feishu-saas-career";
    }
    if (/mokahr|moka/i.test(`${bodyClass} ${scripts}`)) return "moka";
    return "generic";
  }

  function formItemSelectors({ hostname = "" } = {}) {
    if (/hr\.tp-link\.com\.cn$/i.test(hostname)) return [...FORM_ITEM_SELECTORS, ...TP_LINK_FORM_ITEM_SELECTORS];
    if (/campus\.jd\.com$/i.test(hostname)) return [...FORM_ITEM_SELECTORS, "[class*='fieldItem___']"];
    return [...FORM_ITEM_SELECTORS];
  }

  function sectionFromContainerId({ hostname = "", containerId = "" } = {}) {
    if (/jobs\.hisense\.com$/i.test(hostname)) {
      if (/DeliveryIntention/i.test(containerId)) return "preference";
      if (/PersonProfile/i.test(containerId)) return "basic";
      if (/ApplicantEducation/i.test(containerId)) return "education";
      if (/PerfectLang/i.test(containerId)) return "language";
      if (/ApplicantProject/i.test(containerId)) return "project";
      if (/ApplicantInternship/i.test(containerId)) return "work";
      if (/PerfectAwards/i.test(containerId)) return "award";
      if (/PerfectQuestion/i.test(containerId)) return "basic";
    }
    if (/hr\.tp-link\.com\.cn$/i.test(hostname)) return TP_LINK_SECTIONS[containerId] || "";
    if (/campus\.jd\.com$/i.test(hostname)) return JD_SECTION_IDS[containerId] || "";
    return "";
  }

  function recordContainerSelector({ hostname = "", section = "" } = {}) {
    if (/jobs\.hisense\.com$/i.test(hostname)) return ".form";
    if (/hr\.tp-link\.com\.cn$/i.test(hostname)) return TP_LINK_RECORD_SELECTORS[section] || "";
    if (/career\.honor\.com$/i.test(hostname)) return ".form-cell-inner";
    if (/campus\.jd\.com$/i.test(hostname)) return "[class*='formGroupItem___']";
    return "";
  }

  function moduleContainerSelector({ hostname = "" } = {}) {
    if (/career\.honor\.com$/i.test(hostname)) return ".form-cell";
    if (/campus\.jd\.com$/i.test(hostname)) return "[class*='gridContainer___']";
    return "";
  }

  function moduleTitleSelector({ hostname = "" } = {}) {
    if (/career\.honor\.com$/i.test(hostname)) return ".tit-wrap .tit > p";
    if (/campus\.jd\.com$/i.test(hostname)) return "[class*='titleContainer___']";
    return "";
  }

  function preferFormItemLabel({ hostname = "", inputType = "", className = "" } = {}) {
    return (/campus\.jd\.com$/i.test(hostname) && String(inputType).toLowerCase() === "radio")
      || /phoenix-radio-group/i.test(String(className));
  }

  function supplementalControlSelectors() {
    return [".phoenix-radio-group"];
  }

  function allowZeroSizeControl({ inputType = "" } = {}) {
    return String(inputType).toLowerCase() === "file";
  }

  function shouldIgnoreControl({ hostname = "", placeholder = "" } = {}) {
    return /jobs\.hisense\.com$/i.test(hostname) && /搜索职位关键词/.test(compact(placeholder));
  }

  function sectionFromContainerText({ hostname = "", text = "" } = {}) {
    if (!/jobs\.hisense\.com$/i.test(hostname)) return "";
    const label = compact(text);
    if (label.length > 160) return "";
    if (/添加教育经历/.test(label)) return "education";
    if (/添加语言能力/.test(label)) return "language";
    if (/添加项目经历/.test(label)) return "project";
    if (/添加实习经历/.test(label)) return "work";
    if (/添加获奖情况/.test(label)) return "award";
    if (/添加研究成果|研究成果/.test(label)) return "research";
    return "";
  }

  function sectionAncestorSearchDepth({ hostname = "" } = {}) {
    return /jobs\.hisense\.com$/i.test(hostname) ? 24 : 12;
  }

  function groupHintFromAttributes({ hostname = "", dataKey = "", name = "", id = "" } = {}) {
    if (!/maker\.haier\.net$/i.test(hostname)) return { section: "", recordKey: "" };
    const source = `${dataKey} ${name} ${id}`;
    const matched = source.match(/(?:new_)?([a-z][a-z0-9_]*)\[(\d+)](?:\[([^\]]+)])?/i);
    if (!matched) return { section: "", recordKey: "" };
    const collection = matched[1].toLowerCase();
    const explicitGroupIndex = Number(matched[2]);
    let section = "";
    if (/educat|school|academic/.test(collection)) section = "education";
    else if (/project/.test(collection)) section = "project";
    else if (/work|intern|practice|employment|experience|train/.test(collection)) section = "work";
    else if (/language/.test(collection)) section = "language";
    else if (/award|honor|scholarship/.test(collection)) section = "award";
    else if (/research|publication|paper|patent/.test(collection)) section = "research";
    if (!section) return { section: "", recordKey: "" };
    return {
      section,
      explicitGroupIndex,
      recordKey: `${section}:haier-${collection}-${explicitGroupIndex}`
    };
  }

  function detectPagination({ hostname = "", tabTexts = [], activeIndex = -1 } = {}) {
    if (!/career\.sicarrier\.com$/i.test(hostname)) return null;
    const pages = tabTexts.map(compact).filter(Boolean);
    if (pages.length < 2 || !pages.includes("基本信息") || !pages.includes("教育经历")) return null;
    return {
      kind: "manual-sidebar-tabs",
      pages,
      currentPage: pages[activeIndex] || ""
    };
  }

  function classifyPage({ pathname = "", fieldLabels = [], buttonLabels = [], sectionLabels = [] } = {}) {
    const fields = fieldLabels.map(compact);
    const buttons = buttonLabels.map(compact);
    const sections = sectionLabels.map(compact);
    const hasLoginFields = fields.some((label) => /^(手机号|手机号码)$/.test(label))
      && fields.some((label) => /验证码/.test(label));
    const hasLoginButton = buttons.some((label) => /^登录$/.test(label));
    const hasApplicationSection = sections.some((label) => /个人信息|教育经历|实习经历|工作经历|项目经历/.test(label));
    if (/\/login(?:\/|$)/i.test(pathname) || (hasLoginFields && hasLoginButton && !hasApplicationSection)) {
      return "auth-required";
    }
    return hasApplicationSection ? "application" : "unknown";
  }

  function controlType({ tagName = "", inputType = "", role = "", className = "", itemClassName = "", contentEditable = false } = {}) {
    const tag = String(tagName).toUpperCase();
    const type = String(inputType).toLowerCase();
    const classes = `${className} ${itemClassName}`;
    if (type === "file" || /atsx-upload|phoenix-upload/i.test(classes)) return "file";
    if (type === "radio" || /atsx-radio|phoenix-radio/i.test(classes)) return "radio";
    if (type === "checkbox" || /atsx-checkbox|phoenix-checkbox/i.test(classes)) return "checkbox";
    if (tag === "SELECT") return "select";
    if (/atsx-(?:calendar|date|month|range)-picker|phoenix-(?:date|month|range)-picker|el-date-editor/i.test(classes)) {
      return /range|period/i.test(classes) ? "custom-date-range" : "custom-date";
    }
    if (/date-picker-period|date-range|daterange/i.test(classes)) return "custom-date-range";
    if (role === "combobox" || /atsx-select|phoenix-select|ud__select|el-select|ethnicPicker/i.test(classes)) return "custom-select";
    if (contentEditable) return "rich-text";
    if (tag === "TEXTAREA") return "textarea";
    if (type === "date") return "date";
    if (type === "month") return "month";
    if (type === "email") return "email";
    if (type === "tel") return "tel";
    if (type === "number") return "number";
    return "text";
  }

  function isReadonlyCustomControl({ readOnly = false, role = "", className = "" } = {}) {
    if (!readOnly) return false;
    return role === "combobox"
      || /atsx-select|phoenix-select|ud__select|el-select|ethnicPicker|el-date-editor|(?:date|month|range)-picker|date-range|daterange/i.test(String(className));
  }

  root.RecruitmentAutofillAtsAdapter = {
    FORM_ITEM_SELECTORS,
    allowZeroSizeControl,
    classifyPage,
    controlType,
    detectEngine,
    detectPagination,
    formItemSelectors,
    groupHintFromAttributes,
    moduleContainerSelector,
    moduleTitleSelector,
    preferFormItemLabel,
    recordContainerSelector,
    sectionAncestorSearchDepth,
    sectionFromContainerText,
    sectionFromContainerId,
    shouldIgnoreControl,
    supplementalControlSelectors,
    isReadonlyCustomControl
  };
})(globalThis);
