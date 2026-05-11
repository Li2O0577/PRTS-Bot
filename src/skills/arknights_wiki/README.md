# Arknights Wiki Skill

明日方舟 PRTS wiki 查询 skill。

当前能力：

- 调用 PRTS MediaWiki API 搜索页面
- 优先按页面标题直接命中干员/材料/关卡
- 搜索失败时降级到全文搜索
- 对模板页面使用 `parse` 接口抽取文本
- 对“一技能/二技能/三技能”问题优先截取技能附近片段

配置仍由 `smart_reply` 插件的 `.env` 字段提供。

