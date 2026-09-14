/* Pure repeated-record grouping logic. No DOM access. */
(function exposeGrouping(root) {
  const RECORD_RULES = {
    education: {
      families: [/学校名称|学校全称|毕业院校|就读学校/, /专业名称|所学专业|^专业$/, /学历|学位/, /入学时间|开始时间|起止时间|就读时间/, /毕业时间|结束时间|预计毕业时间/],
      required: [0, 1],
      minMatched: 3
    },
    work: {
      families: [/单位名称|工作单位|公司名称|实习公司|任职公司/, /职位名称|实习岗位|岗位名称|担任职位|担任岗位|^职位$|^职务$|^角色$/, /实习内容|实习描述|工作内容|工作职责|工作描述|职责描述|职责与业绩|主要职责与业绩|描述内容|^描述$/, /实习开始时间|工作开始时间|开始时间|起止时间|任职时间/, /实习结束时间|工作结束时间|结束时间/],
      // Some Zhiye forms (for example Dahua) omit the position field entirely.
      // Company + description still anchors the card, while minMatched requires
      // at least one additional work signal such as a date or position.
      required: [0, 2],
      minMatched: 3
    },
    project: {
      families: [/项目名称|项目经历名称/, /项目描述|项目经历描述|项目内容|描述内容|^描述$/, /项目职责|职责描述/, /项目角色|担任.*角色|项目职务/, /项目开始时间|开始时间|起止时间|项目时间/, /项目结束时间|结束时间/],
      required: [0],
      minMatched: 3
    },
    language: {
      families: [/语言名称|语言类型|外语语种|语种|^语言$/, /熟练程度|精通程度|掌握程度|语言水平/, /语言证书|^证书$/, /证书成绩|^成绩$|等级\/分数/],
      required: [0],
      minMatched: 2
    },
    publication: {
      families: [/论文名称/, /发表时间|发表日期/, /论文详情|论文描述/],
      required: [0, 1],
      minMatched: 2
    },
    patent: {
      families: [/专利名称/, /专利编号|专利号/, /发表时间|申请时间|授权时间/, /专利详情|专利描述/],
      required: [0, 1],
      minMatched: 3
    },
    competition: {
      families: [/奖项名称|竞赛名称/, /获奖时间|获奖日期/, /奖项级别|竞赛级别/, /奖项等级|获奖等级|名次/],
      required: [0, 1],
      minMatched: 2
    },
    scholarship: {
      families: [/奖学金名称/, /获奖时间|获奖日期/, /奖学金级别/, /奖项等级|获奖等级/],
      required: [0, 1],
      minMatched: 2
    },
    award: {
      families: [/奖学金名称|奖项名称|^奖项$|荣誉名称|获奖名称/, /获奖时间|获奖日期/],
      required: [0],
      minMatched: 2
    },
    research: {
      families: [/研究成果名称|^名称$/, /研究成果时间|^时间$/, /研究成果等级|^等级$/, /研究成果描述|^描述$/],
      required: [0, 1],
      minMatched: 3
    }
  };

  function semanticLabel(value) {
    return String(value || "")
      .replace(/\s+/g, "")
      .replace(/[：:*？?()（）/\\\-—–.·]/g, "")
      .replace(/请填写(?:您的|你的)?|请输入(?:您的|你的)?|请选择|选择/g, "")
      .trim();
  }

  function isSingleRecordLabels(labels, section) {
    const rule = RECORD_RULES[section];
    if (!rule) return false;
    const awardLikeSections = new Set(["award", "competition", "scholarship"]);
    const hasForeignRecord = Object.entries(RECORD_RULES).some(([otherSection, otherRule]) =>
      otherSection !== section
      && !(awardLikeSections.has(section) && awardLikeSections.has(otherSection))
      && labels.some((label) => otherRule.families[0].test(semanticLabel(label)))
    );
    const basicSignals = labels.filter((label) => /姓名|手机号码|手机号|邮箱|证件号码|出生日期/.test(semanticLabel(label))).length;
    if (hasForeignRecord || basicSignals >= 2) return false;
    const counts = rule.families.map((pattern) => labels.filter((label) => pattern.test(semanticLabel(label))).length);
    const matchedFamilies = counts.filter((count) => count >= 1).length;
    return rule.required.every((index) => counts[index] === 1)
      && matchedFamilies >= rule.minMatched;
  }

  function inferSectionFromLabels(labels) {
    return Object.keys(RECORD_RULES).find((section) => isSingleRecordLabels(labels, section)) || "";
  }

  function chooseItemLabel(directTexts, semanticTexts) {
    return [...(directTexts || []), ...(semanticTexts || [])]
      .map((text) => String(text || "").trim())
      .find((text) => text && text.length <= 80 && !/^(请输入|请选择|搜索)$|删除本条|添加/.test(text)) || "";
  }

  function chooseFormItemCandidate(candidates) {
    const index = (candidates || []).findIndex((candidate) =>
      Boolean(chooseItemLabel(candidate.directTexts, candidate.semanticTexts))
    );
    return index >= 0 ? index : ((candidates || []).length ? 0 : -1);
  }

  function choosePrimaryLabel({ itemLabel = "", placeholder = "", controlCount = 0 } = {}) {
    const meaningfulPlaceholder = String(placeholder || "").trim()
      && !/^(请输入|请选择|搜索)$/.test(String(placeholder || "").trim());
    if (controlCount > 1 && meaningfulPlaceholder) return String(placeholder).trim();
    return String(itemLabel || placeholder || "").trim();
  }

  function fieldLabel(field) {
    return field.formItemLabel || field.label || field.placeholder || field.ariaLabel || field.name || field.id || "";
  }

  function recoverRun(run, section, runIndex) {
    const rule = RECORD_RULES[section];
    if (!rule || run.some((field) => field.recordKey || Number.isInteger(field.explicitGroupIndex))) return run;
    const labels = run.map(fieldLabel);
    const identityPositions = labels
      .map((label, index) => rule.families[0].test(semanticLabel(label)) ? index : -1)
      .filter((index) => index >= 0);
    if (!identityPositions.length) return run;

    if (identityPositions.length === 1) {
      if (!isSingleRecordLabels(labels, section)) return run;
      return run.map((field) => ({ ...field, recordKey: `${section}:sequential-${runIndex}-0` }));
    }

    const signatures = labels.map(semanticLabel);
    const counts = new Map();
    for (const signature of signatures) {
      if (signature) counts.set(signature, (counts.get(signature) || 0) + 1);
    }
    const boundarySignature = signatures.find((signature) => counts.get(signature) === identityPositions.length);
    if (!boundarySignature) return run;
    const starts = signatures
      .map((signature, index) => signature === boundarySignature ? index : -1)
      .filter((index) => index >= 0);
    const segments = starts.map((start, index) => {
      const from = index === 0 ? 0 : start;
      const to = starts[index + 1] ?? run.length;
      return { from, to };
    });
    if (segments.length !== identityPositions.length
      || segments.some(({ from, to }) => !isSingleRecordLabels(labels.slice(from, to), section))) return run;

    return run.map((field, fieldIndex) => {
      const recordIndex = segments.findIndex(({ from, to }) => fieldIndex >= from && fieldIndex < to);
      return recordIndex < 0 ? field : { ...field, recordKey: `${section}:sequential-${runIndex}-${recordIndex}` };
    });
  }

  function recoverSequentialGroups(fields) {
    const recovered = [];
    for (let start = 0, runIndex = 0; start < fields.length; runIndex += 1) {
      const section = fields[start].section;
      let end = start + 1;
      while (end < fields.length && fields[end].section === section) end += 1;
      recovered.push(...recoverRun(fields.slice(start, end), section, runIndex));
      start = end;
    }
    return recovered;
  }

  function assignGroupIndices(fields) {
    const recordKeysBySection = new Map();

    for (const field of fields) {
      if (!field.recordKey || Number.isInteger(field.explicitGroupIndex)) continue;
      if (!recordKeysBySection.has(field.section)) recordKeysBySection.set(field.section, []);
      const keys = recordKeysBySection.get(field.section);
      if (!keys.includes(field.recordKey)) keys.push(field.recordKey);
    }

    return fields.map((field) => {
      if (Number.isInteger(field.explicitGroupIndex)) {
        return { ...field, groupIndex: field.explicitGroupIndex, groupConfidence: "high", groupSource: "data-key" };
      }
      if (field.recordKey) {
        return {
          ...field,
          groupIndex: Math.max(0, recordKeysBySection.get(field.section).indexOf(field.recordKey)),
          groupConfidence: "high",
          groupSource: "record-container"
        };
      }
      const repeated = ["education", "work", "project", "language", "publication", "patent", "competition", "scholarship", "award", "research"].includes(field.section);
      return {
        ...field,
        groupIndex: 0,
        groupConfidence: repeated ? "low" : "high",
        groupSource: repeated ? "unresolved" : "not-repeated"
      };
    });
  }

  root.RecruitmentAutofillGrouping = {
    assignGroupIndices,
    chooseFormItemCandidate,
    chooseItemLabel,
    choosePrimaryLabel,
    inferSectionFromLabels,
    isSingleRecordLabels,
    recoverSequentialGroups
  };
})(globalThis);
