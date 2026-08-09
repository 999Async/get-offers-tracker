# GetOffers

GetOffers 是一个本地优先的求职投递进度管理工具，用于整理岗位、记录流程节点并查看后续安排。

## 功能

- 投递记录的列表与看板视图
- 笔试、一面、二面、三面、HR 面和 Offer 流程时间线
- 从流程时间线自动生成首页安排与日历事件
- 岗位搜索与投递计划
- JSON 数据导入与导出
- 响应式桌面端与移动端界面

## 本地运行

需要 Node.js 22.13 或更高版本。

```bash
npm install
npm run dev
```

构建生产版本：

```bash
npm run build
```

## 数据说明

投递数据默认保存在当前浏览器的本地存储中，不会自动上传到远端服务。清除浏览器数据前，建议先在设置页面导出 JSON 备份。

## 技术栈

- React 19
- TypeScript
- vinext / Vite
- Cloudflare Workers 兼容构建
