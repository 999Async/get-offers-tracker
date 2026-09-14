/* Pure matching logic. No DOM access and no persistence. */
(function exposeMatcher(root) {
  const SECTION_ALIASES = {
    basic: ["基本信息", "个人信息", "申请信息", "联系方式", "basic", "personal"],
    preference: ["求职意向", "岗位意向", "工作意向", "意向信息", "preference"],
    education: ["教育经历", "教育背景", "学历信息", "education", "school"],
    work: ["实习经历", "工作经历", "工作经验", "任职经历", "internship", "work", "employment"],
    project: ["项目经历", "项目经验", "project"],
    language: ["语言能力", "语言情况", "外语能力", "language"],
    publication: ["发表论文", "论文", "publication", "paper"],
    competition: ["竞赛获奖", "竞赛奖项", "competition"],
    scholarship: ["奖学金", "scholarship"],
    patent: ["发明专利", "专利", "patent"],
    research: ["研究成果", "科研成果", "researchoutput", "researchresult"],
    relative: ["亲属信息", "亲属情况", "亲属", "家庭成员", "relative", "family"],
    skill: ["专业技能", "编程技能", "计算机技能", "skill"],
    award: ["奖项", "获奖", "奖学金", "荣誉", "award", "honor", "scholarship"]
  };

  const FIELD_SPECS = [
    spec("personal.name", "basic", ["姓名", "名字", "真实姓名", "name", "fullname"], ["text"]),
    spec("personal.email", "basic", ["邮箱", "邮箱地址", "电子邮箱", "邮件地址", "email", "mail"], ["text", "email"]),
    spec("personal.phone.number", "basic", ["手机号", "手机号码", "移动电话", "联系电话", "电话", "phone", "mobile", "tel"], ["text", "tel"]),
    spec("personal.age", "basic", ["年龄", "age"], ["text", "number"]),
    spec("education[].location.country", "basic", ["最高学历毕业院校所在国家/地区", "最高学历学校所在国家/地区"], ["select", "custom-select", "text"]),
    spec("personal.documentIssuingCountryOrRegion", "basic", ["国家/地区", "证件签发国家/地区", "国籍/地区", "国籍", "documentissuingcountryorregion"], ["select", "custom-select", "text"]),
    spec("personal.identityDocument.type", "basic", ["证件类型", "个人证件", "identitytype", "documenttype"], ["select", "custom-select"]),
    spec("personal.identityDocument.number", "basic", ["个人证件", "证件号码", "证件号", "身份证号码", "身份证号", "identitynumber", "documentnumber"], ["text"]),
    spec("personal.ethnicity", "basic", ["民族", "ethnicity", "ethnicgroup"], ["select", "custom-select", "text"]),
    spec("personal.emergencyContact.name", "basic", ["紧急联系人", "紧急联系人姓名", "应急联系人", "应急联系人姓名", "emergencycontact"], ["text"]),
    spec("personal.emergencyContact.phone", "basic", ["紧急联系电话", "紧急联系人电话", "应急联系电话", "emergencyphone"], ["text", "tel"]),
    spec("personal.gender", "basic", ["性别", "gender", "sex"], ["select", "radio", "custom-select"]),
    spec("personal.birthDate", "basic", ["出生日期", "生日", "birthdate", "birthday", "dateofbirth"], ["date", "month", "custom-date", "text"]),
    spec("personal.nativePlace", "basic", ["籍贯", "家乡", "nativeplace", "hometown"], ["select", "text", "custom-select"]),
    spec("personal.politicalStatus", "basic", ["政治面貌", "politicalstatus"], ["select", "custom-select", "text"]),
    spec("personal.heightCm", "basic", ["身高(cm)", "身高cm", "身高", "heightcm", "height"], ["text", "number"]),
    spec("personal.weightKg", "basic", ["体重(kg)", "体重kg", "体重", "weightkg", "weight"], ["text", "number"]),
    spec("personal.maritalStatus", "basic", ["婚否", "婚姻状况", "婚姻状态", "maritalstatus"], ["radio", "select", "custom-select", "text"]),
    spec("personal.householdType", "basic", ["户口性质", "户籍性质", "householdtype"], ["select", "custom-select", "text"]),
    spec("personal.householdRegistration", "basic", ["户口所在地", "户籍所在地", "户口", "householdregistration"], ["select", "custom-select", "text"]),
    spec("personal.currentResidence", "basic", ["现居住地", "现居住城市", "现居地址", "当前居住地", "当前所处地", "currentresidence"], ["select", "custom-select", "text"]),
    spec("personal.achievements", "basic", ["个人成就", "个人荣誉", "personalachievements"], ["textarea", "text"]),
    spec("personal.additionalInfo", "basic", ["其他说明", "补充说明", "其他信息", "additionalinfo"], ["textarea", "text"]),
    spec("personal.hobbies", "basic", ["兴趣爱好", "爱好", "hobbies", "interests"], ["textarea", "text"]),
    spec("personal.selfEvaluation", "basic", ["自我评价", "个人评价", "自我介绍", "个人简介", "selfevaluation", "summary"], ["textarea", "text"]),
    spec("files.photo", "basic", ["证件照", "个人照片", "照片"], ["file"]),
    spec("files.attachedResume", "basic", ["上传简历", "简历附件", "个人简历"], ["file"]),
    spec("files.otherAttachments", "basic", ["附件", "其他附件"], ["file"]),
    spec("jobPreferences.firstChoiceLocation", "basic", ["意向城市", "期望城市", "期望工作城市", "期望工作地点", "首选工作地点", "工作城市", "preferredlocation"], ["select", "custom-select", "text"]),
    spec("jobPreferences.firstChoiceLocation", "preference", ["意向工作地点", "第一意向工作地", "第一工作意向地", "首选工作地点"], ["select", "custom-select", "text"]),
    spec("jobPreferences.secondChoiceLocation", "preference", ["第二意向工作地", "第二工作意向地", "次选工作地点"], ["select", "custom-select", "text"]),
    spec("jobPreferences.acceptLocationChange", "preference", ["接受工作地变更", "是否接受工作地变更", "接受工作地点调剂"], ["radio", "select", "custom-select"]),
    spec("jobPreferences.acceptRoleReassignment", "preference", ["是否服从岗位调配", "服从岗位调配", "接受岗位调剂"], ["radio", "select", "custom-select"]),
    spec("jobPreferences.firstChoiceRole", "preference", ["第一意向岗位", "第一志愿岗位", "首选岗位", "firstchoicerole"], ["select", "custom-select", "text"]),
    spec("jobPreferences.secondChoiceRole", "preference", ["第二意向岗位", "第二志愿岗位", "次选岗位", "secondchoicerole"], ["select", "custom-select", "text"]),
    spec("jobPreferences.acceptableLocations", "preference", ["愿意接受的工作地点", "可接受工作地点", "接受工作地点", "acceptablelocations"], ["select", "custom-select", "text"]),
    spec("jobPreferences.applicationSource", "preference", ["应聘渠道来源", "招聘信息来源", "应聘来源", "applicationsource"], ["select", "custom-select", "text"]),
    spec("jobPreferences.referralCode", "preference", ["普联内推码", "内推码", "推荐码", "referralcode"], ["text"]),
    spec("jobPreferences.preferredInterviewSite", "basic", ["期望面试站点", "面试站点", "preferredinterviewsite"], ["select", "custom-select", "text"]),
    spec("jobPreferences.acceptRoleReassignment", "basic", ["是否愿意服从公司分配", "愿意服从公司分配"], ["radio", "select", "custom-select"]),
    spec("jobPreferences.acceptRelocation", "basic", ["是否接受外派", "接受外派", "acceptrelocation"], ["radio", "select", "custom-select"]),
    spec("jobPreferences.acceptUnderdevelopedOverseasAssignment", "basic", ["是否可以接受海外欠发达地区分配", "接受海外欠发达地区分配"], ["radio", "select", "custom-select"]),
    spec("educationSummary.highestDiscipline", "basic", ["最高学历学科", "最高学历学科分类"], ["select", "custom-select", "text"]),
    spec("educationSummary.undergraduateDiscipline", "basic", ["本科学科", "本科学科分类"], ["select", "custom-select", "text"]),
    spec("educationSummary.graduationSchool", "basic", ["毕业学校", "毕业院校"], ["text", "select", "custom-select"]),
    spec("educationSummary.graduationMajor", "basic", ["毕业专业"], ["text", "select", "custom-select"]),
    spec("educationSummary.majorRank", "basic", ["专业排名"], ["select", "custom-select", "text"]),
    spec("educationSummary.graduateStatus", "basic", ["应届/往届", "应届往届", "毕业生类型"], ["radio", "select", "custom-select", "text"]),
    spec("educationSummary.englishLevel", "basic", ["英语等级", "英语证书等级"], ["select", "custom-select", "text"]),
    spec("educationSummary.englishScore", "basic", ["英语等级成绩", "英语等级成绩（请填写分数）", "英语等级成绩分数", "英语成绩"], ["text", "number"]),
    spec("educationSummary.otherLanguage", "basic", ["其他外语", "第二外语"], ["select", "custom-select", "text"]),
    spec("educationSummary.otherLanguageLevel", "basic", ["外语等级", "其他外语等级"], ["text", "select", "custom-select"]),
    spec("educationSummary.computerLevel", "basic", ["计算机等级", "计算机证书等级"], ["select", "custom-select", "text"]),
    spec("educationSummary.scholarshipLevel", "basic", ["奖学金", "奖学金级别"], ["select", "custom-select", "text"]),
    spec("educationSummary.outstandingGraduateLevel", "basic", ["优秀毕业生级别", "优秀毕业生等级"], ["select", "custom-select", "text"]),
    spec("educationSummary.practiceCount", "basic", ["参与过的项目或实习实践数量", "项目或实习实践数量", "实践数量"], ["select", "custom-select", "text", "number"]),
    spec("educationSummary.studentLeaderLevel", "basic", ["学生干部职务级别", "学生干部级别"], ["select", "custom-select", "text"]),
    spec("educationSummary.studentLeaderTitle", "basic", ["是否曾经担任如下职务", "曾经担任职务", "学生干部职务"], ["select", "custom-select", "text"]),
    spec("educationSummary.competitionAwardLevel", "basic", ["参与竞赛的奖项级别", "竞赛奖项级别"], ["select", "custom-select", "text"]),
    spec("education[].location.country", "preference", ["当前学校地区", "学校所在国家/地区"], ["select", "custom-select", "text"]),
    spec("education[].location.province", "preference", ["当前学校省份", "学校所在省份"], ["select", "custom-select", "text"]),
    spec("education[].location.city", "preference", ["当前学校城市", "学校所在城市"], ["select", "custom-select", "text"]),

    spec("education[].school", "education", ["学校名称", "学校全称", "毕业院校", "就读学校", "院校", "学校", "school", "university", "college"], ["text", "select", "custom-select"]),
    spec("education[].degree", "education", ["学历", "学位", "最高学历", "degree", "educationlevel"], ["select", "custom-select", "text"]),
    spec("education[].major", "education", ["专业名称", "所学专业", "专业", "major", "fieldofstudy"], ["text", "select", "custom-select"]),
    spec("education[].department", "education", ["院系", "学院", "就读院系", "department", "faculty"], ["text"]),
    spec("education[].startDate", "education", ["入学时间", "入学日期", "教育开始时间", "startdate", "begindate"], ["date", "month", "custom-date", "text"]),
    spec("education[].graduationDate", "education", ["毕业时间", "预计毕业时间", "毕业日期", "结束时间", "graduationdate", "enddate"], ["date", "month", "custom-date", "text"]),
    spec("education[].location.country", "education", ["最高学历毕业院校所在国家/地区", "毕业院校所在国家/地区", "学校所在地", "学校所在国家/地区", "就读国家/地区"], ["select", "custom-select", "text"]),
    spec("education[].location.province", "education", ["学校所在省份", "就读省份"], ["select", "custom-select", "text"]),
    spec("education[].location.city", "education", ["学校所在城市", "就读城市"], ["select", "custom-select", "text"]),
    spec("education[].period", "education", ["起止时间", "就读时间", "在校时间", "period", "daterange"], ["date-range", "custom-date-range"]),
    spec("education[].educationType", "education", ["培养方式", "学历类型", "教育类型", "学习形式", "educationtype", "studytype"], ["select", "custom-select"]),
    spec("education[].disciplineCategory", "education", ["学科", "一级学科分类", "学科分类", "disciplinecategory"], ["select", "custom-select", "text"]),
    spec("education[].gradeRank", "education", ["专业排名", "成绩排名", "学习成绩排名", "排名", "rank", "ranking"], ["text", "select", "custom-select"]),
    spec("education[].gpa", "education", ["GPA/CGPA", "GPA", "CGPA", "平均绩点", "绩点"], ["text", "number"]),
    spec("education[].gpaScale", "education", ["你所在院校的满绩绩点", "所在院校的满绩绩点", "满绩绩点", "满绩", "绩点满分", "最高绩点"], ["text", "number"]),
    spec("education[].advisorName", "education", ["导师姓名", "导师", "advisor", "supervisor"], ["text"]),
    spec("education[].laboratory", "education", ["所在实验室", "实验室名称", "实验室", "laboratory"], ["text"]),
    spec("education[].researchDirection", "education", ["研究方向", "科研方向", "researchdirection", "researcharea"], ["text"]),
    spec("education[].nationalKeyLaboratory", "education", ["国家重点实验室", "是否国家重点实验室"], ["radio", "select", "custom-select"]),
    spec("education[].studentLeader", "education", ["学生干部", "是否学生干部"], ["radio", "select", "custom-select"]),
    spec("education[].isUnifiedEnrollment", "education", ["是否统招", "统招"], ["radio", "select", "custom-select"]),
    spec("education[].overseasStudy", "education", ["是否为海外留学经历", "海外留学经历"], ["radio", "select", "custom-select"]),

    spec("workExperience[].company", "work", ["企业名称", "公司名称", "单位名称", "工作单位", "实习公司", "任职公司", "公司", "company", "employer", "organization"], ["text", "textarea"]),
    spec("workExperience[].position", "work", ["职位名称", "担任职位", "担任岗位", "岗位名称", "实习岗位", "职位", "职务", "岗位", "角色", "title", "position", "jobtitle"], ["text"]),
    spec("workExperience[].department", "work", ["任职部门", "所在部门", "部门", "department"], ["text"]),
    spec("workExperience[].startDate", "work", ["实习开始时间", "工作开始时间", "开始时间", "startdate", "begindate"], ["date", "month", "custom-date", "text"]),
    spec("workExperience[].endDate", "work", ["实习结束时间", "工作结束时间", "结束时间", "enddate"], ["date", "month", "custom-date", "text"]),
    spec("workExperience[].period", "work", ["起止时间", "任职时间", "实习时间", "工作时间", "period", "daterange"], ["date-range", "custom-date-range"]),
    spec("workExperience[].location", "work", ["工作地址", "工作地点", "办公地点"], ["text"]),
    spec("workExperience[].description", "work", ["工作内容", "工作职责", "职责与业绩", "主要职责与业绩", "工作描述", "实习内容", "实习描述", "职责描述", "描述", "description", "responsibilities"], ["textarea", "text"]),

    spec("projects[].name", "project", ["项目经历名称", "项目名称", "项目名", "projectname"], ["text"]),
    spec("projects[].role", "project", ["项目角色", "担任角色", "担任的角色", "项目职务", "职责", "职务", "角色", "projectrole", "role"], ["text"]),
    spec("projects[].startDate", "project", ["项目开始时间", "开始时间", "startdate", "begindate"], ["date", "month", "custom-date", "text"]),
    spec("projects[].endDate", "project", ["项目结束时间", "结束时间", "enddate"], ["date", "month", "custom-date", "text"]),
    spec("projects[].period", "project", ["起止时间", "项目时间", "period", "daterange"], ["date-range", "custom-date-range"]),
    spec("projects[].link", "project", ["项目链接", "项目地址", "项目网址", "代码仓库", "仓库地址", "projectlink", "projecturl", "repository", "github"], ["text"]),
    spec("projects[].location", "project", ["项目地点", "项目所在地", "projectlocation"], ["text"]),
    spec("projects[].description", "project", ["项目经历描述", "项目描述", "项目内容", "项目职责", "主要职责与业绩", "职责描述", "描述内容", "描述", "description"], ["textarea", "text"]),

    spec("languages[].language", "language", ["语言名称", "外语语种", "语种", "语言", "language"], ["select", "custom-select", "text"]),
    spec("languages[].proficiency", "language", ["熟练程度", "精通程度", "掌握程度", "语言水平", "proficiency", "level"], ["select", "custom-select", "text"]),
    spec("languages[].certificate", "language", ["语言证书", "证书", "证书名称", "certificate"], ["select", "custom-select", "text"]),
    spec("languages[].score", "language", ["语言成绩", "证书成绩", "等级/分数", "分数", "成绩", "score"], ["text", "number"]),
    spec("languages[].notes", "language", ["备注", "语言备注", "其他语言说明"], ["textarea", "text"]),

    spec("skills.programmingLanguages", "skill", ["编程语言", "计算机语言", "programminglanguages"], ["select", "custom-select", "text"]),
    spec("skills.programmingProficiency", "skill", ["掌握程度", "编程熟练程度", "programmingproficiency"], ["select", "custom-select", "text"]),

    spec("publications[].title", "publication", ["论文名称", "论文题目", "papertitle", "publicationtitle"], ["text"]),
    spec("publications[].publicationDate", "publication", ["发表时间", "发表日期", "publicationdate"], ["date", "month", "custom-date", "text"]),
    spec("publications[].description", "publication", ["论文详情", "论文描述", "论文摘要", "paperdescription"], ["textarea", "text"]),
    spec("publications[].journal", "publication", ["发表期刊", "期刊名称", "journal"], ["text"]),

    spec("competitions[].name", "competition", ["奖项名称", "竞赛名称", "比赛名称"], ["text"]),
    spec("competitions[].awardDate", "competition", ["获奖时间", "获奖日期"], ["date", "month", "custom-date", "text"]),
    spec("competitions[].level", "competition", ["奖项级别", "竞赛级别"], ["select", "custom-select", "text"]),
    spec("competitions[].awardLevel", "competition", ["奖项等级", "获奖等级", "名次"], ["text", "select", "custom-select"]),

    spec("scholarships[].name", "scholarship", ["奖学金名称"], ["text"]),
    spec("scholarships[].level", "scholarship", ["奖学金级别"], ["select", "custom-select", "text"]),
    spec("scholarships[].awardLevel", "scholarship", ["奖项等级", "获奖等级"], ["text", "select", "custom-select"]),
    spec("scholarships[].awardDate", "scholarship", ["获奖时间", "获奖日期"], ["date", "month", "custom-date", "text"]),

    spec("patents[].number", "patent", ["专利编号", "专利号", "patentnumber"], ["text"]),
    spec("patents[].publicationDate", "patent", ["发表时间", "申请时间", "授权时间", "publicationdate"], ["date", "month", "custom-date", "text"]),
    spec("patents[].name", "patent", ["专利名称", "patentname"], ["text"]),
    spec("patents[].description", "patent", ["专利详情", "专利描述", "patentdescription"], ["textarea", "text"]),

    spec("researchOutputs[].name", "research", ["研究成果名称", "名称", "researchoutputname"], ["text"]),
    spec("researchOutputs[].date", "research", ["研究成果时间", "时间", "researchoutputdate"], ["date", "month", "custom-date", "custom-select", "text"]),
    spec("researchOutputs[].level", "research", ["研究成果等级", "等级", "researchoutputlevel"], ["text", "select", "custom-select"]),
    spec("researchOutputs[].description", "research", ["研究成果描述", "描述", "researchoutputdescription"], ["textarea", "text"]),

    spec("relatives.hasCurrentOrFormerSicarrierEmployee", "relative", ["是否有亲属现在或曾经在新凯来工作", "有无亲属在新凯来工作"], ["radio"]),
    spec("relatives.hasCurrentOrFormerHonorEmployee", "relative", ["是否有亲属在荣耀工作（包含曾经）", "是否有亲属在荣耀工作", "有无亲属在荣耀工作"], ["radio"]),
    spec("relatives.hasCurrentHisenseEmployee", "basic", ["是否有亲属在本公司工作", "有无亲属在本公司工作"], ["radio"]),

    spec("scholarships[].name", "award", ["奖项", "奖学金名称", "奖项名称", "荣誉名称", "获奖名称", "awardname", "honorname"], ["text"]),
    spec("scholarships[].awardDate", "award", ["获奖时间", "获奖日期", "awarddate"], ["date", "month", "text"]),
    spec("scholarships[].type", "award", ["获奖类型", "奖项类型", "awardtype"], ["text", "select", "custom-select"]),
    spec("scholarships[].awardLevel", "award", ["获奖级别", "获奖等级", "奖项等级", "awardlevel"], ["text", "select", "custom-select"]),
    spec("scholarships[].description", "award", ["获奖情况", "获奖描述", "奖项描述", "awarddescription"], ["textarea", "text"])
  ];

  function spec(path, section, aliases, types) {
    return { path, section, aliases: aliases.map(normalize), types };
  }

  function normalize(value) {
    return String(value || "")
      .toLowerCase()
      .replace(/[\s\u00a0*_：:?？()（）/\\\-—–.·]/g, "")
      .replace(/请填写(?:您的|你的)?|请输入(?:您的|你的)?|请选择|填写(?:您的|你的)?|必填|required/g, "");
  }

  function inferSection(text) {
    const normalized = normalize(text);
    let best = { section: "unknown", score: 0 };
    for (const [section, aliases] of Object.entries(SECTION_ALIASES)) {
      for (const alias of aliases) {
        const key = normalize(alias);
        if (normalized === key && best.score < 1) best = { section, score: 1 };
        else if (normalized.includes(key) && best.score < 0.75) best = { section, score: 0.75 };
      }
    }
    return best.section;
  }

  function pathParts(path) {
    return path.replace(/\[\]/g, "").split(".");
  }

  function getValue(profile, path, groupIndex) {
    let cursor = profile;
    const parts = pathParts(path);
    for (let index = 0; index < parts.length; index += 1) {
      const part = parts[index];
      cursor = cursor == null ? undefined : cursor[part];
      if (Array.isArray(cursor)) cursor = cursor[groupIndex ?? 0];
    }
    if (cursor == null || cursor === "") return derivedValue(profile, path);
    return cursor;
  }

  function derivedValue(profile, path) {
    const education = Array.isArray(profile.education) ? profile.education : [];
    const languages = Array.isArray(profile.languages) ? profile.languages : [];
    const scholarships = Array.isArray(profile.scholarships) ? profile.scholarships : [];
    const competitions = Array.isArray(profile.competitions) ? profile.competitions : [];
    const highest = education[0] || {};
    const undergraduate = education.find((item) => /本科|学士/.test(String(item?.degree || ""))) || {};
    const english = languages.find((item) => /英语|english|cet|雅思|托福|toefl|ielts/i.test(
      `${item?.language || ""} ${item?.certificate || ""}`
    )) || languages[0] || {};
    const otherLanguage = languages.find((item) => item !== english) || {};
    const studentLeader = education.find((item) => item?.studentLeaderLevel || item?.studentLeaderTitle) || {};
    const practiceCount = [
      ...(Array.isArray(profile.projects) ? profile.projects.filter((item) => item?.name) : []),
      ...(Array.isArray(profile.workExperience) ? profile.workExperience.filter((item) => item?.company) : [])
    ].length;
    const fallbacks = {
      "educationSummary.highestDiscipline": highest.disciplineCategory,
      "educationSummary.undergraduateDiscipline": undergraduate.disciplineCategory,
      "educationSummary.graduationSchool": highest.school,
      "educationSummary.graduationMajor": highest.major,
      "educationSummary.majorRank": highest.gradeRank,
      "educationSummary.englishLevel": english.certificate || english.proficiency,
      "educationSummary.englishScore": english.score,
      "educationSummary.otherLanguage": otherLanguage.language,
      "educationSummary.otherLanguageLevel": otherLanguage.certificate || otherLanguage.proficiency,
      "educationSummary.scholarshipLevel": scholarships[0]?.level,
      "educationSummary.practiceCount": practiceCount ? String(practiceCount) : undefined,
      "educationSummary.studentLeaderLevel": studentLeader.studentLeaderLevel,
      "educationSummary.studentLeaderTitle": studentLeader.studentLeaderTitle,
      "educationSummary.competitionAwardLevel": competitions[0]?.level
    };
    const value = fallbacks[path];
    return value == null || value === "" ? undefined : value;
  }

  function datesForPeriod(profile, specPath, groupIndex) {
    if (!specPath.endsWith(".period")) return undefined;
    const collection = specPath.startsWith("education")
      ? profile.education
      : specPath.startsWith("workExperience")
        ? profile.workExperience
        : profile.projects;
    const row = collection?.[groupIndex ?? 0];
    if (!row) return undefined;
    const start = row.startDate?.slice(0, 7);
    const endKey = specPath.startsWith("education") ? "graduationDate" : "endDate";
    const end = row[endKey]?.slice(0, 7);
    return start && end ? { start, end } : undefined;
  }

  function typeCompatible(fieldType, allowed) {
    if (!fieldType) return false;
    if (allowed.includes(fieldType)) return true;
    if (fieldType === "email" && allowed.includes("text")) return true;
    if (fieldType === "tel" && allowed.includes("text")) return true;
    return false;
  }

  function aliasScore(field, candidate) {
    const formItemSource = normalize(field.formItemLabel);
    const sources = [
      field.formItemLabel,
      field.label,
      field.ariaLabel,
      field.placeholder,
      field.name,
      field.id,
      field.dataKey,
      `${field.formItemLabel || ""}${field.label || ""}`,
      `${field.formItemLabel || ""}${field.placeholder || ""}`
    ]
      .map(normalize)
      .filter((source) => source && !(formItemSource && /^(是|否|男|女|保密|有|无)$/.test(source)));
    let best = 0;
    for (const source of sources) {
      for (const alias of candidate.aliases) {
        if (source === alias) best = Math.max(best, 0.84);
        else if (source.startsWith(alias) && /请|建议|确保|需|仅|非|用于/.test(source.slice(alias.length))) best = Math.max(best, 0.84);
        else if (source.includes(alias) || alias.includes(source)) best = Math.max(best, 0.68);
      }
    }
    return best;
  }

  function scoreCandidate(field, candidate) {
    let score = aliasScore(field, candidate);
    if (!score) return 0;
    if (field.section === candidate.section) score += 0.12;
    else if (field.section !== "unknown") score -= 0.24;
    if (typeCompatible(field.type, candidate.types)) score += 0.05;
    else score -= 0.08;
    const emergencyContext = /紧急联系人|应急联系人/.test(normalize(field.formItemLabel));
    if (emergencyContext) {
      const emergencyDetail = normalize(field.label || field.placeholder);
      const isEmergencyPhone = /电话|手机|phone|mobile|tel/.test(emergencyDetail);
      const isEmergencyName = /姓名|名字|name/.test(emergencyDetail);
      if (candidate.path.startsWith("personal.emergencyContact.")) score += 0.1;
      else if (["personal.name", "personal.phone.number"].includes(candidate.path)) score -= 0.12;
      if (isEmergencyPhone && candidate.path === "personal.emergencyContact.name") score -= 0.2;
      if (isEmergencyName && candidate.path === "personal.emergencyContact.phone") score -= 0.2;
    }
    return Math.max(0, Math.min(1, score));
  }

  function safeToFill(field, value) {
    if (value === undefined) return false;
    if (["file", "custom-select", "custom-date", "custom-date-range", "rich-text", "radio", "checkbox"].includes(field.type)) return false;
    if (typeof value === "object") return false;
    return true;
  }

  function matchFields(fields, profile) {
    const plan = fields.map((field) => {
      const agreementText = normalize(`${field.formItemLabel || ""}${field.label || ""}`);
      if (/用户协议|隐私声明|知识产权|商业秘密|承诺书|勾选即表示您同意/.test(agreementText)) {
        return result(field, "unmatched", 0, undefined, undefined, "协议与声明必须由用户人工确认");
      }
      const ranked = FIELD_SPECS
        .map((candidate) => ({ candidate, score: scoreCandidate(field, candidate) }))
        .filter((entry) => entry.score > 0)
        .sort((left, right) => right.score - left.score);
      const best = ranked[0];
      const second = ranked[1];
      if (!best) return result(field, "unmatched", 0, undefined, undefined, "未找到语义相近字段");

      const value = best.candidate.path.endsWith(".period")
        ? datesForPeriod(profile, best.candidate.path, field.groupIndex)
        : getValue(profile, best.candidate.path, field.groupIndex);
      const ambiguous = second && best.score - second.score < 0.08;
      if (value === undefined) return result(field, "missing-data", best.score, best.candidate.path, value, "资料库中没有对应值");
      const unresolvedRepeated = best.candidate.path.includes("[]") && (
        field.groupConfidence === "low"
        || field.groupSource === "not-repeated"
        || field.section !== best.candidate.section
      );
      if (unresolvedRepeated) {
        return result(field, "review", best.score, best.candidate.path, value, "重复记录边界不明确，已禁止自动填写以避免经历错位");
      }
      if (ambiguous || best.score < 0.62) return result(field, "review", best.score, best.candidate.path, value, "匹配置信度不足或存在歧义");
      if (!safeToFill(field, value)) return result(field, "review", best.score, best.candidate.path, value, "自定义组件、附件或选择题需要人工确认");
      if (best.score < 0.78) return result(field, "review", best.score, best.candidate.path, value, "中等置信度，建议人工确认");
      return result(field, "safe", best.score, best.candidate.path, value, "高置信度普通控件");
    });
    const scalarTargets = new Map();
    for (const item of plan) {
      if (item.status !== "safe" || !item.path || item.path.includes("[]")) continue;
      const key = `${item.path}:${item.field.groupIndex ?? 0}`;
      scalarTargets.set(key, (scalarTargets.get(key) || 0) + 1);
    }
    return plan.map((item) => {
      const key = item.path ? `${item.path}:${item.field.groupIndex ?? 0}` : "";
      if (item.status === "safe" && scalarTargets.get(key) > 1) {
        return result(item.field, "review", item.score, item.path, item.value, "同一资料对应多个控件，需人工确认级联或拆分方式");
      }
      return item;
    });
  }

  function result(field, status, score, path, value, reason) {
    return { field, status, score: Number(score.toFixed(2)), path, value, reason };
  }

  function summarize(plan) {
    const summary = { total: plan.length, safe: 0, review: 0, unmatched: 0, missingData: 0 };
    for (const item of plan) {
      if (item.status === "safe") summary.safe += 1;
      else if (item.status === "review") summary.review += 1;
      else if (item.status === "missing-data") summary.missingData += 1;
      else summary.unmatched += 1;
    }
    return summary;
  }

  root.RecruitmentAutofillMatcher = {
    FIELD_SPECS,
    inferSection,
    matchFields,
    normalize,
    summarize
  };
})(globalThis);
