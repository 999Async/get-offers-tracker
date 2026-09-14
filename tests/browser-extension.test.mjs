import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const extensionDirectory = new URL("../browser-extension/", import.meta.url);

function readExtensionFile(name) {
  return readFileSync(new URL(name, extensionDirectory), "utf8");
}

test("browser extension uses user-triggered minimum permissions", () => {
  const manifest = JSON.parse(readExtensionFile("manifest.json"));

  assert.equal(manifest.manifest_version, 3);
  assert.deepEqual(manifest.permissions, ["storage", "activeTab", "scripting"]);
  assert.equal(manifest.host_permissions, undefined);
  assert.equal(manifest.content_scripts, undefined);
});

test("browser extension matches safe fields and blocks agreements", () => {
  for (const file of ["ats-adapter.js", "matcher.js", "grouping.js"]) {
    vm.runInThisContext(readExtensionFile(file), { filename: file });
  }

  const fields = [
    {
      label: "姓名",
      formItemLabel: "姓名",
      type: "text",
      section: "basic",
      groupIndex: 0,
      groupConfidence: "high",
      groupSource: "not-repeated",
    },
    {
      label: "公司名称",
      formItemLabel: "公司名称",
      type: "text",
      section: "work",
      groupIndex: 1,
      groupConfidence: "high",
      groupSource: "data-key",
    },
    {
      label: "隐私声明",
      formItemLabel: "隐私声明",
      type: "checkbox",
      section: "basic",
      groupIndex: 0,
      groupConfidence: "high",
      groupSource: "not-repeated",
    },
  ];
  const profile = {
    personal: { name: "测试用户" },
    workExperience: [{ company: "甲公司" }, { company: "乙公司" }],
  };

  const plan = globalThis.RecruitmentAutofillMatcher.matchFields(fields, profile);

  assert.equal(plan[0].status, "safe");
  assert.equal(plan[0].value, "测试用户");
  assert.equal(plan[1].status, "safe");
  assert.equal(plan[1].value, "乙公司");
  assert.equal(plan[2].status, "unmatched");
});

test("bundled profile is an empty template rather than personal data", () => {
  const template = JSON.parse(readExtensionFile("profile-template.json"));

  assert.equal(template.personal.name, "");
  assert.equal(template.personal.email, "");
  assert.equal(template.education[0].school, "");
  assert.equal(template.workExperience[0].company, "");
});

test("profile validation rejects blank or malformed AI output", () => {
  vm.runInThisContext(readExtensionFile("profile-utils.js"), { filename: "profile-utils.js" });
  const utils = globalThis.RecruitmentAutofillProfileUtils;
  const template = JSON.parse(readExtensionFile("profile-template.json"));

  assert.throws(() => utils.validateProfile(template), /空白模板/);
  assert.throws(() => utils.validateProfile({ personal: { name: "测试用户" }, education: {} }), /education 必须是数组/);
  assert.doesNotThrow(() => utils.validateProfile({
    personal: { name: "测试用户" },
    education: [{ school: "测试大学" }],
  }));
});

test("AI generation prompt preserves evidence and requests a JSON file", () => {
  const prompt = readExtensionFile("profile-generation-prompt.txt");

  assert.match(prompt, /不得猜测/);
  assert.match(prompt, /profile-template\.json/);
  assert.match(prompt, /可下载的 profile\.json 文件/);
});

test("extension includes a visual guide linked from the popup", () => {
  const popup = readExtensionFile("popup.html");
  const guide = readExtensionFile("guide.html");

  assert.match(popup, /href="guide\.html"/);
  assert.match(guide, /四步开始使用/);
  for (const image of [
    "docs/images/image.png",
    "docs/images/image-1.png",
    "docs/images/01-extension-home.png",
    "docs/images/03-generate-profile.png",
    "docs/images/04-scan-preview.png",
  ]) {
    assert.ok(guide.includes(image), `guide should include ${image}`);
  }
});
