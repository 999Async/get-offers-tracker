(function exposeProfileUtils(root) {
  const KNOWN_SECTIONS = [
    "personal",
    "jobPreferences",
    "educationSummary",
    "education",
    "workExperience",
    "projects",
    "languages",
    "skills",
    "publications",
    "competitions",
    "scholarships",
    "patents",
    "researchOutputs",
  ];
  const ARRAY_SECTIONS = [
    "education",
    "workExperience",
    "projects",
    "languages",
    "publications",
    "competitions",
    "scholarships",
    "patents",
    "researchOutputs",
  ];

  function validateProfile(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error("JSON 顶层必须是一个对象");
    }
    if (!KNOWN_SECTIONS.some((section) => section in value)) {
      throw new Error("没有找到模板中的简历栏目，请从空白模板开始生成");
    }
    for (const section of ARRAY_SECTIONS) {
      if (section in value && !Array.isArray(value[section])) {
        throw new Error(`${section} 必须是数组，请让 AI 按原模板重新生成`);
      }
    }
    for (const section of ["personal", "jobPreferences", "educationSummary", "skills"]) {
      if (section in value && (!value[section] || typeof value[section] !== "object" || Array.isArray(value[section]))) {
        throw new Error(`${section} 必须是对象，请让 AI 按原模板重新生成`);
      }
    }
    if (countMeaningfulValues(value) === 0) {
      throw new Error("这还是空白模板，请先填写或用 AI 根据简历生成");
    }
    return value;
  }

  function countMeaningfulValues(value) {
    if (Array.isArray(value)) {
      return value.reduce((total, item) => total + countMeaningfulValues(item), 0);
    }
    if (value && typeof value === "object") {
      return Object.values(value).reduce((total, item) => total + countMeaningfulValues(item), 0);
    }
    return value === true || value === false || (typeof value === "number" && Number.isFinite(value))
      || (typeof value === "string" && value.trim() !== "")
      ? 1
      : 0;
  }

  root.RecruitmentAutofillProfileUtils = {
    ARRAY_SECTIONS,
    KNOWN_SECTIONS,
    countMeaningfulValues,
    validateProfile,
  };
})(globalThis);
